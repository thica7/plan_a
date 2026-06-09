# RAG KB Crawler 接入与后端性能优化说明

## 接入方式

当前 crawler/knowledge 链路继续负责采集网页、写入 KB SQLite 和 chunk 表；enterprise/RAG 链路继续消费 `EvidenceRecord`。本次新增桥接层，把 KB 文档和 chunk 投影成项目级证据，不改变原有采集流程，也不要求重新抓取网页。

同步接口：

```http
POST /api/enterprise/projects/{project_id}/evidence/kb-sync
```

后台同步接口：

```http
POST /api/enterprise/projects/{project_id}/evidence/kb-sync/jobs
GET  /api/enterprise/projects/{project_id}/evidence/kb-sync/jobs/{job_id}
```

同步指标接口：

```http
GET /api/enterprise/projects/{project_id}/evidence/kb-sync/metrics
```

常用请求体：

```json
{
  "crawl_run_id": "crawl-run-1",
  "competitors": ["Acme"],
  "dimensions": ["pricing"],
  "source_types": ["webpage_verified"],
  "limit": 200,
  "offset": 0,
  "snippet_chars": 500,
  "full_text_chars": 6000,
  "max_selected_chunks": 8,
  "metadata_keys": ["published_at"],
  "force_resync": false,
  "reindex_embeddings": false,
  "reindex_max_documents": 500,
  "delay_seconds": 0
}
```

## 已落地的后端性能优化

1. SQLite 过滤下推：同步按 `crawl_run_id`、竞品、维度、来源类型和分页条件在 repository 层过滤，避免全库搬到 Python 内存再筛。
2. 复合索引：新增 `chunks(crawl_run_id, document_id)`，提升按采集批次同步时的 chunk 定位速度。
3. 同步水位：新增 `evidence_sync_state`，用 KB 文档 ID 和 `content_hash` 判断是否变化；默认跳过未变化文档。
4. 稳定 evidence ID：`EvidenceRecord.id` 使用 workspace、project、KB 文档 ID 和内容 hash 生成，重复同步覆盖同一条证据。
5. 批量 upsert：`EnterpriseStore` 增加批量 evidence 写入；内存版减少锁竞争，Postgres 版复用同一连接和事务。
6. 后台 job：新增 `kb-sync/jobs`，可把大批量同步放到后台执行，避免长请求占用 HTTP 生命周期。
7. 错峰执行：后台 job 支持 `delay_seconds`，可避开 crawler 写入高峰，降低 SQLite 锁竞争。
8. 正文截断：`full_text_chars` 控制写入 evidence metadata 的正文长度，避免长网页放大存储和索引成本。
9. chunk 精选：`max_selected_chunks` 控制进入 evidence 的 chunk 数量，并按标题、竞品、维度关键词和长度做轻量打分，减少无关内容进入 RAG 检索。
10. metadata 白名单：默认只保留 robots、状态、语言、发布时间等安全字段；可用 `metadata_keys` 显式增加字段。
11. embedding 重建限流：默认使用增量索引；只有设置 `reindex_embeddings=true` 且本批未超过 `reindex_max_documents` 时才全量重建项目 embedding。
12. 同步指标：新增 `evidence_sync_metrics`，记录耗时、文档数、chunk 数、跳过数、索引数、重复数和错误信息。

## 推荐使用方式

常规增量同步：

```json
{
  "crawl_run_id": "crawl-run-1",
  "limit": 200
}
```

大批量后台同步：

```json
{
  "crawl_run_id": "crawl-run-1",
  "limit": 1000,
  "delay_seconds": 30
}
```

修复或强制重同步：

```json
{
  "crawl_run_id": "crawl-run-1",
  "force_resync": true,
  "reindex_embeddings": true,
  "reindex_max_documents": 500
}
```

## 仍建议后续演进

1. 把进程内后台 job 替换为 Temporal 或队列 worker，跨进程部署时更稳。
2. 为 Postgres 批量 upsert 进一步合并 audit 写入，减少高频同步时的 audit 行数。
3. 后续可把当前轻量 chunk 打分升级为摘要模型或 BM25/向量混合精选。
4. 把同步指标接入统一 metrics/trace 面板，便于观察同步吞吐和错误率。

## 不包含范围

本说明只覆盖 RAG KB crawler 采集接入和后端性能优化，不展开门禁质量策略，也不涉及前端系统改造。
