"""Readiness data is scoped, redacted and unlabelled until explicit review."""

import hashlib
import importlib
import json

import pytest


def api():
    try:
        return importlib.import_module('scripts.prepare_agent_readiness')
    except ModuleNotFoundError:
        pytest.fail('Agent readiness export is not implemented')


def artifact(tmp_path, name='run-a', **changes):
    folder = tmp_path / name
    folder.mkdir()
    run = dict(id=name, workspace_id='w', project_id='p', execution_mode='real',
        status='completed', plan={'competitors': ['Example Suite']}, report_md='A local report.',
        raw_sources=[{'id': 's', 'competitor': 'Example Suite', 'url': 'https://example.test/guide'}],
        trace_spans=[{'id': 'a', 'kind': 'llm', 'agent': 'writer', 'name': 'write', 'status': 'ok',
                      'full_input': 'A question', 'full_output': 'A source-bound observation', 'metadata': {}}],
        qa_findings=[], report_dimension_audits=[{'competitor': 'Example Suite', 'dimension': 'feature',
            'consumption_id': 'use', 'claims': [], 'answer_coverage': [{'question_id': 'q',
                'question': 'Can Guests edit?', 'status': 'answered', 'claim_ids': ['c'],
                'answer': 'Guests can edit after authorization.'}]}])
    run.update(changes)
    manifest = {'production_code_sha256': 'a' * 64}
    manifest['manifest_sha256'] = hashlib.sha256(json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    summary = dict(manifest, mechanical_pass=True, llm_transport_attempts=1,
                   provider_total_tokens_last_attempts=100, provider_usage_unknown_transport_spans=0)
    values = {'run.json': run, 'trace.json': run['trace_spans'], 'manifest.json': manifest,
              'summary.json': summary, 'snapshot.json': []}
    for key, value in values.items():
        (folder / key).write_text(json.dumps(value))
    (folder / 'report.md').write_text(run['report_md'] + '\n')
    return folder


def annotation(folder, outcome='success'):
    return dict(run_id=folder.name, question_id='q', product='Example Suite',
        report_sha256=hashlib.sha256((folder / 'report.md').read_bytes()).hexdigest(),
        candidate_outcome=outcome, label_status='candidate',
        review_source='agent_candidate', reason='Awaiting project-user verification.')


def test_completion_and_qa_do_not_generate_correctness_rewards(tmp_path):
    folder = artifact(tmp_path)
    result = api().prepare_readiness([folder], workspace='w')
    row = result['episodes'][0]
    assert row['candidate_outcome'] == 'unlabelled'
    assert row['reward']['correctness'] is None and not row['training_ready']
    assert row['partition'] == 'development'


def test_question_episode_preserves_replayable_claim_selection_metadata(tmp_path):
    folder = artifact(tmp_path)
    run = json.loads((folder / 'run.json').read_text())
    audit = run['report_dimension_audits'][0]
    audit['answer_binding_version'] = 2
    audit['answer_coverage'][0].update(binding_version=2, resolution='conditional', conclusion='depends')
    (folder / 'run.json').write_text(json.dumps(run))
    row = api().prepare_readiness([folder], workspace='w')['episodes'][0]
    assert row['claim_ids'] == ['c']
    assert row['answer_binding_version'] == row['coverage_binding_version'] == 2
    assert row['resolution'] == 'conditional' and row['conclusion'] == 'depends'


@pytest.mark.parametrize('outcome', ['success', 'failure', 'reasonable_abstention'])
def test_explicit_candidate_categories_are_not_human_labels(tmp_path, outcome):
    folder = artifact(tmp_path)
    result = api().prepare_readiness([folder], workspace='w', annotations=[annotation(folder, outcome)])
    row = result['episodes'][0]
    assert row['candidate_outcome'] == outcome and row['label_status'] == 'candidate'
    assert row['reward']['correctness'] is None and not row['training_ready']


@pytest.mark.parametrize('change', [{'workspace_id': 'other'}, {'execution_mode': 'demo'},
                                  {'metadata': {'synthetic': True}}])
def test_scope_and_synthetic_records_are_rejected(tmp_path, change):
    folder = artifact(tmp_path, **change)
    with pytest.raises(ValueError):
        api().prepare_readiness([folder], workspace='w')


def test_input_hashes_and_rerun_group_are_stable_without_mutating_sources(tmp_path):
    first, second = artifact(tmp_path), artifact(tmp_path, 'run-b')
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob('*') if p.is_file()}
    result = api().prepare_readiness([first, second], workspace='w')
    assert len({row['task_group_id'] for row in result['episodes']}) == 1
    assert all(row['partition'] == 'development' for row in result['episodes'])
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
    assert all(row['input_hashes']['run.json'] for row in result['trajectories'])


