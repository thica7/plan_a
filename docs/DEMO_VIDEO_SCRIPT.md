# Competiscope v2 Phase 9 演示视频脚本

本文档用于录制或现场讲解 Phase 9 端到端演示。脚本目标是用 6 到 8 分钟展示系统如何从一个宏观主题出发，自动发现竞品、抓取多源证据、写入知识库、执行混合检索，并通过 QA 与评估指标证明结果可信。

## 0. 录制准备

启动服务：

```bash
cp .env.example .env
docker compose up --build
```

如需真实联网与 LLM 能力，在 `.env` 中配置：

```ini
ARK_API_KEY=your_key
ARK_MODEL=your_model_or_endpoint_id
DEMO_MODE=false
PPLX_API_KEY=your_perplexity_key
WEB_SEARCH_PROVIDER=perplexity
```

录制前确认：

- Console 可访问：`http://localhost:8080`
- Qdrant Dashboard 可访问：`http://localhost:6333/dashboard`
- 后端健康检查通过：`http://localhost:8000/api/health`
- 知识库页面、爬虫页面、Run Detail 页面均可打开

## 1. 开场镜头：输入主题

画面：New Run 页面。

旁白：

> 这是一套图驱动的竞争情报系统。我们不手动输入竞品清单，只给系统一个宏观主题，例如 Agentic AI IDE。Planner 会自动发现直接竞品，并生成需要采集的维度。

操作：

1. 在主题输入框输入 `Agentic AI IDE`
2. 选择 Real API 或 Demo Mode
3. 点击创建分析任务

## 2. 自动竞品发现与 HITL 审核

画面：Run Detail 页面，SSE 事件流开始滚动，Plan 审核弹窗出现。

旁白：

> Planner 节点完成后，系统进入第一次 HITL 中断。这里展示的是自动生成的竞品、维度和采集计划。演示者可以删除无关竞品，加入本地 mock 竞品，也可以调整 pricing、feature、integration 等分析维度。

操作：

1. 展示自动发现的竞品列表
2. 展示分析维度
3. 点击 Approve & Proceed

## 3. 多源爬虫展开

画面：Crawler 页面或 Run Detail 的 crawl progress 区域。

旁白：

> Phase 9 扩展了爬虫源类型。除了 sitemap、RSS、web search 和 manual URL，现在还支持 pricing、official docs、changelog 和 review site。每类源会被专门的 processor 展开成 URL 队列，并通过 SSRFGuard、robots 和正则过滤进入 Frontier。

操作：

1. 展示 source type 下拉或 API payload
2. 切换到 Frontier 统计
3. 展示 queued、running、succeeded、failed 状态变化

推荐画面点：

- pricing 源匹配 `/pricing`、`/plans`、`/billing`
- official_docs 源匹配 `/docs`、`/api`、`/help`
- review_site 源限制到 G2、Capterra、TrustRadius、GetApp 等站点

## 4. 知识库增长与治理

画面：Knowledge 页面。

旁白：

> 抓取成功的网页会立刻进入 ingestion pipeline。系统会抽取正文、切片、写入 SQLite FTS5 和 Qdrant，同时记录 crawl run。Phase 9 还加入了 SimHash 近重复检测和 freshness 权重，让旧文档、重复文档不会污染检索结果。

操作：

1. 展示文档数和 chunk 数变化
2. 打开某条文档详情或版本信息
3. 展示 crawl run 或来源 metadata

## 5. 混合检索与引用追溯

画面：Search 或 RAG 检索抽屉。

旁白：

> 检索不是单一路径。系统会并行执行 Qdrant dense retrieval 和 SQLite sparse retrieval，再通过 RRF 融合、reranker 重排和 MMR 降重输出结果。Phase 9 新增了 retrieval presets，可以针对 pricing 或 comparison 场景切换不同参数。

操作：

1. 输入查询：`What are the entry-level pricing plans for Cursor and Windsurf?`
2. 选择 `pricing` preset
3. 展示返回 chunks、分数、引用 URL
4. 点击 citation 查看原始来源

## 6. QA 缺陷与局部重跑

画面：Run Detail 的 QA 或 revision 区域。

旁白：

> 如果 QA 节点发现某个报告块证据不足，系统不会从头重跑。它会生成 QCIssue，并把 redo scope 精确定位到对应节点和维度，例如 `collector::pricing`。这让修复成本更低，也保留了已有正确结果。

操作：

1. 展示 QA issue
2. 展示 scoped redo 范围
3. 点击确认后展示新的 SSE 事件流

## 7. RAG 评估

画面：Knowledge Eval 或终端。

旁白：

> 最后我们用 30 条标注查询评估检索效果。这些 query 覆盖 pricing、feature、user review 和 comparison 四类竞争情报问题。系统会计算 recall@k、MRR 和 nDCG@k，用指标说明 RAG 质量，而不只依赖主观观感。

操作：

1. 展示 `eval/competitor-analysis-eval.jsonl`
2. 运行或展示评估结果
3. 解释四类 query 的覆盖范围

## 8. 收尾镜头

画面：报告页、架构图或 README。

旁白：

> 至此，一次竞争情报任务完成了从主题输入、自动发现、证据抓取、知识治理、混合检索、QA 重跑到量化评估的闭环。Phase 9 的价值在于把 crawling 和 KB 从附属能力升级为可治理、可追踪、可评估的核心数据链路。

## 推荐时间分配

| 段落 | 时长 |
| --- | --- |
| 开场与主题输入 | 45 秒 |
| Planner 与 HITL | 60 秒 |
| 多源爬虫 | 90 秒 |
| KB 治理 | 75 秒 |
| 混合检索 | 90 秒 |
| QA 重跑 | 60 秒 |
| RAG 评估与收尾 | 60 秒 |

## 备用话术

- 如果真实 API 不稳定：说明当前使用 Demo Mode，但数据流、事件流和治理逻辑与真实模式一致。
- 如果目标站点 robots 拒绝：强调这是安全策略生效，系统会记录失败并走 fallback，而不是强行抓取。
- 如果检索结果不足：切换 `pricing` 或 `comparison` preset，展示参数如何影响召回和多样性。
