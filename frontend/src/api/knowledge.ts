export interface KnowledgeDocument {
  id: string;
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
  competitor?: string;
  dimension?: string;
  source_type?: string;
  page?: number;
  page_size?: number;
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
    if (filters.competitor) params.set('competitor', filters.competitor);
    if (filters.dimension) params.set('dimension', filters.dimension);
    if (filters.source_type) params.set('source_type', filters.source_type);
    if (filters.page) params.set('page', String(filters.page));
    if (filters.page_size) params.set('page_size', String(filters.page_size));
  }
  const res = await fetch(`/api/knowledge/documents?${params}`, { signal });
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
export async function getDocument(id: string): Promise<KnowledgeDocument> {
  const res = await fetch(`/api/knowledge/documents/${id}`);
  if (!res.ok) {
    throw new Error(`HTTP Error ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<KnowledgeDocument>;
}

/**
 * 删除指定的知识库文档
 * @param id 文档唯一标识
 */
export async function deleteDocument(id: string): Promise<void> {
  const res = await fetch(`/api/knowledge/documents/${id}`, {
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
  const res = await fetch('/api/knowledge/search', {
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
