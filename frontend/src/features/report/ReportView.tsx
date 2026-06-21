import { isValidElement, useMemo, useState, type MouseEvent, type ReactNode } from "react";
import { useTranslation } from '../../stores/i18n';
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { RawSource, ReportArtifactV2 } from "../../api/types";
import { ReportSourceTrace } from "./ReportSourceTrace";
import {
  buildCitationLabels,
  collectSourceTokenGroups,
  linkSourceTokens,
  sourceTypeLabel,
} from "./sourceTokens";

export {
  buildCitationLabels,
  collectSourceTokenGroups,
  extractSourceTokens,
  linkSourceTokens,
  resolveSourceId,
  sourceTypeLabel,
} from "./sourceTokens";

export type ReportViewLayer = "report" | "evidence" | "qa" | "audit";

export interface ReportLayerLabels {
  qa: string;
  warnings: string;
  blockers: string;
}

interface Props {
  activeSourceId?: string | null;
  activeLayer?: ReportViewLayer;
  layout?: "stacked" | "reader";
  markdown: string;
  onActiveLayerChange?: (layer: ReportViewLayer) => void;
  onActiveSourceChange?: (sourceId: string | null) => void;
  readerTitle?: string;
  reportArtifact?: ReportArtifactV2 | null;
  showSourceTrace?: boolean;
  sources: RawSource[];
  sourceAliases?: Record<string, string>;
}

const EMPTY_SOURCE_ALIASES: Record<string, string> = {};

