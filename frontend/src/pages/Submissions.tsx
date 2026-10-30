import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { workspaceIdForSearch, workspaceSearch } from '../api/workspaceScope';
import {
  cancelSubmission, getQuotaLedger, getSubmission, getSubmissionRuntime, listSubmissions,
  retrySubmissionDispatch, SubmissionApiError, submissionErrorKey,
} from '../api/submissions';
import type { SubmissionView } from '../api/types';
import { ActionButton } from '../components/interaction/ActionButton';
import { ActionLink } from '../components/interaction/ActionLink';
import { useSubmissionResource } from '../features/submissions/useSubmissionResource';
import { useTranslation } from '../stores/i18n';
import './Submissions.css';

const states: SubmissionView['status'][] = ['pending', 'dispatching', 'dispatched', 'cancelled', 'dispatch_failed'];
const action = (actionId: string, description: string, kind: 'local' | 'mutation' | 'route' = 'local') => ({ actionId: `submissions.${actionId}`, kind, description });
function active(item: SubmissionView) {
  return item.status === 'pending' || item.status === 'dispatching' || (item.status === 'dispatched' && !['completed', 'completed_with_blockers', 'failed'].includes(item.run_status ?? ''));
}
function date(value: string | null | undefined) { return value ? value.replace('T', ' ').replace(/\.\d+Z$/, 'Z').replace('Z', ' UTC') : '—'; }

export function Submissions() {
  const { t } = useTranslation();
  const { submissionId } = useParams();
  const [params, setParams] = useSearchParams();
  const workspace = workspaceIdForSearch(params.toString());
  const [quotaRevision, setQuotaRevision] = useState(0);
  const [workspaceDraft, setWorkspaceDraft] = useState(workspace);
  useEffect(() => setWorkspaceDraft(workspace), [workspace]);
  const runtime = useSubmissionResource('runtime', getSubmissionRuntime);
  const enabled = runtime.data?.task_center_enabled === true;
  function changeWorkspace(event: FormEvent) {
    event.preventDefault();
    if (!workspaceDraft.trim()) return;
    setParams({ workspace_id: workspaceDraft.trim() });
  }
  return <section className="work-surface submissions-page">
    <header className="page-header"><div><h1>{t(submissionId ? 'submissions.detail' : 'submissions.title')}</h1><p>{t('submissions.description')}</p></div>
      <ActionLink to={`/${workspaceSearch(workspace)}`} authenticity={action('new', 'Open research builder', 'route')}>{t('submissions.new')}</ActionLink>
    </header>
    <form className="submission-toolbar" onSubmit={changeWorkspace}>
      <label>{t('submissions.workspace')}<input value={workspaceDraft} onChange={event => setWorkspaceDraft(event.target.value)} /></label>
      <ActionButton type="submit" disabled={!workspaceDraft.trim()} disabledReason={!workspaceDraft.trim() ? t('submissions.workspaceRequired') : undefined} authenticity={action('workspace', 'Change request workspace scope')}>{t('submissions.switchWorkspace')}</ActionButton>
      <span>{t('submissions.scope')}: <strong>{workspace}</strong></span>
    </form>
    {runtime.loading && !runtime.data ? <p role="status">{t('submissions.loading')}</p> : null}
    {runtime.error ? <div className="submission-message"><ErrorMessage error={runtime.error} /><ActionButton onClick={runtime.refresh} authenticity={action('runtime-refresh', 'Reload runtime capability')}>{t('submissions.refreshConnection')}</ActionButton></div> : null}
    {runtime.data && !enabled ? <p role="status">{t('submissions.error.disabled')}</p> : null}
    {enabled ? <>
      <p className="submission-notice">{t('submissions.demo')}</p>
      <div className="submission-columns">
        {submissionId ? <SubmissionDetail key={`${workspace}:${submissionId}`} id={submissionId} workspace={workspace} onMutationConfirmed={() => setQuotaRevision(value => value + 1)} /> : <SubmissionList key={`list:${workspace}`} workspace={workspace} />}
        <QuotaLedger key={`quota:${workspace}`} workspace={workspace} revision={quotaRevision} />
      </div>
    </> : null}
  </section>;
}

function ErrorMessage({ error }: { error: unknown }) {
  const { t } = useTranslation();
  return <p className="error-line" role="alert">{t(submissionErrorKey(error))}</p>;
}
function Status({ item }: { item: SubmissionView }) {
  const { t } = useTranslation();
  return <span className={`submission-state submission-state-${item.status}`}>{t(`submissions.state.${item.status}`)}</span>;
}

