# Competiscope v2 (Plan A) 知识库与爬虫子系统用户指南

本文档作为 **Competiscope v2 (Plan A)** 项目中“知识库（Knowledge Base）”与“爬虫（Crawler）”两大核心子系统的操作指南，旨在帮助开发者与系统操作员理解其核心工作机制、快速部署服务，并执行完整的端到端竞争情报提取任务。

---

## 1. 项目概述 (Project Overview)

**Competiscope v2 (Plan A)** 是一款图驱动（Graph-Driven）的智能竞争情报分析与评估系统。与传统静态的分析平台不同，它以 LangGraph 构建的主 DAG（有向无环图）为流程骨架，利用多 Agent 协同体系在节点内部执行自适应的 ReAct（Reasoning and Acting）循环。系统通过 Schema-First 机制保障数据一致性，并能自动化生成多维度的竞争矩阵和深度分析报告。

作为系统的基石，**知识库（Knowledge Base）** 与 **爬虫（Crawler）** 子系统提供了高精度的信息获取与检索支持。爬虫子系统采用 `httpx` + `trafilatura` 构建并发抓取管道，支持基于 robots.txt 规范的限流与 SSRFGuard 安全校验。它能够将输入的各种爬取源展开为 URL 进行深度抓取和正文结构化提取。

**知识库子系统**采用混合存储架构（Hybrid Storage Layer），将 SQLite（负责文档关系、元数据及 FTS5 稀疏全文索引）与 Qdrant 向量数据库（负责 HNSW 密集向量索引）深度结合。通过基于 `BGE-M3` 模型的混合检索（Dense-Sparse Hybrid Retrieval）和 `BGE-Reranker` 重排序，该子系统为上层 Analyst Agent 提供精准无偏的背景知识与引用源归因支持，确保生成的竞争对比矩阵（Comparison Matrix）百分之百可信。

详细的端到端运行拓扑与时序请参阅 [端到端演示流程设计方案](E2E_DEMO_DESIGN.md)，系统的架构图与模块链路可参阅 [知识库与爬虫子系统架构图](ARCHITECTURE_DIAGRAM.md)。

---

## 2. 快速启动 (Quick Start)

系统推荐通过 Docker 快速启动，也可以使用本地 Conda 环境配合 Makefile 进行精细化开发调试。

### 2.1 Docker 快速启动

Docker 是最便捷的整体运行方式，一键拉起包括前端 Console、FastAPI 后端、Nginx 反代及 Qdrant 向量数据库在内的完整技术栈。

1. **配置环境变量**：
   在仓库根目录下复制配置模板并填入您的 API 凭证。
   ```bash
   cp .env.example .env
   ```
   编辑 `.env` 文件，补充以下关键配置（若无真实 API 凭证，系统将默认降级到 Mock 数据模式运行）：
   ```ini
   # 字节火山引擎 Ark 大模型凭证 (必须)
   ARK_API_KEY=your_ark_api_key
   ARK_MODEL=your_ark_model_endpoint_id
   ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3

   # Perplexity 联网检索凭证 (可选，启用后支持爬虫的 web_search 功能)
   PPLX_API_KEY=your_perplexity_api_key
   PPLX_BASE_URL=https://api.perplexity.ai
   WEB_SEARCH_PROVIDER=perplexity

   # 运行模式
   DEMO_MODE=false
   ```

2. **拉起容器栈**：
   ```bash
   docker compose up --build
   ```
   启动完成后，您可访问以下服务：
   - 整体操作台 (Console)：`http://localhost:8080` (通过 Nginx 统一反代)
   - Qdrant Dashboard：`http://localhost:6333/dashboard`

---

### 2.2 本地 Conda 环境启动 (开发模式)

进行后端开发和性能调优时，推荐使用本地 Conda 环境。

1. **激活 Conda 环境**：
   系统默认使用名为 `bd-competiscope-v2` 的 Conda 环境，请确保您已创建并安装 `pyproject.toml` 中的依赖。
   ```bash
   conda activate bd-competiscope-v2
   ```

2. **启动后端服务**：
   后端基于 FastAPI 框架，使用以下命令在 `http://localhost:8000` 启动运行：
   ```bash
   make dev-backend
   ```

3. **启动前端服务**：
   前端基于 React + Vite + TS，使用 pnpm 启动，运行于 `http://localhost:5173` 并自动反向代理 `/api` 到后端：
   ```bash
   make dev-frontend
   ```

