"""Independent SBML importer backends; event-side semantics are explicit."""

import hashlib, math, json, os
from pathlib import Path
import numpy as np
import pandas as pd
import libsbml as sb
from omex_to_rxode2 import archive_members, metadata
from normalize_omex_sbml_time import normalize

CACHE = {}


def prepare(data, scenario, d):
    normalized, changes = normalize(data)
    members, index = archive_members(normalized)
    entry = next(x for x in index["scenarios"] if x["scenario_id"] == scenario)
    doc = sb.readSBMLFromString(members[entry["sbml"]].decode())
    m = doc.getModel()
    while m.getNumEvents():
        m.removeEvent(0)
    species = [m.getSpecies(i).getId() for i in range(m.getNumSpecies())]
    params = [m.getParameter(i).getId() for i in range(m.getNumParameters())]
    symbols = {
        **dict(zip(d["initial"], species)),
        **dict(zip(["p" + str(i) for i in range(len(params))], params)),
    }
    outputs = {}
    for i, n in enumerate(species):
        outputs["state__" + str(metadata(m.getSpecies(i)).get("native_id") or n)] = (
            "s" + str(i)
        )
    for i, n in enumerate(params):
        meta = metadata(m.getParameter(i))
        if meta.get("role") == "derived_output":
            outputs["output__" + str(meta.get("native_id") or n)] = "p" + str(i)
    return doc, symbols, outputs, changes


def evaluate(expr, env):
    funcs = {
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
    }
    return eval(expr.replace("^", "**"), {"__builtins__": {}}, {**funcs, **env})


def definitions(d, states, parameters, t):
    env = {**states, **parameters, "t": t, "clockorigin": 0}
    for definition in d["definitions"]:
        name, expr = definition.rstrip(";").split("=", 1)
        env[name.strip()] = evaluate(expr, env)
    return env


def apply_events(d, states, parameters, t):
    for event in d["events"]:
        if event["time"] != t:
            continue
        env = definitions(d, states, parameters, t)
        updates = {n: evaluate(expr, env) for n, expr in event["updates"].items()}
        for n, v in updates.items():
            if n in states:
                states[n] = v
            else:
                parameters[n] = v


def run_copasi(data, scenario, d, folder):
    import basico, COPASI

    doc, symbols, outputs, changes = prepare(data, scenario, d)
    m = doc.getModel()
    for i in range(m.getNumSpecies()):
        m.getSpecies(i).setName(m.getSpecies(i).getId())
    for i in range(m.getNumParameters()):
        m.getParameter(i).setName(m.getParameter(i).getId())
    clock = m.createParameter()
    clock.setId("ubi_reference_clockorigin")
    clock.setName("ubi_reference_clockorigin")
    clock.setValue(0)
    clock.setConstant(True)

    def shift_time(node):
        if node.getType() == sb.AST_NAME_TIME:
            shifted = sb.parseL3Formula("time + ubi_reference_clockorigin")
            node.setType(shifted.getType())
            node.addChild(shifted.getChild(0).deepCopy())
            node.addChild(shifted.getChild(1).deepCopy())
            return
        for k in range(node.getNumChildren()):
            shift_time(node.getChild(k))

    for k in range(m.getNumRules()):
        shift_time(m.getRule(k).getMath())
    dm = basico.create_datamodel()
    if not dm.importSBMLFromString(sb.writeSBMLToString(doc), None, True):
        raise ValueError("COPASI SBML import failed")
    basico.set_current_model(dm)
    # SBML amount states occupy a constant unit-size compartment. COPASI's numeric
    # concentration coordinate equals the archived amount coordinate; particle
    # number output would introduce an Avogadro conversion and is not used.
    if any(
        abs(m.getCompartment(i).getSize() - 1) > 1e-15
        for i in range(m.getNumCompartments())
    ):
        raise ValueError("COPASI adapter requires unit-size compartments")
    states = dict(d["initial"])
    parameters = dict(d["parameters"])
    times = d["times"]
    rows = []
    bounds = sorted(set([times[0], times[-1]] + [e["time"] for e in d["events"]]))
    apply_events(d, states, parameters, times[0])
    atol = min(
        (
            min(d["solver"]["atol"].values())
            if isinstance(d["solver"]["atol"], dict)
            else d["solver"]["atol"]
        ),
        1e-12,
    )
    rtol = min(d["solver"]["rtol"], 1e-9)
    for left, right in zip(bounds, bounds[1:]):
        for n, v in states.items():
            basico.set_species(
                symbols[n], exact=True, initial_concentration=v, model=dm
            )
        for n, v in parameters.items():
            if n != "clockorigin":
                basico.set_parameters(symbols[n], exact=True, initial_value=v, model=dm)
        dm.getModel().setInitialTime(0)
        basico.set_parameters(
            "ubi_reference_clockorigin", exact=True, initial_value=left, model=dm
        )
        sample = sorted(set([left, right] + [t for t in times if left <= t <= right]))
        frame = basico.run_time_course(
            model=dm,
            values=[t - left for t in sample],
            initial_time=0,
            start_time=0,
            duration=right - left,
            r_tol=rtol,
            a_tol=atol,
            max_steps=1000000,
            use_numbers=False,
            use_initial_values=True,
            update_model=True,
        )
        if frame is None or len(frame) != len(sample):
            raise ValueError(
                "COPASI observation grid mismatch: "
                + str((None if frame is None else len(frame), len(sample), left, right))
            )
        if not np.allclose(
            frame.index.to_numpy(), np.array(sample) - left, rtol=0, atol=1e-10
        ):
            raise ValueError("COPASI time coordinate mismatch")
        for j, t in enumerate(sample):
            states = {n: float(frame.iloc[j][symbols[n]]) for n in states}
            if t in times and (t > left or left == times[0]):
                env = definitions(d, states, parameters, t)
                rows.append({"time": t, **{n: env[s] for n, s in outputs.items()}})
        apply_events(d, states, parameters, right)
    basico.remove_datamodel(dm)
    return pd.DataFrame(rows), {
        "engine": "COPASI",
        "version": COPASI.CVersion.VERSION.getVersion(),
        "algorithm": "LSODA",
        "rtol": rtol,
        "atol": atol,
        "sampling": d["sampling"],
        "sbml_time_normalization": changes,
    }


