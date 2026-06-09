import { describe, expect, it } from "vitest";
import { auditTsxSource } from "./interaction-authenticity-audit";

describe("interaction authenticity audit", () => {
  it("rejects raw buttons without an action contract", () => {
    const result = auditTsxSource('<button type="button" onClick={save}>Save</button>');

    expect(result.errorCount).toBeGreaterThan(0);
    expect(result.findings.some((finding) => finding.rule === "raw-button-contract")).toBe(true);
  });

  it("rejects empty handlers", () => {
    const result = auditTsxSource(
      '<button type="button" data-action-id="bad" data-action-audit="local" onClick={() => {}}>Bad</button>',
    );

    expect(result.findings.some((finding) => finding.rule === "noop-handler")).toBe(true);
  });

  it("rejects placeholder links", () => {
    const result = auditTsxSource('<a href="#">Open</a>');

    expect(result.findings.some((finding) => finding.rule === "fake-link")).toBe(true);
  });

  it("rejects unknown audit kinds", () => {
    const result = auditTsxSource(
      '<button type="button" data-action-id="bad" data-action-audit="pretend" onClick={save}>Save</button>',
    );

    expect(result.findings.some((finding) => finding.rule === "unknown-audit-kind")).toBe(true);
  });

  it("rejects role buttons without keyboard support", () => {
    const result = auditTsxSource('<div role="button" onClick={save}>Save</div>');

    expect(result.findings.some((finding) => finding.rule === "role-button-keyboard")).toBe(true);
  });

  it("ignores comments and strings that mention buttons", () => {
    const result = auditTsxSource('const text = "<button>not real</button>"; // <button />');

    expect(result.errorCount).toBe(0);
  });

  it("allows native controls only through a non-expired allowlist entry", () => {
    const result = auditTsxSource(
      '<button type="button" onClick={save}>Save</button>',
      "src/legacy/Allowed.tsx",
      {
        allowlist: [
          {
            file: "src/legacy/Allowed.tsx",
            owner: "legacy",
            reason: "real callback pending migration",
            expires: "2099-01-01",
          },
        ],
      },
    );

    expect(result.errorCount).toBe(0);
    expect(result.warningCount).toBe(1);
  });
});