4. **进行 Smoke Test 冒烟测试**：
   为验证本地 API 和网络组件的连贯性，可执行以下冒烟指令（需确保 `.env` 中已写入对应 Key）：
   ```bash
   # 运行离线架构基本检查
   make m0-check

   # 验证 LLM 连接
   make smoke-llm

   # 验证 Perplexity 检索服务
   make smoke-search

   # 验证网页下载及抓取器
   make smoke-fetch
   ```

---

## 3. 知识库工作流 (Knowledge Base Workflow)

知识库的数据生命周期分为“上传/采集”、“段落感知切分”、“混合向量化入库”、“多模态检索”及“召回评估”五个阶段。

```
[ 手动 Upload / 爬虫 Crawl ]
           │
           ▼
┌───────────────────────────────────────┐
│        Ingestion Pipeline             │
│  1. 段落感知切片 (Paragraph Chunking)  │
│  2. BGE-M3 / Hash 向量化生成 (1024D)   │
│  3. Content-Hash 去重校验              │
└──────────────────┬────────────────────┘
                   │
         ┌─────────┴─────────┐
         ▼                   ▼
┌─────────────────┐ ┌─────────────────┐
│   SQLite WAL    │ │  Qdrant HNSW    │
│  元数据与 FTS5  │ │   密集向量库    │
└────────┬────────┘ └────────┬────────┘
         │                   │
         └─────────┬─────────┘
                   ▼
┌───────────────────────────────────────┐
│           Hybrid Retrieval            │
│ 1. Dense (Qdrant) 与 Sparse (FTS5) 并行│
│ 2. 加权 RRF 融合与 BGE-Reranker 重排   │
│ 3. MMR (最大边界相关性) 降重输出      │
└───────────────────────────────────────┘
```

### 3.1 页面操作与上传 (Upload)
在前端 **Knowledge Base** 页面上，操作员可通过弹窗进行单个或多个文档的上传。支持三种源数据导入形式：
- **url**：输入目标网页链接，后端爬虫会在后台异步拉取、解析并入库。
- **text**：直接粘贴纯文本/Markdown 内容，并指定标题。
- **base64**：上传 PDF/Word 等二进制文档，前端将其转化为 Base64 格式发送至后端解析服务。

### 3.2 批量入库机制 (Batch Ingest)
调用批量入库接口 `POST /api/knowledge/batch` 时，后端使用 `IngestionPipeline` 处理：
1. **段落感知切片 (Paragraph-Aware Chunking)**：
   为保持语义的逻辑完整性，切片器不采取机械的字数强切，而是首先识别双换行符 `\n\n` 进行段落分割；随后对于过短的段落进行向上合并，若单段过长（超过 1000 字符），则回退到按句子边界分割，最终维持 Chunk 大小在 500-1000 字符之间。
2. **生成向量表示 (Embedding Generator)**：
   每个 Chunk 通过 `BGE-M3` 编码器生成 1024 维的 Dense Vector。若本地库中未加载 `sentence-transformers` 依赖，系统会优雅降级为具有确定性的 `HashEmbeddingProvider` 以供本地脱机调试。
3. **元数据与全文索引写入**：
   - 将文档元数据与 Chunks 数据异步写入 SQLite 数据库，并将其正文内容同步 Upsert 到 SQLite 的 **FTS5 虚拟全文检索表** 中，用于 Sparse 检索。
   - 将 Chunk ID、向量数组（Vectors）和 Payload（包含所属竞品 `competitor`、所属分析维度 `dimension` 以及 `content_hash` 等）写入 Qdrant。
4. **Content-Hash 去重校验**：
   入库前对整篇文档计算 MD5/SHA256 哈希值，若发现数据库内已存在相同哈希值的激活态文档，则会自动跳过或覆盖，避免垃圾数据膨胀。

### 3.3 爬虫触发 (Crawl)
见第 4 节的爬虫工作流，爬取完成的内容会自动进入上述 Batch Ingest 管道。

