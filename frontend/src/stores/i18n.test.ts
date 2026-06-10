import { describe, expect, it } from "vitest";
import { useI18n } from "./i18n";

describe("i18n store", () => {
  it("defaults first-time users to Simplified Chinese", () => {
    expect(useI18n.getState().locale).toBe("zh-CN");
  });
});
