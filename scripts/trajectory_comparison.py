"""Strict finite, complete trajectory comparison shared by validation reruns."""
import csv
import math


def read_reference(path, columns=None):
    """Read declared comparison columns; unrelated R diagnostics may repeat."""
    with path.open(newline="") as stream:
        reader = csv.reader(stream)
        names = next(reader, [])
        selected = list(names if columns is None else columns)
        if (not names or "time" not in selected or len(selected) != len(set(selected))
                or any(names.count(name) != 1 for name in selected)):
            raise ValueError("Reference comparison columns must be unique and include time")
        rows = list(reader)
    if not rows or any(len(row) != len(names) for row in rows):
        raise ValueError("Empty or malformed reference table")
    return {name: [float(row[names.index(name)]) for row in rows] for name in selected}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def compare_columns(reference, native, declared_columns, aliases=None):
    """Compare every declared series at the exact finite observation grid.

    Native projections use source_output_N/library_state_N aliases in the
    declared reference-column order. Ordinary series use state__/output__ names.
    Values must satisfy abs(delta) <= 1e-8 + 1e-4 * abs(reference).
    """
    declared = list(declared_columns)
    if not declared or len(declared) != len(set(declared)) or set(reference) != {"time", *declared}:
        raise ValueError("Reference declared column inventory differs")
    times = native.get("times")
    expected_times = reference["time"]
    if (not isinstance(times, list) or not times or len(times) != len(expected_times)
            or any(not finite(t) or not finite(r) or abs(t-r) > 1e-10 for t, r in zip(times, expected_times))):
        raise ValueError("Observation time grid differs or contains nonfinite values")
    for values in reference.values():
        if len(values) != len(times) or any(not finite(v) for v in values):
            raise ValueError("Reference series length differs or contains nonfinite values")
    if aliases is not None and (not aliases or len(set(aliases.values())) != len(aliases)
                                or set(aliases.values()) != set(declared)):
        raise ValueError("Native alias inventory differs")
    groups = {prefix: [c for c in declared if c.startswith(prefix)] for prefix in ("state__", "output__")}
    seen, results = set(), []
    for category, prefix in (("states", "state__"), ("outputs", "output__")):
        series = native.get(category, [])
        if not isinstance(series, list):
            raise ValueError("Native series must be an array")
        for item in series:
            name = item["name"]
            column = prefix + name
            for alias, group in (("source_output_", "output__"), ("library_state_", "state__")):
                if aliases is None and name.startswith(alias):
                    suffix = name[len(alias):]
                    if not suffix.isdigit() or int(suffix) >= len(groups[group]):
                        raise ValueError("Unknown native projection alias: " + name)
                    column = groups[group][int(suffix)]
            if aliases is not None:
                if name not in aliases:
                    raise ValueError("Unknown native projection alias: " + name)
                column = aliases[name]
            if column not in declared or column in seen:
                raise ValueError("Unknown or duplicate native column: " + column)
            seen.add(column)
            values = item["values"]
            if not isinstance(values, list) or len(values) != len(times):
                raise ValueError("Native series length differs: " + column)
            if any(not finite(v) for v in values):
                raise ValueError("Nonfinite native value: " + column)
            ref = reference[column]
            errors = [abs(a-b) for a, b in zip(values, ref)]
            scaled = [e / (1e-8 + 1e-4*abs(r)) for e, r in zip(errors, ref)]
            results.append({"column": column, "max_absolute_error": max(errors),
                            "max_scaled_error": max(scaled), "passed": max(scaled) <= 1})
    if seen != set(declared):
        raise ValueError("Native declared series coverage differs")
    return {"status": "matched" if all(r["passed"] for r in results) else "mismatch", "columns": results}


def vector(values, count, label):
    if not isinstance(values, list) or len(values) != count or not count:
        raise ValueError(label + " length differs or is empty")
    if any(not finite(v) for v in values):
        raise ValueError(label + " contains a nonfinite or nonnumeric value")
    return values


def same_grid(actual, expected):
    vector(expected, len(expected), "Reference time grid")
    vector(actual, len(expected), "Native time grid")
    if any(abs(a-b) > 1e-10 for a, b in zip(actual, expected)):
        raise ValueError("Observation time grid differs")


def output_series(native):
    times = native.get("times", [])
    vector(times, len(times), "Native time grid")
    result = {}
    for item in native.get("outputs", []):
        name = item["name"]
        if not isinstance(name, str) or not name or name in result:
            raise ValueError("Duplicate or invalid native output name")
        vector(item["values"], len(times), "Native output " + name)
        if not isinstance(item.get("unit"), str) or not item["unit"]:
            raise ValueError("Missing native output unit: " + name)
        result[name] = item
    if not result:
        raise ValueError("Empty native output inventory")
    return result


def validate_run(native, request, model=None):
    """Validate the declared native request contract before comparing coordinates.

    Units are projection labels, not a claim of source physical qualification.
    Archived validation requests all declare explicit observation times and sides.
    """
    observations = request["regimen"]["observations"]
    if not observations:
        raise ValueError("Empty requested observation grid")
    expected = [o["time"]["value"] for o in observations]
    same_grid(native.get("times", []), expected)
    units = {o["time"]["unit"] for o in observations}
    if len(units) != 1 or native.get("time_unit") not in units:
        raise ValueError("Native/request time units differ")
    sides = [o["side"] for o in observations]
    if any(s not in ("pre", "post") for s in sides) or native.get("sides") != sides:
        raise ValueError("Native/request observation sides differ")
    outputs = output_series(native)
    # Some result profiles also expose states separately; do not ignore bad arrays.
    seen = set()
    for item in native.get("states", []):
        if item["name"] in seen:
            raise ValueError("Duplicate native state name")
        seen.add(item["name"])
        vector(item["values"], len(expected), "Native state " + item["name"])
    if model is not None:
        specs = model["outputs"]
        declared = {s["name"]: s["unit"] for s in specs}
        if len(declared) != len(specs) or set(outputs) != set(declared):
            raise ValueError("Native/model output inventory differs")
        if any(outputs[n]["unit"] != unit for n, unit in declared.items()):
            raise ValueError("Native/model output units differ")
        if native["time_unit"] != model["time_unit"]:
            raise ValueError("Native/model time units differ")
    return outputs


def compare_mapped(reference, native, mapping):
    """Compare the explicitly mapped condition outputs, without broadcasting."""
    if not mapping or len(set(mapping.values())) != len(mapping):
        raise ValueError("Empty or duplicate comparison mapping")
    same_grid(native.get("times", []), reference["time"])
    outputs = output_series(native)
    if set(outputs) != set(mapping.values()):
        raise ValueError("Native mapped output inventory differs")
    errors = []
    for column, name in mapping.items():
        ref = vector(reference[column], len(native["times"]), "Reference output " + column)
        actual = outputs[name]["values"]
        errors.extend(abs(a-r) / (1e-7 + 1e-6*abs(r)) for a, r in zip(actual, ref))
    return {"status": "match" if max(errors) <= 1 else "mismatch", "max_scaled_error": max(errors)}


def projection_aliases(index):
    aliases = {}
    for category, prefix in (("states", "state__"), ("outputs", "output__")):
        for logical, spec in index["native_execution"][category].items():
            name = spec["native_name"]
            if name in aliases:
                raise ValueError("Duplicate declared native projection name")
            aliases[name] = prefix + logical
    return aliases
