"""Literal membership for non-operation text, without proving entailment."""

import re

from packages.research.evidence.operations import required_operations


def literal_non_operation_originals(fact, *, questions=()):
    """Offer a few complete source members; never truncate one to a budget."""
    from packages.agents.writer.answer_coverage import question_terms

    originals = [fact.quote, *(fact.value if isinstance(fact.value, (list, tuple)) else [fact.value])]
    choices = []
    for original in originals:
        if not isinstance(original, str):
            continue
        for text in [original.strip(), *re.split(r"(?<=[.!?])(?=\s|$)|(?<=[。！？])", original)]:
            text = text.strip()
            if (text not in choices and len(text) <= 600 and "\n" not in text
                    and literal_non_operation(text, [fact.id], [fact])):
                choices.append(text)
    hints = set().union(*(question_terms(q['question'], fact.competitor) for q in questions))
    return sorted(choices, key=lambda text: -len(hints & question_terms(text, fact.competitor)))[:3]


def literal_non_operation(text, fact_ids, source_facts):
    """Match a complete original sentence or value entry, never metadata.

    Callers restrict these originals to the facts actually sent to the writer.
    Source scope, date conditions and semantic QA still apply to the claim.
    """
    ids = tuple(fact_ids)
    if len(ids) != 1 or not text.strip() or required_operations(text):
        return False
    for original in source_facts:
        fact = original if isinstance(original, dict) else dict(
            id=original.id, field=original.field, quote=original.quote, value=original.value
        )
        if fact.get("id") != ids[0] or fact.get("field") != "evidence_terms":
            continue
        value = fact.get("value")
        originals = [fact.get("quote")]
        originals.extend(value if isinstance(value, (list, tuple)) else [value])
        for original in originals:
            if not isinstance(original, str):
                continue
            if text == original.strip():
                return True
            sentences = re.split(r"(?<=[.!?])(?=\s|$)|(?<=[。！？])", original)
            if any(
                text == sentence.strip() and re.search(r"[.!?。！？]$", sentence.strip())
                for sentence in sentences
            ):
                return True
        return False
    return False
