#!/usr/bin/env python3
"""Compare completed matched fits, keeping convergence and numerical agreement separate."""
import argparse, collections, json, math
from pathlib import Path
from trajectory_comparison import finite, same_grid, validate_run, vector


def compare(root, cli_sha256=None):
    plan = json.loads((root / "plan.json").read_text())
    limits = plan["comparison_limits"]
    rows = []
    keys = [(c["dataset"], str(c["subject"])) for c in plan["cases"]]
    if not keys or len(keys) != len(set(keys)):
        raise ValueError("Empty or duplicate fitting contracts")
    for case in plan["cases"]:
        folder = root / case["dataset"] / str(case["subject"])
        reference_path = folder / "nlmixr2-result.json"
        reference = (
            json.loads(reference_path.read_text())
            if reference_path.exists()
            else {"status": "missing"}
        )
        for solver in ["diffsol_bdf", "diffsol_rodas5p"]:
            row = {
                "dataset": case["dataset"],
                "subject": case["subject"],
                "solver": solver,
                "observations": case["observations"],
            }
            path = folder / (solver + "-result.json")
            native = json.loads(path.read_text()) if path.exists() else {}
            if reference.get("status") != "executed":
                row.update(status="reference_failed", reference=reference)
            elif "fit" not in native:
                row.update(status="native_failed", error=native.get("error", native))
            else:
                fit = native["fit"]
                estimated = case["estimated"]
                if (not estimated or len(estimated) != len(set(estimated))
                        or set(reference["parameters"]) != set(estimated)
                        or set(fit["parameters"]) != set(estimated)):
                    raise ValueError("Estimated parameter inventory differs")
                if any(not finite(reference["parameters"][n])
                       or not finite(fit["parameters"][n]["value"]) for n in estimated):
                    raise ValueError("Nonfinite or nonnumeric fitted parameter")
                if not finite(reference["nll"]) or not finite(fit["objective"]["negative_log_likelihood"]):
                    raise ValueError("Nonfinite or nonnumeric likelihood")
                fit_request = json.loads((folder / (solver + "-request.json")).read_text())
                bounds = fit_request["problem"]["request"]["bounds"]
                units = {b["parameter"]: b["lower"]["unit"] for b in bounds}
                if (len(units) != len(bounds) or set(units) != set(estimated)
                        or any(fit["parameters"][n].get("unit") != units[n] for n in estimated)):
                    raise ValueError("Fitted parameter units or bounds inventory differ")
                row["native_convergence"] = fit["status"]
                row["reference_convergence"] = reference.get("convergence")
                row["parameters"] = {
                    n: {
                        "native": fit["parameters"][n]["value"],
                        "reference": v,
                        "relative_difference": abs(fit["parameters"][n]["value"] - v)
                        / max(abs(v), 1e-12),
                    }
                    for n, v in reference["parameters"].items()
                }
                parameter_match = all(
                    abs(v["native"] - v["reference"])
                    <= limits["parameter_atol"]
                    + limits["parameter_rtol"] * abs(v["reference"])
                    for v in row["parameters"].values()
                )
                row["nll_difference"] = (
                    fit["objective"]["negative_log_likelihood"] - reference["nll"]
                )
                nll_match = abs(row["nll_difference"]) <= limits["nll_atol"]
                prediction_path = folder / (solver + "-prediction.json")
                prediction = (
                    json.loads(prediction_path.read_text())
                    if prediction_path.exists()
                    else {}
                )
                if "outputs" in prediction:
                    fit_request = json.loads((folder / (solver + "-request.json")).read_text())
                    request = fit_request["problem"]["request"]["objective"]["simulation"]["run"]
                    outputs = validate_run(prediction, request)
                    if set(outputs) != {"cp"}:
                        raise ValueError("Fitting prediction output inventory differs")
                    if outputs["cp"]["unit"] != "1":
                        raise ValueError("Fitting prediction coordinate unit differs")
                    times = [x["TIME"] for x in reference["predictions"]]
                    same_grid(prediction["times"], times)
                    count = case["observations"]
                    if type(count) is not int or count <= 0 or len(times) != count:
                        raise ValueError("Declared fitting observation count differs")
                    values = outputs["cp"]["values"]
                    refs = vector([x["IPRED"] for x in reference["predictions"]], count, "Reference prediction")
                    row["prediction_max_absolute_difference"] = max(
                        abs(a - b) for a, b in zip(values, refs)
                    )
                    prediction_match = all(
                        abs(a - b)
                        <= limits["prediction_atol"]
                        + limits["prediction_rtol"] * abs(b)
                        for a, b in zip(values, refs)
                    )
                else:
                    prediction_match = False
                    row["prediction_error"] = prediction.get("error")
                row["numeric_match"] = (
                    parameter_match and nll_match and prediction_match
                )
                row["status"] = (
                    "matched_converged"
                    if row["numeric_match"] and fit["status"] == "converged"
                    else (
                        "matched_not_converged"
                        if row["numeric_match"]
                        else "numerical_mismatch"
                    )
                )
            rows.append(row)
    summary = {
        "schema": "qspquest.matched-example-fitting/v1",
        "contracts": len(plan["cases"]),
        "solver_runs": len(rows),
        "cli_sha256": cli_sha256 or plan["cli_sha256"],
        "recorded_cli_sha256": plan["cli_sha256"],
        "comparison_limits": limits,
        "counts": dict(collections.Counter(r["status"] for r in rows)),
        "by_dataset": {
            n: {
                s: dict(
                    collections.Counter(
                        r["status"]
                        for r in rows
                        if r["dataset"] == n and r["solver"] == s
                    )
                )
                for s in ["diffsol_bdf", "diffsol_rodas5p"]
            }
            for n in sorted({c["dataset"] for c in plan["cases"]})
        },
        "datasets": plan["datasets"],
        "rows": rows,
    }
    (root / "comparison.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: summary[k]
                for k in ["contracts", "solver_runs", "counts", "by_dataset"]
            },
            indent=2,
        )
    )
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    compare(p.parse_args().directory)