function SubmissionList({ workspace }: { workspace: string }) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<SubmissionView['status'] | ''>('');
  const [cursor, setCursor] = useState<string>();
  const resource = useSubmissionResource(`list:${workspace}:${status}:${cursor ?? ''}`, signal => listSubmissions({ workspaceId: workspace, status: status || undefined, cursor }, signal), true, page => page.items.some(active));
  return <section className="panel submission-panel" aria-label={t('submissions.list')}>
    <div className="submission-section-header"><h2>{t('submissions.list')}</h2><ActionButton onClick={resource.refresh} isLoading={resource.loading} loadingLabel={t('submissions.refreshing')} authenticity={action('list-refresh', 'Reload submissions from server')}>{t('submissions.refreshList')}</ActionButton></div>
    <label>{t('submissions.filter')}<select value={status} onChange={event => { setStatus(event.target.value as typeof status); setCursor(undefined); }}>
      <option value="">{t('submissions.all')}</option>{states.map(value => <option key={value} value={value}>{t(`submissions.state.${value}`)}</option>)}
    </select></label>
    {resource.error ? <ErrorMessage error={resource.error} /> : null}
    {!resource.data && resource.loading ? <p role="status">{t('submissions.loading')}</p> : null}
    {resource.data ? <>
      {resource.data.items.length === 0 ? <p>{t('submissions.empty')}</p> : <ul className="submission-list">{resource.data.items.map(item => <li key={item.id}>
        <div><ActionLink to={`/submissions/${encodeURIComponent(item.id)}${workspaceSearch(workspace)}`} authenticity={action('open-detail', 'Open the persisted submission', 'route')}>{item.id}</ActionLink><Status item={item} /></div>
        <p>{t('submissions.created')}: {date(item.created_at)}</p>
        <p>{t('submissions.runState')}: {t(`submissions.run.${item.run_status ?? 'unobserved'}`)}</p>
      </li>)}</ul>}
    </> : null}
    <div className="submission-pagination">
      <ActionButton onClick={() => setCursor(undefined)} disabled={!cursor || resource.loading} disabledReason={!cursor ? t('submissions.firstPage') : resource.loading ? t('submissions.loading') : undefined} authenticity={action('list-first', 'Reset server submission cursor')}>{t('submissions.firstList')}</ActionButton>
      <ActionButton onClick={() => setCursor(resource.data?.next_cursor || undefined)} disabled={!resource.data?.next_cursor || resource.loading} disabledReason={resource.loading ? t('submissions.loading') : !resource.data?.next_cursor ? t('submissions.noNextPage') : undefined} authenticity={action('list-next', 'Load server submission cursor')}>{t('submissions.nextList')}</ActionButton>
    </div>
  </section>;
}

function SubmissionDetail({ id, workspace, onMutationConfirmed }: { id: string; workspace: string; onMutationConfirmed: () => void }) {
  const { t } = useTranslation();
  const resource = useSubmissionResource(`detail:${workspace}:${id}`, signal => getSubmission(id, workspace, signal), true, active);
  const [mutation, setMutation] = useState<'cancel' | 'retry' | null>(null);
  const [mutationError, setMutationError] = useState<unknown>(null);
  const mutationController = useRef<AbortController | null>(null);
  useEffect(() => () => { mutationController.current?.abort(); }, []);
  async function mutate(kind: 'cancel' | 'retry') {
    if (mutationController.current) return;
    const controller = new AbortController();
    mutationController.current = controller;
    setMutation(kind); setMutationError(null);
    try {
      const item = await (kind === 'cancel' ? cancelSubmission : retrySubmissionDispatch)(id, workspace, controller.signal);
      if (!controller.signal.aborted) {
        resource.setData(item);
        onMutationConfirmed();
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setMutationError(error);
        if (error instanceof SubmissionApiError && error.status === 409) resource.refresh();
      }
    } finally {
      if (!controller.signal.aborted) { mutationController.current = null; setMutation(null); }
    }
  }
  const item = resource.data;
  return <section className="panel submission-panel" aria-label={t('submissions.detail')}>
    <div className="submission-section-header"><ActionLink to={`/submissions${workspaceSearch(workspace)}`} authenticity={action('back', 'Return to current workspace submissions', 'route')}>{t('submissions.back')}</ActionLink>
      <ActionButton onClick={resource.refresh} isLoading={resource.loading} loadingLabel={t('submissions.refreshing')} authenticity={action('detail-refresh', 'Reload persisted submission state')}>{t('submissions.refreshDetail')}</ActionButton></div>
    {resource.error ? <ErrorMessage error={resource.error} /> : null}
    {mutationError ? <ErrorMessage error={mutationError} /> : null}
    {!item && resource.loading ? <p role="status">{t('submissions.loading')}</p> : null}
    {item ? <>
      <h2>{item.id}</h2><Status item={item} />
      <p>{t('submissions.dispatchedMeaning')}</p>
      <dl className="submission-facts">
        <div><dt>{t('submissions.runState')}</dt><dd>{t(`submissions.run.${item.run_status ?? 'unobserved'}`)}</dd></div>
        <div><dt>{t('submissions.observed')}</dt><dd>{date(item.run_status_observed_at)}</dd></div>
        <div><dt>{t('submissions.attempts')}</dt><dd>{item.dispatch_attempt_count}</dd></div>
        <div><dt>{t('submissions.expected')}</dt><dd>{item.expected_run_id}</dd></div>
        <div><dt>{t('submissions.created')}</dt><dd>{date(item.created_at)}</dd></div>
        <div><dt>{t('submissions.updated')}</dt><dd>{date(item.updated_at)}</dd></div>
      </dl>
      {item.last_error_code ? <p className="submission-notice">{t(['attempts_exhausted', 'dispatch_error', 'lease_expired'].includes(item.last_error_code) ? `submissions.dispatchError.${item.last_error_code}` : 'submissions.dispatchError.unknown')} <code>{item.last_error_code}</code></p> : null}
      {item.run_id ? <ActionLink to={`/runs/${encodeURIComponent(item.run_id)}?view=report`} authenticity={action('open-run', 'Open the actual bound research run', 'route')}>{t('submissions.openRun')}</ActionLink> : <p>{t('submissions.notBound')}</p>}
      <div className="submission-actions">
        {item.status === 'pending' ? <ActionButton onClick={() => { void mutate('cancel'); }} isLoading={mutation === 'cancel'} loadingLabel={t('submissions.cancelling')} disabled={mutation !== null} disabledReason={mutation ? t('submissions.mutating') : undefined} authenticity={action('cancel', 'Cancel pending submission on server', 'mutation')}>{t('submissions.cancel')}</ActionButton> : null}
        {item.status === 'dispatch_failed' ? <><p>{t('submissions.retryMeaning')}</p><ActionButton onClick={() => { void mutate('retry'); }} isLoading={mutation === 'retry'} loadingLabel={t('submissions.retrying')} disabled={mutation !== null} disabledReason={mutation ? t('submissions.mutating') : undefined} authenticity={action('retry', 'Retry dispatch of the existing reserved submission', 'mutation')}>{t('submissions.retry')}</ActionButton></> : null}
      </div>
    </> : null}
  </section>;
}