def run_amici(data, scenario, d, folder):
    import amici
    from amici.sim.sundials import (
        run_simulation,
        LinearMultistepMethod,
        NonlinearSolverIteration,
    )

    doc, symbols, outputs, changes = prepare(data, scenario, d)
    m = doc.getModel()
    assignments = {
        m.getRule(i).getVariable()
        for i in range(m.getNumRules())
        if m.getRule(i).isAssignment()
    }
    for i in range(m.getNumParameters()):
        p = m.getParameter(i)
        if p.getId() not in assignments:
            p.setConstant(True)
    key = d["model_id"]
    compiled = (
        Path(
            os.environ.get(
                "AMICI_MODEL_CACHE", str(folder.parents[1] / "compiled-models")
            )
        )
        / key
    )
    if key not in CACHE:
        compiled.mkdir(parents=True, exist_ok=True)
        source = compiled / "model.xml"
        source.write_text(sb.writeSBMLToString(doc))
        name = "ref_" + hashlib.sha256(key.encode()).hexdigest()[:12]
        for element in [doc.getModel()] + [
            doc.getModel().getElementBySId(n) for n in symbols.values()
        ]:
            if element is not None:
                element.unsetAnnotation()
        source.write_text(sb.writeSBMLToString(doc))
        if (compiled / name).exists() and list((compiled / name).glob("*.so")):
            model = amici.import_model_module(name, str(compiled)).get_model()
        else:
            importer = amici.SbmlImporter(str(source), discard_annotations=True)
            model = importer.sbml2amici(
                name,
                compiled,
                generate_sensitivity_code=False,
                compute_conservation_laws=False,
                verbose=False,
            )
            if model is None:
                model = amici.import_model_module(name, str(compiled)).get_model()
        CACHE[key] = model
    model = CACHE[key]
    solver = model.create_solver()
    solver.set_relative_tolerance(min(d["solver"]["rtol"], 1e-9))
    atol = min(
        (
            min(d["solver"]["atol"].values())
            if isinstance(d["solver"]["atol"], dict)
            else d["solver"]["atol"]
        ),
        1e-12,
    )
    solver.set_absolute_tolerance(atol)
    solver.set_max_steps(1000000)
    algorithm = "CVODES BDF/Newton"
    if "yuan_" in d["model_id"]:
        # The original equations contain a fractional power at zero. Its analytic
        # Jacobian is singular there; Adams/fixed-point avoids requesting that Jacobian.
        solver.set_linear_multistep_method(LinearMultistepMethod.adams)
        solver.set_stability_limit_flag(False)
        solver.set_non_linear_solver_iteration(NonlinearSolverIteration.fixedpoint)
        algorithm = "CVODES Adams/fixed-point (singular initial analytic Jacobian)"
    stateids = list(model.get_state_ids())
    paramids = list(model.get_free_parameter_ids())
    states = dict(d["initial"])
    parameters = dict(d["parameters"])
    times = d["times"]
    rows = []
    bounds = sorted(set([times[0], times[-1]] + [e["time"] for e in d["events"]]))
    apply_events(d, states, parameters, times[0])
    reverse = {original: alias for alias, original in symbols.items()}
    for left, right in zip(bounds, bounds[1:]):
        model.set_initial_state([states[reverse[n]] for n in stateids])
        model.set_t0(left)
        model.set_free_parameters([parameters[reverse[n]] for n in paramids])
        sample = sorted(set([left, right] + [t for t in times if left <= t <= right]))
        model.set_timepoints(sample)
        result = run_simulation(model, solver)
        if result.status != 0:
            raise ValueError("AMICI simulation status " + str(result.status))
        for j, t in enumerate(sample):
            states = {reverse[n]: float(result.x[j, i]) for i, n in enumerate(stateids)}
            if t in times and (t > left or left == times[0]):
                env = definitions(d, states, parameters, t)
                rows.append({"time": t, **{n: env[s] for n, s in outputs.items()}})
        apply_events(d, states, parameters, right)
    return pd.DataFrame(rows), {
        "engine": "AMICI",
        "version": amici.__version__,
        "algorithm": algorithm,
        "rtol": min(d["solver"]["rtol"], 1e-9),
        "atol": atol,
        "sampling": d["sampling"],
        "sbml_time_normalization": changes,
    }