### 3.4 混合检索原理 (Hybrid Search)
当收到 RAG 检索请求 `POST /api/knowledge/search` 时：
1. **Dense Vector Search**：使用嵌入模型编码 Query，在 Qdrant 中通过 HNSW 索引查询最相似的 Top-K 向量，结果执行 Min-Max 归一化。
2. **Sparse Keyword Search**：使用 FTS5 的 `MATCH` 语法在 SQLite 中对 Chunk 内容进行关键字快速召回，检索结果同样按照排名进行倒数归一化。
3. **RRF (Reciprocal Rank Fusion) 融合**：
   使用可配置权重对 Dense 和 Sparse 的重合 Chunks 进行融合评分：
   $$RRF\_Score(d) = \sum_{m \in \{dense, sparse\}} \frac{w_m}{k + Rank_m(d)}$$
   其中预设常数 $k=60$。
4. **重排与 MMR (Maximal Marginal Relevance) 降重**：
   若启用了 Reranker（如 `BGE-Reranker-v2-m3`），前 Top-N 的融合结果将送至重排服务提高语义对齐度；随后通过 MMR 计算降低信息冗余，避免返回高度同质化的相邻片段。

### 3.5 评估与分析 (Eval)
见第 6 节的评估接口配置。

---

## 4. 爬虫工作流 (Crawler Workflow)

爬虫子系统基于高效的 `httpx` 异步通信客户端与 `trafilatura` 结构化 HTML 抽取引擎。调度器使用协程信号量（Semaphore）控制单域名与全局的并发上限，以防触发目标站点的反爬封禁；同时，利用 `SSRFGuard` 防御机制，严格禁止爬虫请求内网及受保护的本地 IP 段。

### 4.1 8 种源类型（Source Types）展开逻辑

当配置一种源（Crawl Source）并提交任务时，对应的 **SourceProcessor** 会在爬取前将其自动展开（Expand）为具体待爬的网页 URL 集合。

#### 1. sitemap (站点地图)
- **解析逻辑**：`SitemapProcessor` 会抓取给定的 `sitemap.xml`。通过 ElementTree 递归解析所有的 `<loc>` 标签。如果包含 `<sitemapindex>` 指向子地图，它会递归展开（最大深度 20 层），并最终通过配置中的 `include_patterns`/`exclude_patterns` 正则过滤网页链接，最大输出限制为 `max_urls` (默认 1000)。
- **应用场景**：全面抓取竞品官网的公共页面。

#### 2. rss (新闻源/订阅源)
- **解析逻辑**：`RssProcessor` 抓取 RSS 或 Atom 协议的 XML 订阅源，优先使用 Python 的 `feedparser` 库（无该库时正则回退），读取 `<item>` 或 `<entry>` 节点下的 `<link>`。
- **应用场景**：实时监听竞品的技术博客、官方媒体中心或发布动态。

#### 3. web_search (搜索引擎联动)
- **解析逻辑**：`WebSearchProcessor` 调用 Perplexity 检索 API（支持自定义模型如 `sonar`）。将用户输入的 `query` 发送到 Perplexity 搜索，然后从接口返回的结构化 `citations`（引用链接列表）中提取外部 URL 列表返回。
- **应用场景**：在没有明确竞品网址的情况下进行泛在的网络情报搜集。

#### 4. manual (人工静态指定)
- **解析逻辑**：`ManualProcessor` 最为简单，无网络拓展行为。它直接读取用户填写的 `urls` 数组，将其原封不动地返回为抓取队列。
- **应用场景**：分析师指定的特定对比分析页面、深度研究论文或特定第三方报告链接。

#### 5. pricing (竞品定价监控)
- **解析逻辑**：`PricingPageProcessor` 继承自 `WebSearchProcessor`。如果只配置了 `competitor` 字段，它会自动组装搜索词：`"{competitor} pricing plans enterprise billing"` 并发送 Perplexity 搜索；召回候选链接后，利用定价网址的独有正则（如 `/pricing`, `/plans`, `/billing` 等）进行严格过滤。
- **应用场景**：定期监控竞品的订阅等级、特惠活动与企业版收费变动。

#### 6. official_docs (官方文档采集)
- **解析逻辑**：`OfficialDocsProcessor` 继承自 `WebSearchProcessor`。自动组装搜索词 `"{competitor} official docs documentation API help learn"` 并搜索；随后对链接进行 `/docs`, `/api`, `/documentation` 以及主机名 `docs.*` 的前缀与路径匹配过滤。
- **应用场景**：追踪竞品的开发文档、功能规范和开放能力。

