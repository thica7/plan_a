"""The opt-in CLI archive keeps full captures without changing production results."""

import hashlib
import json

import pytest

from packages.research.models import CapturedPage, SourceCandidate
from packages.research import pipeline
from scripts import eval_official_writer


def candidate_and_page():
    candidate = SourceCandidate(title='Example billing', url='https://example.test/billing',
                                competitor='Example', dimension='feature', origin='manual')
    body = 'Pricing\nRequests and CPU time are billed separately.\n' * 300
    page = CapturedPage(
        candidate_id=candidate.id, requested_url=candidate.url, final_url=candidate.url,
        title=candidate.title, text=body, status='ok', status_code=200,
        content_hash=hashlib.sha256(body.encode()).hexdigest(),
        metadata={'document_headings': [[1, 'Pricing']], 'capture_marker': 'original'},
    )
    return candidate, page


@pytest.mark.asyncio
async def test_full_body_and_actual_headings_are_saved_without_replacing_the_result(tmp_path, monkeypatch):
    candidate, page = candidate_and_page()

    async def capture(*args, **kwargs):
        return page

    monkeypatch.setattr(pipeline, 'capture_candidate', capture)
    before = page.model_dump_json()
    with eval_official_writer.capture_archive(tmp_path):
        assert await pipeline.capture_candidate(candidate, object()) is page
    assert pipeline.capture_candidate is capture and page.model_dump_json() == before
    records = json.loads((tmp_path / 'pipeline-captures.json').read_text())
    assert len(records) == 1 and records[0]['page'] == page.model_dump(mode='json')
    assert len(records[0]['page']['text']) > 12000
    assert records[0]['body_sha256'] == hashlib.sha256(page.text.encode()).hexdigest()
    assert records[0]['exported_body_sha256'] == records[0]['body_sha256']
    assert records[0]['body_redacted'] is False
    assert records[0]['candidate']['id'] == candidate.id


@pytest.mark.asyncio
async def test_completed_capture_survives_later_failure_and_the_wrapper_is_restored(tmp_path, monkeypatch):
    candidate, page = candidate_and_page()

    async def capture(*args, **kwargs):
        return page

    monkeypatch.setattr(pipeline, 'capture_candidate', capture)
    with pytest.raises(RuntimeError, match='later stage failed'):
        with eval_official_writer.capture_archive(tmp_path):
            await pipeline.capture_candidate(candidate, object())
            raise RuntimeError('later stage failed')
    assert pipeline.capture_candidate is capture
    assert json.loads((tmp_path / 'pipeline-captures.json').read_text())[0]['page']['id'] == page.id


@pytest.mark.asyncio
async def test_capture_archive_uses_existing_secret_redaction(tmp_path, monkeypatch):
    candidate, page = candidate_and_page()
    page.text += '\napi_key=synthetic-credential-only\n'

    async def capture(*args, **kwargs):
        return page

    monkeypatch.setattr(pipeline, 'capture_candidate', capture)
    with eval_official_writer.capture_archive(tmp_path):
        await pipeline.capture_candidate(candidate, object())
    saved = (tmp_path / 'pipeline-captures.json').read_text()
    assert 'synthetic-credential-only' not in saved and '[redacted:' in saved
    assert 'synthetic-credential-only' in page.text
    record = json.loads(saved)[0]
    assert record['body_redacted'] is True
    assert record['exported_body_sha256'] == hashlib.sha256(record['page']['text'].encode()).hexdigest()
    assert record['exported_body_sha256'] != record['body_sha256']
