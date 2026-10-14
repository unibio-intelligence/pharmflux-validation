"""Normalize native time identifiers to the standard SBML time csymbol."""

import hashlib, json, zipfile, io
from pathlib import Path
import libsbml as sb
from omex_to_rxode2 import archive_members


def normalize(data):
    members, index = archive_members(data)
    changes = []
    for name in {r["sbml"] for r in index["scenarios"]}:
        doc = sb.readSBMLFromString(members[name].decode())
        model = doc.getModel()
        count = 0

        def walk(node):
            nonlocal count
            if node.getType() == sb.AST_NAME and node.getName() == "t":
                node.setType(sb.AST_NAME_TIME)
                node.setName("time")
                count += 1
            for i in range(node.getNumChildren()):
                walk(node.getChild(i))

        for i in range(model.getNumRules()):
            walk(model.getRule(i).getMath())
        for i in range(model.getNumEvents()):
            event = model.getEvent(i)
            walk(event.getTrigger().getMath())
            for j in range(event.getNumEventAssignments()):
                walk(event.getEventAssignment(j).getMath())
        if count:
            members[name] = sb.writeSBMLToString(doc).encode()
            changes.append({"member": name, "time_identifiers": count})
    if not changes:
        return data, []
    index["members"] = {
        n: hashlib.sha256(members[n]).hexdigest() for n in index["members"]
    }
    members["index.json"] = (
        json.dumps(index, indent=2, sort_keys=True) + "\n"
    ).encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in sorted(members):
            info = zipfile.ZipInfo(n, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, members[n])
    return out.getvalue(), changes


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("source", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    data, changes = normalize(a.source.read_bytes())
    a.output.write_bytes(data)
    print(json.dumps({"changes": changes, "sha256": hashlib.sha256(data).hexdigest()}))
