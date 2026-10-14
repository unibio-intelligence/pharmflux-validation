"""Generate independent OrdinaryDiffEq Rodas5P executions from verified SBML ASTs."""

import argparse, json, re, hashlib
from pathlib import Path
from omex_to_rxode2 import archive_members, translate


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--validation", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    lines = [
        "using OrdinaryDiffEq, DelimitedFiles",
        "function simulate(f!, output!, initial, parameters, times, events, folder, rtol, atol)",
        "    states=copy(initial); frames=Vector{Vector{Float64}}();last=times[1]",
        "    for (j,t) in enumerate(times)",
        "        if t>last",
        "            prob=ODEProblem(f!,states,(last,t),parameters)",
        "            sol=solve(prob,Rodas5P();reltol=rtol,abstol=atol,maxiters=1000000,save_everystep=false)",
        '            if !(string(sol.retcode) in ("Success","ReturnCode.Success"));error(string(sol.retcode));end',
        "            states=copy(sol.u[end])",
        "        end",
        "        if j==1 && haskey(events,t);states,parameters=events[t](states,parameters,t);end",
        "        values=output!(states,parameters,t);push!(frames,vcat(t,values))",
        "        if j>1 && haskey(events,t);states,parameters=events[t](states,parameters,t);end",
        "        last=t",
        "    end",
        "    return permutedims(hcat(frames...))",
        "end",
    ]
    emitted = set()
    for archive in sorted(
        (a.validation / "selected-models/models").glob("*/*/model.omex")
    ):
        data = archive.read_bytes()
        _, index = archive_members(data)
        for case in index["scenarios"]:
            name = case["scenario_id"]
            d = translate(data, name)
            folder = a.out / index["model_id"] / name
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "experiment.json").write_text(json.dumps(d, indent=2) + "\n")
            key = "f" + hashlib.sha256(d["model_code"].encode()).hexdigest()[:12]
            states = list(d["initial"])
            params = list(d["parameters"])
            variables = (
                "\n".join(n + " = u[" + str(i + 1) + "]" for i, n in enumerate(states))
                + "\n"
                + "\n".join(
                    n + " = p[" + str(i + 1) + "]" for i, n in enumerate(params)
                )
            )
            definitions = "\n".join(d["definitions"])
            rates = [
                line for line in d["model_code"].splitlines() if line.startswith("d/dt")
            ]
            captures = [
                line for line in d["model_code"].splitlines() if line.startswith("obs")
            ]
            if key not in emitted:
                lines += (
                    ["function " + key + "(du,u,p,t)", variables, definitions]
                    + [
                        re.sub(
                            r"d/dt\((s\d+)\)",
                            lambda m: "du[" + str(states.index(m[1]) + 1) + "]",
                            line,
                        )
                        for line in rates
                    ]
                    + [
                        "nothing",
                        "end",
                        "function " + key + "out(u,p,t)",
                        variables,
                        definitions,
                    ]
                    + captures
                    + ["[" + ",".join(d["output_columns"].values()) + "]", "end"]
                )
                emitted.add(key)
            ev = []
            for event in d["events"]:
                updates = event["updates"]
                assignments = "\n".join(
                    "v" + str(i) + " = " + expr
                    for i, expr in enumerate(updates.values())
                )
                writes = []
                for i, n in enumerate(updates):
                    writes.append(
                        (
                            "u[" + str(states.index(n) + 1) + "]"
                            if n in states
                            else "p[" + str(params.index(n) + 1) + "]"
                        )
                        + " = v"
                        + str(i)
                    )
                ev.append(
                    repr(float(event["time"]))
                    + " => ((u,p,t)->begin\n"
                    + variables
                    + "\nclockorigin=0.0\n"
                    + definitions
                    + "\n"
                    + assignments
                    + "\n"
                    + "\n".join(writes)
                    + "\n(u,p)\nend)"
                )
            atol = d["solver"]["atol"]
            atol = min(atol.values()) if isinstance(atol, dict) else atol
            path = str((folder / "trajectory.csv").resolve())
            header = ",".join(["time"] + list(d["output_columns"]))
            lines += [
                "try",
                "result=simulate("
                + key
                + ","
                + key
                + "out,"
                + repr(list(d["initial"].values()))
                + ","
                + repr(list(d["parameters"].values()))
                + ","
                + repr(d["times"])
                + ",Dict{Float64,Function}("
                + ",".join(ev)
                + "),"
                + json.dumps(str(folder.resolve()))
                + ","
                + repr(min(d["solver"]["rtol"], 1e-9))
                + ","
                + repr(min(atol, 1e-12))
                + ")",
                "open(" + json.dumps(path) + ',"w") do io',
                "println(io," + json.dumps(header) + ")",
                "writedlm(io,result,',')",
                "end",
                "println("
                + json.dumps(index["model_id"] + " " + name + " executed")
                + ")",
                "catch e",
                "open("
                + json.dumps(str((folder / "error.log").resolve()))
                + ',"w") do io; showerror(io,e,catch_backtrace());end',
                "println("
                + json.dumps(index["model_id"] + " " + name + " failed")
                + ")",
                "end",
            ]
    (a.out / "run.jl").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
