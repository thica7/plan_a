export type AuthenticActionKind =
  | "route"
  | "external"
  | "mutation"
  | "local"
  | "submit"
  | "copy"
  | "download"
  | "toggle"
  | "disabled"
  | "display";

export interface AuthenticityMetadata {
  actionId: string;
  kind: AuthenticActionKind;
  description: string;
}

export function assertAuthenticityMetadata(metadata: AuthenticityMetadata): void {
  if (!metadata.actionId.trim()) {
    throw new Error("Action authenticity metadata requires a non-empty actionId.");
  }
  if (!metadata.description.trim()) {
    throw new Error(`Action "${metadata.actionId}" requires a non-empty description.`);
  }
}

export function shouldAssertInteractionContracts(): boolean {
  return import.meta.env.MODE === "test" || import.meta.env.DEV;
}