def test_sensitive_and_truncated_actions_are_not_training_ready(tmp_path):
    secret = 'sk-' + 'syntheticsecret' * 3
    folder = artifact(tmp_path, trace_spans=[dict(id='x', kind='llm', agent='writer', name='write',
        status='ok', full_input='api_key=' + secret + ' person@example.test',
        full_output='condition ' * 1000, metadata={})])
    result = api().prepare_readiness([folder], workspace='w')
    serialized = json.dumps(result)
    assert secret not in serialized and 'person@example.test' not in serialized
    assert result['trajectories'][0]['actions'][0]['output_truncated']
    assert not result['episodes'][0]['training_ready']


def test_a_candidate_annotation_cannot_be_silently_promoted_or_rebound(tmp_path):
    folder = artifact(tmp_path)
    for change in ({'label_status': 'reviewed'}, {'report_sha256': '0' * 64},
                   {'run_id': 'different-run'}, {'question_id': 'different-question'},
                   {'product': 'Other Suite'}):
        with pytest.raises(ValueError):
            api().prepare_readiness([folder], workspace='w', annotations=[annotation(folder) | change])


def test_inconsistent_artifact_files_are_rejected(tmp_path):
    folder = artifact(tmp_path)
    (folder / 'report.md').write_text('A different report.')
    with pytest.raises(ValueError):
        api().prepare_readiness([folder], workspace='w')


def test_runtime_evaluation_input_contains_no_gold_or_excerpt():
    rows = [dict(id='new', product='New Suite', question='Can reviewers approve?',
        expected_boundary='Secret gold', review_status='candidate',
        sources=[dict(id='new-s', title='Official', url='https://new.test/help', excerpt='Secret quote')])]
    runtime = api().evaluation_runtime(rows)
    assert runtime == [dict(id='new', product='New Suite', question='Can reviewers approve?',
        sources=[dict(id='new-s', title='Official', url='https://new.test/help')])]


@pytest.mark.parametrize('product,url', [('Example Suite', 'https://different.test/help'),
    ('New Suite', 'https://example.test/guide#section')])
def test_product_or_document_overlap_is_not_independent_holdout(tmp_path, product, url):
    result = api().prepare_readiness([artifact(tmp_path)], workspace='w')
    candidate = [dict(id='holdout', product=product, question='Question?',
        sources=[dict(id='s', title='Official', url=url)])]
    with pytest.raises(ValueError):
        api().validate_eval_isolation(result, candidate)


def test_disjoint_holdout_is_candidate_only_and_does_not_enter_trajectory_export(tmp_path):
    result = api().prepare_readiness([artifact(tmp_path)], workspace='w')
    candidates = [dict(id='holdout', product='New Suite', question='Question?',
        sources=[dict(id='s', title='Official', url='https://new.test/help')])]
    assert api().validate_eval_isolation(result, candidates)['status'] == 'disjoint_candidate'
    assert all(row['product'] != 'New Suite' for row in result['episodes'])


def test_shared_actions_and_cost_are_not_multiplied_by_question_count(tmp_path):
    folder = artifact(tmp_path)
    run = json.loads((folder / 'run.json').read_text())
    run['report_dimension_audits'][0]['answer_coverage'].append(
        dict(question_id='q2', question='Second question?', status='unverified'))
    (folder / 'run.json').write_text(json.dumps(run))
    result = api().prepare_readiness([folder], workspace='w')
    assert len(result['episodes']) == 2 and len(result['trajectories']) == 1
    assert result['summary']['provider_tokens_known'] == 100


def test_run_identity_alias_cannot_duplicate_labels_episodes_or_cost(tmp_path):
    first = artifact(tmp_path, 'run-a')
    second = artifact(tmp_path, 'second-folder')
    run = json.loads((second / 'run.json').read_text())
    run['id'] = 'RUN-A'
    (second / 'run.json').write_text(json.dumps(run))
    with pytest.raises(ValueError):
        api().prepare_readiness([first, second], workspace='w', annotations=[annotation(first)])


