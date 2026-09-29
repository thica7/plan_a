import {
  AlertTriangle,
  CheckCircle2,
  Database,
  FileCheck2,
  KeyRound,
  Play,
  RefreshCw,
  ShieldCheck,
  UserCheck,
} from "lucide-react";
import type { ReactNode } from "react";
import type {
  RuntimeConfig,
  ScenarioPack,
  WorkspaceQuotaDecision,
} from "../../api/types";
import { ActionButton } from "../../components/interaction/ActionButton";
import { useTranslation } from "../../stores/i18n";
import { displayLabel, runtimeDiagnostic } from "../../i18n/display";
import { SystemMessage } from "../../i18n/SystemMessage";
import { RuntimeLine } from "./RuntimeLine";
import type { CollaborationMode, CompetitorMode, ExecutionMode, LayerSelection, ResearchDepth } from "./types";

interface RunReadinessRailProps {
  targetName: string;
  autoRedoWarn: boolean;
  competitorList: string[];
  competitorMode: CompetitorMode;
  collaborationMode: CollaborationMode;
  dynamicScenarioSelected: boolean;
  error: string | null;
  executionMode: ExecutionMode;
  manualScopeError: string | null;
  isSubmitting: boolean;
  quotaDecision: WorkspaceQuotaDecision | null;
  runBlockedByQuota: boolean;
  runtime: RuntimeConfig | null;
  selected: string[];
  selectedLayer: LayerSelection;
  researchDepth: ResearchDepth;
  selectedScenario: ScenarioPack | null;
  setAutoRedoWarn: (enabled: boolean) => void;
}

