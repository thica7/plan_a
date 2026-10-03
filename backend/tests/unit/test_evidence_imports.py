"""Fresh interpreters must not rely on pytest's existing import order."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PUBLIC_EXPORTS = (
    "accepted_evidence_by_page",
    "accepted_evidence_items",
    "admit_evidence_items",
    "citation_refs_from_evidence_items",
    "dedupe_by_id",
    "deterministic_claim_text_from_source",
    "evidence_items_from_extractions",
    "normalized_fields_as_dicts",
    "normalized_fields_from_evidence_items",
    "normalized_fields_from_source",
    "normalized_summary_from_source",
    "publishable_text_noise_problem",
    "rejected_evidence_items",
    "raw_source_from_capture",
    "raw_sources_from_research_result",
    "snippet_from_evidence_items",
    "source_business_snippet",
    "source_quality_problem",
)


@pytest.mark.parametrize(
    "first_import",
    [
        "from packages.schema.api_dto import RunDetail",
        "from packages.memory.run_journal import RunJournal",
        "from packages.research.evidence import *",
    ],
)
def test_evidence_public_exports_support_fresh_import_order(first_import: str) -> None:
    program = f"""
{first_import}
from packages.schema.api_dto import RunDetail
from packages.memory.run_journal import RunJournal
import packages.research.evidence as evidence
expected = {PUBLIC_EXPORTS!r}
assert tuple(evidence.__all__) == expected
assert all(callable(getattr(evidence, name)) for name in expected)
namespace = {{}}
exec('from packages.research.evidence import *', namespace)
assert all(callable(namespace[name]) for name in expected)
try:
    evidence.unknown_export
except AttributeError:
    pass
else:
    raise AssertionError('unknown exports must raise AttributeError')
"""
    environment = os.environ.copy()
    environment["COMPETISCOPE_LOAD_ENV_FILES"] = "0"
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    result = subprocess.run(
        [sys.executable, "-c", program],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
