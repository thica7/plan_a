from copy import deepcopy
from types import SimpleNamespace

from packages.agents.comparator.context import compact_analysis_context
from packages.research.evidence.snapshot_models import canonical_json


def test_exact_duplicate_uses_current_fact_reference_and_preserves_other_analysis():
    value = "完整的产品功能证据，包含限制条件和原始数值 17.49。" * 12
    fact = SimpleNamespace(id="current-f1", value=value, quote="", qualifiers={})
    payload = {
        "finding": value,
        "rationale": "适用于共同维护产品文档的团队。",
        "qualifiers": {"billing_interval": "annual", "tax_scope": "unknown"},
    }
    original = deepcopy(payload)
    compact = compact_analysis_context(payload, [fact])
    assert compact["finding"] == {"evidence_fact_refs": ["current-f1"], "field": "value"}
    assert compact["rationale"] == payload["rationale"]
    assert compact["qualifiers"] == payload["qualifiers"]
    assert payload == original
    assert len(canonical_json(compact)) < len(canonical_json(payload))


def test_different_numbers_or_conditions_are_never_fuzzy_deduplicated():
    value = "Price is 17.49 under the explicitly stated annual billing conditions. " * 5
    payload = {
        "finding": value.replace("17.49", "17.50"),
        "price": 17.49,
        "qualifiers": {"billing_interval": "monthly"},
    }
    fact = SimpleNamespace(id="f1", value=value, quote="", qualifiers={})
    assert compact_analysis_context(payload, [fact]) == payload


def test_fact_quotes_resolve_to_explicit_quote_field_and_keep_both_source_facts():
    quote = "A long shared quotation with a capture date and explicit product constraints. " * 5
    facts = [SimpleNamespace(id=f"f{i}", value=17.49, quote=quote, qualifiers={}) for i in (1, 2)]
    result = compact_analysis_context({"quote": quote, "source_ids": ["a", "b"]}, facts)
    assert result["quote"] == {"evidence_fact_refs": ["f1", "f2"], "field": "quote"}
    assert result["source_ids"] == ["a", "b"]


def test_empty_current_view_never_reuses_previous_facts():
    payload = {"finding": "长证据" * 80, "source_ids": ["old"]}
    assert compact_analysis_context(payload, []) == payload


def test_ambiguous_value_and_quote_do_not_drop_evidence_scope():
    text = "Same long text in different evidence fields. " * 15
    facts = [
        SimpleNamespace(id="value-fact", value=text, quote=""),
        SimpleNamespace(id="quote-fact", value=1, quote=text),
    ]
    assert compact_analysis_context({"finding": text}, facts) == {"finding": text}


def test_whole_object_reference_never_hides_comparison_conditions():
    value = {"qualifiers": {"tax_scope": "unknown"}, "source_ids": ["s"], "finding": "x" * 300}
    fact = SimpleNamespace(id="f", value=value, quote="")
    assert compact_analysis_context({"analysis": value}, [fact]) == {"analysis": value}


def test_list_reference_never_hides_nested_comparison_conditions():
    value = [{"qualifiers": {"tax_scope": "unknown"}, "source_ids": ["s"], "finding": "x" * 300}]
    fact = SimpleNamespace(id="f", value=value, quote="")
    assert compact_analysis_context({"analyses": value}, [fact]) == {"analyses": value}