#### 7. changelog (更新日志抓取)
- **解析逻辑**：`ChangelogProcessor` 采用双通道策略。如果配置了 `feed_url`，它首先提取 RSS Feed；同时，使用 Perplexity 搜索 `"{competitor} changelog releases what's new"`，将两路链接合并后通过专属正则 `/changelog`, `/releases`, `/what-s-new` 过滤去重。
- **应用场景**：自动监控竞品产品的更新频次、新增 Feature 和 Bug 修复。

#### 8. review_site (第三方评价采集)
- **解析逻辑**：`ReviewSiteProcessor` 继承自 `WebSearchProcessor`。其核心是把搜索结果链接限制在主流的 SaaS 评价域名内：`g2.com`, `capterra.com`, `trustradius.com`, `getapp.com`。它会拒绝除这些官方评论站之外的所有其他杂乱搜索结果。
- **应用场景**：采集最终用户对竞品的痛点吐槽、功能评分和使用心得。

---

### 4.2 爬虫 API 调用示例

所有爬虫源任务的触发接口统一为：`POST /api/crawl/sources`。

#### Sitemap 示例
```http
POST /api/crawl/sources HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "url": "https://example-competitor.com/sitemap.xml",
  "competitor": "ExampleComp",
  "dimension": "features"
}
```

#### Web Search (Perplexity) 检索示例
```http
POST /api/crawl/sources HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "url": "web_search://?query=Competitor+X+VS+Competitor+Y+feature+matrix",
  "competitor": "CompetitorX",
  "dimension": "integrations"
}
```

#### Pricing 定价监控示例
```http
POST /api/crawl/sources HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "url": "pricing://?competitor=Copilot",
  "competitor": "Copilot",
  "dimension": "pricing"
}
```

---

## 5. RAG 检索预设 (RAG Retrieval Presets)

为了满足不同分析节点对信息精确度与召回面（Recall vs. Precision）的不同倾斜度，系统提炼出三种 RAG 检索参数预设方案（Presets）：

| 预设模式 (Preset) | 检索模式 (`mode`) | Dense 权重 | Sparse 权重 | 重排深度 (`rerank_top_k`) | MMR 多样性 (`mmr_lambda`) | 适用场景 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`general`** (通用探索) | `hybrid` | `1.0` | `1.0` | `8` | `0.0` (不启用) | 宏观行业趋势探索、泛功能大纲查找、产品通识回答 |
| **`pricing`** (定价精细匹配) | `hybrid` (倾斜 Sparse) | `0.4` | `1.0` | `12` | `0.3` (轻度去重) | 提取特定套餐价格、查找计费词汇（如 "API credit"）、分析付费边界 |
| **`comparison`** (对比多样检索) | `hybrid` (倾斜 Dense) | `1.0` | `0.6` | `16` | `0.5` (平衡去重) | 填充竞品功能差异对比矩阵，防止某一竞品的信息完全覆盖窗口 |

### 5.1 通用探索预设 (General)
- **参数组合**：
  ```json
  {
    "query": "用户提问",
    "mode": "hybrid",
    "dense_weight": 1.0,
    "sparse_weight": 1.0,
    "top_k": 20,
    "rerank_top_k": 8,
    "final_top_k": 8,
    "mmr_lambda": 0.0,
    "enable_query_rewrite": true,
    "num_rewrites": 3
  }
  ```
- **配置逻辑**：等权融合 Dense 和 Sparse 的优点。由于使用最大 3 次 Query 改写，能有效避免因分析师提问遣词差异带来的漏检索，适合大多数非敏感的综合概览查询。

### 5.2 定价精细匹配预设 (Pricing)
- **参数组合**：
  ```json
  {
    "query": "定价相关提问",
    "mode": "hybrid",
    "dense_weight": 0.4,
    "sparse_weight": 1.0,
    "top_k": 30,
    "rerank_top_k": 12,
    "final_top_k": 8,
    "mmr_lambda": 0.3,
    "enable_query_rewrite": true,
    "num_rewrites": 1,
    "dimensions": ["pricing"]
  }
  ```
- **配置逻辑**：定价信息多以结构化表格和数字呈现，在 Dense 语义空间中极易发生漂移（例如：“$9”和“$99”的向量表征可能高度相近）。这里大幅提高 Sparse Keyword 的比重，依靠 SQLite FTS5 对精准计费关键词和数字进行锁定。降低 Query 改写次数以防词义漂移，并使用轻度的 MMR 惩罚过滤高度同质化的计费细节段落。

