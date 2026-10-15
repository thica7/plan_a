from types import SimpleNamespace

import pytest

from packages.agents.survey.logic import SurveyInterviewAgentMixin
from packages.research.evidence.admission import admit_evidence_items
from packages.research.extraction.feature import extract_generic_capabilities
from packages.research.extraction.persona import extract_generic_persona
from packages.research.extraction.quality import quote_quality_problem
from packages.research.models import CapturedPage, ResearchBrief


def brief(dimension='feature'):
    return ResearchBrief(run_id='hardware', topic='portable devices', competitor='Orion Pocket OLED',
                         dimension=dimension, product_category='handheld')


def page(text, **updates):
    return CapturedPage(candidate_id='hardware', requested_url='https://review.example/devices',
        final_url='https://review.example/devices', title='Portable devices', text=text,
        status='ok', quality_score=.9, content_hash='hardware', **updates)


@pytest.mark.parametrize('fact', [
    'Orion Pocket OLED has a 50 Wh battery for portable gaming.',
    'Orion Pocket OLED has a 50 Whr battery for portable gaming.',
    'Orion Pocket OLED has a 45 W power supply for charging.',
    'Orion Pocket OLED has a weight of 640 g including controllers.',
    'Orion Pocket OLED comes with Wifi 6E for online play.',
    'Orion Pocket OLED has 30-50% more battery life.',
    'Orion Pocket OLED 配備 50 Whr 電池與 45 W 電源供應器。',
])
def test_named_hardware_facts_reach_admission(fact):
    p = page(fact)
    result = extract_generic_capabilities(brief(), p)
    assert result.quotes
    assert all(p.text[q.start_offset:q.end_offset] == q.text for q in result.quotes)
    assert all(i.status == 'accepted' for i in admit_evidence_items([result], captured_pages=[p]))


def test_section_specs_without_sentence_identity_remain_a_collection_gap():
    text = ('Orion Pocket LCD\nBattery 40 Whr; 2-8 hours depending on game content.\n'
            'Orion Pocket OLED\nBattery 50 Whr; 3-12 hours depending on game content.\n'
            'Power supply 45 W. Weight 640 g. Display 1280 x 800 OLED. Wifi 6E.\n'
            'Other device\nBattery 99 Whr; 20 hours of play.')
    p = page(text, metadata={'document_headings': [(2, 'Orion Pocket LCD'),
        (2, 'Orion Pocket OLED'), (2, 'Other device')]})
    result = extract_generic_capabilities(brief(), p)
    assert result.fields == {}
    assert result.missing_fields == ['product_capabilities']
    assert not admit_evidence_items([result], captured_pages=[p])


@pytest.mark.parametrize('text,metadata', [
    ('Other device\nBattery 50 Whr for portable gaming.', {'document_headings': [(2,'Other device')]}),
    ('OLED\nBattery 50 Whr for portable gaming.', {'document_headings': [(2,'OLED')]}),
    ('Battery 50 Whr for portable gaming.', {'document_headings': [(2,'Orion Pocket OLED')]}),
    ('Orion Pocket OLED\nBattery 50 for portable gaming.', {'document_headings': [(2,'Orion Pocket OLED')]}),
    ('Orion Pocket OLED\nWin a 50 Whr battery in our launch giveaway.', {'document_headings': [(2,'Orion Pocket OLED')]}),
    ('Orion Pocket OLED\nSkip to content Navigation menu Sign in Privacy policy 50 Whr.', {'document_headings': [(2,'Orion Pocket OLED')]}),
])
def test_unbound_or_noisy_spec_sections_stay_empty(text, metadata):
    assert not extract_generic_capabilities(brief(), page(text, metadata=metadata)).fields


@pytest.mark.parametrize('fact,field,value', [
    ('Orion Pocket OLED is designed for portable PC gaming.', 'primary_use_case', 'portable PC gaming'),
    ('Orion Pocket OLED is optimized for handheld gaming.', 'primary_use_case', 'handheld gaming'),
    ('Orion Pocket OLED is for travelling players.', 'target_segment', 'travelling players'),
])
def test_explicit_english_persona_relationship_preserves_quote_offsets(fact, field, value):
    p=page(fact)
    result=extract_generic_persona(brief('persona'),p)
    assert result.fields[field] == value
    assert all(p.text[q.start_offset:q.end_offset] == q.text for q in result.quotes)
    assert all(i.status == 'accepted' for i in admit_evidence_items([result], captured_pages=[p]))
    assert p.final_url == 'https://review.example/devices'


@pytest.mark.parametrize('fact', [
    'Orion Pocket OLED has a 50 Whr battery and 640 g weight.',
    'Orion Pocket LCD is designed for portable PC gaming.',
    'Orion Pocket OLED X is designed for portable PC gaming.',
    'Orion Pocket OLED and Orion Pocket LCD are designed for portable PC gaming.',
    'Orion Pocket OLED is not designed for portable PC gaming.',
    'A case for Orion Pocket OLED is designed for travelling players.',
])
def test_specs_and_wrong_or_negated_subject_do_not_infer_persona(fact):
    assert not extract_generic_persona(brief('persona'),page(fact)).fields


