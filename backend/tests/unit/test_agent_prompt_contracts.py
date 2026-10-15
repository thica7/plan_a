import pytest
from test_run_evidence_snapshot import make_detail

from packages.config import Settings
from packages.memory import KBCache, RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.models import ComparisonMatrix, RawSource
from packages.skills.registry import SkillRegistry


@pytest.fixture
def service(tmp_path):
    return RunService(
        SkillRegistry.from_default_path(),
        Settings(demo_mode=True),
        journal=RunJournal(tmp_path / "journal.db"),
        kb_cache=KBCache.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )


def detail_with_sources():
    detail = make_detail()
    detail.plan.dimensions = ["pricing"]
    detail.raw_sources = [
        RawSource(
            id=f"source-{name}",
            competitor=name,
            dimension="pricing",
            source_type="webpage_verified",
            title=f"{name} price",
            url=f"https://{name[-1].lower()}.example/pricing",
            snippet=f"{name} Pro $20 per seat monthly",
            confidence=0.95,
            content_hash=f"hash-{name}",
        )
        for name in detail.plan.competitors
    ]
    return detail


def assessment(status, winner=None, ids=None):
    return dict(
        status=status,
        winner=winner,
        rationale="Evidence differs or is missing.",
        scenario="US solo buyer",
        tradeoffs=["Coverage does not imply product superiority."],
        gaps=[] if status == "comparable" else ["billing interval unclear"],
        source_ids=ids or [],
    )


@pytest.mark.parametrize("status", ["not_comparable", "insufficient_evidence"])
def test_unresolved_comparison_is_preserved_and_cannot_become_winner(service, status):
    detail = detail_with_sources()
    payload = {
        "winner_by_dimension": {"pricing": "Product A"},
        "assessments": {"pricing": assessment(status)},
    }
    matrix = service._build_comparison_matrix(detail, payload)
    assert "pricing" not in matrix.winner_by_dimension
    saved = ComparisonMatrix.model_validate_json(matrix.model_dump_json())
    assert saved.model_dump()["assessments"]["pricing"]["status"] == status


def test_comparable_winner_requires_sources_for_all_researched_products(service):
    detail = detail_with_sources()
    matrix = service._build_comparison_matrix(
        detail,
        {
            "assessments": {"pricing": assessment("comparable", "Product A", ["source-Product A"])},
        },
    )
    assert "pricing" not in matrix.winner_by_dimension
    assert matrix.model_dump()["assessments"]["pricing"]["status"] == "insufficient_evidence"


@pytest.mark.parametrize("ids", [["invented"], ["source-Product A", "source-Product B"]])
def test_unknown_or_wrong_dimension_citations_cannot_support_winner(service, ids):
    detail = detail_with_sources()
    detail.raw_sources[1].dimension = "feature"
    matrix = service._build_comparison_matrix(
        detail,
        {
            "assessments": {"pricing": assessment("comparable", "Product A", ids)},
        },
    )
    assert "pricing" not in matrix.winner_by_dimension


def test_valid_assessment_overrides_source_count_vote(service):
    detail = detail_with_sources()
    # B having more pages must not override the task-specific assessment favoring A.
    detail.raw_sources.extend(
        [detail.raw_sources[1].model_copy(update={"id": f"extra-{n}"}) for n in range(4)]
    )
    matrix = service._build_comparison_matrix(
        detail,
        {
            "assessments": {
                "pricing": assessment(
                    "comparable", "Product A", ["source-Product A", "source-Product B"]
                )
            },
        },
    )
    assert matrix.winner_by_dimension.get("pricing") == "Product A"
    assert matrix.model_dump()["assessments"]["pricing"]["scenario"] == "US solo buyer"


def test_legacy_comparison_matrix_remains_loadable():
    assert (
        ComparisonMatrix(competitors=["A"], dimensions=["pricing"]).model_dump().get("assessments")
        == {}
    )


@pytest.mark.parametrize(
    "source_type,confidence",
    [("web_search_result", 0.95), ("llm_public_knowledge", 0.95), ("webpage_verified", 0.5)],
)
def test_search_or_low_confidence_evidence_cannot_support_comparable_winner(
    service, source_type, confidence
):
    detail = detail_with_sources()
    detail.raw_sources[1].source_type = source_type
    detail.raw_sources[1].confidence = confidence
    matrix = service._build_comparison_matrix(
        detail,
        {
            "assessments": {
                "pricing": assessment(
                    "comparable", "Product A", ["source-Product A", "source-Product B"]
                )
            },
        },
    )
    assert "pricing" not in matrix.winner_by_dimension
