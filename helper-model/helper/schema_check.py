"""A small JSON Schema (2020-12) checker for the keywords schemas/*.json use. Stdlib only.

Numbers follow Go's encoding/json, not JSON Schema: "integer" means an integer literal
(85, not 85.0), because that is all Chimera's decoder accepts. An unsupported keyword raises
rather than being ignored, so a schema can't quietly check less than it says.
"""
from __future__ import annotations

import json
import os
import re

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schemas")

_ANNOTATIONS = {"$schema", "$id", "title", "description", "$defs", "$comment", "examples", "default"}
_SUPPORTED = {"$ref", "type", "enum", "const", "properties", "required", "additionalProperties", "items",
              "minItems", "maxItems", "uniqueItems", "minLength", "maxLength", "pattern", "minimum",
              "maximum", "allOf", "if", "then", "else"}


def load(job: str) -> dict:
    with open(os.path.join(SCHEMA_DIR, job + ".schema.json"), encoding="utf-8") as f:
        return json.load(f)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _type_ok(v, t):
    if t == "object":
        return isinstance(v, dict)
    if t == "array":
        return isinstance(v, list)
    if t == "string":
        return isinstance(v, str)
    if t == "boolean":
        return isinstance(v, bool)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return _is_num(v)
    if t == "null":
        return v is None
    raise ValueError(f"unknown type {t!r}")


def _describe(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if _is_num(v):
        return "number " + json.dumps(v)
    if isinstance(v, str):
        return "string"
    return "array" if isinstance(v, list) else "object"


def _equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if _is_num(a) and _is_num(b):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_equal(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def _resolve(root, ref):
    if not ref.startswith("#/"):
        raise ValueError(f"only local $refs are supported: {ref}")
    node = root
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def errors(instance, schema, root=None, path="$"):
    """List of (path, keyword, message) for everything in instance the schema rejects."""
    root = schema if root is None else root
    unknown = set(schema) - _SUPPORTED - _ANNOTATIONS
    if unknown:
        raise ValueError(f"schema keyword(s) not supported here: {sorted(unknown)}")
    out = []
    if "$ref" in schema:
        out += errors(instance, _resolve(root, schema["$ref"]), root, path)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(instance, t) for t in types):
            msg = f"expected {' or '.join(types)}, got {_describe(instance)}"
            if "integer" in types and isinstance(instance, float):
                msg += " (Go's decoder only takes integer literals)"
            return out + [(path, "type", msg)]
    if "enum" in schema and not any(_equal(instance, e) for e in schema["enum"]):
        out.append((path, "enum", f"{json.dumps(instance)} is not one of {json.dumps(schema['enum'])}"))
    if "const" in schema and not _equal(instance, schema["const"]):
        out.append((path, "const", f"expected {json.dumps(schema['const'])}"))
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            out.append((path, "minLength", f"must have at least {schema['minLength']} character(s)"))
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            out.append((path, "maxLength", f"must have at most {schema['maxLength']} character(s)"))
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            out.append((path, "pattern", f"{json.dumps(instance)} doesn't match {schema['pattern']}"))
    if _is_num(instance):
        if "minimum" in schema and instance < schema["minimum"]:
            out.append((path, "minimum", f"{instance} is below {schema['minimum']}"))
        if "maximum" in schema and instance > schema["maximum"]:
            out.append((path, "maximum", f"{instance} is above {schema['maximum']}"))
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            out.append((path, "minItems", f"has {len(instance)} item(s), needs at least {schema['minItems']}"))
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            out.append((path, "maxItems", f"has {len(instance)} item(s), allows at most {schema['maxItems']}"))
        if schema.get("uniqueItems"):
            for i in range(len(instance)):
                if any(_equal(instance[i], instance[j]) for j in range(i)):
                    out.append((f"{path}[{i}]", "uniqueItems", f"repeats {json.dumps(instance[i])}"))
        if "items" in schema:
            for i, x in enumerate(instance):
                out += errors(x, schema["items"], root, f"{path}[{i}]")
    if isinstance(instance, dict):
        for k in schema.get("required", []):
            if k not in instance:
                out.append((path, "required", f"missing {json.dumps(k)}"))
        props = schema.get("properties", {})
        for k, v in instance.items():
            if k in props:
                out += errors(v, props[k], root, f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                out.append((f"{path}.{k}", "additionalProperties", f"unexpected key {json.dumps(k)}"))
    for sub in schema.get("allOf", []):
        out += errors(instance, sub, root, path)
    if "if" in schema:
        if not errors(instance, schema["if"], root, path):
            if "then" in schema:
                out += errors(instance, schema["then"], root, path)
        elif "else" in schema:
            out += errors(instance, schema["else"], root, path)
    return out
