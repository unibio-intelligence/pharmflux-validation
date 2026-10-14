#!/usr/bin/env python3
"""Reproduce pinned validation contracts into a new output directory."""
import argparse, collections, hashlib, json, math, subprocess, sys, zipfile
from pathlib import Path, PurePosixPath
from replay_formats import validate_native, write_native_copy

ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def unpack(name, destination):
    entry = next(
        x
        for x in json.loads((ROOT / "inputs/index.json").read_text())["archives"]
        if x["archive"] == "inputs/" + name
    )
    data = (ROOT / entry["archive"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise ValueError("fixture archive checksum differs")
    import io

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        checks = json.loads(archive.read("checksums.json"))
        if set(archive.namelist()) != set(checks) | {"manifest.xml", "checksums.json"}:
            raise ValueError("fixture member inventory differs")
        for name, digest in checks.items():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ValueError("unsafe fixture path")
            target = destination.joinpath(*path.parts)
            if target.exists():
                raise ValueError("fixture destination already exists")
            target.parent.mkdir(parents=True, exist_ok=True)
            if any(parent.is_symlink() for parent in [target.parent, *target.parents]):
                raise ValueError("symlink in fixture destination")
            payload = archive.read(name)
            if hashlib.sha256(payload).hexdigest() != digest:
                raise ValueError("fixture member checksum differs: " + name)
            with target.open("xb") as stream:
                stream.write(payload)


def run_native(cli, command, model, request, output):
    executed_request = output.with_name(output.stem + "-request.json")
    input_record = {"schema": "qspquest.validation.replay-inputs/v1",
                    "request": write_native_copy(request, executed_request, command)}
    executed_model = model
    if model.suffix == ".json":
        executed_model = output.with_name(output.stem + "-model.json")
        input_record["model"] = write_native_copy(model, executed_model, "model")
    write(output.with_name(output.stem + "-inputs.json"), input_record)
    proc = subprocess.run(
        [str(cli), command, str(executed_model), str(executed_request)],
        text=True,
        capture_output=True,
        timeout=1800,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr or proc.stdout)
    value = json.loads(proc.stdout)
    if command == "run":
        from trajectory_comparison import validate_run
        definition = json.loads(model.read_text()) if model.suffix == ".json" else None
        validate_run(value, json.loads(request.read_text()), definition)
    write(output, value)
    return value


def selected(workspace, cli, model_filter, case_filter):
    from omex_to_rxode2 import archive_members

    for archive in sorted(
        (workspace / "selected-models/models").glob("*/*/model.omex")
    ):
        members, index = archive_members(archive.read_bytes())
        if model_filter and index["model_id"] != model_filter:
            archive.unlink()  # This is the extracted scratch copy, not the checked fixture.
            continue
        native = index["native_execution"]
        for c in index["scenarios"]:
            sid = c["scenario_id"]
            if case_filter and sid != case_filter:
                continue
            folder = workspace / "selected-model-simulations" / index["model_id"] / sid
            folder.mkdir(parents=True, exist_ok=True)
            model = folder / "model.json"
            model.write_bytes(members[native["model"]])
            for solver in ["diffsol_bdf", "diffsol_rodas5p"]:
                run_native(
                    cli,
                    "run",
                    model,
                    folder / (solver + "-request.json"),
                    folder / (solver + "-result.json"),
                )
        if case_filter:
            # Reference tools enumerate scenarios from the immutable OMEX index.
            raise ValueError(
                "--case is supported for nlmixr2, presets and fitting; OMEX reference suites use --model"
            )


def compare_reference_folder(workspace, reference):
    import pandas as pd
    from omex_to_rxode2 import archive_members, translate
    from validate_omex_independent_engines import compare

    rows = []
    for archive in sorted(
        (workspace / "selected-models/models").glob("*/*/model.omex")
    ):
        data = archive.read_bytes()
        _, index = archive_members(data)
        for c in index["scenarios"]:
            sid = c["scenario_id"]
            folder = reference / index["model_id"] / sid
            frame = pd.read_csv(folder / "trajectory.csv")
            d = translate(data, sid)
            from trajectory_comparison import projection_aliases
            d["native_aliases"] = projection_aliases(index)
            tests = {}
            for solver in ["diffsol_bdf", "diffsol_rodas5p"]:
                native = json.loads(
                    (
                        workspace
                        / "selected-model-simulations"
                        / index["model_id"]
                        / sid
                        / (solver + "-result.json")
                    ).read_text()
                )
                tests[solver] = compare(frame, native, d)
            rows.append(
                {
                    "model_id": index["model_id"],
                    "scenario_id": sid,
                    "status": (
                        "matched"
                        if all(t["status"] == "matched" for t in tests.values())
                        else "mismatch"
                    ),
                    "comparisons": tests,
                }
            )
    report = {
        "cases": rows,
        "counts": dict(collections.Counter(r["status"] for r in rows)),
    }
    write(reference / "comparison.json", report)
    if any(r["status"] != "matched" for r in rows):
        raise RuntimeError("reference comparison did not pass")
    return report


def fit(workspace, cli, dataset_filter, subject_filter, rscript):
    root = workspace / "fitting-examples-20261005"
    plan = json.loads((root / "plan.json").read_text())
    plan["cases"] = [
        c
        for c in plan["cases"]
        if (not dataset_filter or c["dataset"] == dataset_filter)
        and (not subject_filter or str(c["subject"]) == subject_filter)
    ]
    if not plan["cases"]:
        raise ValueError("no fitting contracts selected")
    for case in plan["cases"]:
        folder = root / case["dataset"] / str(case["subject"])
        case["directory"] = str(folder.resolve())
        for solver in ["diffsol_bdf", "diffsol_rodas5p"]:
            request = folder / (solver + "-request.json")
            result = run_native(
                cli,
                "fit",
                folder / "model.qsp",
                request,
                folder / (solver + "-result.json"),
            )
            run = json.loads(request.read_text())["problem"]["request"]["objective"][
                "simulation"
            ]["run"]
            run["parameters"].update(result["fit"]["parameters"])
            write(folder / (solver + "-prediction-request.json"), validate_native(run, "run"))
            run_native(
                cli,
                "run",
                folder / "model.qsp",
                folder / (solver + "-prediction-request.json"),
                folder / (solver + "-prediction.json"),
            )
    for filename, extra in [
        ("fit_nlmixr_omex_examples.R", False),
        ("fit_remaining_omex_examples.R", True),
    ]:
        partition = dict(
            plan, cases=[c for c in plan["cases"] if ("r_model" in c) == extra]
        )
        if partition["cases"]:
            write(root / "plan.json", partition)
            subprocess.run(
                [rscript, str(ROOT / "scripts" / filename), str(root)], check=True
            )
    write(root / "plan.json", plan)
    from compare_nlmixr_omex_fits import compare

    report = compare(root, cli_sha256=hashlib.sha256(cli.read_bytes()).hexdigest())
    if report["counts"] != {"matched_converged": 2 * len(plan["cases"])}:
        raise RuntimeError("fitting comparison did not pass")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--suite",
        required=True,
        choices=[
            "omex-rxode2",
            "mrgsolve",
            "ordinarydiffeq",
            "roadrunner",
            "copasi",
            "amici",
            "nlmixr2-bdf",
            "nlmixr2-rodas5p",
            "nlmixr2-patched-bdf",
            "nlmixr2-patched-rodas5p",
            "presets",
            "fitting",
        ],
    )
    p.add_argument("--cli", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--model")
    p.add_argument("--case")
    p.add_argument("--rscript", default="Rscript")
    p.add_argument("--julia", default="julia")
    a = p.parse_args()
    a.cli = a.cli.expanduser().resolve()
    a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=False)
    environment = json.loads((ROOT / "environment.json").read_text())
    write(
        a.output / "replay-engine.json",
        {
            "cli_sha256": hashlib.sha256(a.cli.read_bytes()).hexdigest(),
            "recorded_cli_sha256": environment["cli_sha256"],
            "same_binary": hashlib.sha256(a.cli.read_bytes()).hexdigest()
            == environment["cli_sha256"],
        },
    )
    workspace = a.output / "workspace"
    workspace.mkdir()
    if a.suite.startswith("nlmixr2-"):
        unpack("nlmixr2-simulations.omex", workspace)
        lane = {
            "nlmixr2-bdf": "conditions-bdf",
            "nlmixr2-rodas5p": "conditions-rodas5p",
            "nlmixr2-patched-bdf": "conditions-patched-rxode2-bdf",
            "nlmixr2-patched-rodas5p": "conditions-patched-rxode2-rodas5p",
        }[a.suite]
        if "patched" in a.suite:
            subprocess.run(
                [
                    a.rscript,
                    str(
                        ROOT / "upstream-patches/rxode2/validate_administered_history.R"
                    ),
                    str(a.output / "history-regressions"),
                ],
                check=True,
            )
        dataset = workspace / "nlmixr2lib-0.3.2" / lane
        if a.case:
            if not a.model:
                raise ValueError("--case requires --model")
            path = dataset / a.model / "plan.json"
            plan = json.loads(path.read_text())
            plan["cases"] = [c for c in plan["cases"] if c["condition_id"] == a.case]
            if not plan["cases"]:
                raise ValueError("unknown case")
            write(path, plan)
        command = [
            sys.executable,
            str(ROOT / "scripts/reproduce_qspquest_condition_snapshot.py"),
            "--dataset",
            str(dataset),
            "--cli",
            str(a.cli),
            "--rscript",
            a.rscript,
            "--output",
            str(a.output / "results"),
        ]
        if a.model:
            command += ["--model-id", a.model]
        subprocess.run(command, check=True)
        report = json.loads((a.output / "results/summary.json").read_text())
        expected_report = json.loads((dataset / "summary.json").read_text())
        expected_cases = {
            (m["model_id"], c["condition_id"]): c["expected_status"]
            for m in expected_report["models"]
            for c in m["cases"]
        }
        for model in report["models"]:
            for case in model["cases"]:
                if (
                    case["status"]
                    != expected_cases[(model["model_id"], case["condition_id"])]
                ):
                    raise RuntimeError("condition outcome differs from recorded result")
    elif a.suite == "fitting":
        unpack("individual-fitting.omex", workspace)
        report = fit(workspace, a.cli, a.model, a.case, a.rscript)
    elif a.suite == "presets":
        from trajectory_comparison import compare_columns, read_reference

        unpack("source-presets.omex", workspace)
        rows = []
        for folder in sorted(
            (workspace / "additional-model-simulations-20261005").glob("*/*")
        ):
            if (
                not folder.is_dir()
                or (a.model and folder.parent.name != a.model)
                or (a.case and folder.name != a.case)
            ):
                continue
            native = run_native(
                a.cli,
                "run",
                folder / "model.json",
                folder / "request.json",
                folder / "result.json",
            )
            reference = read_reference(folder / "reference.csv")
            test = compare_columns(reference, native, [c for c in reference if c != "time"])
            rows.append(
                {"model_id": folder.parent.name, "scenario_id": folder.name, **test}
            )
        if not rows:
            raise ValueError("no presets selected")
        report = {
            "cases": rows,
            "counts": dict(collections.Counter(r["status"] for r in rows)),
        }
        if any(r["status"] != "matched" for r in rows):
            raise RuntimeError("preset comparison did not pass")
    else:
        if a.case:
            raise ValueError("OMEX reference suites use --model, not --case")
        unpack("omex-simulations.omex", workspace)
        selected(workspace, a.cli, a.model, None)
        reference = a.output / "reference"
        if a.suite in ["roadrunner", "copasi", "amici"]:
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/validate_omex_independent_engines.py"),
                    "--validation",
                    str(workspace),
                    "--output",
                    str(reference),
                    "--engine",
                    a.suite,
                ],
                check=True,
            )
        elif a.suite == "mrgsolve":
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/prepare_omex_mrgsolve.py"),
                    "--validation",
                    str(workspace),
                    "--out",
                    str(reference),
                ],
                check=True,
            )
            subprocess.run(
                [
                    a.rscript,
                    str(ROOT / "scripts/simulate_omex_mrgsolve.R"),
                    str(reference / "batch.json"),
                ],
                check=True,
            )
        elif a.suite == "ordinarydiffeq":
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/prepare_omex_julia.py"),
                    "--validation",
                    str(workspace),
                    "--out",
                    str(reference),
                ],
                check=True,
            )
            subprocess.run([a.julia, str(reference / "run.jl")], check=True)
        else:
            from omex_to_rxode2 import archive_members, translate

            reference.mkdir()
            batch = []
            for archive in sorted(
                (workspace / "selected-models/models").glob("*/*/model.omex")
            ):
                data = archive.read_bytes()
                _, index = archive_members(data)
                folder = reference / index["model_id"]
                folder.mkdir()
                for c in index["scenarios"]:
                    sid = c["scenario_id"]
                    path = folder / (sid + "-experiment.json")
                    write(path, translate(data, sid))
                    batch.append(
                        {
                            "experiment": str(path),
                            "output": index["model_id"] + "/" + sid,
                        }
                    )
            write(
                reference / "batch.json",
                {"schema": "ubi.omex.rxode2-batch/v1", "cases": batch},
            )
            subprocess.run(
                [
                    a.rscript,
                    str(ROOT / "scripts/simulate_omex_rxode2.R"),
                    str(reference / "batch.json"),
                    str(reference),
                ],
                check=True,
            )
        report = compare_reference_folder(workspace, reference)
    if not report.get("models", report.get("cases", report.get("solver_runs"))):
        raise RuntimeError("empty replay")
    write(a.output / "summary.json", report)
    print(json.dumps(report.get("counts", {}), indent=2))


if __name__ == "__main__":
    main()
