import type { ComparisonMatrix, CompetitorKB, CompetitorKnowledge, KnowledgeClaim, RawSource } from "../../api/types";
import { useTranslation } from '../../stores/i18n';
import { displayLabel } from "../../i18n/display";

interface Props {
  kbs: Record<string, CompetitorKB>;
  knowledge: Record<string, CompetitorKnowledge>;
  matrix?: ComparisonMatrix | null;
  sources: RawSource[];
}

export function KbMatrixView({ kbs, knowledge, matrix, sources }: Props) {
  const { locale, t } = useTranslation();
  const competitors = matrix?.competitors ?? Array.from(new Set([...Object.keys(kbs), ...Object.keys(knowledge)]));
  const dimensions =
    matrix?.dimensions ??
    Array.from(new Set(Object.values(kbs).flatMap((kb) => Object.keys(kb.slices))));
  const sourceMap = new Map(sources.map((source) => [source.id, source]));

  return (
    <section className="panel kb-matrix-panel">
      <h2>{t('kb.title')}</h2>
      {competitors.length === 0 ? (
        <p>{t('kb.noStructuredKb')}</p>
      ) : (
        <>
          <div className="matrix-table-wrap">
            <table className="matrix-table">
              <thead>
                <tr>
                  <th>{t('kb.dimension')}</th>
                  {competitors.map((competitor) => (
                    <th key={competitor}>
                      {competitor}{matrix?.target_product === competitor ? ` · ${t('kb.targetProduct')}` : ""}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {dimensions.map((dimension) => (
                  <tr key={dimension}>
                    <th>{displayLabel(dimension, locale)}</th>
                    {competitors.map((competitor) => {
                      const cell = matrix?.cells.find(
                        (item) => item.dimension === dimension && item.competitor === competitor,
                      );
                      const fallback = kbs[competitor]?.slices[dimension]?.join("; ");
                      return (
                        <td key={`${dimension}-${competitor}`}>
                          <p>{cell?.value || fallback || t('kb.noFinding')}</p>
                          {cell ? <span>{Math.round(cell.confidence * 100)}%</span> : null}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {matrix?.summary.length ? (
            <div className="matrix-summary">
              {matrix.summary.map((item) => (
                <p key={item}>{item}</p>
              ))}
            </div>
          ) : null}

          <div className="kb-list">
            {Object.values(kbs).map((kb) => (
              <article key={kb.competitor}>
                <strong>{kb.competitor}{matrix?.target_product === kb.competitor ? ` · ${t('kb.targetProduct')}` : ""}</strong>
                <span>{Math.round(kb.confidence * 100)}% {t('kb.avgConfidence')} · {kb.sources.length} {t('kb.sources')}</span>
                {Object.entries(kb.slices).map(([dimension, findings]) => (
                  <div key={dimension}>
                    <em>{displayLabel(dimension, locale)}</em>
                    <ul>
                      {findings.map((finding) => (
                        <li key={finding}>{finding}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </article>
            ))}
          </div>

          <div className="knowledge-list">
            {Object.values(knowledge).map((item) => (
              <article key={item.competitor}>
                <strong>{item.competitor} {t('kb.schema')}</strong>
                <span>{Math.round(item.confidence * 100)}% {t('kb.confidence')} · {item.source_ids.length} {t('kb.tracedSources')}</span>
                <KnowledgeSection title={t('kb.featureTree')} claims={item.feature_tree.summary_claims} sourceMap={sourceMap} />
                {item.feature_tree.nodes.map((node) => (
                  <div key={`${item.competitor}-${node.name}`}>
                    <em>{node.name}</em>
                    <ClaimList claims={node.claims} sourceMap={sourceMap} />
                  </div>
                ))}
                <KnowledgeSection
                  title={t('kb.pricingModel')}
                  claims={[
                    ...item.pricing_model.notes,
                    ...item.pricing_model.tiers.flatMap((tier) => tier.claims),
                  ]}
                  sourceMap={sourceMap}
                />
                <KnowledgeSection
                  title={t('kb.userPersonas')}
                  claims={[
                    ...item.user_personas.summary_claims,
                    ...item.user_personas.segments.flatMap((segment) => segment.claims),
                  ]}
                  sourceMap={sourceMap}
                />
                {item.user_personas.segments.length > 0 ? (
                  <div>
                    <em>{t('kb.personaSegments')}</em>
                    <ul>
                      {item.user_personas.segments.map((segment) => (
                        <li key={`${item.competitor}-${segment.name}`}>
                          <strong>{segment.name}</strong>
                          <span>
                            {segment.role} / {segment.company_size}
                          </span>
                          {segment.use_cases.length > 0 ? <small>{segment.use_cases.join("; ")}</small> : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function KnowledgeSection({
  title,
  claims,
  sourceMap,
}: {
  title: string;
  claims: KnowledgeClaim[];
  sourceMap: Map<string, RawSource>;
}) {
  if (claims.length === 0) return null;
  return (
    <div>
      <em>{title}</em>
      <ClaimList claims={claims} sourceMap={sourceMap} />
    </div>
  );
}

function ClaimList({ claims, sourceMap }: { claims: KnowledgeClaim[]; sourceMap: Map<string, RawSource> }) {
  if (claims.length === 0) return null;
  return (
    <ul>
      {claims.map((claim, index) => (
        <li key={`${claim.claim}-${index}`}>
          {claim.claim}
          <SourceIds ids={claim.source_ids} sourceMap={sourceMap} />
        </li>
      ))}
    </ul>
  );
}

function SourceIds({ ids, sourceMap }: { ids: string[]; sourceMap: Map<string, RawSource> }) {
  const { locale, t } = useTranslation();
  if (ids.length === 0) return null;
  return (
    <span className="source-id-links">
      {ids.map((id) => {
        const source = sourceMap.get(id);
        return (
          <a
            href={source?.url || `#source-${id}`}
            key={id}
            rel={source?.url ? "noreferrer" : undefined}
            target={source?.url ? "_blank" : undefined}
            title={source ? `${source.title} / ${displayLabel(source.dimension, locale)}` : t('kb.unknownSource')}
          >
            {id}
          </a>
        );
      })}
    </span>
  );
}
