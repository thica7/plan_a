"""A bounded question delivery does not require an invented competitor."""

import pytest
from test_run_evidence_snapshot import make_detail
from test_writer_question_delivery import service_for

from packages.schema.models import (
    ComparisonCell, ComparisonMatrix, DecisionBrief, ReflectionRecord, TargetProduct,
)

COMPARISON_GAPS = [
    'Feature dimension is marked insufficient_evidence (gap_count=6), blocking a validated feature comparison.',
    'No multi-competitor feature matrix exists; cross-competitor comparison cannot be produced.',
]


def scope_case():
    detail = make_detail()
    detail.topic = detail.plan.topic = 'ExampleCompute 权限与计费条件研究'
    detail.plan.competitors = ['ExampleCompute']
    detail.plan.dimensions = ['feature']
    detail.plan.target_product = TargetProduct(name='ExampleCompute')
    detail.plan.decision_brief = DecisionBrief(decision_question=(
        'ExampleCompute: Can this role clear another domain?\n'
        'ExampleCompute: Does 15 million requests determine our exact monthly bill?'))
    detail.comparison_matrix = ComparisonMatrix(competitors=['ExampleCompute'], dimensions=['feature'],
        cells=[ComparisonCell(competitor='ExampleCompute', dimension='feature', value='Bounded evidence',
                              source_ids=['example-source'], confidence=.9)])
    service, _ = service_for(detail)
    return detail, service


def gate(service, detail, gaps=COMPARISON_GAPS):
    return service._reflection_gate(detail, coverage_gaps=[], confidence_outliers=[],
        cross_competitor_gaps=[], llm_gate_status='block', llm_blocking_gaps=gaps)


def test_server_rechecks_llm_comparison_only_blocks_for_explicit_single_product_questions():
    detail, service = scope_case()
    assert gate(service, detail)[0] != 'block'
    detail.reflections = [ReflectionRecord(iteration=1, gate_status='block', blocking_gaps=COMPARISON_GAPS)]
    assert not [i for i in service._build_reflector_qa_issues(detail) if i.severity == 'blocker']


@pytest.mark.parametrize('change', ['multi', 'target', 'full', 'full_analysis', 'full_research',
                                   'better_than', 'comparison', 'no_questions'])
def test_comparison_and_actual_coverage_gaps_keep_the_original_gate(change):
    detail, service = scope_case()
    if change == 'multi':
        detail.plan.competitors.append('OtherCompute')
    elif change == 'target':
        detail.plan.target_product = TargetProduct(name='OtherCompute')
    elif change == 'full':
        detail.plan.topic = 'ExampleCompute 完整 PM 全功能分析报告'
    elif change in {'full_analysis', 'full_research', 'better_than'}:
        detail.plan.decision_brief = DecisionBrief(decision_question={
            'full_analysis': 'ExampleCompute: 请完整分析 ExampleCompute 的权限与计费能力？',
            'full_research': 'ExampleCompute: 请完整研究 ExampleCompute 的权限与计费能力？',
            'better_than': 'ExampleCompute: Is ExampleCompute better than OtherCompute for role permissions?',
        }[change])
    elif change == 'comparison':
        detail.plan.decision_brief = DecisionBrief(decision_question='ExampleCompute: Compare all features and rank competitors?')
    elif change == 'no_questions':
        detail.plan.decision_brief = None
    assert gate(service, detail)[0] == 'block'
    detail.reflections = [ReflectionRecord(iteration=1, gate_status='block', blocking_gaps=COMPARISON_GAPS)]
    assert any(i.severity == 'blocker' for i in service._build_reflector_qa_issues(detail))


@pytest.mark.parametrize('finding', [
    'The requested role scope has no supporting evidence.',
    'The second question is unanswered.',
    'The published comparison conclusion has no supporting evidence.',
    'Unknown unresolved issue requires review.',
    'No multi-competitor matrix exists; the requested role has no supporting evidence.',
    'Feature dimension is marked insufficient_evidence (gap_count=6), blocking a validated feature comparison. The billing rule is absent.',
    'Missing comparison cell for ExampleCompute / feature '
    'because the requested role has no supporting evidence.',
    'Missing comparison cell for ExampleCompute / feature '
    'because the billing rule is absent.',
    'Comparison cell for ExampleCompute / feature '
    'because the requested role has no supporting evidence has no source_ids.',
    'Missing comparison cell for OtherCompute / feature.',
    'Comparison cell for ExampleCompute / pricing has no source_ids.',
])
def test_question_evidence_and_unknown_blocks_are_preserved(finding):
    detail, service = scope_case()
    assert gate(service, detail, [*COMPARISON_GAPS, finding]) == ('block', [finding])
    detail.reflections = [ReflectionRecord(iteration=1, gate_status='block',
        blocking_gaps=[*COMPARISON_GAPS, finding])]
    assert [i.problem for i in service._build_reflector_qa_issues(detail)
            if i.severity == 'blocker'] == [finding]


def test_block_without_a_reason_is_not_reinterpreted_as_a_comparison_gap():
    detail, service = scope_case()
    assert gate(service, detail, [])[0] == 'block'


@pytest.mark.parametrize('finding', [
    'Missing comparison cell for ExampleCompute / feature.',
    'Comparison cell for ExampleCompute / feature has no source_ids.',
])
def test_only_current_plan_complete_cell_messages_are_outside_question_scope(finding):
    detail, service = scope_case()
    assert gate(service, detail, [finding])[0] != 'block'
    detail.reflections = [ReflectionRecord(iteration=1, gate_status='block',
        blocking_gaps=[finding])]
    assert not [i for i in service._build_reflector_qa_issues(detail) if i.severity == 'blocker']


@pytest.mark.parametrize('matrix', ['missing', 'empty', 'uncited'])
def test_explicit_question_scope_does_not_require_matrix_or_matrix_citations(matrix):
    detail, service = scope_case()
    if matrix == 'missing':
        detail.comparison_matrix = None
    elif matrix == 'empty':
        detail.comparison_matrix.cells = []
    else:
        detail.comparison_matrix.cells[0].source_ids = []
    assert gate(service, detail)[0] != 'block'
    payload = service._deterministic_reflector_payload(detail)
    assert not payload['cross_competitor_gaps']
    assert not payload['coverage_gaps']
    assert gate(service, detail, ['The second question is unanswered.'])[0] == 'block'


def test_explicit_exact_price_instruction_is_question_scope_without_question_mark():
    from packages.agents.reflector.logic import _question_delivery_scope

    detail, service = scope_case()
    detail.comparison_matrix = None
    detail.plan.decision_brief = DecisionBrief(decision_question=(
        'ExampleCompute: 能访问两个容器吗？\n'
        'ExampleCompute: 300名员工购买一年。请仅凭公开定价页，'
        '直接给出精确的人民币含税总价，不要给区间。'))
    assert not _question_delivery_scope(detail)['requires_comparison']
    assert gate(service, detail)[0] != 'block'
