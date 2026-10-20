"""Lossless bounded transport deltas, not a market-data or retention policy.

Every reconstructed checkpoint is hashed and schema validated by the transport.
Old Git objects remain reachable: consolidation never deletes evidence.
"""
import copy
import json

CONSOLIDATE_EVERY = 24
MAX_RETAINED_BYTES = 256 * 1024 * 1024
OBJECT_OVERHEAD_RESERVE = 32768


def encode(value):
    return json.dumps(value, sort_keys=True, allow_nan=False).encode()


def difference(previous, current):
    operations = []

    def visit(old, new, path):
        if old == new:
            return
        if isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(old.keys() - new.keys()):
                operations.append(["remove", path + [key]])
            for key in sorted(new):
                if key not in old:
                    operations.append(["set", path + [key], new[key]])
                else:
                    visit(old[key], new[key], path + [key])
        elif isinstance(old, list) and isinstance(new, list) and new[:len(old)] == old:
            operations.append(["append", path, new[len(old):]])
        else:
            operations.append(["set", path, new])

    visit(previous, current, [])
    return operations


def apply(previous, operations):
    result = copy.deepcopy(previous)
    if not isinstance(operations, list):
        raise ValueError("invalid journal operations")
    for operation in operations:
        if not isinstance(operation, list) or len(operation) not in (2, 3):
            raise ValueError("invalid journal operation")
        kind, path = operation[:2]
        if not isinstance(path, list) or any(not isinstance(k, str) for k in path):
            raise ValueError("invalid journal path")
        if not path:
            if kind != "set" or len(operation) != 3:
                raise ValueError("invalid journal root")
            result = copy.deepcopy(operation[2])
            continue
        parent = result
        for key in path[:-1]:
            if not isinstance(parent, dict) or key not in parent:
                raise ValueError("missing journal parent")
            parent = parent[key]
        if not isinstance(parent, dict):
            raise ValueError("invalid journal parent")
        key = path[-1]
        if kind == "remove" and len(operation) == 2:
            del parent[key]
        elif kind == "set" and len(operation) == 3:
            parent[key] = copy.deepcopy(operation[2])
        elif kind == "append" and len(operation) == 3 and isinstance(parent.get(key), list) and isinstance(operation[2], list):
            parent[key].extend(copy.deepcopy(operation[2]))
        else:
            raise ValueError("invalid journal operation type")
    return result
