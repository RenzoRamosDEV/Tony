import hashlib

import pytest

from tony.core.guard.audit import args_hash, canonical_json

AB_HASH = "21501dbaf73f5223934d22283f01caff4132bc1de4a9550c1ed0dffeb397a323"


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({}, "{}"),
        ({"b": 1, "a": 2}, '{"a": 2, "b": 1}'),
        ({"z": {"y": [1, {"b": None, "a": True}]}}, '{"z": {"y": [1, {"a": true, "b": null}]}}'),
        ({"path": "~/notas/año.md"}, '{"path": "~/notas/año.md"}'),
    ],
)
def test_canonical_json_sorts_keys_with_default_separators(args, expected):
    assert canonical_json(args) == expected


@pytest.mark.parametrize("args", [{"b": 1, "a": 2}, {"a": 2, "b": 1}])
def test_hash_ignores_key_order(args):
    assert args_hash(args) == AB_HASH


def test_hash_keeps_non_ascii():
    expected = hashlib.sha256('{"q": "acción"}'.encode()).hexdigest()

    assert args_hash({"q": "acción"}) == expected


def test_different_args_hash_differently():
    assert args_hash({"a": 1}) != args_hash({"a": 2})