### 5.3 对比多样检索预设 (Comparison)
- **参数组合**：
  ```json
  {
    "query": "跨竞品对比提问",
    "mode": "hybrid",
    "dense_weight": 1.0,
    "sparse_weight": 0.6,
    "top_k": 40,
    "rerank_top_k": 16,
    "final_top_k": 10,
    "mmr_lambda": 0.5,
    "enable_query_rewrite": true,
    "num_rewrites": 4
  }
  ```
- **配置逻辑**：用于生成跨竞品能力对比矩阵。提升 Dense 语义检索权重以发掘不同厂商对同一技术功能的不同描述（同义词召回）。设置深度重排 (`rerank_top_k: 16`) 和中等强度的 MMR 惩罚 (`mmr_lambda: 0.5`)，强制检索结果在代表“高相关性”的同时兼具“来源竞品多样性”，防止因单个站点文档篇幅过大而“霸屏”检索框，确保最终返回的 Top-10 包含多个竞品的比对论据。

---

## 6. 评估 (Evaluation)

为持续监测混合检索组件在面对不同问题集时的准确度，后端提供了 `/api/knowledge/eval` 评估接口。

### 6.1 评测请求 (POST /api/knowledge/eval)

调用评估接口时，需要提交一组标注好的 Labeled Set。每个标注点（Label Item）包含一个检索 Query，以及预期必须召回的 `relevant_doc_ids`（必须命中的文档 ID 集合）或 `relevant_chunk_ids`（必须命中的 Chunk ID 集合）。

#### API 请求示例
```http
POST /api/knowledge/eval HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "top_k": 10,
  "labels": [
    {
      "query": "What are the pricing tiers of Copilot?",
      "relevant_doc_ids": ["doc-copilot-pricing-001"],
      "relevant_chunk_ids": ["chunk-copilot-tier-99"]
    },
    {
      "query": "Does Cursor support offline model execution?",
      "relevant_doc_ids": ["doc-cursor-docs-offline"],
      "relevant_chunk_ids": []
    }
  ]
}
```

#### API 返回结果示例
```json
{
  "id": "e2920275-c54d-4be9-ba18-bc6b4c6e9a03",
  "created_at": "2026-06-07T11:15:00Z",
  "top_k": 10,
  "metrics": {
    "top_k": 10,
    "query_count": 2,
    "recall_at_k": 0.5,
    "mrr": 0.75,
    "ndcg_at_k": 0.612,
    "per_query": [
      {
        "query": "What are the pricing tiers of Copilot?",
        "relevant_count": 2,
        "retrieved_count": 10,
        "matched_count": 1,
        "recall_at_k": 0.5,
        "mrr": 0.5,
        "ndcg_at_k": 0.43
      },
      {
        "query": "Does Cursor support offline model execution?",
        "relevant_count": 1,
        "retrieved_count": 10,
        "matched_count": 1,
        "recall_at_k": 1.0,
        "mrr": 1.0,
        "ndcg_at_k": 1.0
      }
    ]
  },
  "labels": [
    {
      "query": "What are the pricing tiers of Copilot?",
      "relevant_doc_ids": ["doc-copilot-pricing-001"],
      "relevant_chunk_ids": ["chunk-copilot-tier-99"]
    },
    {
      "query": "Does Cursor support offline model execution?",
      "relevant_doc_ids": ["doc-cursor-docs-offline"],
      "relevant_chunk_ids": []
    }
  ],
  "results": [
    {
      "query": "What are the pricing tiers of Copilot?",
      "hits": [
        {
          "chunk_id": "chunk-copilot-tier-12",
          "document_id": "doc-copilot-pricing-001",
          "text": "GitHub Copilot offers Individual ($10/mo), Business ($19/mo)...",
          "score": 0.892,
          "url": "https://github.com/features/pricing",
          "title": "GitHub Copilot Pricing"
        }
      ]
    }
  ]
}
```

### 6.2 核心指标算法说明

1. **Recall@K (召回率)**：
   计算所有匹配的“文档/分块单元”占标注集中标注单元的比例。
   $$Recall@K = \frac{|Matched\_Units\_In\_TopK|}{|All\_Relevant\_Units|}$$
