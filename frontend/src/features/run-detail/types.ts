export type RunDetailView = "overview" | "report" | "agents" | "quality";

export interface ReflectionItem {
  kind: string;
  text: string;
  index: number;
}
