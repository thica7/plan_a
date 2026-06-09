# 知识库与爬虫子系统架构图 (Architecture Diagrams)

本文档使用 Mermaid 流程图直观展示 **Competiscope v2 (Plan A)** 知识库和爬虫子系统的核心链路，包含：(a) 完整的 RAG 检索管道，(b) 爬虫源的展开与过滤扩展，以及 (c) 并发网页抓取与结构化入库流程。

详细的接口定义、配置参数以及端到端演示流程请参阅 [知识库与爬虫子系统用户指南](USER_GUIDE.md)。

---

## (a) 完整的 RAG 检索管道 (Full RAG Pipeline)

该图展示了从前端收到 `RetrievalRequest` 开始，如何将密集检索（Dense Retrieval）与稀疏检索（Sparse Keyword Retrieval）结果并行搜集，并最终通过互反排名融合（RRF）、模型重排（Rerank）以及最大边界相关性降重（MMR）返回给 Agent 提示词作为上下文的过程。

```mermaid
graph TD
    UserQuery["用户查询 (RetrievalRequest)"] --> QueryEmbed["查询向量化 (Embedding Provider)"]
    UserQuery --> KeywordSearch["稀疏检索 (SQLite FTS5 MATCH)"]
    QueryEmbed --> VectorSearch["密集向量检索 (Qdrant HNSW)"]
    
    VectorSearch --> NormaliseDense["分数 Min-Max 归一化 (Dense Hits)"]
    KeywordSearch --> NormaliseSparse["分数倒数排名归一化 (Sparse Hits)"]
    
    NormaliseDense --> RRFFusion{"RRF 融合权重计算<br/>(Reciprocal Rank Fusion)"}
    NormaliseSparse --> RRFFusion
    
    RRFFusion --> FilterThreshold["分数阈值过滤 (Score Threshold)"]
    FilterThreshold --> RerankCheck{"是否启用 Reranker?"}
    
    RerankCheck -- 是 --> BGERerank["深度重排序 (BGE-Reranker-v2-m3)"]
    RerankCheck -- 否 --> MMRCheck{"是否开启 MMR 降重?"}
    
    BGERerank --> MMRCheck
    
    MMRCheck -- 是 --> MMRRerank["MMR 多样性计算 (Maximal Marginal Relevance)"]
    MMRCheck -- 否 --> FinalK["Top-K 截断返回 (RetrievalResponse)"]
    
    MMRRerank --> FinalK
```

---

## (b) 爬虫源扩展流程 (Crawler Source Expansion)

该图展示了 `scheduler.py` 与 `sources.py` 中 8 种不同的源类型（Source Types）是如何通过各自特定的 `SourceProcessor` 执行网络检索、协议展开或路径正则映射，将其从抽象定义转换为实体 URL 队列的。

```mermaid
graph TD
    CrawlSource["CrawlSource 原始输入<br/>(POST /api/crawl/sources)"] --> SrcType{"评估源类型 (source_type)"}
    
    SrcType -->|sitemap| SitemapProc["SitemapProcessor"]
    SrcType -->|rss| RssProc["RssProcessor"]
    SrcType -->|web_search| WebSearchProc["WebSearchProcessor"]
    SrcType -->|manual| ManualProc["ManualProcessor"]
    SrcType -->|pricing| PricingProc["PricingPageProcessor"]
    SrcType -->|official_docs| DocsProc["OfficialDocsProcessor"]
    SrcType -->|changelog| ChangelogProc["ChangelogProcessor"]
    SrcType -->|review_site| ReviewProc["ReviewSiteProcessor"]
    
    SitemapProc --> SitemapRead["拉取 xml ➡ 递归展开 loc 链接"]
    RssProc --> RssRead["拉取 Feed ➡ 提取 item/entry 链接"]
    WebSearchProc --> PplxSearch["调用 Perplexity (sonar) 联网搜索"]
    ManualProc --> ManualRead["读取配置中声明的静态 urls"]
    
    PricingProc --> PriceSearch["Perplexity 搜索定价主题 ➡ 匹配 pricing/plans 路径"]
    DocsProc --> DocsSearch["Perplexity 搜索文档主题 ➡ 匹配 docs/api 路径"]
    ChangelogProc --> ChangeSearch["合并 RSS Feed 与 Perplexity 搜索 ➡ 匹配 changelog"]
    ReviewProc --> ReviewSearch["Perplexity 搜索评价主题 ➡ 严格限制第三方点评域名"]
    
    SitemapRead --> RegFilter["正则包含/排除过滤 & SSRFGuard 校验"]
    RssRead --> RegFilter
    PplxSearch --> RegFilter
    ManualRead --> RegFilter
    PriceSearch --> RegFilter
    DocsSearch --> RegFilter
    ChangeSearch --> RegFilter
    ReviewSearch --> RegFilter
    
    RegFilter --> UrlQueue["待抓取 URL 队列"]
```

---

## (c) 结构化入库流程 (Ingestion Flow)

该图展示了网页 URL 经过并发管理器，执行 Robots 协议及安全准入检查，完成 HTML 内容的下载、解析和正文提取，随后通过段落感知分块，生成多维度密集向量，最终并行存入 SQLite 关系全文检索数据库和 Qdrant 向量数据库的闭环。

```mermaid
graph TD
    URLQueue["待抓取 URL 队列"] --> ParallelCrawl["并发调度器 (Semaphore 限流)"]
    ParallelCrawl --> Fetcher["Fetcher HTTP 抓取器"]
    Fetcher --> SSRFCheck{"SSRFGuard 校验与<br/>robots.txt 限速校验"}
    
    SSRFCheck -- 通过 --> HttpxFetch["httpx 异步抓取 HTML 页面"]
    SSRFCheck -- 阻断 --> DropUrl["丢弃 URL 并记录错误"]
    
    HttpxFetch --> TrafilaturaParse["trafilatura 正文 Markdown 提取"]
    TrafilaturaParse --> HashCheck{"计算内容 Content-Hash<br/>去重校验"}
    
    HashCheck -- 重复 --> DropDup["跳过并使用缓存/覆盖入库"]
    HashCheck -- 新文档 --> ParagraphChunk["段落感知切片器 (Paragraph-Aware Chunking)<br/>- 双换行段落分割<br/>- 短段向上合并 / 超长句回退"]
    
    ParagraphChunk --> EmbedBatch["批量向量生成 (BGE-M3 Provider)"]
    EmbedBatch --> ConcurrentWrite{"并发并行写入"}
    
    ConcurrentWrite --> SQLiteWrite["写入 SQLite 元数据 & chunks 表"]
    SQLiteWrite --> SQLiteFTS5["写入 SQLite chunks_fts 虚拟全文检索表"]
    
    ConcurrentWrite --> QdrantWrite["Qdrant Vector Store Upsert 向量与 Payload"]
    
    SQLiteFTS5 --> Complete["入库就绪，用于 RAG 检索"]
    QdrantWrite --> Complete
```
