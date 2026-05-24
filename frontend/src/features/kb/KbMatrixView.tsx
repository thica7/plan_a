import type { ComparisonMatrix, CompetitorKB } from "../../api/types";

interface Props {
  kbs: Record<string, CompetitorKB>;
  matrix?: ComparisonMatrix | null;
}

export function KbMatrixView({ kbs, matrix }: Props) {
  const competitors = matrix?.competitors ?? Object.keys(kbs);
  const dimensions =
    matrix?.dimensions ??
    Array.from(new Set(Object.values(kbs).flatMap((kb) => Object.keys(kb.slices))));

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
        </>
      )}
    </section>
  );
}
