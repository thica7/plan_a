from __future__ import annotations

import pytest

from packages.knowledge.ingestion import IngestionPipeline
from packages.knowledge.models import DocumentCreate
from packages.knowledge.repository import KnowledgeRepository

CHINESE_TEXT = "这是一段没有空格的中文产品说明" * 30


def test_unspaced_chinese_token_estimate_scales_with_content():
    estimate = IngestionPipeline._estimate_tokens(CHINESE_TEXT)

    assert estimate > 100
    assert IngestionPipeline._estimate_tokens(CHINESE_TEXT * 2) == pytest.approx(
        estimate * 2, abs=1
    )


def test_mixed_language_token_estimate_includes_chinese_content():
    prefix = "Enterprise pricing and SSO: "

    assert IngestionPipeline._estimate_tokens(prefix + CHINESE_TEXT) > 100
    assert IngestionPipeline._estimate_tokens(prefix + CHINESE_TEXT) > (
        IngestionPipeline._estimate_tokens(CHINESE_TEXT)
    )


@pytest.mark.parametrize("text", ["!!!", "🧑‍💻", "Basic pricing: 29 USD/month."])
def test_nonempty_token_estimates_remain_positive(text):
    assert IngestionPipeline._estimate_tokens(text) >= 1


@pytest.mark.asyncio
async def test_ingestion_persists_a_scaled_chinese_token_estimate(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "knowledge.db")) as repo:
        document_id = await IngestionPipeline(repo, object()).ingest(
            DocumentCreate(
                title="中文产品说明",
                source_type="manual",
                text=CHINESE_TEXT,
            )
        )
        chunks = await repo.get_chunks_for_document(document_id)

    assert len(chunks) == 1
    assert chunks[0].text == CHINESE_TEXT
    assert chunks[0].token_count > 100
