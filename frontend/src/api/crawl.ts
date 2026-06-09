export interface CrawlJob {
  id: string;
  run_id: string | null;
  url: string;
  competitor: string | null;
  dimension: string | null;
  status: 'pending' | 'running' | 'completed' | 'failed' | string;
  attempt_count: number;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateCrawlJobRequest {
  url: string;
  competitor?: string;
  dimension?: string;
}

/**
 * 获取爬虫任务列表
 * @param signal 可选的取消信号
 * @returns 爬虫任务数组，可能附带 totalCount 属性
 */
export async function listCrawlJobs(signal?: AbortSignal): Promise<CrawlJob[] & { totalCount?: number }> {
  const res = await fetch('/api/crawl/jobs', { signal });
  if (!res.ok) {
    throw new Error(`HTTP Error ${res.status}: ${res.statusText}`);
  }
  const data = await res.json() as CrawlJob[];
  const totalCount = res.headers.get('X-Total-Count');
  const result = data as CrawlJob[] & { totalCount?: number };
  if (totalCount !== null) {
    result.totalCount = parseInt(totalCount, 10);
  }
  return result;
}

/**
 * 创建新的爬虫任务
 * @param req 创建任务的请求参数，包含 url, competitor(可选), dimension(可选)
 * @param signal 可选的取消信号
 * @returns 新建的爬虫任务详情
 */
export async function createCrawlJob(req: CreateCrawlJobRequest, signal?: AbortSignal): Promise<CrawlJob> {
  const res = await fetch('/api/crawl/jobs', {
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
  return res.json() as Promise<CrawlJob>;
}

/**
 * 获取单个爬虫任务详情
 * @param id 任务唯一标识
 * @returns 任务详情
 */
export async function getCrawlJob(id: string): Promise<CrawlJob> {
  const res = await fetch(`/api/crawl/jobs/${id}`);
  if (!res.ok) {
    throw new Error(`HTTP Error ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<CrawlJob>;
}

/**
 * 删除爬虫任务
 * @param id 任务唯一标识
 * @param signal 可选的取消信号
 */
export async function deleteCrawlJob(id: string, signal?: AbortSignal): Promise<void> {
  const res = await fetch(`/api/crawl/jobs/${id}`, {
    method: 'DELETE',
    signal,
  });
  if (!res.ok) {
    throw new Error(`HTTP Error ${res.status}: ${res.statusText}`);
  }
}

/**
 * 重试爬虫任务
 * @param id 任务唯一标识
 * @param signal 可选的取消信号
 * @returns 重试后的爬虫任务详情
 */
export async function retryCrawlJob(id: string, signal?: AbortSignal): Promise<CrawlJob> {
  const res = await fetch(`/api/crawl/jobs/${id}/retry`, {
    method: 'POST',
    signal,
  });
  if (!res.ok) {
    throw new Error(`HTTP Error ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<CrawlJob>;
}
