import json
from pathlib import Path

MAX_INPUT_BYTES = 32 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def string(obj, key):
    value = obj.get(key)
    require(
        isinstance(value, str) and value.strip(), f"{key} must be a nonempty string"
    )
    return value


def array(obj, key):
    value = obj.get(key)
    require(isinstance(value, list), f"{key} must be a list")
    return value


def object_value(value, name):
    require(isinstance(value, dict), f"{name} must be an object")
    return value


def read_json(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_INPUT_BYTES + 1)
    require(len(data) <= MAX_INPUT_BYTES, "JSON input exceeds size limit")

    def reject_constant(value):
        raise ValueError(f"invalid JSON number {value}")

    def unique_object(items):
        result = dict(items)
        require(len(items) == len(result), "duplicate JSON object key")
        return result

    return json.loads(
        data, parse_constant=reject_constant, object_pairs_hook=unique_object
    )