export function ReportView({
  activeSourceId: controlledActiveSourceId,
  activeLayer: controlledActiveLayer,
  layout = "stacked",
  markdown,
  onActiveLayerChange,
  onActiveSourceChange,
  readerTitle = "Report",
  reportArtifact = null,
  showSourceTrace = true,
  sources,
  sourceAliases = EMPTY_SOURCE_ALIASES,
}: Props) {
  const { t } = useTranslation();
  const [internalActiveSourceId, setInternalActiveSourceId] = useState<string | null>(null);
  const [internalActiveLayer, setInternalActiveLayer] = useState<ReportViewLayer>("report");
  const activeSourceId =
    controlledActiveSourceId === undefined ? internalActiveSourceId : controlledActiveSourceId;
  const activeLayer = controlledActiveLayer ?? internalActiveLayer;
  const layerMarkdown = selectReportLayerMarkdown(reportArtifact, markdown, activeLayer, {
    qa: t("report.layers.qa"),
    warnings: t("report.layers.qaWarnings"),
    blockers: t("report.layers.qaBlockers"),
  });
  const sourceMap = useMemo(() => new Map(sources.map((source) => [source.id, source])), [sources]);
  const sourceGroups = useMemo(
    () => collectSourceTokenGroups(layerMarkdown, sourceMap, sourceAliases),
    [layerMarkdown, sourceAliases, sourceMap],
  );
  const citedSourceGroups = sourceGroups.filter((group) => group.source);
  const missingSourceGroups = sourceGroups.filter((group) => !group.source);
  const citedSourceIds = useMemo(
    () => new Set(citedSourceGroups.map((group) => group.sourceId)),
    [citedSourceGroups],
  );
  const citationLabels = useMemo(() => buildCitationLabels(sourceGroups), [sourceGroups]);
  const linkedMarkdown = useMemo(
    () => linkSourceTokens(layerMarkdown, sourceMap, sourceAliases, citationLabels),
    [citationLabels, layerMarkdown, sourceAliases, sourceMap],
  );
  const totalCitationCount = sourceGroups.reduce((total, group) => total + group.count, 0);

  function handleSourceJump(event: MouseEvent<HTMLAnchorElement>, href: string | undefined) {
    const anchorId = href?.startsWith("#") ? href.slice(1) : "";
    if (!anchorId) return;
    const target = document.getElementById(anchorId);
    if (!target) return;
    event.preventDefault();
    const sourceId = anchorId.startsWith("source-")
      ? anchorId.slice("source-".length)
      : anchorId.startsWith("missing-source-")
        ? anchorId.slice("missing-source-".length)
        : null;
    setInternalActiveSourceId(sourceId);
    onActiveSourceChange?.(sourceId);
    window.history.replaceState(null, "", `#${anchorId}`);
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function handleLayerChange(layer: ReportViewLayer) {
    if (controlledActiveLayer === undefined) {
      setInternalActiveLayer(layer);
    }
    onActiveLayerChange?.(layer);
  }

  const reportBody = (
    <section className={`panel report-panel${layout === "reader" ? " report-reader-panel" : ""}`}>
      <div className="panel-heading-row">
        <h2>{readerTitle}</h2>
        {totalCitationCount ? <span className="report-citation-count">{totalCitationCount} citations</span> : null}
      </div>
      {reportArtifact ? (
        <div role="group" aria-label={t("report.layers.label")} className="report-mode-toggle report-layer-tabs">
          {([
            ["report", t("report.layers.report")],
            ["evidence", t("report.layers.evidence")],
            ["qa", t("report.layers.qa")],
            ["audit", t("report.layers.audit")],
          ] as const).map(([key, label]) => (
            <button
              className={activeLayer === key ? "active" : undefined}
              key={key}
              aria-pressed={activeLayer === key}
              onClick={() => handleLayerChange(key)}
              type="button"
            >
              {label}
            </button>
          ))}
        </div>
      ) : null}
      {layerMarkdown ? (
        <div className="report-reader-body">
          <ReactMarkdown
            components={{
              a({ href, children, ...props }) {
                const sourceLink = href?.startsWith("#source-");
                const missingSourceLink = Boolean(href?.startsWith("#missing-source-"));
                const sourceId = sourceLink ? href?.slice("#source-".length) : undefined;
                const source = sourceId ? sourceMap.get(sourceId) : undefined;
                const citationLabel = sourceId ? citationLabels.get(sourceId) : undefined;
                return (
                  <a
                    className={
                      sourceLink || missingSourceLink
                        ? `source-token-link${missingSourceLink ? " missing" : ""}${
                            sourceId && activeSourceId === sourceId ? " active" : ""
                          }`
                        : undefined
                    }
                    data-source-id={sourceId}
                    href={href}
                    onClick={(event) => handleSourceJump(event, href)}
                    title={buildSourceTitle(missingSourceLink, source, citationLabel)}
                    {...props}
                  >
                    {children}
                  </a>
                );
              },
              h1({ children, ...props }) {
                return <h1 id={slugReportHeading(reactNodeToText(children))} {...props}>{children}</h1>;
              },
              h2({ children, ...props }) {
                return <h2 id={slugReportHeading(reactNodeToText(children))} {...props}>{children}</h2>;
              },
              h3({ children, ...props }) {
                return <h3 id={slugReportHeading(reactNodeToText(children))} {...props}>{children}</h3>;
              },
              h4({ children, ...props }) {
                return <h4 id={slugReportHeading(reactNodeToText(children))} {...props}>{children}</h4>;
              },
            }}
            remarkPlugins={[remarkGfm]}
          >
            {linkedMarkdown}
          </ReactMarkdown>
        </div>
      ) : (
        <p>{t('report.noDraft')}</p>
      )}
    </section>
  );

  const sourceTrace = (
    <section className="panel report-source-panel">
      <div className="panel-heading-row">
        <h2>{t('report.sourceTrace')}</h2>
        <span className={missingSourceGroups.length > 0 ? "report-source-warning" : "report-source-ok"}>
          {missingSourceGroups.length > 0 ? `${missingSourceGroups.length} missing` : "linked"}
        </span>
      </div>
      <ReportSourceTrace
        activeSourceId={activeSourceId}
        citationLabels={citationLabels}
        citedSourceGroups={citedSourceGroups}
        citedSourceIds={citedSourceIds}
        missingSourceGroups={missingSourceGroups}
        onSourceJump={handleSourceJump}
        sources={sources}
        totalCitationCount={totalCitationCount}
      />
    </section>
  );

  if (!showSourceTrace) {
    return reportBody;
  }

  if (layout === "reader") {
    return (
      <div className="report-reader-layout">
        {reportBody}
        <aside className="report-source-rail">{sourceTrace}</aside>
      </div>
    );
  }

  return (
    <>
      {reportBody}
      {sourceTrace}
    </>
  );
}

export function selectReportLayerMarkdown(
  reportArtifact: ReportArtifactV2 | null | undefined,
  markdown: string,
  activeLayer: ReportViewLayer,
  labels: ReportLayerLabels,
) {
  if (!reportArtifact) return markdown;
  if (activeLayer === "report") return reportArtifact.render_cache.core_markdown;
  if (activeLayer === "evidence") return reportArtifact.render_cache.support_markdown;
  if (activeLayer === "audit") return reportArtifact.render_cache.audit_markdown;
  return [
    `## ${labels.qa}`,
    `${labels.warnings}: ${reportArtifact.quality.warnings.length}`,
    `${labels.blockers}: ${reportArtifact.quality.blockers.length}`,
  ].join("\n\n");
}

export function slugReportHeading(text: string) {
  const slug = text
    .toLowerCase()
    .replace(/[`*_~()[\]{}:;,.!?'"<>|/\\]+/g, " ")
    .replace(/\s+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
  return `report-section-${slug || "section"}`;
}

function reactNodeToText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(reactNodeToText).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return reactNodeToText(node.props.children);
  return "";
}

function buildSourceTitle(missingSourceLink: boolean, source: RawSource | undefined, citationLabel: string | undefined) {
  if (missingSourceLink) return "Missing source token";
  if (!source) return undefined;
  return `${citationLabel ?? source.id}: ${source.title} / ${sourceTypeLabel(source.source_type)} / ${Math.round(
    source.confidence * 100,
  )}%`;
}
