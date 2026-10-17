"""Prepare scoped diagnostic episodes; never assign truth rewards or train."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from packages.identity import normalize_url
from scripts.export_agent_eval import MAX_ACTIONS, MAX_TEXT, _action, _non_real, _redact, _text

OUTCOMES = ('success', 'failure', 'reasonable_abstention', 'unlabelled')
FILES = ('run.json', 'trace.json', 'summary.json', 'manifest.json', 'snapshot.json', 'report.md')
ANNOTATION_FIELDS = {'run_id', 'question_id', 'product', 'report_sha256',
                     'candidate_outcome', 'label_status', 'review_source', 'reason'}


def _digest(body):
    return hashlib.sha256(body).hexdigest()


def _is_digest(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _identity_digest(value):
    return _digest(_identity(value).encode())


def _identity(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('A nonblank identity is required.')
    return ' '.join(value.casefold().split())


def _document(url):
    if not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        return None
    # Omit credentials, query values and fragments. Coarse grouping can reject
    # independent candidates conservatively; it cannot separate document chunks.
    return normalize_url(urlunsplit((parsed.scheme, parsed.hostname, parsed.path, '', '')))


def _actions(spans):
    eligible = [span for span in spans if not _non_real(span)]
    actions = []
    for span in eligible[:MAX_ACTIONS]:
        action = _action(span)
        for direction in ('input', 'output'):
            raw = span.get('full_' + direction)
            raw = raw if isinstance(raw, str) and raw else span.get(direction + '_preview')
            safe = _redact(raw) if isinstance(raw, str) else ''
            action[direction + '_truncated'] = len(safe) > MAX_TEXT
            action[direction + '_redacted'] = isinstance(raw, str) and safe != raw
        actions.append(action)
    return actions, len(spans) - len(eligible), max(0, len(eligible) - MAX_ACTIONS)


def _load(folder, workspace):
    try:
        bodies = {name: (folder / name).read_bytes() for name in FILES}
        values = {name: json.loads(body) for name, body in bodies.items() if name.endswith('.json')}
        run, trace = values['run.json'], values['trace.json']
        summary, manifest = values['summary.json'], values['manifest.json']
        if (not isinstance(run, dict) or run.get('workspace_id') != workspace
                or run.get('execution_mode') != 'real' or _non_real(run)):
            raise ValueError('Only explicitly real, matching workspace artifacts are allowed.')
        for field in ('id', 'project_id'):
            _identity(run.get(field))
        if (not isinstance(trace, list) or any(not isinstance(span, dict) for span in trace)
                or trace != run.get('trace_spans')):
            raise ValueError('Run and trace artifacts disagree.')
        code_hash = manifest.get('production_code_sha256')
        manifest_hash = manifest.get('manifest_sha256')
        canonical = json.dumps({key: value for key, value in manifest.items()
                                if key != 'manifest_sha256'}, ensure_ascii=False,
                               sort_keys=True, separators=(',', ':')).encode()
        if (not _is_digest(code_hash) or not _is_digest(manifest_hash)
                or code_hash != summary.get('production_code_sha256')
                or manifest_hash != summary.get('manifest_sha256')
                or manifest_hash != _digest(canonical)):
            raise ValueError('Code or manifest identities disagree.')
        for field in ('provider_total_tokens_last_attempts',
                      'provider_usage_unknown_transport_spans', 'llm_transport_attempts'):
            value = summary.get(field)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError('Invalid provider usage counter.')
        report = bodies['report.md'].decode()
        if not isinstance(run.get('report_md'), str) or report.rstrip('\n') != run['report_md'].rstrip('\n'):
            raise ValueError('Run and report artifacts disagree.')
        hashes = {name: _digest(body) for name, body in bodies.items()}
        if any(_digest((folder / name).read_bytes()) != digest for name, digest in hashes.items()):
            raise ValueError('Artifacts changed during preparation.')
        return run, summary, hashes
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError) as error:
        raise ValueError('Unable to read consistent readiness artifacts.') from error


def prepare_readiness(artifact_dirs, *, workspace, annotations=()):
    """Export question-level review candidates, with shared run costs counted once.

    Source files are read only. Text summaries may be truncated/redacted and
    therefore are explicitly unsuitable as a lossless policy-training dataset.
    """
    _identity(workspace)
    labels = {}
    for row in annotations:
        if (not isinstance(row, dict) or set(row) != ANNOTATION_FIELDS
                or row.get('label_status') != 'candidate'
                or row.get('candidate_outcome') not in OUTCOMES[:-1]
                or row.get('review_source') != 'agent_candidate'):
            raise ValueError('Only explicit, unpromoted review candidates are accepted.')
        key = tuple(_identity(row.get(field)) for field in ('run_id', 'question_id', 'product'))
        _identity(row.get('reason'))
        if key in labels:
            raise ValueError('Duplicate candidate annotation.')
        labels[key] = row
    trajectories, episodes, used, seen_runs = [], [], set(), set()
    product_identities, document_identities = set(), set()
    for folder in artifact_dirs:
        run, summary, hashes = _load(Path(folder), workspace)
        run_identity = _identity(run['id'])
        if run_identity in seen_runs:
            raise ValueError('Duplicate run artifact.')
        seen_runs.add(run_identity)
        # Identity grouping uses complete source values, never exported summaries.
        for product in run.get('plan', {}).get('competitors', []):
            product_identities.add(_identity_digest(product))
        for source in run.get('raw_sources', []):
            product_identities.add(_identity_digest(source.get('competitor')))
            document = _document(source.get('url'))
            if document:
                document_identities.add(_digest(document.encode()))
        trajectory_id = 'trajectory-' + _digest(json.dumps(hashes, sort_keys=True).encode())[:24]
        actions, filtered, omitted = _actions(run['trace_spans'])
        trajectories.append(dict(id=trajectory_id, run_id=_text(run['id']),
            workspace_id=_text(workspace), project_id=_text(run['project_id']),
            input_hashes=hashes, production_code_sha256=summary['production_code_sha256'],
            actions=actions, actions_filtered=filtered, actions_omitted=omitted,
            text_limit=MAX_TEXT, representation='redacted_diagnostic_summaries',
            provider_tokens_known=summary.get('provider_total_tokens_last_attempts'),
            provider_usage_unknown_spans=summary.get('provider_usage_unknown_transport_spans'),
            llm_transport_attempts=summary.get('llm_transport_attempts'), training_ready=False))
        seen_questions = set()
        for audit in run.get('report_dimension_audits', []):
            product = audit['competitor']
            _identity(product)
            product_identities.add(_identity_digest(product))
            urls = sorted({_document(source.get('url')) for source in run.get('raw_sources', [])
                           if _identity(source.get('competitor')) == _identity(product)
                           and _document(source.get('url'))})
            group = 'product-' + _digest(json.dumps([workspace, _identity(product)]).encode())[:24]
            for answer in audit.get('answer_coverage', []):
                qid = answer['question_id']
                key = tuple(_identity(value) for value in (run['id'], qid, product))
                if key in seen_questions:
                    raise ValueError('Duplicate question scope.')
                seen_questions.add(key)
                candidate = labels.get(key)
                if candidate is not None:
                    if candidate['report_sha256'] != hashes['report.md']:
                        raise ValueError('Candidate is bound to a different report.')
                    used.add(key)
                episodes.append(dict(id='episode-' + _digest(json.dumps(key).encode())[:24],
                    unit='question_episode', trajectory_id=trajectory_id,
                    run_id=_text(run['id']), project_id=_text(run['project_id']),
                    product=_text(product), dimension=_text(audit['dimension']),
                    question_id=_text(qid), question=_text(answer.get('question')),
                    task_group_id=group, partition='development', exposure='previously_exposed',
                    source_urls=[_redact(url) for url in urls],
                    consumption_id=_text(audit.get('consumption_id')),
                    reported_coverage_status=_text(answer.get('status')),
                    claim_ids=[_text(value) for value in answer.get('claim_ids', [])],
                    answer_binding_version=2 if audit.get('answer_binding_version') == 2 else None,
                    coverage_binding_version=2 if answer.get('binding_version') == 2 else None,
                    resolution=_text(answer.get('resolution')), conclusion=_text(answer.get('conclusion')),
                    published_answer=_text(answer.get('answer')),
                    text_omissions=[field for field, raw in (
                        ('question', answer.get('question')), ('published_answer', answer.get('answer')),
                        ('label_reason', candidate['reason'] if candidate else None))
                        if isinstance(raw, str) and len(_redact(raw)) > MAX_TEXT],
                    candidate_outcome=candidate['candidate_outcome'] if candidate else 'unlabelled',
                    label_status='candidate' if candidate else 'unlabelled',
                    label_source='agent_candidate' if candidate else None,
                    label_reason=_text(candidate['reason']) if candidate else None,
                    report_sha256=hashes['report.md'],
                    mechanical_run_pass=summary.get('mechanical_pass') is True,
                    qa_blockers=sum(item.get('severity') == 'blocker' for item in run.get('qa_findings', [])),
                    reward={'correctness': None, 'source': None}, training_ready=False))
    if used != set(labels):
        raise ValueError('Annotation does not match an exported question episode.')
    tokens = [row['provider_tokens_known'] for row in trajectories]
    return dict(schema_version=1, purpose='offline_audit_candidates',
        trajectories=trajectories, episodes=episodes,
        development_identities=dict(product_sha256=sorted(product_identities),
                                    document_sha256=sorted(document_identities)),
        summary=dict(runs=len(trajectories), question_episodes=len(episodes),
            candidate_counts=dict(Counter(row['candidate_outcome'] for row in episodes)),
            provider_tokens_known=sum(value for value in tokens if type(value) is int and value >= 0),
            runs_missing_provider_tokens=sum(value is None for value in tokens),
            human_reviewed=0, training_ready=False, model_training_performed=False))


def evaluation_runtime(cases):
    """Allowlist only task and source identities; never forward reference fields."""
    result = []
    for case in cases:
        for field in ('id', 'product', 'question'):
            _identity(case.get(field))
        if not isinstance(case.get('sources'), list) or not case['sources']:
            raise ValueError('Candidate sources are required.')
        sources = []
        for source in case['sources']:
            for field in ('id', 'title', 'url'):
                _identity(source.get(field))
            if _document(source['url']) is None:
                raise ValueError('Invalid candidate document URL.')
            sources.append({field: source[field] for field in ('id', 'title', 'url')})
        result.append({field: case[field] for field in ('id', 'product', 'question')} | {'sources': sources})
    if len({row['id'] for row in result}) != len(result):
        raise ValueError('Duplicate evaluation case identity.')
    return result


def validate_eval_isolation(development, candidates):
    identities = development['development_identities']
    development_products = set(identities['product_sha256'])
    development_urls = set(identities['document_sha256'])
    runtime = evaluation_runtime(candidates)
    for case in runtime:
        if (_identity_digest(case['product']) in development_products
                or any(_digest(_document(source['url']).encode()) in development_urls
                       for source in case['sources'])):
            raise ValueError('Candidate holdout overlaps development product or document.')
    return {'status': 'disjoint_candidate', 'candidate_cases': len(runtime),
            'formal_acceptance': False, 'training_ready': False}


def write_readiness(result, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for name, rows in [('trajectories', result['trajectories']),
                       *[(outcome, [row for row in result['episodes'] if row['candidate_outcome'] == outcome])
                         for outcome in OUTCOMES]]:
        (output / (name + '.jsonl')).write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))
    manifest = {key: value for key, value in result.items() if key not in {'trajectories', 'episodes'}}
    manifest['file_hashes'] = {path.name: _digest(path.read_bytes()) for path in sorted(output.glob('*.jsonl'))}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', nargs='+', required=True, type=Path)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--annotations', type=Path)
    parser.add_argument('--holdout-candidates', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        annotations = json.loads(args.annotations.read_text())['annotations'] if args.annotations else []
        result = prepare_readiness(args.artifacts, workspace=args.workspace, annotations=annotations)
        if args.holdout_candidates:
            cases = [json.loads(line) for line in args.holdout_candidates.read_text().splitlines() if line.strip()]
            result['holdout_isolation'] = validate_eval_isolation(result, cases)
        write_readiness(result, args.output)
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(1, 'Readiness export rejected; check scope, artifact consistency and review identities.\n')
    print(json.dumps(result['summary'], ensure_ascii=False))


if __name__ == '__main__':
    main()