export function RunReadinessRail({
  targetName,
  autoRedoWarn,
  competitorList,
  competitorMode,
  collaborationMode,
  dynamicScenarioSelected,
  error,
  executionMode,
  manualScopeError,
  isSubmitting,
  quotaDecision,
  runBlockedByQuota,
  runtime,
  selected,
  selectedLayer,
  researchDepth,
  selectedScenario,
  setAutoRedoWarn,
}: RunReadinessRailProps) {
  const { locale, t } = useTranslation();

  const llmReady = Boolean(
    (runtime?.has_ark_api_key && runtime.has_ark_model) ||
      (runtime?.has_backup_llm_api_key && runtime.has_backup_llm_model),
  );
  const searchReady = Boolean(runtime?.has_web_search_key);
  const temporalReady = Boolean(runtime?.temporal_cutover_ready);
  const pydanticReady = Boolean(runtime?.pydantic_ai_model_backed_ready);
  const complianceReady = Boolean(runtime?.compliance_redaction_enabled);
  const aiAutoRedoEnabled = collaborationMode === "ai" && autoRedoWarn;
  const readyCount = [
    llmReady,
    searchReady,
    temporalReady,
    complianceReady,
    quotaDecision?.allowed !== false,
    selected.length > 0,
  ].filter(Boolean).length;
  const readinessStatus = runBlockedByQuota
    ? t('run.readiness.blocked')
    : readyCount >= 5
      ? t('run.readiness.ready')
      : t('run.readiness.review');
  const competitorSummary =
    competitorMode === "auto"
      ? t('newRun.autoDiscover')
      : competitorList.length > 0
        ? `${competitorList.length} ${t('run.selected')}`
        : t('newRun.manual');

  return (
    <aside className="run-builder-rail">
      <section className="panel run-readiness-panel">
        <div className="run-readiness-header">
          <div>
            <h2>{t('run.readiness.title')}</h2>
            <p>{t('run.readiness.description')}</p>
          </div>
          <span className={runBlockedByQuota ? "flow-status failed" : "flow-status pass"}>
            <CheckCircle2 size={14} aria-hidden />
            {readinessStatus}
          </span>
        </div>

        <div className="readiness-checklist" aria-label={t('run.readiness.checklist')}>
          <ReadinessItem icon={<ShieldCheck size={15} />} ok={Boolean(quotaDecision?.allowed ?? true)} title={t('run.workspace')}>
            {quotaDecision?.allowed === false ? <SystemMessage message={quotaDecision.reason} /> : t('run.acmeCorp')}
          </ReadinessItem>
          <ReadinessItem icon={<FileCheck2 size={15} />} ok={selected.length > 0} title={t('newRun.dimensions')}>
            {selected.length} {t('run.selected')}
          </ReadinessItem>
          <ReadinessItem icon={<Database size={15} />} ok={searchReady} title={t('run.dataSources')}>
            {runtime?.has_web_search_key ? `${runtime.web_search_provider}, ${t('run.web')}, ${t('run.registry')}` : t('run.searchKeyMissing')}
          </ReadinessItem>
          <ReadinessItem icon={<KeyRound size={15} />} ok={llmReady} title={t('run.modelRoute')}>
            {runtime?.has_ark_api_key && runtime.has_ark_model
              ? runtime.ark_model
              : runtime?.has_backup_llm_api_key && runtime.has_backup_llm_model
                ? runtime.backup_llm_model
                : t('run.credentialsMissing')}
          </ReadinessItem>
          <ReadinessItem icon={<UserCheck size={15} />} ok={collaborationMode === "assisted" || aiAutoRedoEnabled} title={t('run.qualityControls')}>
            {collaborationMode === "assisted" ? t('run.humanReviewEnabled') : aiAutoRedoEnabled ? t('run.autoRedoEnabled') : t('run.manualLaunch')}
          </ReadinessItem>
        </div>

        <div className="readiness-section">
          <header>
            <h3>{t('run.costEstimate')}</h3>
            <ActionButton
              className="ghost-button"
              authenticity={{
                actionId: 'new-run.cost-details.disabled',
                kind: 'disabled',
                description: 'detailed cost breakdown not available in demo'
              }}
              disabled
              disabledReason={t('run.details.disabled')}
            >
              {t('run.details')}
            </ActionButton>
          </header>
          <p>{t('run.costUnavailable')}</p>
        </div>

        <div className="readiness-section">
          <header>
            <h3>{t('run.sourcePolicy')}</h3>
            <span>{t('run.strict')}</span>
          </header>
          <dl className="readiness-cost-list">
            <div>
              <dt>{t('run.verifiedSourcesOnly')}</dt>
              <dd>{t('run.required')}</dd>
            </div>
            <div>
              <dt>{t('run.minDomainAuthority')}</dt>
              <dd>40</dd>
            </div>
            <div>
              <dt>{t('run.maxSourcesPerClaim')}</dt>
              <dd>5</dd>
            </div>
            <div>
              <dt>{t('run.citationRequired')}</dt>
              <dd>{t('common.yes')}</dd>
            </div>
          </dl>
        </div>

        <div className="readiness-section">
          <header>
            <h3>{t('run.runtimeSignals')}</h3>
            <span>{displayLabel(executionMode, locale)}</span>
          </header>
          <div className="runtime-lines compact">
            <RuntimeLine ok={searchReady}>
              {searchReady ? `${runtime?.web_search_provider} ${t('run.searchEnabled')}` : t('run.searchCredentialsMissing')}
            </RuntimeLine>
            <RuntimeLine ok={temporalReady}>
              {temporalReady ? `Temporal ${runtime?.temporal_task_queue}` : <SystemMessage message={runtime?.temporal_cutover_reason ?? t('run.temporalUnavailable')} />}
            </RuntimeLine>
            <RuntimeLine ok={pydanticReady}>
              {pydanticReady
                ? `Pydantic-AI ${runtime?.pydantic_ai_model_name}`
                : <SystemMessage message={runtime?.pydantic_ai_model_backed_reason ?? t('run.pydanticDisabled')} />}
            </RuntimeLine>
            <RuntimeLine ok={complianceReady}>
              {complianceReady ? t('run.complianceRedactionEnabled') : t('run.complianceRedactionDisabled')}
            </RuntimeLine>
          </div>
        </div>

        <div className="readiness-section">
          <header>
            <h3>{t('run.autoRedoWarnings')}</h3>
            <span>{collaborationMode === "ai" ? t('common.optional') : t('newRun.collaboration.assisted')}</span>
          </header>
          <label className="toggle-row compact">
            <input
              checked={aiAutoRedoEnabled}
              disabled={runtime?.auto_redo_enabled === false || collaborationMode === "assisted"}
              onChange={(event) => setAutoRedoWarn(event.target.checked)}
              type="checkbox"
            />
            <span>
              <strong>{t('run.autoRedoWarnings')}</strong>
              <em>{t('run.autoRedoWarningsDesc')}</em>
            </span>
          </label>
        </div>

        {manualScopeError ? <p className="error-line" role="alert">{manualScopeError}</p> : null}
        {error ? <p className="error-line"><SystemMessage message={error} /></p> : null}

        <ActionButton
          className="primary-button full-width"
          type="submit"
          authenticity={{
            actionId: 'new-run.submit',
            kind: 'submit',
            description: 'submits the new run builder form'
          }}
          disabled={Boolean(manualScopeError) || targetName.trim().length < 2 || selected.length === 0 || runBlockedByQuota || (competitorMode === "auto" && !searchReady)}
          disabledReason={
            runBlockedByQuota
              ? runtimeDiagnostic(quotaDecision?.reason || t('run.disabled.quota'), locale)
              : manualScopeError
                ? t('run.disabled.scope')
              : targetName.trim().length < 2
                ? t('run.disabled.targetProduct')
              : competitorMode === "auto" && !searchReady
                ? t('run.disabled.discoverySearch')
              : selected.length === 0
                ? t('run.disabled.dimensions')
                : undefined
          }
          isLoading={isSubmitting}
          loadingLabel={t('run.submitting')}
        >
          {isSubmitting ? <RefreshCw size={18} aria-hidden /> : <Play size={18} aria-hidden />}
          {t('run.submit')}
        </ActionButton>
      </section>

      <section className="panel run-contract-panel">
        <h2>{t('run.runContract')}</h2>
        <dl className="contract-list">
          <div>
            <dt>{t('runHeader.layer')}</dt>
            <dd>{displayLabel(selectedLayer, locale)}</dd>
          </div>
          <div>
            <dt>{t('newRun.researchDepth')}</dt>
            <dd>{t(`newRun.researchDepth.${researchDepth}`)}</dd>
          </div>
          <div>
            <dt>{t('newRun.collaboration')}</dt>
            <dd>{t(`newRun.collaboration.${collaborationMode}`)}</dd>
          </div>
          <div>
            <dt>{t('runHeader.scenario')}</dt>
            <dd>{selectedScenario ? displayLabel(selectedScenario.name, locale) : dynamicScenarioSelected ? t('run.dynamic') : t('newRun.auto')}</dd>
          </div>
          <div>
            <dt>{t('newRun.competitors')}</dt>
            <dd>{competitorSummary}</dd>
          </div>
        </dl>
        <div className="contract-chips">
          {selected.map((dimension) => (
            <span key={dimension}>{displayLabel(dimension, locale)}</span>
          ))}
        </div>
      </section>
    </aside>
  );
}

function ReadinessItem({
  children,
  icon,
  ok,
  title,
}: {
  children: ReactNode;
  icon: ReactNode;
  ok: boolean;
  title: string;
}) {
  return (
    <div className={ok ? "readiness-item ok" : "readiness-item warn"}>
      <span>{icon}</span>
      <div>
        <strong>{title}</strong>
        <em>{children}</em>
      </div>
      {ok ? <CheckCircle2 size={14} aria-hidden /> : <AlertTriangle size={14} aria-hidden />}
    </div>
  );
}