2. **MRR (Mean Reciprocal Rank，平均倒数排名)**：
   衡量第一个正确结果排在第几位。若第一个检索出的正确答案处于第 $r$ 位，则倒数排名为 $1/r$。如果前 K 个结果都未命中，则该查询分数为 0。
   $$MRR = \frac{1}{|Q|} \sum_{i=1}^{|Q|} \frac{1}{first\_rank_i}$$
3. **NDCG@K (归一化折损累计增益)**：
   考量匹配项的“排序位置”是否靠前。前部的命中比深处的命中有更高的权重收益。折损分会根据排名对数衰减。

---

## 7. 端到端演示 (End-to-End Demo - Phase 9.6)

基于 Phase 9.6 优化的“图运行拓扑”，一次完整的“输入 Topic 到生成最终对比矩阵报告”的流程如下：

```
 [用户输入 Topic & 规则]
           │
           ▼
┌──────────────────────────────────────┐
│            1. Planner                │
│  - 联网校验竞品是否存在              │
│  - 提取官网首页, 拆解核心维度        │
│  - 产出结构化 AnalysisPlan           │
└──────────────────┬───────────────────┘
                   │
           [ HITL Interrupt #1 ]  <-- 人工修正 Plan
                   │
                   ▼
┌──────────────────────────────────────┐
│     2. Collector Dispatch (Fan-out)  │
│  - 按 (竞品 x 维度) 分发子协程       │
│  - 独立 ReAct 循环收敛数据           │
│  - 输出原始数据 RawSource[]          │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│           3. Collect Join            │
│  - 内容按 Content-Hash 快速去重      │
│  - 标准化竞品名归属                  │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│      4. Analyst Dispatch (Fan-out)   │
│  - 按 (竞品 x 维度分片) 启动分析     │
│  - 严格引用强校验                    │
│  - 输出 partial CompetitorKB         │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│           5. Analyst Join            │
│  - 汇聚合并为完整的 CompetitorKB     │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│            6. Comparator             │
│  - 执行跨竞品横向分析                │
│  - 产出结构化 ComparisonMatrix       │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│            7. Reflector              │
│  - 自主反思, 对照 Plan 查漏补缺      │
│  - 产生 self-found gaps 修正请求      │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│              8. Writer               │
│  - 确定性模板渲染 Markdown 报告     │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│               9. QA                  │
│  - 自动执行数据一致性校验            │
│  - 产生 QCIssue (带有 redo_scope)    │
└──────────────────┬───────────────────┘
                   │
           [ HITL Interrupt #2 ]  <-- 人工审计 Blockers
                   │
      qc_failed ───┴───► [ 局部 Scoped Redo 窄化重跑 ]
      qc_passed ───► [ 产出最终完美 Report -> END ]
```

### Step 1: Input Topic & Auto-discover
用户在前端 Console 输入一个宏观主题（如 `"Agentic AI IDE"`），且不硬编码竞品。
1. `planner` 节点启动，首先使用大模型配合 `web_search` 工具发现当前市场上最火热的 3 个竞品（如 Cursor, Windsurf, Copilot Workspace）并获取它们的官方域名。
2. 随后输出 `AnalysisPlan`（包含选定的维度、竞品列表和预估复杂度）。
3. 触发 **HITL Interrupt #1**（人机协同中断），运行挂起，等待用户在前端网页对竞品名或评估维度（yaml 技能）进行增删调整。

### Step 2: Collector Dispatch & ReAct Source Collection
用户点击“确认执行”后，流程进入扇出（Fan-out）并行抓取：
1. `collector_dispatch` 根据 Plan 中的 `[竞品 × 维度]` 分发并发任务给各个 Collector 子代理。
2. 每个子代理拥有**完全独立**的 context 隔离空间，在其内部的 ReAct Loop 中，按优先级策略操作：
   - 首先调用 `rag_retrieve` 检查本地知识库是否已有该竞品的当前维度数据（例如 `pricing` 维度）。
   - 若本地数据过期或不全，使用 `web_search` 在网络中广泛搜寻线索。
   - 提取搜索到的网页链接，调用 `crawl_page` 抓取并解析正文。
   - 最后使用 `ingest_document` 将爬取到的新文档实时存回知识库。
3. 收集子代理在 ReAct 循环终止时，产出结构化的 `RawSource[]` 数组。

