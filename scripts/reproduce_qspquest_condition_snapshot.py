#!/usr/bin/env python3
"""Replay a self-contained pinned nlmixr2lib simulation snapshot."""
import argparse, collections, hashlib, json, os, subprocess
from pathlib import Path
from trajectory_comparison import compare_mapped, read_reference, validate_run
from replay_formats import condition_request, write_native_copy

p = argparse.ArgumentParser()
p.add_argument("--dataset", type=Path, required=True)
p.add_argument("--cli", type=Path, required=True)
p.add_argument("--rscript", default="Rscript")
p.add_argument("--output", type=Path, required=True)
p.add_argument("--model-id", action="append")
a = p.parse_args()
a.output.mkdir(exist_ok=False)
root = Path(__file__).resolve().parents[1]
summary = json.loads((a.dataset / "summary.json").read_text())
mapping = json.loads((a.dataset.parent / "native-models/summary.json").read_text())
symbols = {
    m["model_id"]: m["translation"]["compared_outputs"] for m in mapping["models"]
}
results = []
for model in summary["models"]:
    mid = model["model_id"]
    if a.model_id and mid not in a.model_id:
        continue
    source = a.dataset / mid
    dest = a.output / mid
    dest.mkdir()
    plan = json.loads((source / "plan.json").read_text())
    plan["source_file"] = str((source / plan["source_file"]).resolve())
    cases = []
    native_path = source / "model.json"
    if hashlib.sha256(native_path.read_bytes()).hexdigest() != model["model_sha256"]:
        raise ValueError("native model pin differs")
    executed_model = dest / "qspquest-model.json"
    model_record = write_native_copy(native_path, executed_model, "model")
    plan["schema"] = "qspquest.validation.condition-plan/v1"
    plan["model_input"] = model_record
    for case in plan["cases"]:
        sid = case["condition_id"]
        folder = dest / sid
        folder.mkdir()
        request_path = condition_request(source / sid, case)
        executed_request = folder / "qspquest-request.json"
        request_record = write_native_copy(request_path, executed_request, "run")
        case["qspquest_request_sha256"] = request_record["executed_sha256"]
        case["qspquest_request"] = str(executed_request.resolve())
        case["request_input"] = request_record
        case["r_request"] = str(
            (source / case["condition_id"] / "r-request.json").resolve()
        )
    (dest / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    with (dest / "R.log").open("w") as log:
        subprocess.run(
            [
                a.rscript,
                str(root / "scripts/run_nlmixr_condition_matrix.R"),
                str((dest / "plan.json").resolve()),
                str((dest / "reference").resolve()),
            ],
            stdout=log,
            stderr=log,
            check=True,
        )
    for case in plan["cases"]:
        sid = case["condition_id"]
        folder = dest / sid
        request_path = Path(case["qspquest_request"])
        proc = subprocess.run(
            [
                str(a.cli.resolve()),
                "run",
                str(executed_model.resolve()),
                str(request_path.resolve()),
            ],
            text=True,
            capture_output=True,
            timeout=900,
        )
        (folder / "stdout.json").write_text(proc.stdout)
        (folder / "stderr.json").write_text(proc.stderr)
        record = {
            "condition_id": sid,
            "native_exit": proc.returncode,
            "purpose": case["purpose"],
        }
        if proc.returncode:
            diagnostic = json.loads(proc.stderr)["error"]
            record["status"] = (
                "expected_rejection"
                if case["purpose"] != "numerical_comparison"
                and diagnostic["code"] in ["domain", "solver"]
                else "failed"
            )
            record["diagnostic"] = diagnostic
        else:
            try:
                actual = json.loads(proc.stdout)
                reference = read_reference(dest / "reference" / sid / "trajectory.csv", ["time", *symbols[mid]])
                request = json.loads(request_path.read_text())
                validate_run(actual, request, json.loads(executed_model.read_text()))
                record.update(compare_mapped(reference, actual, symbols[mid]))
            except Exception as e:
                record.update(status="failed", error=str(e))
        cases.append(record)
    results.append({"model_id": mid, "cases": cases})
    (a.output / "summary.json").write_text(
        json.dumps(
            {
                "models": results,
                "counts": dict(
                    collections.Counter(
                        c["status"] for m in results for c in m["cases"]
                    )
                ),
            },
            indent=2,
        )
        + "\n"
    )
    print(mid, collections.Counter(c["status"] for c in cases), flush=True)

if not results or any(not m["cases"] for m in results):
    raise ValueError("No nonempty condition plans selected")
if any(c["status"] == "failed" for m in results for c in m["cases"]):
    raise SystemExit("Condition execution or comparison contract failed")
