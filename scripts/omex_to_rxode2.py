#!/usr/bin/env python3
"""Load the declared Ubi OMEX ODE profile into rxode2, without QSPQuest lowering.

Executable equations and scheduled events are read from SBML. SED-ML selects
the experiment; the execution annotation preserves exact event-side sampling.
This is deterministic simulation interoperability, not an NLME fitting adapter.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import posixpath
import stat
import zipfile
from xml.etree import ElementTree as ET

import libsbml as sb


def sha(data):
    return hashlib.sha256(data).hexdigest()


def archive_members(data):
    if len(data) > 50_000_000:
        raise ValueError("OMEX archive too large")
    members = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = z.infolist()
        if len(infos) > 5000 or sum(i.file_size for i in infos) > 200_000_000:
            raise ValueError("OMEX expansion budget exceeded")
        for i in infos:
            n = i.filename
            if (
                n in members
                or n.startswith("/")
                or posixpath.normpath(n) != n
                or ".." in n.split("/")
                or "\\" in n
            ):
                raise ValueError("duplicate or unsafe archive member")
            if (
                stat.S_ISLNK(i.external_attr >> 16)
                or i.flag_bits & 1
                or i.file_size > 10_000_000
            ):
                raise ValueError("unsupported archive member")
            members[n] = z.read(i)
    index = json.loads(members["index.json"])
    if index["profile"] != "ubi.omex.rust-ode/v1":
        raise ValueError("unsupported OMEX execution profile")
    if set(members) != set(index["members"]) | {"index.json", "manifest.xml"}:
        raise ValueError("archive inventory mismatch")
    for name, expected in index["members"].items():
        if sha(members[name]) != expected:
            raise ValueError("archive member hash mismatch: " + name)
    manifest = xml(members["manifest.xml"])
    locations = [e.attrib["location"] for e in manifest]
    if len(set(locations)) != len(locations) or set(locations) != {"."} | {
        "./" + n for n in members if n != "manifest.xml"
    }:
        raise ValueError("manifest mismatch")
    return members, index


def xml(data):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("XML entities prohibited")
    return ET.fromstring(data)


def metadata(element):
    def visit(node):
        if (
            node.getName() == "metadata"
            and node.getURI() == "https://unibio.ai/ns/pkpd"
        ):
            return json.loads(
                "".join(
                    node.getChild(i).getCharacters()
                    for i in range(node.getNumChildren())
                )
            )
        for i in range(node.getNumChildren()):
            found = visit(node.getChild(i))
            if found is not None:
                return found
        return None

    node = element.getAnnotation()
    return (visit(node) if node is not None else None) or {}


class MathRenderer:
    def __init__(self, symbols, functions):
        self.symbols, self.functions = symbols, functions

    def render(self, n, bindings=None, depth=0):
        if depth > 128:
            raise ValueError("expression depth exceeded")
        bindings = bindings or {}
        render = lambda c: self.render(c, bindings, depth + 1)
        t = n.getType()
        children = [n.getChild(i) for i in range(n.getNumChildren())]
        if n.isNumber():
            v = n.getValue()
            if not math.isfinite(v):
                raise ValueError("nonfinite mathematical constant")
            return format(v, ".17g")
        if t == sb.AST_CONSTANT_TRUE:
            return "1"
        if t == sb.AST_CONSTANT_FALSE:
            return "0"
        if t == sb.AST_NAME_TIME:
            return "(t + clockorigin)"
        if n.isName():
            if n.getName() == "t":
                return "(t + clockorigin)"
            if n.getName() in bindings:
                return bindings[n.getName()]
            if n.getName() not in self.symbols:
                raise ValueError("unknown SBML symbol: " + n.getName())
            return self.symbols[n.getName()]
        operators = {
            sb.AST_PLUS: "+",
            sb.AST_MINUS: "-",
            sb.AST_TIMES: "*",
            sb.AST_DIVIDE: "/",
            sb.AST_POWER: "^",
            sb.AST_FUNCTION_POWER: "^",
            sb.AST_RELATIONAL_EQ: "==",
            sb.AST_RELATIONAL_NEQ: "!=",
            sb.AST_RELATIONAL_LT: "<",
            sb.AST_RELATIONAL_LEQ: "<=",
            sb.AST_RELATIONAL_GT: ">",
            sb.AST_RELATIONAL_GEQ: ">=",
            sb.AST_LOGICAL_AND: "&",
            sb.AST_LOGICAL_OR: "|",
        }
        if t in operators:
            if len(children) == 1 and t == sb.AST_MINUS:
                return "(-" + render(children[0]) + ")"
            return (
                "(" + (" " + operators[t] + " ").join(render(c) for c in children) + ")"
            )
        if t == sb.AST_LOGICAL_NOT:
            return "(!" + render(children[0]) + ")"
        if t == sb.AST_FUNCTION_PIECEWISE:
            if len(children) < 3 or len(children) % 2 == 0:
                raise ValueError("piecewise needs explicit otherwise")
            result = render(children[-1])
            for i in range(len(children) - 3, -1, -2):
                result = (
                    "ifelse("
                    + render(children[i + 1])
                    + ", "
                    + render(children[i])
                    + ", "
                    + result
                    + ")"
                )
            return result
        functions = {
            sb.AST_FUNCTION_EXP: "exp",
            sb.AST_FUNCTION_LN: "log",
            sb.AST_FUNCTION_ABS: "abs",
            sb.AST_FUNCTION_FLOOR: "floor",
            sb.AST_FUNCTION_CEILING: "ceil",
            sb.AST_FUNCTION_MIN: "min",
            sb.AST_FUNCTION_MAX: "max",
            sb.AST_FUNCTION_SIN: "sin",
            sb.AST_FUNCTION_COS: "cos",
            sb.AST_FUNCTION_TAN: "tan",
        }
        if t in functions:
            return functions[t] + "(" + ", ".join(render(c) for c in children) + ")"
        if t == sb.AST_FUNCTION_LOG:
            return (
                "(log(" + render(children[-1]) + ") / log(" + render(children[0]) + "))"
            )
        if t == sb.AST_FUNCTION_ROOT:
            return "(" + render(children[-1]) + " ^ (1 / " + render(children[0]) + "))"
        if t == sb.AST_FUNCTION and n.getName() in self.functions:
            f = self.functions[n.getName()]
            names = [f.getChild(i).getName() for i in range(f.getNumChildren() - 1)]
            if len(names) != len(children):
                raise ValueError("function arity mismatch")
            return self.render(
                f.getChild(f.getNumChildren() - 1),
                dict(zip(names, map(render, children))),
                depth + 1,
            )
        raise ValueError("unsupported SBML math: " + str(sb.formulaToL3String(n)))


def dependencies(n):
    found = {n.getName()} if n.isName() else set()
    for i in range(n.getNumChildren()):
        found |= dependencies(n.getChild(i))
    return found


def translate(data, scenario_id):
    members, index = archive_members(data)
    rows = [s for s in index["scenarios"] if s["scenario_id"] == scenario_id]
    if len(rows) != 1:
        raise ValueError("scenario does not resolve uniquely")
    entry = rows[0]
    sedml = xml(members[entry["sedml"]])
    ns = {"s": "http://sed-ml.org/sed-ml/level1/version5"}
    profile_node = next(
        (e for e in sedml.iter() if e.tag.endswith("executionProfile")), None
    )
    if profile_node is None:
        raise ValueError("exact sampling profile missing")
    profile = json.loads(profile_node.text)
    utc = next(e for e in sedml.iter() if e.tag.endswith("uniformTimeCourse"))
    span = profile["time_span"]
    if (
        float(utc.attrib["initialTime"]) != span["start"]
        or float(utc.attrib["outputStartTime"]) != span["start"]
    ):
        raise ValueError("SED-ML initial time mismatch")
    sedml_models = [e for e in sedml.iter() if e.tag.endswith("}model")]
    if (
        len(sedml_models) != 1
        or posixpath.normpath(
            posixpath.join(
                posixpath.dirname(entry["sedml"]), sedml_models[0].attrib["source"]
            )
        )
        != entry["sbml"]
    ):
        raise ValueError("SED-ML model reference mismatch")
    doc = sb.readSBMLFromString(members[entry["sbml"]].decode())
    errors = [
        doc.getError(i).getMessage()
        for i in range(doc.getNumErrors())
        if doc.getError(i).getSeverity() >= sb.LIBSBML_SEV_ERROR
    ]
    if errors:
        raise ValueError("invalid SBML: " + str(errors[:3]))
    m = doc.getModel()
    if m.getNumReactions() or m.getNumInitialAssignments() or m.getNumConstraints():
        raise ValueError(
            "unsupported SBML reactions, initial assignments or constraints"
        )
    states = {
        m.getSpecies(i).getId(): m.getSpecies(i) for i in range(m.getNumSpecies())
    }
    params = {
        m.getParameter(i).getId(): m.getParameter(i)
        for i in range(m.getNumParameters())
    }
    symbols = {name: "s" + str(i) for i, name in enumerate(states)}
    symbols.update({name: "p" + str(i) for i, name in enumerate(params)})
    functions = {
        m.getFunctionDefinition(i).getId(): m.getFunctionDefinition(i).getMath()
        for i in range(m.getNumFunctionDefinitions())
    }
    renderer = MathRenderer(symbols, functions)
    assignments, rates = {}, {}
    for i in range(m.getNumRules()):
        rule = m.getRule(i)
        target = rule.getVariable()
        if rule.isAssignment() and target in params:
            assignments[target] = rule.getMath()
        elif rule.isRate() and target in states:
            rates[target] = rule.getMath()
        else:
            raise ValueError("unsupported or invalid SBML rule")
    if set(rates) != set(states):
        raise ValueError("species/rate rule mismatch")
    ordered = []
    pending = dict(assignments)
    while pending:
        ready = [n for n, e in pending.items() if not dependencies(e) & set(pending)]
        if not ready:
            raise ValueError("cyclic assignment rules")
        for n in ready:
            ordered.append(n)
            del pending[n]
    definitions = [
        symbols[n] + " = " + renderer.render(assignments[n]) + ";" for n in ordered
    ]
    lines = list(definitions)
    lines += [
        "d/dt(" + symbols[n] + ") = " + renderer.render(e) + ";"
        for n, e in rates.items()
    ]
    outputs = {}
    for n, s in states.items():
        outputs["state__" + str(metadata(s).get("native_id") or n)] = symbols[n]
    for n, p in params.items():
        meta = metadata(p)
        if meta.get("role") == "derived_output":
            outputs["output__" + str(meta.get("native_id") or n)] = symbols[n]
    output_columns = {}
    for i, (name, expression) in enumerate(outputs.items()):
        alias = "obs" + str(i)
        lines.append(alias + " = " + expression + ";")
        output_columns[name] = alias
    initial = {}
    for n, s in states.items():
        if (
            s.getConstant()
            or s.getBoundaryCondition()
            or not s.getHasOnlySubstanceUnits()
            or not s.isSetInitialAmount()
        ):
            raise ValueError("unsupported species semantics")
        initial[symbols[n]] = s.getInitialAmount()
    parameters = {
        symbols[n]: p.getValue() for n, p in params.items() if n not in assignments
    }
    parameters["clockorigin"] = 0.0
    events = []
    for i in range(m.getNumEvents()):
        event = m.getEvent(i)
        if (
            event.isSetDelay()
            or event.isSetPriority()
            or not event.getUseValuesFromTriggerTime()
        ):
            raise ValueError("unsupported event semantics")
        trigger = event.getTrigger().getMath()
        if (
            trigger.getType() != sb.AST_RELATIONAL_GEQ
            or trigger.getNumChildren() != 2
            or trigger.getChild(0).getType() != sb.AST_NAME_TIME
            or not trigger.getChild(1).isNumber()
        ):
            raise ValueError("only scheduled time triggers supported")
        time = trigger.getChild(1).getValue()
        updates = {}
        for j in range(event.getNumEventAssignments()):
            ea = event.getEventAssignment(j)
            if ea.getVariable() in assignments or ea.getVariable() not in symbols:
                raise ValueError("event target invalid")
            updates[symbols[ea.getVariable()]] = renderer.render(ea.getMath())
        events.append({"time": time, "updates": updates})
    if len({e["time"] for e in events}) != len(events):
        raise ValueError("simultaneous events must have explicit batched assignments")
    events.sort(key=lambda e: e["time"])
    if any(e["time"] < span["start"] or e["time"] > span["end"] for e in events):
        raise ValueError("events outside experiment")
    start, end, step = span["start"], span["end"], span["step"]
    if (
        not all(math.isfinite(x) for x in [start, end, step])
        or not start < end
        or step <= 0
        or (end - start) / step > 100000
    ):
        raise ValueError("invalid observation span")
    grid = [start + i * step for i in range(int((end - start) / step) + 1)]
    all_times = sorted(
        grid + [end] + [e["time"] for e in events] + span.get("checkpoints", [])
    )
    times = []
    for t in all_times:
        if t < start or t > end:
            raise ValueError("checkpoint outside span")
        if not times or not math.isclose(t, times[-1], rel_tol=1e-12, abs_tol=1e-12):
            times.append(t)
    options = {
        e.attrib["kisaoID"]: float(e.attrib["value"])
        for e in sedml.iter()
        if e.tag.endswith("algorithmParameter")
    }
    if any(
        not math.isfinite(options[k]) or options[k] <= 0
        for k in ["KISAO:0000209", "KISAO:0000211"]
    ):
        raise ValueError("invalid declared solver tolerance")
    # The BDF request maps to rxode2's independently implemented LSODA path.
    algorithm = next(e for e in sedml.iter() if e.tag.endswith("}algorithm"))
    if algorithm.attrib["kisaoID"] != "KISAO:0000288":
        raise ValueError("unsupported algorithm request")
    atol = options["KISAO:0000211"]
    policy = index.get("solver_policy")
    if policy is not None:
        if policy.get("schema") != "ubi.omex.solver-policy/v1":
            raise ValueError("unsupported archived solver policy")
        if (
            policy["relative_tolerance"] != options["KISAO:0000209"]
            or policy["native_request_absolute_tolerance"] != options["KISAO:0000211"]
        ):
            raise ValueError("solver policy differs from SED-ML declaration")
        caps = policy["state_absolute_tolerance_caps"]
        native_states = {
            str(metadata(s).get("native_id") or n): symbols[n]
            for n, s in states.items()
        }
        if set(caps) != set(native_states) or any(
            type(v) not in (float, int) or not math.isfinite(v) or v <= 0
            for v in caps.values()
        ):
            raise ValueError("state tolerance policy must cover every state")
        atol = {native_states[n]: min(atol, caps[n]) for n in native_states}
    return {
        "schema": "ubi.omex.rxode2/v1",
        "model_id": index["model_id"],
        "model_version": index["model_version"],
        "scenario_id": scenario_id,
        "archive_sha256": sha(data),
        "sbml_sha256": sha(members[entry["sbml"]]),
        "sedml_sha256": sha(members[entry["sedml"]]),
        "source": "SBML mathematical AST",
        "model_code": "\n".join(lines),
        "definitions": definitions,
        "initial": initial,
        "parameters": parameters,
        "events": events,
        "times": times,
        "output_columns": output_columns,
        "time_unit": metadata(m).get("time_unit"),
        "solver": {
            "method": "liblsoda",
            "rtol": options["KISAO:0000209"],
            "atol": atol,
        },
        "archived_solver_policy": policy,
        "sampling": "initial_post_event,later_pre_event",
        "algorithm_substitution": "SED-ML BDF request; independent rxode2 liblsoda reference",
        "adapter_sha256": sha(Path(__file__).read_bytes()),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("--scenario", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    document = translate(a.archive.read_bytes(), a.scenario)
    a.output.write_text(json.dumps(document, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
