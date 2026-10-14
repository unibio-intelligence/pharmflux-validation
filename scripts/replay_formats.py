"""Validate QSPQuest replay inputs and preserve their exact bytes."""
import hashlib
import json

NATIVE_SCHEMAS = {f"qspquest.{kind}/v0.1" for kind in ("model", "run", "sensitivity", "fit")}


def validate_native(document, kind):
    """Require the declared QSPQuest format without altering the document."""
    expected = f"qspquest.{kind}/v0.1"
    if not isinstance(document, dict) or document.get("schema") != expected:
        raise ValueError("Unsupported native " + kind + " schema")

    def visit(node):
        if isinstance(node, dict):
            if "schema" in node:
                schema = node["schema"]
                if not isinstance(schema, str) or schema not in NATIVE_SCHEMAS:
                    raise ValueError("Unsupported nested native schema: " + str(schema))
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(document)
    return document


def write_native_copy(source, target, kind):
    payload = source.read_bytes()
    value = validate_native(json.loads(payload), kind)
    target.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    return {"recorded_sha256": digest, "executed_sha256": digest,
            "schema": value["schema"], "executed_file": target.name}


def condition_request(folder, case):
    """Require the pinned QSPQuest condition request."""
    path = folder / "qspquest-request.json"
    digest = case.get("qspquest_request_sha256")
    if not isinstance(digest, str) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("Native request pin differs")
    validate_native(json.loads(path.read_bytes()), "run")
    return path