### Step 3: Collect Join & Dedup
所有的 `RawSource` 在 `collect_join` 节点会合：
- 系统依据 `content_hash` 对全渠道重复抓取网页进行秒级去重。
- 对未匹配到规范竞品名称的碎片化网页进行自动规整与竞品归属映射。

### Step 4: Analyst Dispatch & Inference
数据汇聚完毕后，再次进行扇出分析：
- 按照 `[竞品 × 维度分片]` 派发任务给 Analyst Agent。
- Analyst 子代理在隔离的会话内执行 ReAct 分析推理，依据 `RawSource` 提取能力特性与关键指标。
- 期间调用**引用校验工具 (validate_citations)** 逐字核对推导出的每一个事实结论是否都在 `RawSource` 正文中真实存在（排除幻觉）。
- 输出各自局部的 `CompetitorKB` 片段。

### Step 5: Analyst Join & Matrix Generation
- `analyst_join` 节点接收所有局部 KB 并执行 Schema Reducer 合并。
- 紧接着，进入 **`comparator`** 新增节点，对所有竞品的多维特性进行横向综合比对，最终实例化生成符合 Pydantic 规范的跨竞品 **`ComparisonMatrix`**。

### Step 6: Reflector (自我反思)
- 主动运行 `reflector` 节点。在此节点中，大模型会核对当前的分析产出是否完美契合最初设定的 `AnalysisPlan`。
- 如果发现某一个竞品缺失了特定维度的关键信息（如缺少 pricing 详情），或者某些引用的置信度偏低，它会主动产生 `self-found gaps`。

### Step 7: Writer (最终报告编写)
- `writer` 节点启动，利用确定性的渲染层自动拼装前面的对比矩阵和竞品 KB 事实。
- 随后调用大模型生成高级“高管摘要（Executive Takeaways）”，并移除无引用支撑的幽灵数据（phantom removal），保证整篇报告结构严整。

### Step 8: QA & Scoped Redo
- `qa` 节点对整份报告及对比矩阵进行多层自动化审查（包括 matrix 与 raw_source 的事实核对、跨竞品对比格式检查等）。
- 若检查未通过，QA 节点会生成带有一组 QC 问题（`QCIssue`）的响应，并为每个问题指派一个 **`redo_scope`**（可能的值包括：`writer_only` / `comparator` / `analyst::<slice>` / `collector::<dim>` / `full`）。
- 触发 **HITL Interrupt #2**，允许操作员在页面上直接覆写该 QA 问题，或者让系统依据 redo 范围执行自动重跑。
- **Scoped Redo 窄化重跑**：如果只是竞品 B 的 `pricing` 数据质量不过关，LangGraph 不会回到最开头重跑所有节点，而是自动精准定位至 `collector::<pricing>`，在此分支以 QA finding 为 prompt 重新联网抓取补充数据，再重新走 Analyst 和 Writer 渲染，极大地缩短了纠错耗时，体现了 Plan A 的架构优势。若 QA 通过，则任务输出最终报告，流程结束（END）。

---

## 8. 常见问题排查 (Troubleshooting Common Issues)

### 8.1 Qdrant 向量数据库连接超时或失败
- **故障现象**：启动后端或调用检索时报错 `httpx.ConnectError`，或者日志中出现 `Qdrant connection refused on port 6333`。
- **原因分析**：Docker 容器未成功拉起，或本机的 6333 端口被其他旧版 Qdrant/服务占用，导致容器运行中断。
- **解决对策**：
  1. 运行 `docker compose ps` 查看 `qdrant` 服务状态是否为 `Up`。
  2. 若端口冲突，可在 `docker-compose.yml` 中修改端口映射（例如 `"6340:6333"`），并同步修改后端环境变量中的 `QDRANT_HOST` 与 `QDRANT_PORT`。
  3. 如果是脱机运行，可将环境变量 `KB_EMBEDDING_PROVIDER` 设为 `hash`，此时系统将对向量操作进行离线模拟而不需要 Qdrant 容器服务。

### 8.2 Perplexity (PPLX) 检索返回空链接
- **故障现象**：Collector 的 Web 检索任务没有抓到任何链接，导致分析结果完全缺失，但离线检查均通过。
- **原因分析**：未配置 `PPLX_API_KEY` 或 Key 欠费失效；或者 Perplexity API 访问遭遇国际网络限制导致超时。
- **解决对策**：
  1. 检查根目录下的 `.env` 文件，确认 `PPLX_API_KEY` 是否有效。
  2. 运行 `make smoke-search`。若报错 401，请检查 API Key 拼写与额度。若报错 504，说明网络连接存在瓶颈，请配置 HTTP 代理。

