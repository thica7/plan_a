import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { CrawlJob } from "../../api/crawl";
import { useI18n } from "../../stores/i18n";
import { JobQueueTable } from "./JobQueueTable";

const job = { id: "job:original:1", url: "https://example.com/original", status: "failed", run_id: null, created_at: "2026-09-29T00:00:00Z" } as CrawlJob;

beforeEach(() => useI18n.getState().setLocale("zh-CN"));

it("disables unsupported pause and identifies local queue ordering as display sorting", () => {
  render(<JobQueueTable jobs={[job]} sources={[]} onRetryJob={vi.fn()} onRetrySource={vi.fn()} />);
  expect(screen.getByRole("button", { name: /暂停/ })).toBeDisabled();
  expect(screen.getByText("当前尚未提供暂停采集的能力。")).toBeInTheDocument();
  expect(screen.getByText("显示排序")).toBeInTheDocument();
  expect(screen.getByText("失败")).toBeInTheDocument();
});

it("retries jobs and sources with their complete original IDs", async () => {
  const user = userEvent.setup();
  const onRetryJob = vi.fn().mockResolvedValue(undefined);
  const onRetrySource = vi.fn().mockResolvedValue(undefined);
  render(<JobQueueTable jobs={[job]} sources={[{ id: "source:original:2", type: "manual", config: {}, created_at: "2026-09-29T00:00:00Z" }]} onRetryJob={onRetryJob} onRetrySource={onRetrySource} />);
  for (const button of screen.getAllByRole("button", { name: "重试" })) await user.click(button);
  expect(onRetryJob).toHaveBeenCalledWith("job:original:1");
  expect(onRetrySource).toHaveBeenCalledWith("source:original:2");
});
