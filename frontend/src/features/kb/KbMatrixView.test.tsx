import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KbMatrixView } from "./KbMatrixView";
import type { CompetitorKnowledge, RawSource } from "../../api/types";
import { useI18n } from "../../stores/i18n";

describe("KbMatrixView", () => {
  it('keeps source IDs without URLs as text and preserves real external source links', () => {
    const item = { competitor: 'Acme', confidence: 0.9, source_ids: ['no-url', 'with-url'], feature_tree: { summary_claims: [{ claim: '已知事实', source_ids: ['no-url', 'with-url'], confidence: 0.9 }], nodes: [] }, pricing_model: { notes: [], tiers: [] }, user_personas: { summary_claims: [], segments: [] } } as unknown as CompetitorKnowledge;
    const { container } = render(<KbMatrixView kbs={{}} knowledge={{ Acme: item }} sources={[{ id: 'no-url', title: '未提供网址', url: '', dimension: 'pricing' }, { id: 'with-url', title: '有网址', url: 'https://example.com/source', dimension: 'pricing' }] as RawSource[]} />);
    expect(screen.queryByRole('link', { name: 'no-url' })).not.toBeInTheDocument();
    expect(container.querySelector('a[href^="#"]')).toBeNull();
    expect(screen.getByText('no-url · 未提供来源链接')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'with-url' })).toHaveAttribute('href', 'https://example.com/source');
    act(() => useI18n.getState().setLocale('en-US'));
    expect(screen.getByText('no-url · Source URL unavailable')).toBeInTheDocument();
    act(() => useI18n.getState().setLocale('zh-CN'));
  });

  it("marks the researched target separately from rival products", () => {
    render(
      <KbMatrixView
        kbs={{}}
        knowledge={{}}
        sources={[]}
        matrix={{
          competitors: ["洁净家", "飞跃牌"],
          target_product: "洁净家",
          dimensions: ["pricing"],
          cells: [],
          winner_by_dimension: {},
          summary: [],
        }}
      />,
    );
    expect(screen.getByRole("columnheader", { name: /洁净家.*目标产品/ })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "飞跃牌" })).toBeTruthy();
  });
});
