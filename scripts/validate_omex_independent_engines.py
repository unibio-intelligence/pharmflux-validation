#!/usr/bin/env python3
"""Independent deterministic simulations of byte-verified SBML/SED-ML OMEX inputs."""
import argparse, hashlib, json, math, os, subprocess, traceback
from pathlib import Path
from collections import Counter
import numpy as np
import pandas as pd
import libsbml as sb
from omex_to_rxode2 import archive_members, translate, metadata
from normalize_omex_sbml_time import normalize


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_roadrunner(data, scenario, d):
    import roadrunner

    normalized, changes = normalize(data)
    members, index = archive_members(normalized)
    entry = next(x for x in index["scenarios"] if x["scenario_id"] == scenario)
    doc = sb.readSBMLFromString(members[entry["sbml"]].decode())
    m = doc.getModel()
    species = [m.getSpecies(i).getId() for i in range(m.getNumSpecies())]
    params = [m.getParameter(i).getId() for i in range(m.getNumParameters())]
    symbols = {
        **dict(zip(d["initial"], species)),
        **dict(zip(["p" + str(i) for i in range(len(params))], params)),
    }
    # Segment scheduled assignments explicitly to preserve archived event-side sampling.
    while m.getNumEvents():
        m.removeEvent(0)
    rr = roadrunner.RoadRunner(sb.writeSBMLToString(doc))
    rr.integrator = "cvode"
    rr.integrator.relative_tolerance = min(d["solver"]["rtol"], 1e-9)
    at = d["solver"]["atol"]
    if isinstance(at, dict):
        alias = {original: n for n, original in symbols.items()}
        rr.integrator.setValue("absolute_tolerance", [at[alias[n]] for n in species])
    else:
        rr.integrator.absolute_tolerance = min(at, 1e-12)
    rr.integrator.maximum_num_steps = 1000000
    states = dict(d["initial"])
    parameters = dict(d["parameters"])
    rr.time = d["times"][0]

    def expression(expr, env):
        env = {
            **{
                "exp": math.exp,
                "log": math.log,
                "abs": abs,
                "min": min,
                "max": max,
                "floor": math.floor,
                "ceil": math.ceil,
                "sin": math.sin,
                "cos": math.cos,
                "tan": math.tan,
                "ifelse": lambda c, a, b: a if c else b,
            },
            **env,
        }
        return eval(expr.replace("^", "**"), {"__builtins__": {}}, env)

    def apply(t):
        nonlocal states, parameters
        for event in d["events"]:
            if event["time"] != t:
                continue
            env = {**states, **parameters, "t": t, "clockorigin": 0}
            for definition in d["definitions"]:
                name, expr = definition.rstrip(";").split("=", 1)
                env[name.strip()] = expression(expr, env)
            updates = {
                name: expression(expr, env) for name, expr in event["updates"].items()
            }
            for n, v in updates.items():
                if n in states:
                    states[n] = v
                    rr["[" + symbols[n] + "]"] = v
                else:
                    parameters[n] = v
                    rr[symbols[n]] = v

    for n, v in states.items():
        rr["[" + symbols[n] + "]"] = v
    for n, v in parameters.items():
        if n != "clockorigin":
            rr[symbols[n]] = v
    apply(d["times"][0])
    rows = []
    last = d["times"][0]
    outputs = {}
    for i, n in enumerate(species):
        outputs["state__" + str(metadata(m.getSpecies(i)).get("native_id") or n)] = (
            "[" + n + "]"
        )
    for i, n in enumerate(params):
        meta = metadata(m.getParameter(i))
        if meta.get("role") == "derived_output":
            outputs["output__" + str(meta.get("native_id") or n)] = n
    for t in d["times"]:
        if t > last:
            rr.oneStep(last, t - last, True)
        states = {n: float(rr["[" + symbols[n] + "]"]) for n in states}
        rows.append(
            {"time": t, **{name: float(rr[target]) for name, target in outputs.items()}}
        )
        if t != d["times"][0]:
            apply(t)
        last = t
    return pd.DataFrame(rows), {
        "engine": "RoadRunner",
        "version": roadrunner.__version__,
        "algorithm": "CVODE BDF",
        "rtol": rr.integrator.relative_tolerance,
        "atol": (
            list(rr.integrator.absolute_tolerance)
            if isinstance(rr.integrator.absolute_tolerance, (list, tuple, np.ndarray))
            else rr.integrator.absolute_tolerance
        ),
        "event_execution": "segmented simultaneous SBML assignments",
        "sampling": d["sampling"],
        "sbml_time_normalization": changes,
        "executed_sbml_sha256": hashlib.sha256(
            sb.writeSBMLToString(doc).encode()
        ).hexdigest(),
    }


