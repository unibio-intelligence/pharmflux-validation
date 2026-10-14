"""Compile closed SBML AST equations into standalone mrgsolve model specifications."""

import argparse, json, re
from pathlib import Path
import libsbml as sb
import omex_to_rxode2 as adapter

Base = adapter.MathRenderer


class CRenderer(Base):
    def render(self, n, bindings=None, depth=0):
        children = [n.getChild(i) for i in range(n.getNumChildren())]
        r = lambda x: self.render(x, bindings, depth + 1)
        if n.getType() in (sb.AST_FUNCTION_MIN, sb.AST_FUNCTION_MAX):
            fn = "fmin" if n.getType() == sb.AST_FUNCTION_MIN else "fmax"
            result = r(children[0])
            for child in children[1:]:
                result = fn + "(" + result + "," + r(child) + ")"
            return result
        if n.getType() in (sb.AST_POWER, sb.AST_FUNCTION_POWER):
            return "pow(" + r(children[0]) + "," + r(children[1]) + ")"
        if n.getType() == sb.AST_FUNCTION_ROOT:
            return "pow(" + r(children[-1]) + ",1.0/" + r(children[0]) + ")"
        if n.getType() == sb.AST_FUNCTION_PIECEWISE:
            result = r(children[-1])
            for i in range(len(children) - 3, -1, -2):
                result = (
                    "("
                    + r(children[i + 1])
                    + " ? "
                    + r(children[i])
                    + " : "
                    + result
                    + ")"
                )
            return result
        return (
            super()
            .render(n, bindings, depth)
            .replace(" & ", " && ")
            .replace(" | ", " || ")
        )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--validation", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    cases = []
    for archive in sorted(
        (a.validation / "selected-models/models").glob("*/*/model.omex")
    ):
        data = archive.read_bytes()
        _, index = adapter.archive_members(data)
        for case in index["scenarios"]:
            name = case["scenario_id"]
            d = adapter.translate(data, name)
            adapter.MathRenderer = CRenderer
            try:
                c = adapter.translate(data, name)
            finally:
                adapter.MathRenderer = Base
            folder = a.out / index["model_id"] / name
            folder.mkdir(parents=True, exist_ok=True)
            definitions = "\n".join("double " + x for x in c["definitions"])
            rates = "\n".join(
                re.sub(r"d/dt\((\w+)\)", r"dxdt_\1", line)
                for line in c["model_code"].splitlines()
                if line.startswith("d/dt")
            )
            captures = "\n".join(
                "double " + line
                for line in c["model_code"].splitlines()
                if line.startswith("obs")
            )
            code = (
                "$PARAM\n"
                + ",\n".join(n + " = " + repr(v) for n, v in c["parameters"].items())
                + "\n$CMT\n"
                + " ".join(c["initial"])
                + "\n$ODE\ndouble t = SOLVERTIME;\n"
                + definitions
                + "\n"
                + rates
                + "\n$TABLE\nt = TIME;\n"
                + "\n".join(c["definitions"])
                + "\n"
                + captures
                + "\n$CAPTURE\n"
                + " ".join(c["output_columns"].values())
                + "\n"
            )
            (folder / "model.cpp").write_text(code)
            (folder / "experiment.json").write_text(json.dumps(d, indent=2) + "\n")
            cases.append(
                {
                    "experiment": str((folder / "experiment.json").resolve()),
                    "folder": str(folder.resolve()),
                }
            )
    (a.out / "batch.json").write_text(json.dumps({"cases": cases}, indent=2) + "\n")


if __name__ == "__main__":
    main()
