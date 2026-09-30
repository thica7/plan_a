import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ReportReleaseGate, ReportVersionRecord } from '../../api/types';
import { useI18n } from '../../stores/i18n';
import { ReleaseGateReviewQueue } from './ReleaseGateReviewQueue';
import { ReportReviewDesk } from './ReportReviewDesk';

const position = 'supported / see https://example.com/pricing vs plans';
const gate = {
  allowed: false, status: 'blocked', issues: [{
    id: 'issue-1', rule_id: 'claim_self_consistency_required', rule_name: 'Claim self-consistency',
    severity: 'blocker', message: '已知中文提示', recommendation: '', claim_ids: [], evidence_ids: [],
    metadata: {
      claim_validation_issue_types: ['conflicting_evidence', 'stale_evidence'],
      source_age_days: 121, freshness_policy_days: 90, freshness_basis: 'source_age',
      source_evidence_pairs: [{ kb_source_id: 'archived', kb_position: position }],
      evidence_audit_trail: [{ evidence_id: 'draft', kb_document_id: 'doc', kb_document_version: 2, kb_document_status: 'archived' }],
    },
  }],
} as unknown as ReportReleaseGate;

describe.each(['desk', 'queue'] as const)('release audit localization: %s', (view) => {
  it('localizes structured labels on locale changes while retaining evidence, URLs and callback selectors', () => {
    useI18n.getState().setLocale('zh-CN');
    const onRollbackKbIssue = vi.fn();
    const selectedVersion = { run_id: 'run-1' } as ReportVersionRecord;
    render(view === 'queue'
      ? <ReleaseGateReviewQueue releaseGate={gate} selectedVersion={selectedVersion} onRollbackKbIssue={onRollbackKbIssue} />
      : <ReportReviewDesk releaseGate={gate} selectedVersion={null} previousVersion={null} scopedClaims={[]}
          evidenceById={new Map()} diff={null} isDiffLoading={false} onEvidenceQuality={() => undefined}
          onSelectClaim={() => undefined} onSelectEvidence={() => undefined} onRollbackKbIssue={onRollbackKbIssue} />);
    expect(screen.getByText('证据冲突、证据过期')).toBeInTheDocument();
    expect(screen.getByText('doc / v2 / 已归档')).toHaveAttribute('href', '/knowledge?document_id=doc');
    expect(screen.getByText('来源已过去 121 天 / 策略要求 90 天 / 来源年龄')).toBeInTheDocument();
    expect(screen.getByText(`archived (${position}) 对照 实时来源`)).toHaveAttribute('href', '/knowledge?raw_source_id=archived');
    expect(screen.getByText('draft')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /回滚知识库/ }));
    expect(onRollbackKbIssue).toHaveBeenCalledWith('issue-1', { document_ids: ['doc'], restore_previous: true });

    act(() => useI18n.getState().setLocale('en-US'));
    expect(screen.getByText('conflicting_evidence, stale_evidence')).toBeInTheDocument();
    expect(screen.getByText('doc / v2 / archived')).toBeInTheDocument();
    expect(screen.getByText('121d old / 90d policy / source_age')).toBeInTheDocument();
    expect(screen.getByText(`archived (${position}) vs live source`)).toBeInTheDocument();
  });
});
