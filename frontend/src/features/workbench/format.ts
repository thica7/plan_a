import type { ReportVersionRecord } from "../../api/types";

export function reportStatusTone(status: ReportVersionRecord["status"]) {
  if (status === "published" || status === "approved") return "good";
  if (status === "rejected" || status === "archived") return "bad";
  if (status === "in_review") return "warn";
  return "neutral";
}

export function formatPercent(value: number) {
  if (!Number.isFinite(value)) return "0%";
  return `${Math.round(value * 100)}%`;
}

export function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
