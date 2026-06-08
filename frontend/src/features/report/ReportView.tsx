import { useMemo, useState, type MouseEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { RawSource } from "../../api/types";
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

interface Props {
  markdown: string;
  sources: RawSource[];
  sourceAliases?: Record<string, string>;
}

const EMPTY_SOURCE_ALIASES: Record<string, string> = {};

export function ReportView({ markdown, sources, sourceAliases = EMPTY_SOURCE_ALIASES }: Props) {
  const [activeSourceId, setActiveSourceId] = useState<string | null>(null);
  const sourceMap = useMemo(() => new Map(sources.map((source) => [source.id, source])), [sources]);
  const sourceGroups = useMemo(
    () => collectSourceTokenGroups(markdown, sourceMap, sourceAliases),
    [markdown, sourceAliases, sourceMap],
  );
  const citedSourceGroups = sourceGroups.filter((group) => group.source);
  const missingSourceGroups = sourceGroups.filter((group) => !group.source);
  const citedSourceIds = useMemo(
    () => new Set(citedSourceGroups.map((group) => group.sourceId)),
    [citedSourceGroups],
  );
  const citationLabels = useMemo(() => buildCitationLabels(sourceGroups), [sourceGroups]);
  const linkedMarkdown = useMemo(
    () => linkSourceTokens(markdown, sourceMap, sourceAliases, citationLabels),
    [citationLabels, markdown, sourceAliases, sourceMap],
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
    setActiveSourceId(sourceId);
    window.history.replaceState(null, "", `#${anchorId}`);
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <section className="panel report-panel">
      <h2>Report</h2>
      {markdown ? (
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
          }}
          remarkPlugins={[remarkGfm]}
        >
          {linkedMarkdown}
        </ReactMarkdown>
      ) : (
        <p>The writer has not produced a draft yet.</p>
      )}
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
}

function buildSourceTitle(missingSourceLink: boolean, source: RawSource | undefined, citationLabel: string | undefined) {
  if (missingSourceLink) return "Missing source token";
  if (!source) return undefined;
  return `${citationLabel ?? source.id}: ${source.title} / ${sourceTypeLabel(source.source_type)} / ${Math.round(
    source.confidence * 100,
  )}%`;
}
