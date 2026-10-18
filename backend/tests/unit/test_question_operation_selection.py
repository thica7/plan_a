"""Anonymous retrieval cases: selection hints never establish an answer."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from test_question_retrieval import replace_snapshot, research_case, retrieval_api

from packages.knowledge.embeddings import HashEmbeddingProvider
from packages.knowledge.local_models import LocalEmbeddingProvider, LocalRerankerProvider
from packages.research.evidence.operations import operation_observations
from packages.research.evidence.snapshot_models import EvidenceConflict

QUESTION = "Example Product: Can guests comment on and edit documents on Free plan?"
BACKGROUNDS = [
    f"Guests on Free plan: documents collaboration overview {index}." for index in range(3)
]
COMMENT = "Guests can comment on documents on paid plans."
EDIT = "Guests can edit documents on paid plans."


def anonymous_case(quotes, *, question=QUESTION):
    detail, snapshot = research_case(quotes, question=question)
    originals = [fact for fact in snapshot.facts if fact.field == "evidence_terms"]
    facts = tuple(
        next(fact for fact in originals if fact.quote == quote).model_copy(
            update={"id": f"anonymous-fact-{number:03}"}
        )
        for number, quote in enumerate(quotes)
    )
    return detail, replace_snapshot(detail, snapshot, facts=facts)


def fact_id(snapshot, quote):
    return next(fact.id for fact in snapshot.facts if fact.quote == quote)


@pytest.mark.asyncio
async def test_missing_operations_survive_repeated_higher_ranked_background():
    detail, snapshot = anonymous_case([*BACKGROUNDS, COMMENT, EDIT])
    before = snapshot.model_dump_json()
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert {fact_id(snapshot, COMMENT), fact_id(snapshot, EDIT)} <= set(selected)
    assert len(selected) == 3
    assert snapshot.model_dump_json() == before
    assert diagnostic["ranking_only"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prerequisite,question",
    [
        (
            "Guests must log in on Free plan before collaboration on documents.",
            "Example Product: Must guests log in to comment on and edit documents on Free plan?",
        ),
        (
            "Guests need an invitation on Free plan before collaboration on documents.",
            "Example Product: Do guests need an invitation to comment on and edit documents "
            "on Free plan?",
        ),
    ],
)
async def test_high_ranked_non_operation_prerequisites_keep_their_slot(prerequisite, question):
    detail, snapshot = anonymous_case(
        [prerequisite, *BACKGROUNDS, COMMENT, EDIT], question=question
    )
    assert operation_observations(snapshot.facts[0]) == []
    selected, _ = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert set(selected) == {
        fact_id(snapshot, prerequisite), fact_id(snapshot, COMMENT), fact_id(snapshot, EDIT)
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "condition",
    [
        "Guests on Free plan documents collaboration depending on account membership.",
        "Guests on Free plan documents collaboration：只有绑定账户才可用。",
        "Guests on Free plan documents collaboration：仅当绑定账户才可用。",
    ],
)
async def test_conditional_non_operation_at_the_original_cutoff_is_preserved(condition):
    detail, snapshot = anonymous_case(
        [*BACKGROUNDS[:2], condition, BACKGROUNDS[2], COMMENT, EDIT]
    )
    target = next(fact for fact in snapshot.facts if fact.quote == condition)
    assert operation_observations(target) == []
    selected, _ = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert set(selected) == {
        target.id, fact_id(snapshot, COMMENT), fact_id(snapshot, EDIT)
    }


@pytest.mark.asyncio
async def test_unrelated_condition_terms_do_not_protect_all_background_quotes():
    detail, snapshot = anonymous_case([*BACKGROUNDS, COMMENT, EDIT])
    facts = tuple(
        fact.model_copy(update={
            "value_json": json.dumps([
                fact.quote, "A separate workflow depending on account membership needs setup."
            ])
        }) if fact.quote in BACKGROUNDS else fact
        for fact in snapshot.facts
    )
    snapshot = replace_snapshot(detail, snapshot, facts=facts)
    selected, _ = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert {fact_id(snapshot, COMMENT), fact_id(snapshot, EDIT)} <= set(selected)


@pytest.mark.asyncio
async def test_unrelated_login_context_does_not_protect_all_background_quotes():
    question = (
        "Example Product: Must guests log in to comment on and edit documents on Free plan?"
    )
    detail, snapshot = anonymous_case([*BACKGROUNDS, COMMENT, EDIT], question=question)
    snapshot = replace_snapshot(detail, snapshot, facts=tuple(
        fact.model_copy(update={
            "value_json": json.dumps([fact.quote, "A separate workflow uses login credentials."])
        }) if fact.quote in BACKGROUNDS else fact
        for fact in snapshot.facts
    ))
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert {fact_id(snapshot, COMMENT), fact_id(snapshot, EDIT)} <= set(selected)
    assert diagnostic["questions"][0]["missing_operations"] == []
    assert diagnostic["ranking_only"] is True


@pytest.mark.asyncio
async def test_explicit_login_quote_at_the_cutoff_keeps_its_protected_slot():
    login = "Guests on Free plan log in for documents collaboration."
    question = "Example Product: Must guests log in to comment on and edit documents on Free plan?"
    detail, snapshot = anonymous_case(
        [*BACKGROUNDS[:2], login, BACKGROUNDS[2], COMMENT, EDIT], question=question
    )
    snapshot = replace_snapshot(detail, snapshot, facts=tuple(
        fact.model_copy(update={"value_json": json.dumps([
            fact.quote, "A separate workflow asks users to log in with credentials."
        ])}) if fact.quote in BACKGROUNDS[:2] else fact
        for fact in snapshot.facts
    ))
    selected, _ = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert set(selected) == {
        fact_id(snapshot, login), fact_id(snapshot, COMMENT), fact_id(snapshot, EDIT)
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("login_question", [False, True])
async def test_unrequested_operation_in_the_same_quote_does_not_disable_login_protection(
    login_question,
):
    login = (
        "Guests must log in on Free plan before collaboration on documents. "
        "Members can view boards."
    )
    question = (
        "Example Product: Must guests log in to comment on and edit documents on Free plan?"
    ) if login_question else QUESTION
    detail, snapshot = anonymous_case(
        [*BACKGROUNDS[:2], login, BACKGROUNDS[2], COMMENT, EDIT], question=question
    )
    if login_question:
        snapshot = replace_snapshot(detail, snapshot, facts=tuple(
            fact.model_copy(update={"value_json": json.dumps([
                fact.quote, "A separate workflow asks users to log in with credentials."
            ])}) if fact.quote in BACKGROUNDS[:2] else fact
            for fact in snapshot.facts
        ))
    original = next(fact for fact in snapshot.facts if fact.quote == login)
    assert {row["operation"] for row in operation_observations(original)} == {"read"}
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert set(selected) == {
        original.id, fact_id(snapshot, COMMENT), fact_id(snapshot, EDIT)
    }
    assert diagnostic["questions"][0]["missing_operations"] == []
    assert diagnostic["ranking_only"] is True


@pytest.mark.asyncio
async def test_requested_operation_cannot_replace_a_separate_explicit_login_sentence():
    login = (
        "Guests must log in on Free plan before collaboration on documents. "
        "Members can comment on boards."
    )
    replacement = "Members can edit boards and comment on boards."
    question = "Example Product: Must guests log in to comment on and edit documents on Free plan?"
    detail, snapshot = anonymous_case(
        [*BACKGROUNDS[:2], login, BACKGROUNDS[2], replacement], question=question
    )
    snapshot = replace_snapshot(detail, snapshot, facts=tuple(
        fact.model_copy(update={"value_json": json.dumps([
            fact.quote, "A separate workflow asks users to log in and comment with credentials."
        ])}) if fact.quote in BACKGROUNDS[:2] else fact
        for fact in snapshot.facts
    ))
    original = next(fact for fact in snapshot.facts if fact.quote == login)
    rows = operation_observations(original)
    assert {row["operation"] for row in rows} == {"comment"}
    assert rows[0]["role"] == "Members"
    assert rows[0]["prerequisites"] == []
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert original.id in selected
    assert fact_id(snapshot, replacement) in selected
    assert len(selected) == 3
    assert diagnostic["questions"][0]["missing_operations"] == []
    assert diagnostic["ranking_only"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["comment on", "view"])
@pytest.mark.parametrize(
    "prerequisite,question,context",
    [
        (
            "Guests need an invitation on Free plan before collaboration on documents.",
            "Example Product: Do guests need an invitation to comment on and edit documents "
            "on Free plan?",
            "A separate workflow needs an invitation to comment with credentials.",
        ),
        (
            "Guests must have an account on Free plan before collaboration on documents.",
            "Example Product: Must guests have an account to comment on and edit documents "
            "on Free plan?",
            "A separate workflow must have an account to comment with credentials.",
        ),
        (
            "Guests on Free plan only participate in collaboration on documents "
            "after verification.",
            "Example Product: Can guests only comment on and edit documents on Free plan "
            "after verification?",
            "A separate workflow only enables comment after verification.",
        ),
    ],
)
async def test_explicit_prerequisite_is_independent_of_same_quote_operations(
    operation, prerequisite, question, context
):
    mixed = prerequisite + f" Members can {operation} boards."
    replacement = "Members can edit boards and comment on boards."
    detail, snapshot = anonymous_case(
        [*BACKGROUNDS[:2], mixed, BACKGROUNDS[2], replacement], question=question
    )
    snapshot = replace_snapshot(detail, snapshot, facts=tuple(
        fact.model_copy(update={"value_json": json.dumps([fact.quote, context])})
        if fact.quote in BACKGROUNDS[:2] else fact
        for fact in snapshot.facts
    ))
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert fact_id(snapshot, mixed) in selected
    assert fact_id(snapshot, replacement) in selected
    assert len(selected) == 3
    assert diagnostic["questions"][0]["missing_operations"] == []
    assert diagnostic["ranking_only"] is True


@pytest.mark.asyncio
async def test_mixed_prerequisites_can_leave_an_explicit_selection_capacity_gap():
    prerequisites = [
        "Guests need an invitation on Free plan before collaboration on documents.",
        "Guests must have an account on Free plan before collaboration on documents.",
        "Guests on Free plan only participate in collaboration on documents after verification.",
    ]
    mixed = [quote + " Members can comment on boards." for quote in prerequisites]
    replacement = "Members can edit boards and comment on boards."
    detail, snapshot = anonymous_case([*mixed, replacement])
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert set(selected) == {fact_id(snapshot, quote) for quote in mixed}
    assert len(selected) == 3
    assert diagnostic["questions"][0]["missing_operations"] == ["edit"]
    assert diagnostic["questions"][0]["candidate_missing_operations"] == []
    assert diagnostic["ranking_only"] is True


@pytest.mark.parametrize(
    "replacement",
    [
        "Members on Free plan can comment on and edit documents.",
        "Guests on Enterprise plans can comment on and edit documents.",
        "Guests on Free plan cannot comment on and edit documents.",
        "Guests on Free plan can edit boards and comment on boards.",
        "Guests on Free plan can comment on and edit documents only after verification.",
    ],
)
def test_new_operations_do_not_replace_a_different_selected_source_branch(replacement):
    original = "Guests on Free plan can comment on documents."
    detail, snapshot = anonymous_case([*BACKGROUNDS[:2], original, replacement])
    module = retrieval_api()
    observations = {fact.id: operation_observations(fact) for fact in snapshot.facts}
    operations = {
        key: {row["operation"] for row in rows} for key, rows in observations.items()
    }
    assert operations[fact_id(snapshot, replacement)] == {"comment", "edit"}
    quotes = {fact.id: fact.quote for fact in snapshot.facts}
    hints = {key: module.question_terms(quote, "Example Product") for key, quote in quotes.items()}
    row = [fact_id(snapshot, quote) for quote in [*BACKGROUNDS[:2], original]]
    candidates = [*row, fact_id(snapshot, replacement)]
    selected = module._select_operation_facts(
        row, candidates, ("comment", "edit"), operations, quotes, hints,
        module.question_terms(QUESTION, "Example Product"), observations,
    )
    assert fact_id(snapshot, original) in selected
    assert fact_id(snapshot, replacement) in selected
    assert len(selected) == 3


def test_equivalent_repeated_source_branches_allow_one_copy_to_be_replaced():
    login = "Guests on Free plan must log in before collaboration on documents."
    original = "Guests on Free plan can comment on documents."
    detail, snapshot = anonymous_case([login, original, original, EDIT])
    module = retrieval_api()
    observations = {fact.id: operation_observations(fact) for fact in snapshot.facts}
    operations = {
        key: {row["operation"] for row in rows} for key, rows in observations.items()
    }
    quotes = {fact.id: fact.quote for fact in snapshot.facts}
    hints = {key: module.question_terms(quote, "Example Product") for key, quote in quotes.items()}
    row = [fact.id for fact in snapshot.facts[:3]]
    selected = module._select_operation_facts(
        row, [*row, fact_id(snapshot, EDIT)], ("comment", "edit"), operations, quotes, hints,
        module.question_terms(QUESTION, "Example Product"), observations,
    )
    assert fact_id(snapshot, login) in selected
    assert fact_id(snapshot, EDIT) in selected
    assert len(set(row[1:]) & set(selected)) == 1


def test_equivalent_branch_with_an_extra_operation_can_replace_the_original():
    login = "Guests on Free plan must log in before collaboration on documents."
    invitation = "Guests on Free plan need an invitation before collaboration on documents."
    original = "Guests on Free plan can comment on documents."
    replacement = "Guests on Free plan can comment on and edit documents."
    detail, snapshot = anonymous_case([login, invitation, original, replacement])
    module = retrieval_api()
    observations = {fact.id: operation_observations(fact) for fact in snapshot.facts}
    operations = {
        key: {row["operation"] for row in rows} for key, rows in observations.items()
    }
    quotes = {fact.id: fact.quote for fact in snapshot.facts}
    hints = {key: module.question_terms(quote, "Example Product") for key, quote in quotes.items()}
    row = [fact.id for fact in snapshot.facts[:3]]
    selected = module._select_operation_facts(
        row, [*row, fact_id(snapshot, replacement)], ("comment", "edit"), operations, quotes, hints,
        module.question_terms(QUESTION, "Example Product"), observations,
    )
    assert set(selected) == {
        fact_id(snapshot, login), fact_id(snapshot, invitation), fact_id(snapshot, replacement)
    }


@pytest.mark.asyncio
async def test_role_and_plan_conditions_stay_bound_to_their_original_fact():
    members = "Members on Enterprise plans can comment on documents."
    guests = "Guests on Free plan cannot edit documents."
    detail, snapshot = anonymous_case([*BACKGROUNDS, members, guests])
    before = {fact.id: operation_observations(fact) for fact in snapshot.facts}
    selected, _ = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert {fact_id(snapshot, members), fact_id(snapshot, guests)} <= set(selected)
    assert before == {fact.id: operation_observations(fact) for fact in snapshot.facts}
    assert before[fact_id(snapshot, members)][0]["role"] == "Members"
    assert before[fact_id(snapshot, members)][0]["plan"] == "Enterprise plans"
    assert before[fact_id(snapshot, guests)][0]["role"] == "Guests"
    assert before[fact_id(snapshot, guests)][0]["effect"] == "denied"


@pytest.mark.asyncio
async def test_question_conditions_do_not_supply_missing_source_operation_structure():
    detail, snapshot = anonymous_case(BACKGROUNDS)
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert len(selected) == 3
    row = diagnostic["questions"][0]
    assert set(row["requested_operations"]) == {"comment", "edit"}
    assert row["selected_operations"] == []
    assert set(row["missing_operations"]) == {"comment", "edit"}
    assert all(operation_observations(fact) == [] for fact in snapshot.facts)


@pytest.mark.asyncio
async def test_rejected_stored_operation_structure_cannot_gain_a_slot():
    detail, snapshot = anonymous_case([*BACKGROUNDS, COMMENT, EDIT])
    originals = tuple(
        fact.model_copy(update={"qualifiers_json": json.dumps({"operations": []})})
        if fact.quote in {COMMENT, EDIT} else fact
        for fact in snapshot.facts
    )
    snapshot = replace_snapshot(detail, snapshot, facts=originals)
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert not {fact_id(snapshot, COMMENT), fact_id(snapshot, EDIT)} & set(selected)
    assert set(diagnostic["questions"][0]["missing_operations"]) == {"comment", "edit"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,updates",
    [
        ("fact", {"competitor": "Other Product"}),
        ("fact", {"dimension": "pricing"}),
        ("fact", {"status": "signal"}),
        ("fact", {"status": "unknown"}),
        ("fact", {"source_id": "missing-source"}),
        ("source", {"role": "historical_report"}),
        ("source", {"material_level": "summary"}),
        ("source", {"material_level": "unknown"}),
        ("source", {"document_workspace_id": "foreign-workspace"}),
        ("source", {"document_project_id": "foreign-project"}),
        ("source", {"competitor": "Other Product", "covered_competitors": ()}),
        ("source", {"dimension": "pricing"}),
        ("source", {"last_verified_at": datetime.now(UTC) - timedelta(days=60)}),
    ],
)
async def test_operation_rescue_cannot_bypass_fact_or_source_eligibility(scope, updates):
    detail, snapshot = anonymous_case([*BACKGROUNDS, COMMENT])
    target = next(fact for fact in snapshot.facts if fact.quote == COMMENT)
    if scope == "fact":
        snapshot = replace_snapshot(
            detail, snapshot, facts=tuple(
                fact.model_copy(update=updates) if fact.id == target.id else fact
                for fact in snapshot.facts
            ),
        )
    else:
        snapshot = replace_snapshot(
            detail, snapshot, sources=tuple(
                source.model_copy(update=updates) if source.id == target.source_id else source
                for source in snapshot.sources
            ),
        )
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert target.id not in selected
    assert diagnostic["eligible_count"] == len(BACKGROUNDS)
    assert "comment" in diagnostic["questions"][0]["candidate_missing_operations"]


@pytest.mark.asyncio
async def test_conflicted_operation_original_cannot_gain_a_slot():
    detail, snapshot = anonymous_case([*BACKGROUNDS, COMMENT])
    target = next(fact for fact in snapshot.facts if fact.quote == COMMENT)
    conflict = EvidenceConflict(
        id="anonymous-conflict", competitor="Example Product", dimension="feature",
        field="evidence_terms", fact_ids=(target.id,), source_ids=(target.source_id,),
    )
    snapshot = replace_snapshot(detail, snapshot, conflicts=(conflict,))
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert target.id not in selected
    assert "comment" in diagnostic["questions"][0]["candidate_missing_operations"]


@pytest.mark.asyncio
async def test_operation_rescue_stays_inside_the_bounded_candidate_pool():
    backgrounds = [
        f"Guests on Free plan: documents collaboration overview {index}." for index in range(130)
    ]
    detail, snapshot = anonymous_case([*backgrounds, COMMENT, EDIT])
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert not {fact_id(snapshot, COMMENT), fact_id(snapshot, EDIT)} & set(selected)
    assert diagnostic["candidate_count"] == 128
    assert diagnostic["capacity_limited"] is True
    assert set(diagnostic["questions"][0]["missing_operations"]) == {"comment", "edit"}


@pytest.mark.asyncio
async def test_capacity_gaps_are_explicit_when_prerequisites_fill_the_question_quota():
    prerequisites = [
        "Guests must log in on Free plan before collaboration on documents.",
        "Guests need an invitation on Free plan before collaboration on documents.",
    ]
    question = (
        "Example Product: Must guests log in with an invitation to comment on and edit documents "
        "on Free plan?"
    )
    detail, snapshot = anonymous_case(
        [*prerequisites, *BACKGROUNDS, COMMENT, EDIT], question=question
    )
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert {fact_id(snapshot, quote) for quote in prerequisites} <= set(selected)
    assert len(selected) == 3
    row = diagnostic["questions"][0]
    assert len(row["selected_operations"]) == 1
    assert len(row["missing_operations"]) == 1
    assert row["candidate_missing_operations"] == []


@pytest.mark.asyncio
async def test_total_quota_diagnostics_describe_only_originals_actually_selected():
    quotes, questions = [], []
    for number in range(4):
        questions.append(
            "Example Product: Can guests comment on and edit documents on Free plan "
            f"for workflow{number}?"
        )
        quotes.extend([
            f"Guests on Free plan: documents collaboration overview for workflow{number}.",
            f"Guests can comment on documents for workflow{number}.",
            f"Guests can edit documents for workflow{number}.",
        ])
    detail, snapshot = anonymous_case(quotes, question="\n".join(questions))
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert len(selected) == 8
    assert all(len(row["fact_ids"]) <= 3 for row in diagnostic["questions"])
    originals = {fact.id: fact for fact in snapshot.facts}
    for row in diagnostic["questions"]:
        observed = {
            observation["operation"]
            for key in row["fact_ids"] if key in selected
            for observation in operation_observations(originals[key])
        }
        assert set(row["selected_operations"]) == observed & set(row["requested_operations"])
        assert set(row["missing_operations"]) == set(row["requested_operations"]) - observed
    assert any(row["missing_operations"] for row in diagnostic["questions"])


@pytest.mark.asyncio
async def test_non_operation_questions_keep_the_original_ranking():
    detail, snapshot = anonymous_case(
        [*BACKGROUNDS, COMMENT, EDIT],
        question="Example Product: What are the Free plan documents collaboration settings?",
    )
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert selected == tuple(fact_id(snapshot, quote) for quote in BACKGROUNDS)
    assert diagnostic["questions"][0]["requested_operations"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("rerank", [False, True])
async def test_structural_selection_runs_after_hybrid_or_truncated_reranking(
    tmp_path, monkeypatch, rerank
):
    class AnonymousEncoder:
        def encode(self, texts, **kwargs):
            return [[1.0, 0.0] for text in texts]

    class AnonymousReranker:
        def predict(self, pairs, **kwargs):
            assert len(pairs) == 12
            return [float(-number) for number, pair in enumerate(pairs)]

    monkeypatch.setattr(
        "packages.knowledge.local_models._load_sentence_transformer",
        lambda *args, **kwargs: AnonymousEncoder(),
    )
    monkeypatch.setattr(
        "packages.knowledge.local_models._load_cross_encoder",
        lambda *args, **kwargs: AnonymousReranker(),
    )
    background = [
        f"Guests on Free plan: documents collaboration overview {number}." for number in range(13)
    ]
    detail, snapshot = anonymous_case([*background, COMMENT, EDIT])
    provider = LocalEmbeddingProvider(
        tmp_path, model_id="intfloat/multilingual-e5-small", revision="anonymous-test"
    )
    reranker = LocalRerankerProvider(
        tmp_path, model_id="BAAI/bge-reranker-v2-m3", revision="anonymous-test", batch_size=12
    ) if rerank else None
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature",
        embedding_provider=provider, reranker_provider=reranker,
    )
    assert {fact_id(snapshot, COMMENT), fact_id(snapshot, EDIT)} <= set(selected)
    assert diagnostic["mode"] == ("hybrid_reranked" if rerank else "hybrid")
    assert diagnostic["candidate_count"] == 15


@pytest.mark.asyncio
async def test_explicit_lexical_degradation_keeps_structural_selection():
    detail, snapshot = anonymous_case([*BACKGROUNDS, COMMENT, EDIT])
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", embedding_provider=HashEmbeddingProvider()
    )
    assert {fact_id(snapshot, COMMENT), fact_id(snapshot, EDIT)} <= set(selected)
    assert diagnostic["mode"] == "degraded_lexical"