def compare(frame, native, d):
    from trajectory_comparison import compare_columns

    if not frame.columns.is_unique:
        raise ValueError("Duplicate reference columns")
    reference = {name: frame[name].tolist() for name in frame.columns}
    return compare_columns(reference, native, d["output_columns"], d.get("native_aliases"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--validation", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--engine", choices=["roadrunner", "copasi", "amici"], default="roadrunner"
    )
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for archive in sorted(
        (a.validation / "selected-models/models").glob("*/*/model.omex"),
        key=lambda p: ("liu_" in str(p), str(p)),
    ):
        data = archive.read_bytes()
        _, index = archive_members(data)
        for case in index["scenarios"]:
            name = case["scenario_id"]
            folder = a.output / index["model_id"] / name
            folder.mkdir(parents=True, exist_ok=True)
            row = {
                "model_id": index["model_id"],
                "scenario_id": name,
                "archive_sha256": sha(archive),
            }
            try:
                d = translate(data, name)
                from trajectory_comparison import projection_aliases
                d["native_aliases"] = projection_aliases(index)
                if a.engine == "roadrunner":
                    frame, provenance = run_roadrunner(data, name, d)
                else:
                    from omex_reference_backends import run_copasi, run_amici

                    frame, provenance = (
                        run_copasi if a.engine == "copasi" else run_amici
                    )(data, name, d, folder)
                frame.to_csv(folder / "trajectory.csv", index=False)
                provenance.update(
                    archive_sha256=sha(archive),
                    sbml_sha256=d["sbml_sha256"],
                    sedml_sha256=d["sedml_sha256"],
                    adapter_sha256=sha(Path(__file__)),
                    trajectory_sha256=sha(folder / "trajectory.csv"),
                )
                (folder / "provenance.json").write_text(
                    json.dumps(provenance, indent=2) + "\n"
                )
                tests = {}
                for method in ["diffsol_bdf", "diffsol_rodas5p"]:
                    path = (
                        a.validation
                        / "selected-model-simulations"
                        / index["model_id"]
                        / name
                        / (method + "-result.json")
                    )
                    native = json.loads(path.read_text())
                    from trajectory_comparison import validate_run
                    request = json.loads(path.with_name(method + "-request.json").read_text())
                    validate_run(native, request)
                    tests[method] = compare(frame, native, d)
                    tests[method]["native_result_sha256"] = sha(path)
                row.update(
                    status=(
                        "matched"
                        if all(t["status"] == "matched" for t in tests.values())
                        else "mismatch"
                    ),
                    comparisons=tests,
                )
            except Exception as e:
                row.update(status="failed", error=str(e))
                (folder / "error.log").write_text(traceback.format_exc())
            (folder / "comparison.json").write_text(json.dumps(row, indent=2) + "\n")
            rows.append(row)
            (a.output / "summary.json").write_text(
                json.dumps(
                    {
                        "scope": "Deterministic OMEX simulations; no fitting equivalence claim",
                        "engine": a.engine,
                        "limits": {"atol": 1e-8, "rtol": 1e-4},
                        "counts": dict(Counter(r["status"] for r in rows)),
                        "cases": rows,
                    },
                    indent=2,
                )
                + "\n"
            )
            print(
                index["model_id"], name, row["status"], row.get("error", ""), flush=True
            )

    if not rows or any(r["status"] != "matched" for r in rows):
        raise SystemExit("Independent reference comparison failed or selected no cases")


if __name__ == "__main__":
    main()
