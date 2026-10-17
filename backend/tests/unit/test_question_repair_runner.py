from types import SimpleNamespace

import pytest

from scripts.eval_official_writer import collect_sources


@pytest.mark.asyncio
async def test_fixed_official_runner_enables_question_repairs_without_discovery():
    calls = []

    class Service:
        async def _collect_competitor_with_research_pipeline(self, *args, **kwargs):
            calls.append(kwargs)
            return []

        def _finish_delivery_phase(self, *args):
            pass

    record = SimpleNamespace(detail=SimpleNamespace(id='unit', raw_sources=[],
        plan=SimpleNamespace(competitors=['Example Suite'])))
    await collect_sources(Service(), record, [dict(product='Example Suite', sources=[
        dict(title='Official guide', url='https://example.invalid/docs')])])
    assert len(calls) == 1
    assert calls[0]['enable_repair'] is True
    assert calls[0]['enable_search'] is False
    assert calls[0]['include_official'] is False


@pytest.mark.asyncio
async def test_fixed_official_runner_counts_shared_document_only_once():
    calls = []

    class Service:
        async def _collect_competitor_with_research_pipeline(self, *args, **kwargs):
            calls.append(kwargs)
            return []

        def _finish_delivery_phase(self, *args):
            pass

    record = SimpleNamespace(detail=SimpleNamespace(id='unit', raw_sources=[],
        plan=SimpleNamespace(competitors=['Example Suite'])))
    payloads = [dict(product='Example Suite', sources=[dict(title=title,
        url='https://example.invalid/docs')]) for title in ['Guide, question A', 'Guide, question B']]
    await collect_sources(Service(), record, payloads)
    assert calls[0]['target_source_count'] == 1
    assert len(calls[0]['seed_candidates']) == 1