def test_existing_output_is_never_overwritten(tmp_path):
    output = tmp_path / 'existing'
    output.mkdir()
    (output / 'keep').write_text('original')
    with pytest.raises(FileExistsError):
        api().write_readiness({'episodes': [], 'trajectories': [], 'summary': {}}, output)
    assert (output / 'keep').read_text() == 'original'


def test_truncated_question_and_answer_are_explicitly_marked(tmp_path):
    folder = artifact(tmp_path)
    run = json.loads((folder / 'run.json').read_text())
    row = run['report_dimension_audits'][0]['answer_coverage'][0]
    row['question'] = 'A long question ' * 100
    row['answer'] = 'A conditional answer ' * 100
    (folder / 'run.json').write_text(json.dumps(run))
    episode = api().prepare_readiness([folder], workspace='w')['episodes'][0]
    assert set(episode['text_omissions']) >= {'question', 'published_answer'}


@pytest.mark.parametrize('tokens', [True, -1, '100'])
def test_invalid_provider_usage_is_not_silently_counted_as_zero(tmp_path, tokens):
    folder = artifact(tmp_path)
    summary = json.loads((folder / 'summary.json').read_text())
    summary['provider_total_tokens_last_attempts'] = tokens
    (folder / 'summary.json').write_text(json.dumps(summary))
    with pytest.raises(ValueError):
        api().prepare_readiness([folder], workspace='w')


def test_long_product_identity_is_not_truncated_before_holdout_isolation(tmp_path):
    product = 'A' * 650
    folder = artifact(tmp_path)
    run = json.loads((folder / 'run.json').read_text())
    run['report_dimension_audits'][0]['competitor'] = product
    (folder / 'run.json').write_text(json.dumps(run))
    result = api().prepare_readiness([folder], workspace='w')
    candidate = [dict(id='holdout', product=product, question='Question?',
        sources=[dict(id='s', title='Official', url='https://different.test/help')])]
    with pytest.raises(ValueError):
        api().validate_eval_isolation(result, candidate)


def test_missing_or_self_inconsistent_manifest_is_rejected(tmp_path):
    for name, change in [('missing', None), ('changed', 'f' * 64)]:
        folder = artifact(tmp_path, name)
        manifest = json.loads((folder / 'manifest.json').read_text())
        summary = json.loads((folder / 'summary.json').read_text())
        if change is None:
            manifest.pop('manifest_sha256')
            summary.pop('manifest_sha256')
        else:
            manifest['manifest_sha256'] = summary['manifest_sha256'] = change
        (folder / 'manifest.json').write_text(json.dumps(manifest))
        (folder / 'summary.json').write_text(json.dumps(summary))
        with pytest.raises(ValueError):
            api().prepare_readiness([folder], workspace='w')


@pytest.mark.parametrize('mode', ['no_audits', 'another_product'])
def test_all_exposed_products_and_documents_enter_isolation(tmp_path, mode):
    folder = artifact(tmp_path)
    run = json.loads((folder / 'run.json').read_text())
    run['raw_sources'].append(dict(competitor='Other Suite', url='https://other.test/help'))
    if mode == 'no_audits':
        run['report_dimension_audits'] = []
    (folder / 'run.json').write_text(json.dumps(run))
    result = api().prepare_readiness([folder], workspace='w')
    for product, url in [('Other Suite', 'https://unused.test/help'),
                         ('Unseen Suite', 'https://other.test/help')]:
        with pytest.raises(ValueError):
            api().validate_eval_isolation(result, [dict(id='h', product=product, question='Question?',
                sources=[dict(id='s', title='Official', url=url)])])


def test_preview_fallback_uses_actual_text_for_truncation_metadata(tmp_path):
    folder = artifact(tmp_path, trace_spans=[dict(id='x', kind='llm', agent='writer', name='write',
        status='ok', full_input='', input_preview='a' * 1000, metadata={})])
    action = api().prepare_readiness([folder], workspace='w')['trajectories'][0]['actions'][0]
    assert action['input_truncated'] is True


def test_nonhex_code_identity_is_rejected(tmp_path):
    folder = artifact(tmp_path)
    for name in ('manifest.json', 'summary.json'):
        value = json.loads((folder / name).read_text())
        value['production_code_sha256'] = 'z' * 64
        (folder / name).write_text(json.dumps(value))
    with pytest.raises(ValueError):
        api().prepare_readiness([folder], workspace='w')
