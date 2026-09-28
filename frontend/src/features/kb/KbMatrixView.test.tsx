import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KbMatrixView } from "./KbMatrixView";

describe("KbMatrixView", () => {
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
