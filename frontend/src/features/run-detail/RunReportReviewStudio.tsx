import { Download, Send, ShieldCheck } from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { UNSAFE_LocationContext } from "react-router-dom";
import { useReportAnchorJump } from '../report/reportAnchors';
import { useTranslation } from '../../stores/i18n';
import { createManualReportRevision, listProjectReportVersions, exportReportVersion, startReportApprovalWorkflow } from "../../api/client";
import { saveArtifactDownload } from "../../api/artifactDownload";
import type { QCIssue, ReportVersionRecord, RunDetail as RunDetailRecord } from "../../api/types";
import { Panel, StatusPill } from "../../components/ui";
import {
  buildCitationLabels,
  collectSourceTokenGroups,
  selectReportLayerMarkdown,
  type ReportViewLayer,
} from "../report/ReportView";
import { ReportSourceTrace } from "../report/ReportSourceTrace";
import type { ReportSourceBundle } from "../report/sourceBundle";
import { RevisionDiff } from "../revisions/RevisionDiff";
import { ReportOutline } from "./ReportOutline";
import { ReportReaderWorkspace } from "./ReportReaderWorkspace";
import { ReportStatusStrip } from "./ReportStatusStrip";
import { displayLabel } from "../../i18n/display";
import { SystemMessage } from "../../i18n/SystemMessage";
import { DimensionEvidencePanel } from './DimensionEvidencePanel';

interface RunReportReviewStudioProps {
  detail: RunDetailRecord;
  reportSources: ReportSourceBundle;
  onRepair?: (issueIds: string[]) => Promise<boolean> | void;
}

type ReviewActionState = "idle" | "pending" | "success" | "error";
type ReviewActionFeedback =
  | { type: "approval-pending" }
  | { type: "approval-success"; status: string; workflowId: string }
  | { type: "export-pending"; format: string }
  | { type: "export-success"; filename: string }
  | { type: "approval-error" | "export-error" }
  | { type: "system-error"; message: string };

// Keep unsaved edits for this browser page session, including loading branches
// that unmount the studio. Scope comes from the server-returned run detail.
const unsavedReportDrafts = new Map<string, string>();

function reportDraftKey(detail: RunDetailRecord, versionId: string | null) {
  return JSON.stringify([detail.workspace_id, detail.project_id, detail.id, versionId]);
}

export function RunReportReviewStudio(props: RunReportReviewStudioProps) {
  return <ReportReviewSession key={reportDraftKey(props.detail, null)} {...props} drafts={unsavedReportDrafts} />;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}

