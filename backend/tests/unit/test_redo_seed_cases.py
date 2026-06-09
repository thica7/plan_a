import json
from pathlib import Path

from packages.orchestrator.redo_seed_cases import (
    DEFAULT_REDO_SCOPE_SNAPSHOT_PATH,
    EXPECTED_REDO_SCOPE_KINDS,
    build_redo_scope_seed_cases,
    redo_scope_seed_snapshot,
)


def test_redo_scope_seed_cases_cover_all_five_routes() -> None:
    cases = build_redo_scope_seed_cases()

    assert {case.assigned_scope.kind for case in cases} == EXPECTED_REDO_SCOPE_KINDS
    assert [case.expected_scope.kind for case in cases] == [
        "writer_only",
        "comparator",
        "analyst",
        "collector",
        "full",
    ]
    assert all(case.assigned_scope == case.expected_scope for case in cases)


def test_redo_scope_seed_cases_match_expected_snapshot() -> None:
    expected = json.loads(Path(DEFAULT_REDO_SCOPE_SNAPSHOT_PATH).read_text(encoding="utf-8"))

    assert redo_scope_seed_snapshot() == expected