### 8.3 SQLite 数据库被锁定 (`database is locked`)
- **故障现象**：后端日志频繁抛出 `sqlite3.OperationalError: database is locked`，导致分析任务在 `collect_join` 或 `analyst_join` 节点卡死。
- **原因分析**：SQLite 数据库不支持高并发的同时写操作。高并发的 Collector 在同时向 SQLite 提交 ingestion 入库请求。
- **解决对策**：
  1. 系统在初始化 SQLite 时已开启 **WAL 模式 (Write-Ahead Logging)**，若未生效，可手动在 SQLite 客户端执行 `PRAGMA journal_mode=WAL;`。
  2. 确认 `routes/knowledge.py` 中使用了 `_repository_lock = asyncio.Lock()` 进行互斥锁机制，确保没有发生跨进程的无锁并行写。

### 8.4 爬虫没有抓到网页正文 (抓取结果为空或 Null)
- **故障现象**：Crawl Job 的状态是 `completed`，但 document 详情中 `text` 和 `markdown` 均为空白。
- **原因分析**：
  1. 目标站点为单页面应用（SPA），数据完全依赖前端异步 JS 渲染，纯 HTTP GET 无法获取有效数据。
  2. 触发了系统内置的安全策略 `SSRFGuard`（如该 URL 指向内网 IP，或解析到的实际 IP 为本地局域网，或者属于 robots.txt 禁止爬取的路径）。
- **解决对策**：
  1. 检查后台日志是否包含 `SSRF security violation` 或 `RobotsPolicy blocked`。如果是合法的目标站点但被 robots.txt 拦截，可以通过修改 `policy.py` 中的限流和准入规则进行策略宽松处理。
  2. 对于强 JS 依赖的页面，本系统 Phase 2/3 架构中设计了 Playwright 动态渲染服务，此时可通过配置 `CRAWLER_RENDER_JS=true` 启用 Headless 浏览器进行抓取。

---

## 9. Phase 9 高级功能

本章节介绍 Phase 9 引入的三个核心数据治理与可追溯性功能：SimHash 近重复检测、新鲜度权重、以及爬虫运行可追溯性。

### 9.1 SimHash 近重复检测 (SimHash Near-Duplicate Detection)
与传统的强哈希去重（MD5/SHA256，仅能识别字节完全一致的重复文档）不同，系统引入了基于 SimHash 算法的近重复检测机制。
- **工作原理**：对文档进行分词并根据词频计算一个 64 位的指纹（Fingerprint）。通过计算两个指纹之间的汉明距离（Hamming Distance），评估文档的相似度。
- **阈值配置**：汉明距离 $\le 3$ 时，系统判定两篇文档为“近重复”文档。在 Ingestion 阶段，如果检测到近重复文档，系统会根据策略自动合并或跳过，避免知识库冗余。

### 9.2 新鲜度权重 (Freshness & Staleness Weighting)
为了在检索时倾向于最新的情报，系统在混合检索阶段引入了时间新鲜度权重计算。
- **时间衰减函数**：利用时间衰减因子对检索结果的得分进行动态修正。
  $$Score_{fresh} = Score_{original} \times e^{-\lambda \cdot t}$$
  其中 $t$ 为当前时间与文档发布/抓取时间的时间差（天数），$\lambda$ 为可配置的衰减常数。
- **应用场景**：这使得在 `pricing` 和 `changelog` 等时效性要求极高的维度下，最新抓取的情报能够获得更高的排序优先级。

### 9.3 爬取运行可追溯性 (Crawl-Run Traceability)
系统为每一次 Ingestion 的 Chunk 建立了完整的追溯链条。
- **可追溯元数据**：每个入库的 Chunk 均绑定了 `run_id`、`source_type` 以及原始的 `crawl_url`。
- **追溯机制**：在 Agent 执行 RAG 检索并引用相应内容时，分析终端可通过 `run_id` 和 `crawl_url` 一键定位到抓取时的 Frontier 任务状态、抓取时间及原始 HTML 抓取快照，实现事实结论的“闭环验证”。