function ReportReviewSession({ detail, reportSources, onRepair, drafts }: RunReportReviewStudioProps & { drafts: Map<string, string> }) {
  const { locale, t } = useTranslation();
  const jump = useReportAnchorJump();
  const scope = useRef<HTMLDivElement>(null);
  const hash = useContext(UNSAFE_LocationContext)?.location.hash ?? '';
  const sourceAnchorId = useMemo(() => {
    try {
      const id = decodeURIComponent(hash.slice(1));
      return id.startsWith('source-') || id.startsWith('missing-source-') ? id : null;
    } catch { return null; }
  }, [hash]);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const initialVersion = detail.enterprise_projection?.report_version ?? null;
  const [versions, setVersions] = useState<ReportVersionRecord[]>(initialVersion ? [initialVersion] : []);
  const [selectedId, setSelectedId] = useState(initialVersion?.id ?? null);
  const reportVersion = versions.find(version => version.id === selectedId) ?? initialVersion;
  const markdown = reportVersion?.report_md ?? detail.report_md ?? '';
  const reportArtifact = reportVersion ? reportVersion.report_artifact ?? null : detail.report_artifact;
  const metadata = objectValue(reportVersion?.quality_metadata);
  const semanticReview = objectValue(metadata.manual_semantic_review);
  const releaseGate = objectValue(metadata.release_gate);
  const versionFindings = Array.isArray(metadata.run_qa_findings) ? metadata.run_qa_findings as QCIssue[] : [];
  const draftKey = reportDraftKey(detail, reportVersion?.id ?? null);
  const [editing, setEditing] = useState(() => drafts.has(draftKey));
  const [editText, setEditText] = useState(() => drafts.get(draftKey) ?? markdown);
  const dirty = editing && editText !== markdown;
  const [editState, setEditState] = useState<ReviewActionState>('idle');
  const [editError, setEditError] = useState<string | null>(null);
  const [versionError, setVersionError] = useState(false);
  const mounted = useRef(true);
  const operation = useRef(0);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; operation.current += 1; }; }, []);
  useEffect(() => {
    let active = true;
    if (initialVersion) setVersions(current => [initialVersion, ...current.filter(v => v.id !== initialVersion.id)]);
    if (detail.project_id && initialVersion) {
      listProjectReportVersions(detail.project_id).then(listed => {
        if (!active) return;
        setVersions(current => {
          const merged = new Map(listed.filter(v => v.run_id === detail.id).map(v => [v.id, v]));
          current.forEach(v => merged.set(v.id, v));
          return Array.from(merged.values()).sort((a, b) => b.version_number - a.version_number);
        });
      }).catch(() => { if (active) setVersionError(true); });
    }
    return () => { active = false; };
  }, [detail.id, detail.project_id, initialVersion]);
  useEffect(() => {
    if (!dirty) return;
    const protect = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', protect);
    return () => window.removeEventListener('beforeunload', protect);
  }, [dirty]);
  function selectVersion(id: string) {
    if (dirty && !window.confirm(t('reportStudio.confirmSwitch'))) return;
    const version = versions.find(v => v.id === id);
    if (!version) return;
    operation.current += 1;
    setSelectedId(id); setActiveLayer('report');
    const nextDraftKey = reportDraftKey(detail, id);
    setEditText(drafts.get(nextDraftKey) ?? version.report_md); setEditing(drafts.has(nextDraftKey));
    setEditState('idle'); setEditError(null); setActionState('idle'); setActionFeedback(null);
  }
  async function saveRevision() {
    if (!reportVersion || !dirty || editState === 'pending') return;
    const token = ++operation.current;
    const submittedText = editText;
    setEditState('pending'); setEditError(null);
    try {
      const revision = await createManualReportRevision(reportVersion.id, { report_md: submittedText });
      if (drafts.get(draftKey) === submittedText) drafts.delete(draftKey);
      if (!mounted.current || token !== operation.current) return;
      setVersions(current => [revision, ...current.filter(v => v.id !== revision.id)]);
      setSelectedId(revision.id); setEditing(false); setEditText(revision.report_md);
      setActiveLayer('report'); setEditState('success'); setActionFeedback(null);
    } catch (err) {
      if (!mounted.current || token !== operation.current) return;
      setEditState('error'); setEditError(err instanceof Error ? err.message : t('reportStudio.saveError'));
    }
  }
  const currentDetail: RunDetailRecord = reportVersion ? {
    ...detail, report_md: markdown, report_artifact: reportArtifact,
    qa_findings: versionFindings,
    enterprise_projection: detail.enterprise_projection ? { ...detail.enterprise_projection, report_version: reportVersion, claim_records: [] } : null,
  } : detail;
  const [activeLayer, setActiveLayer] = useState<ReportViewLayer>("report");
  const selectedMarkdown = selectReportLayerMarkdown(reportArtifact, markdown, activeLayer, {
    qa: t("report.layers.qa"),
    warnings: t("report.layers.qaWarnings"),
    blockers: t("report.layers.qaBlockers"),
  });
  const wordCount = locale === "zh-CN"
    ? Array.from(selectedMarkdown.replace(/\s/g, "")).length
    : selectedMarkdown.trim() ? selectedMarkdown.trim().split(/\s+/).length : 0;
  const [activeSourceId, setActiveSourceId] = useState<string | null>(null);
  const [actionState, setActionState] = useState<ReviewActionState>("idle");
  const [actionFeedback, setActionFeedback] = useState<ReviewActionFeedback | null>(null);

  useEffect(() => {
    if (!sourceAnchorId) return;
    setActiveSourceId(sourceAnchorId.replace(/^(?:missing-)?source-/, ''));
    setDetailsOpen(true);
  }, [sourceAnchorId, detail.id]);
  useEffect(() => {
    if (!sourceAnchorId || !detailsOpen || activeSourceId !== sourceAnchorId.replace(/^(?:missing-)?source-/, '')) return;
    const target = Array.from(scope.current?.querySelectorAll<HTMLElement>('[id]') ?? []).find(element => element.id === sourceAnchorId);
    target?.scrollIntoView({ behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'nearest' });
  }, [sourceAnchorId, detailsOpen, activeSourceId, detail.id]);

  const sourceMap = useMemo(
    () => new Map(reportSources.sources.map((source) => [source.id, source])),
    [reportSources.sources],
  );
  const sourceGroups = useMemo(
    () => collectSourceTokenGroups(selectedMarkdown, sourceMap, reportSources.aliases),
    [selectedMarkdown, reportSources.aliases, sourceMap],
  );
  const citedSourceGroups = sourceGroups.filter((group) => group.source);
  const missingSourceGroups = sourceGroups.filter((group) => !group.source);
  const citedSourceIds = useMemo(
    () => new Set(citedSourceGroups.map((group) => group.sourceId)),
    [citedSourceGroups],
  );
  const citationLabels = useMemo(() => buildCitationLabels(sourceGroups, t('report.missing')), [sourceGroups, locale, t]);
  const totalCitationCount = sourceGroups.reduce((total, group) => total + group.count, 0);

  function handleSourceJump(event: MouseEvent<HTMLAnchorElement>, href: string) {
    const anchorId = href.startsWith("#") ? href.slice(1) : "";
    if (!anchorId) return;
    const sourceId = anchorId.startsWith("source-")
      ? anchorId.slice("source-".length)
      : anchorId.startsWith("missing-source-")
        ? anchorId.slice("missing-source-".length)
        : null;
    jump(event, href, () => handleActiveSourceChange(sourceId));
  }

  function handleActiveSourceChange(sourceId: string | null) {
    setActiveSourceId(sourceId);
    if (sourceId) setDetailsOpen(true);
  }

  async function handleRequestApproval() {
    if (!reportVersion) return;
    const token = ++operation.current;
    setActionState("pending");
    setActionFeedback({ type: "approval-pending" });
    try {
      const response = await startReportApprovalWorkflow({
        report_version_id: reportVersion.id,
        requested_by: "frontend-review-studio",
      });
      if (!mounted.current || token !== operation.current) return;
      setActionState("success");
      setActionFeedback({ type: "approval-success", status: response.status, workflowId: response.workflow_id });
    } catch (err) {
      if (!mounted.current || token !== operation.current) return;
      setActionState("error");
      setActionFeedback(err instanceof Error ? { type: "system-error", message: err.message } : { type: "approval-error" });
    }
  }

  async function handleExport(format: "markdown" | "html" | "csv") {
    if (!reportVersion) return;
    const token = ++operation.current;
    setActionState("pending");
    setActionFeedback({ type: "export-pending", format });
    try {
      const response = await exportReportVersion(reportVersion.id, format);
      if (!mounted.current || token !== operation.current) return;
      await saveArtifactDownload(response.artifact, () => mounted.current && token === operation.current);
      if (!mounted.current || token !== operation.current) return;
      setActionState("success");
      setActionFeedback({ type: "export-success", filename: response.artifact.filename });
    } catch (err) {
      if (!mounted.current || token !== operation.current) return;
      setActionState("error");
      setActionFeedback(err instanceof Error ? { type: "system-error", message: err.message } : { type: "export-error" });
    }
  }

  function renderActionFeedback() {
    if (!actionFeedback) return null;
    switch (actionFeedback.type) {
      case "approval-pending":
        return t('reportStudio.startingApproval');
      case "approval-success":
        return `${t('reportStudio.approvalWorkflow')} ${displayLabel(actionFeedback.status, locale)}: ${actionFeedback.workflowId}`;
      case "export-pending":
        return `${t('common.exporting')} ${actionFeedback.format.toUpperCase()}`;
      case "export-success":
        return `${t('reportStudio.exported')} ${actionFeedback.filename}`;
      case "approval-error":
        return t('reportStudio.unableToApprove');
      case "export-error":
        return t('reportStudio.unableToExport');
      case "system-error":
        return <SystemMessage message={actionFeedback.message} />;
    }
  }

  const actionDisabled = !reportVersion || actionState === "pending" || editState === "pending" || dirty;

  return (
    <div className="run-report-review-studio" ref={scope}>
      <ReportStatusStrip version={reportVersion} detail={currentDetail} reportSources={reportSources} wordCount={wordCount} />
      <DimensionEvidencePanel detail={currentDetail} onRepair={reportVersion?.id === initialVersion?.id ? onRepair : undefined} />
      {reportVersion ? <Panel title={t('reportStudio.currentVersion')}>
        <label>{t('reportStudio.version')} <select className="input input-bordered" aria-label={t('reportStudio.version')} value={reportVersion.id} onChange={event => selectVersion(event.target.value)}>
          {versions.map(version => <option key={version.id} value={version.id}>v{version.version_number} · {displayLabel(version.status, locale)}</option>)}
        </select></label>
        <p>{t('reportStudio.versionStatus')} {displayLabel(reportVersion.status, locale)}{reportVersion.parent_version_id ? ` · ${t('reportStudio.parentVersion')} ${reportVersion.parent_version_id}` : ''}</p>
        {versionError ? <p role="alert">{t('reportStudio.versionError')}</p> : null}
        <p>{semanticReview.status === 'pending_review' ? t('reportStudio.pendingReview') : semanticReview.status === 'checked' ? t('reportStudio.checked') : t('reportStudio.currentQuality')}</p>
        <p>{releaseGate.allowed === true ? t('reportStudio.gateAllowed') : releaseGate.allowed === false ? t('reportStudio.gateBlocked') : t('reportStudio.gateUnknown')}</p>
        {versionFindings.length ? <ul>{versionFindings.map((finding, index) => <li key={finding.id ?? index}>
          {locale === 'zh-CN' && /^Current manual claim/.test(finding.problem) ? t(finding.problem.includes('no scoped source citation') ? 'reportStudio.missingCitation' : 'reportStudio.claimBlocked') : <SystemMessage message={finding.problem} />}
          {typeof finding.metadata?.claim_text === 'string' ? <blockquote>{typeof finding.metadata.line_number === 'number' ? `第${finding.metadata.line_number}行：` : ''}{finding.metadata.claim_text}</blockquote> : null}
          {locale === 'zh-CN' && /^Current manual claim/.test(finding.problem) ? <details><summary>{t('common.details')}</summary>{finding.problem}</details> : null}
        </li>)}</ul> : null}
        {editing ? <div className="grid gap-3">
          <label>{t('reportStudio.body')}<textarea aria-label={t('reportStudio.body')} className="textarea textarea-bordered w-full min-h-64 font-mono" value={editText} disabled={editState === 'pending'} onChange={event => { setEditText(event.target.value); if (event.target.value === markdown) drafts.delete(draftKey); else drafts.set(draftKey, event.target.value); }} /></label>
          {dirty ? <p role="status">{t('reportStudio.unsaved')}</p> : null}
          <button className="primary-action" type="button" disabled={!dirty || editState === 'pending'} onClick={saveRevision}>{t(editState === 'pending' ? 'reportStudio.saving' : 'reportStudio.save')}</button>
          <button className="icon-text-button" type="button" disabled={editState === 'pending'} onClick={() => { if (dirty && !window.confirm(t('reportStudio.confirmDiscard'))) return; drafts.delete(draftKey); setEditText(markdown); setEditing(false); }}>{t('reportStudio.cancelEdit')}</button>
        </div> : <button className="icon-text-button" type="button" disabled={actionState === 'pending'} onClick={() => { setEditText(drafts.get(draftKey) ?? markdown); setEditing(true); setEditState('idle'); }}>{t('reportStudio.edit')}</button>}
        {editState === 'success' ? <p role="status">{t('reportStudio.saved')}</p> : null}
        {editError ? <p role="alert">{t('reportStudio.saveError')}：<SystemMessage message={editError} /></p> : null}
      </Panel> : null}

      <div className={`report-review-workspace${detailsOpen ? ' details-open' : ''}`}>
        <ReportOutline markdown={selectedMarkdown} hidden={!detailsOpen} />

        <ReportReaderWorkspace
          activeSourceId={activeSourceId}
          activeLayer={activeLayer}
          markdown={markdown}
          onActiveLayerChange={setActiveLayer}
          onActiveSourceChange={handleActiveSourceChange}
          detailsOpen={detailsOpen}
          onDetailsToggle={() => setDetailsOpen(open => !open)}
          reportArtifact={reportArtifact ?? null}
          reportSources={reportSources}
        />

        <aside className="report-review-inspector">
          <div hidden={!detailsOpen}>
          <Panel
            className="report-review-source-panel"
            title={t('reportStudio.sourceTrace')}
            icon={<ShieldCheck size={16} aria-hidden />}
            actions={
              <StatusPill tone={missingSourceGroups.length ? "warn" : "good"}>
                {missingSourceGroups.length ? `${missingSourceGroups.length} ${t('report.missing')}` : t('report.linked')}
              </StatusPill>
            }
          >
            <ReportSourceTrace
              activeSourceId={activeSourceId}
              citationLabels={citationLabels}
              citedSourceGroups={citedSourceGroups}
              citedSourceIds={citedSourceIds}
              missingSourceGroups={missingSourceGroups}
              onSourceJump={handleSourceJump}
              sources={reportSources.sources}
              totalCitationCount={totalCitationCount}
            />
          </Panel>

          <RevisionDiff compact revisions={detail.revisions} />
          </div>

          <Panel className="report-review-actions-panel" title={t('reportStudio.reviewActions')}>
            <button className="primary-action" disabled={actionDisabled || releaseGate.allowed === false || semanticReview.status === 'pending_review'} onClick={handleRequestApproval} type="button">
              <Send size={15} aria-hidden />
              {t('reportStudio.requestApproval')}
            </button>
            <div className="report-review-export-grid" aria-label={t('reportStudio.exportActions')}>
              {(["markdown", "html", "csv"] as const).map((format) => (
                <button
                  className="icon-text-button"
                  disabled={actionDisabled}
                  key={format}
                  onClick={() => handleExport(format)}
                  type="button"
                >
                  <Download size={14} aria-hidden />
                  {format.toUpperCase()}
                </button>
              ))}
            </div>
            {!reportVersion ? <p className="muted-line">{t('reportStudio.noEnterpriseReport')}</p> : null}
            {actionFeedback ? <p className={`review-action-message ${actionState}`}>{renderActionFeedback()}</p> : null}
          </Panel>
        </aside>
      </div>
    </div>
  );
}
