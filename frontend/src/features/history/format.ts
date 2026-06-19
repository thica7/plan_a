import type { RunStatus } from "../../api/types";

export function statusClass(status: RunStatus) {
  if (status === "completed") return "good";
  if (status === "failed" || status === "completed_with_blockers") return "warn";
  return "neutral";
}

export function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}