@pytest.mark.asyncio
async def test_real_enrichment_leaves_missing_external_research_without_synthetic_facts():
    class Harness(SurveyInterviewAgentMixin):
        def __init__(self): self.messages=[]; self.events=[]
        async def emit(self,*args): self.events.append(args)
        def _append_agent_message(self, record, **kwargs): self.messages.append(kwargs)
        def _qa_feedback_for_branch(self,*args): return []
        def _build_survey_interview_bundle(self,*args,**kwargs):
            pytest.fail('real research must not auto-generate synthetic evidence')
    h=Harness()
    detail=SimpleNamespace(id='real-hardware', execution_mode='real', current_node='',raw_sources=[],
                           competitor_knowledge={},competitor_kbs={})
    await h._run_survey_interview_enrichment(SimpleNamespace(detail=detail),['persona'],['Orion Pocket OLED'])
    assert detail.raw_sources == []
    assert h.messages[-1]['payload']['reason'] == 'external_user_research_required'
    assert h.messages[-1]['payload']['dimensions'] == ['persona']
    assert h.messages[-1]['payload']['competitors'] == ['Orion Pocket OLED']
    assert h.events[-1][-1]['missing'] == [{'dimension':'persona','competitor':'Orion Pocket OLED'}]


@pytest.mark.parametrize('fact', [
    'Orion Pocket OLED X has a 50 Whr battery for portable gaming.',
    'Orion Pocket OLED has a new screen with amazing gaming performance.',
    'Orion Pocket OLED offers a 50 Whr battery prize in our giveaway.',
])
def test_named_wrong_model_or_marketing_is_not_hardware_evidence(fact):
    assert not extract_generic_capabilities(brief(), page(fact)).fields


def test_spec_section_does_not_override_explicit_different_model_subject():
    p = page('Orion Pocket OLED\nOrion Pocket LCD has a 40 Whr battery for portable gaming.',
             metadata={'document_headings': [(2, 'Orion Pocket OLED')]})
    result = extract_generic_capabilities(brief(), p)
    assert result.fields == {}
    assert not admit_evidence_items([result], captured_pages=[p])


@pytest.mark.parametrize(('fact', 'expected'), [
    ('Orion Pocket OLED is designed for portable PC gaming; only while connected to power.',
     'portable PC gaming; only while connected to power'),
    ('Orion Pocket OLED is optimized for portable gaming with firmware 3.5 or later.',
     'portable gaming with firmware 3.5 or later'),
    ('Orion Pocket OLED is designed for gaming on a 7.4-inch display.',
     'gaming on a 7.4-inch display'),
])
def test_english_persona_keeps_adjacent_condition_and_decimal(fact, expected):
    p = page(fact)
    result = extract_generic_persona(brief('persona'), p)
    assert result.fields['primary_use_case'] == expected
    assert result.quotes[0].text == fact
    assert all(p.text[q.start_offset:q.end_offset] == q.text for q in result.quotes)
    assert all(i.status == 'accepted' for i in admit_evidence_items([result], captured_pages=[p]))


@pytest.mark.parametrize('body', [
    'Battery (Orion Pocket LCD): 40 Whr for portable gaming.',
    'Battery 50 Whr. Orion Pocket LCD: Battery 40 Whr.',
])
def test_section_label_cannot_override_explicit_other_model(body):
    p = page('Orion Pocket OLED\n' + body,
             metadata={'document_headings': [(2, 'Orion Pocket OLED')]})
    # Even an exact specs title cannot reactivate the old fallback on a sectioned page.
    p.title = 'Orion Pocket OLED specifications'
    assert not extract_generic_capabilities(brief(), p).fields


@pytest.mark.asyncio
async def test_real_run_service_enrichment_uses_registered_skip_message_payload():
    from packages.config import Settings
    from packages.orchestrator.checkpointer import GraphCheckpointer
    from packages.orchestrator.service import RunService
    from packages.schema.api_dto import RunCreateRequest
    from packages.skills.registry import SkillRegistry

    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=False, ark_api_key='offline-fixture',
                          ark_model='model', ark_base_url='https://invalid.example/v3'),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    try:
        detail = await service.create_run(RunCreateRequest(
            topic='Hardware user research', competitors=['Orion Pocket OLED'],
            dimensions=['persona'], execution_mode='real',
        ))
        record = service._runs[detail.id]
        await service._run_survey_interview_enrichment(record, ['persona'], ['Orion Pocket OLED'])
        message = record.detail.agent_messages[-1]
        assert message.message_type == 'survey_interview_skipped'
        assert message.payload_schema == 'SurveyEvidenceBundle[]'
        assert message.payload['reason'] == 'external_user_research_required'
        assert message.payload['bundles'] == []
        assert message.payload['dimensions'] == ['persona']
        assert message.payload['competitors'] == ['Orion Pocket OLED']
        assert 'missing' not in message.payload
        assert record.detail.raw_sources == []
        assert record.detail.competitor_knowledge == {}
        completed = next(event for event in service.get_trace(detail.id) or []
                         if event.type == 'node_completed' and event.agent == 'survey_interview')
        assert completed.payload['missing'] == [
            {'dimension': 'persona', 'competitor': 'Orion Pocket OLED'},
        ]
    finally:
        await service._graph_checkpointer.aclose()
