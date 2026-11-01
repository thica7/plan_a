"""Strict parser failures stay ValueError while preserving the original cause."""

import json

import pytest

from packages.llm.json_extract import JsonExtractionError, strict_json_object


@pytest.mark.parametrize("shape", ["field", "unclosed", "array"])
def test_strict_json_normalizes_parse_depth_failure_without_changing_raw(shape):
    nested = "[" * 1100 + "0"
    raw = nested if shape == "array" else '{"candidate_ref":' + nested
    if shape != "unclosed":
        raw += "]" * 1100 + ("}" if shape == "field" else "")
    before = raw
    with pytest.raises(JsonExtractionError) as error:
        strict_json_object(raw)
    assert isinstance(error.value, ValueError)
    assert isinstance(error.value.__cause__, RecursionError)
    assert raw == before


def test_strict_json_success_and_existing_negative_contracts_are_unchanged():
    raw = '{"version":1,"candidate_ref":[0]}'
    assert strict_json_object(raw) == json.loads(raw)
    for bad in ['{"version":1,"version":2}', raw + " {}", "[]"]:
        with pytest.raises(ValueError):
            strict_json_object(bad)


def test_strict_json_does_not_swallow_unrelated_runtime_errors(monkeypatch):
    import packages.llm.json_extract as module

    def unrelated(*args, **kwargs):
        raise RuntimeError("unrelated programming failure")

    monkeypatch.setattr(module.json, "loads", unrelated)
    with pytest.raises(RuntimeError, match="unrelated programming failure"):
        strict_json_object("{}")