function QuotaLedger({ workspace, revision }: { workspace: string; revision: number }) {
  const { t } = useTranslation();
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [cursor, setCursor] = useState<string>();
  const resource = useSubmissionResource(`quota:${workspace}:${month}:${cursor ?? ''}:${revision}`, signal => getQuotaLedger({ workspaceId: workspace, periodStart: `${month}-01T00:00:00Z`, cursor }, signal));
  const snapshot = resource.data?.snapshot;
  return <section className="panel submission-panel" aria-label={t('submissions.quota')}>
    <div className="submission-section-header"><h2>{t('submissions.quota')}</h2><ActionButton onClick={resource.refresh} isLoading={resource.loading} loadingLabel={t('submissions.refreshing')} authenticity={action('quota-refresh', 'Reload authoritative monthly quota snapshot')}>{t('submissions.refreshQuota')}</ActionButton></div>
    <label>{t('submissions.month')}<input type="month" value={month} onChange={event => { if (/^\d{4}-\d{2}$/.test(event.target.value)) { setMonth(event.target.value); setCursor(undefined); } }} /></label>
    <p>{t('submissions.quotaMeaning')}</p>
    {resource.error ? <ErrorMessage error={resource.error} /> : null}
    {!snapshot && resource.loading ? <p role="status">{t('submissions.loading')}</p> : null}
    {snapshot ? <>
      <p className="submission-period">{snapshot.period_start.slice(0, 10)} — {snapshot.period_end.slice(0, 10)} (UTC)</p>
      <dl className="submission-quota-grid">{([
        ['limit', snapshot.limit], ['imported', snapshot.imported_count], ['reserved', snapshot.reserved_count], ['available', snapshot.available],
      ] as const).map(([label, value]) => <div key={label}><dt>{t(`submissions.${label}`)}</dt><dd aria-label={t(`submissions.${label}`)}>{value}</dd></div>)}</dl>
      <p className="submission-notice">{t(`submissions.enforcement.${snapshot.enforcement}`)}</p>
      <h3>{t('submissions.ledger')}</h3>
      {resource.data?.items.length ? <ul className="submission-ledger">{resource.data.items.map(entry => <li key={entry.id}><code>{entry.id}</code><strong>{t(`submissions.ledger.${entry.action}`)}</strong><span>{entry.amount}</span><span>{entry.submission_id}</span><time>{date(entry.created_at)}</time></li>)}</ul> : <p>{t('submissions.emptyLedger')}</p>}
    </> : null}
    <div className="submission-pagination">
      <ActionButton onClick={() => setCursor(undefined)} disabled={!cursor || resource.loading} disabledReason={!cursor ? t('submissions.firstPage') : resource.loading ? t('submissions.loading') : undefined} authenticity={action('ledger-first', 'Reset server quota ledger cursor')}>{t('submissions.firstLedger')}</ActionButton>
      <ActionButton onClick={() => setCursor(resource.data?.next_cursor || undefined)} disabled={!resource.data?.next_cursor || resource.loading} disabledReason={resource.loading ? t('submissions.loading') : !resource.data?.next_cursor ? t('submissions.noNextPage') : undefined} authenticity={action('ledger-next', 'Load server quota ledger cursor')}>{t('submissions.nextLedger')}</ActionButton>
    </div>
  </section>;
}
