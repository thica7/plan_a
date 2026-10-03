import { apiFetch } from "./http";
export interface KnowledgeDocument {
  id: string;
  workspace_id?: string | null;
  project_id?: string | null;
  url: string | null;
  title: string;
  source_type: string;
  competitor: string | null;
  dimension: string | null;
  content_hash: string;
  text: string;
  markdown: string;
  status: string;
  fetched_at: string;
  indexed_at: string | null;
  metadata: Record<string, unknown>;
}

export interface RetrievalHit {
  chunk_id: string;
  document_id: string;
  text: string;
  score: number;
  rerank_score: number | null;
  url: string | null;
  title: string;
  competitor: string | null;
  dimension: string | null;
  source_type: string;
}

export interface RetrievalRequest {
  query: string;
  top_k?: number;
  rerank_top_k?: number;
  mode?: 'hybrid' | string;
}

export interface RetrievalResponse {
  hits: RetrievalHit[];
}

export interface ListDocumentsFilters {
  project_id?: string | null;
  competitor?: string;
  dimension?: string;
  source_type?: string;
  page?: number;
  page_size?: number;
}

export function knowledgeProjectUrl(path: string, projectId: string | null = null): string {
  if (!projectId) return path;
  const separator = path.includes('?') ? '&' : '?';
  return `${path}${separator}${new URLSearchParams({ project_id: projectId })}`;
}

/**
 * 获取知识库文档列表
 * @param filters 过滤条件，支持 competitor, dimension, source_type, page, page_size
 * @param signal AbortSignal
 * @returns 知识库文档数组（包含 totalCount 属性以向后兼容）
 */
export async function listDocuments(
  filters?: ListDocumentsFilters,
  signal?: AbortSignal
): Promise<KnowledgeDocument[] & { totalCount: number }> {
  const params = new URLSearchParams();
  if (filters) {
    if (filters.project_id) params.set('project_id', filters.project_id);
    if (filters.competitor) params.set('competitor', filters.competitor);
    if (filters.dimension) params.set('dimension', filters.dimension);
    if (filters.source_type) params.set('source_type', filters.source_type);
    if (filters.page_size) params.set('limit', String(filters.page_size));
    if (filters.page) params.set('offset', String((filters.page - 1) * (filters.page_size ?? 10)));
  }
  const res = await apiFetch(`/api/knowledge/documents?${params}`, { signal });
  if (!res.ok) {
    throw new Error(`HTTP Error ${res.status}: ${res.statusText}`);
  }
  const totalHeader = res.headers.get('X-Total-Count');
  const totalCount = totalHeader ? parseInt(totalHeader, 10) : 0;
  const data = await res.json() as KnowledgeDocument[];
  return Object.assign(data, { totalCount });
}

/**
 * 获取单个知识库文档详情
 * @param id 文档唯一标识
 * @returns 知识库文档详情
 */
export async function getDocument(id: string, projectId: string | null = null): Promise<KnowledgeDocument> {
  const res = await apiFetch(knowledgeProjectUrl(`/api/knowledge/documents/${id}`, projectId));
  if (!res.ok) {
    throw new Error(`HTTP Error ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<KnowledgeDocument>;
}

/**
 * 删除指定的知识库文档
 * @param id 文档唯一标识
 */
export async function deleteDocument(id: string, projectId: string | null = null): Promise<void> {
  const res = await apiFetch(knowledgeProjectUrl(`/api/knowledge/documents/${id}`, projectId), {
    method: 'DELETE',
  });
  if (!res.ok) {
    throw new Error(`HTTP Error ${res.status}: ${res.statusText}`);
  }
}

/**
 * 检索/搜索知识库内容 (RAG 检索接口)
 * @param req 检索请求参数
 * @param signal AbortSignal
 * @returns 匹配的 RetrievalHit 列表
 */
export async function searchKnowledge(
  req: RetrievalRequest,
  signal?: AbortSignal
): Promise<RetrievalResponse> {
  const res = await apiFetch('/api/knowledge/search', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(req),
    signal,
  });
  if (!res.ok) {
    throw new Error(`HTTP Error ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<RetrievalResponse>;
}
