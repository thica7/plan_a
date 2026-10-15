import { useEffect, useState } from 'react';
import type { QCIssue, RunDetail } from '../../api/types';
import { Panel } from '../../components/ui';
import { displayLabel } from '../../i18n/display';
import { SystemMessage } from '../../i18n/SystemMessage';
import { useTranslation } from '../../stores/i18n';
import './dimensionEvidence.css';

export function DimensionEvidencePanel({ detail, onRepair }: {
  detail: RunDetail;
  onRepair?: (issueIds: string[]) => Promise<boolean> | void;
}) {
  const { t, locale } = useTranslation();
  const [feedback, setFeedback] = useState<'pending' | 'started' | 'error' | null>(null);
  const terminal = ['completed', 'completed_with_blockers', 'failed'].includes(detail.status);
  useEffect(() => {
    if (['completed', 'completed_with_blockers', 'failed'].includes(detail.status)) setFeedback(null);
  }, [detail.id, detail.status, detail.updated_at]);
  const disabled = !onRepair || !terminal || detail.revisions.length >= detail.max_iterations || feedback === 'pending' || feedback === 'started';
  async function repair(issues: QCIssue[]) {
    setFeedback('pending');
    try {
      const result = await onRepair?.(issues.map(issue => issue.id));
      setFeedback(result === false ? 'error' : 'started');
    } catch { setFeedback('error'); }
  }
  const relevantIssues = detail.qa_findings.filter(issue => issue.target_agent === 'collector');
  const currentSnapshot = detail.evidence_snapshots?.find(snapshot => snapshot.id === detail.evidence_snapshot_id);
  const admittedIds = currentSnapshot ? new Set(currentSnapshot.sources.filter(source => source.status === 'active').map(source => source.id)) : null;
  return <Panel className="dimension-evidence-panel" title={t('dimensionEvidence.title')}>
    <p className="muted-line">{t('dimensionEvidence.explanation')}</p>
    {(detail.plan.dimensions ?? []).map(dimension => {
      const dimensionLabel = displayLabel(dimension, locale);
      const gaps = relevantIssues.filter(issue => issue.target_subagent === dimension);
      const wholeGaps = gaps.filter(issue => !issue.target_competitor && !issue.redo_scope.target_competitor && !issue.redo_scope.target_competitors?.length);
      return <section key={dimension} aria-label={dimensionLabel} className="dimension-evidence-section">
        <h3>{dimensionLabel}</h3>
        {wholeGaps.map(issue => <p key={issue.id} className="dimension-evidence-gap"><SystemMessage message={issue.problem} /></p>)}
        {wholeGaps.length ? <button className="icon-text-button" type="button" disabled={disabled} onClick={() => repair(wholeGaps)} aria-label={`${t('dimensionEvidence.repair')}：${dimensionLabel}`}>{t('dimensionEvidence.repair')}</button> : null}
        <div className="dimension-evidence-grid">
          {detail.plan.competitors.map(competitor => {
            const sources = detail.raw_sources.filter(source => source.dimension === dimension && source.source_type === 'webpage_verified' && source.confidence >= .35 && !detail.evidence_retired_source_ids?.includes(source.id) && (!admittedIds || admittedIds.has(source.id)) && (source.covered_competitors?.length ? source.covered_competitors.includes(competitor) : source.competitor === competitor));
            const branchGaps = gaps.filter(issue => issue.target_competitor === competitor || issue.redo_scope.target_competitor === competitor || issue.redo_scope.target_competitors?.includes(competitor));
            return <article className="dimension-evidence-product" key={competitor}>
              <h4>{competitor}</h4>
              <p className="dimension-evidence-label">{t(detail.execution_mode === 'demo' ? 'dimensionEvidence.demoContent' : 'dimensionEvidence.content')}</p>
              {sources.length ? sources.map(source => <div key={source.id}>
                <blockquote>{source.snippet}</blockquote>
                {Array.from(new Set((Array.isArray(source.metadata?.normalized_fields) ? source.metadata.normalized_fields : []).flatMap(field => {
                  const terms = field && typeof field === 'object' && 'evidence_terms' in field ? field.evidence_terms : [];
                  return Array.isArray(terms) ? terms.filter((term): term is string => typeof term === 'string' && !source.snippet.includes(term)) : [];
                }))).map(term => <blockquote key={term}>{term}</blockquote>)}
                {source.url ? <a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a> : <span>{source.title}</span>}
              </div>) : <p className="muted-line">{t('dimensionEvidence.unknown')}</p>}
              {branchGaps.length ? <>
                <p className="dimension-evidence-label">{t('dimensionEvidence.gap')}</p>
                {branchGaps.map(issue => <p className="dimension-evidence-gap" key={issue.id}><SystemMessage message={issue.problem} /></p>)}
                <button className="icon-text-button" type="button" disabled={disabled} onClick={() => repair(branchGaps)} aria-label={`${t('dimensionEvidence.repair')}：${competitor} / ${dimensionLabel}`}>{t('dimensionEvidence.repair')}</button>
              </> : null}
            </article>;
          })}
        </div>
      </section>;
    })}
    {detail.revisions.length >= detail.max_iterations ? <p className="muted-line">{t('dimensionEvidence.limit')}</p> : null}
    {feedback ? <p role="status">{t(`dimensionEvidence.${feedback}`)}</p> : null}
  </Panel>;
}
