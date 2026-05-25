import type { ComparisonMatrix, CompetitorKB, CompetitorKnowledge, KnowledgeClaim, RawSource } from "../../api/types";

interface Props {
  kbs: Record<string, CompetitorKB>;
  knowledge: Record<string, CompetitorKnowledge>;
  matrix?: ComparisonMatrix | null;
  sources: RawSource[];
}

export function KbMatrixView({ kbs, knowledge, matrix, sources }: Props) {
  const competitors = matrix?.competitors ?? Array.from(new Set([...Object.keys(kbs), ...Object.keys(knowledge)]));
  const dimensions =
    matrix?.dimensions ??
    Array.from(new Set(Object.values(kbs).flatMap((kb) => Object.keys(kb.slices))));
  const sourceMap = new Map(sources.map((source) => [source.id, source]));

  return (
    <section className="panel kb-matrix-panel">
      <h2>KB & Matrix</h2>
      {competitors.length === 0 ? (
        <p>No structured KB yet.</p>
      ) : (
        <>
          <div className="matrix-table-wrap">
            <table className="matrix-table">
              <thead>
                <tr>
                  <th>Dimension</th>
                  {competitors.map((competitor) => (
                    <th key={competitor}>{competitor}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {dimensions.map((dimension) => (
                  <tr key={dimension}>
                    <th>{dimension}</th>
                    {competitors.map((competitor) => {
                      const cell = matrix?.cells.find(
                        (item) => item.dimension === dimension && item.competitor === competitor,
                      );
                      const fallback = kbs[competitor]?.slices[dimension]?.join("; ");
                      return (
                        <td key={`${dimension}-${competitor}`}>
                          <p>{cell?.value || fallback || "No finding"}</p>
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
                <strong>{kb.competitor}</strong>
                <span>{Math.round(kb.confidence * 100)}% avg confidence · {kb.sources.length} sources</span>
                {Object.entries(kb.slices).map(([dimension, findings]) => (
                  <div key={dimension}>
                    <em>{dimension}</em>
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
                <strong>{item.competitor} schema</strong>
                <span>{Math.round(item.confidence * 100)}% confidence · {item.source_ids.length} traced sources</span>
                <KnowledgeSection title="Feature tree" claims={item.feature_tree.summary_claims} sourceMap={sourceMap} />
                {item.feature_tree.nodes.map((node) => (
                  <div key={`${item.competitor}-${node.name}`}>
                    <em>{node.name}</em>
                    <ClaimList claims={node.claims} sourceMap={sourceMap} />
                  </div>
                ))}
                <KnowledgeSection
                  title="Pricing model"
                  claims={[
                    ...item.pricing_model.notes,
                    ...item.pricing_model.tiers.flatMap((tier) => tier.claims),
                  ]}
                  sourceMap={sourceMap}
                />
                <KnowledgeSection
                  title="User personas"
                  claims={[
                    ...item.user_personas.summary_claims,
                    ...item.user_personas.segments.flatMap((segment) => segment.claims),
                  ]}
                  sourceMap={sourceMap}
                />
                {item.user_personas.segments.length > 0 ? (
                  <div>
                    <em>Persona segments</em>
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
            title={source ? `${source.title} / ${source.dimension}` : "Unknown source"}
          >
            {id}
          </a>
        );
      })}
    </span>
  );
}
