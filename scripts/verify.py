#!/usr/bin/env python3
"""Verify the minimal validation snapshot and its declared evidence coverage."""
import ast, collections, csv, gzip, hashlib, io, json, zipfile
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def check(condition, message):
    if not condition:
        raise ValueError(message)


def report(name):
    with gzip.open(ROOT / "results" / name, "rt") as f:
        return json.load(f)


def main():
    import runpy
    runpy.run_path(str(ROOT / "scripts/evidence_contract.py"))["verify_evidence"](ROOT)
    manifest = json.loads((ROOT / "manifest.json").read_text())
    actual = {
        str(p.relative_to(ROOT)): p
        for p in ROOT.rglob("*")
        if p.is_file()
        and ".git" not in p.relative_to(ROOT).parts
        and "__pycache__" not in p.relative_to(ROOT).parts
        and p.name != "manifest.json"
    }
    check(set(actual) == set(manifest["files"]), "snapshot inventory differs")
    for name, p in actual.items():
        check(
            hashlib.sha256(p.read_bytes()).hexdigest() == manifest["files"][name],
            "checksum differs: " + name,
        )
    for entry in json.loads((ROOT / "inputs/index.json").read_text())["archives"]:
        data = (ROOT / entry["archive"]).read_bytes()
        check(
            hashlib.sha256(data).hexdigest() == entry["sha256"],
            "fixture checksum differs",
        )
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            checks = json.loads(z.read("checksums.json"))
            check(len(checks) == entry["files"], "fixture count differs")
            names = z.namelist()
            check(len(names) == len(set(names)), "duplicate fixture members")
            check(
                set(names) == set(checks) | {"manifest.xml", "checksums.json"},
                "fixture inventory differs",
            )
            declared = {
                c.attrib["location"].removeprefix("./")
                for c in ET.fromstring(z.read("manifest.xml"))
            }
            check(
                declared == set(checks) | {".", "checksums.json"},
                "COMBINE manifest inventory differs",
            )
            for name, sha in checks.items():
                path = PurePosixPath(name)
                check(
                    not path.is_absolute()
                    and ".." not in path.parts
                    and "\\" not in name,
                    "unsafe fixture member",
                )
                check(
                    hashlib.sha256(z.read(name)).hexdigest() == sha,
                    "fixture member checksum differs: " + name,
                )
    env = json.loads((ROOT / "environment.json").read_text())
    expected = env["engine"]["compiler_source_sha256"]
    check(env["engine"]["compiler_version"].startswith("qspquest/"), "unexpected engine compiler")
    selected = report("omex-rxode2.json.gz")
    check(len(selected["models"]) == 8, "OMEX model count differs")
    check(
        sum(len(m["cases"]) for m in selected["models"]) == 47,
        "OMEX scenario count differs",
    )
    for m in selected["models"]:
        for c in m["cases"]:
            check(len(c["solvers"]) == 2, "missing native solver")
            for s in c["solvers"]:
                check(s["status"] == "match", "OMEX mismatch")
                check(
                    s["identity"]["compiler_source_sha256"] == expected,
                    "old OMEX engine",
                )
    for name in ["mrgsolve", "ordinarydiffeq", "roadrunner", "copasi", "amici"]:
        j = report(name + ".json.gz")
        check(len(j["cases"]) == 47, "independent-engine denominator differs")
        for c in j["cases"]:
            check(c["status"] == "matched", "independent-engine mismatch")
            for r in c["comparisons"].values():
                check(
                    r["native_engine_identity"]["compiler_source_sha256"] == expected,
                    "old independent-engine evidence",
                )
    for lane in [
        "conditions-bdf",
        "conditions-rodas5p",
        "conditions-patched-rxode2-bdf",
        "conditions-patched-rxode2-rodas5p",
    ]:
        j = report("nlmixr2-" + lane + ".json.gz")
        cases = [c for m in j["models"] for c in m["cases"]]
        check(
            len(j["models"]) == 59 and len(cases) == 420, "nlmixr2 denominator differs"
        )
        wanted = (
            {"match": 404, "expected_rejection": 16}
            if "patched" in lane
            else {"match": 403, "mismatch": 1, "expected_rejection": 16}
        )
        check(
            dict(collections.Counter(c["status"] for c in cases)) == wanted,
            "nlmixr2 outcomes differ",
        )
        check(
            j["compiler_source_sha256"] == expected
            and j["cli_sha256"] == env["cli_sha256"],
            "old nlmixr2 matrix identity",
        )
        for c in cases:
            if c["status"] != "expected_rejection":
                check(
                    c["execution_identity"]["compiler_source_sha256"] == expected,
                    "old nlmixr2 result",
                )
    extra = report("source-presets.json.gz")
    check(len(extra["cases"]) == 597, "source-preset denominator differs")
    for c in extra["cases"]:
        check(c["status"] == "matched", "source-preset mismatch")
        check(
            c["engine_identity"]["compiler_source_sha256"] == expected,
            "old source-preset engine",
        )
    fit = report("individual-fitting.json.gz")
    check(
        fit["contracts"] == 1906
        and len(fit["datasets"]) == 21
        and len(fit["rows"]) == 3812,
        "fitting denominator differs",
    )
    check(fit["compiler_source_sha256"] == expected, "old fitting engine")
    check(
        all(
            r["status"] == "matched_converged"
            and r["native_convergence"] == "converged"
            for r in fit["rows"]
        ),
        "fitting result differs",
    )
    for filename, count in [("simulations.csv", 2841), ("fitting.csv", 3812)]:
        with (ROOT / "results" / filename).open() as f:
            rows = list(csv.DictReader(f))
        check(len(rows) == count, "CSV count differs: " + filename)
    for p in (ROOT / "scripts").glob("*.py"):
        ast.parse(p.read_text())
    print(
        "Verified all file and OMEX member hashes; 2,841 simulation comparisons and 3,812 fitting comparisons; recorded QSPQuest engine identities consistent."
    )



if __name__ == "__main__":
    main()
