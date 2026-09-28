# plan_a 最新状态与优化审计

日期：2026-09-28。审计基线：`main` / `a58ce5d2796c24c30a895f703fdeee2cfabb4925`。

## 1. 拉取与范围

- 已克隆至 `/Users/a1/Documents/ChatGPT/竞品分析优化/plan_a`。
- `git ls-remote --symref origin HEAD` 与本地 HEAD 一致，远端默认分支是 `main`。
- 最新提交时间为 2026-06-23 18:39:38 +0800；获取到的其他远端分支没有比该分支更新的分支头。
- `7fce73b` 已将 RAG KB 优化分支合入 main。后续优化应以 main 为基线，避免再次引入旧分支实现。
- 当前审计包含源码阅读、现有测试、内存数据库故障注入、OpenAPI 对照、端口绑定检查。
- 未修改业务代码。未调用真实收费模型、搜索 API；未启动 Docker 服务；未删除历史代码或用户进程。

仓库体量已经不小：后端非 tests 目录有 330 个 Python 文件，前端 src 有 170 个 TS/TSX 文件。需要优先提高主流程的可靠性与可维护性。

## 2. 当前架构

前端：React 18、TypeScript、Vite、Zustand、React Router。当前为侧边栏加页面路由，没有桌面窗口管理。

后端：FastAPI、LangGraph、Temporal 外层工作流、企业 Postgres 存储、SQLite journal/checkpoint/知识元数据、Qdrant。

主分析链路：

```text
planner → 人工计划审阅 → collector 按竞品 × 维度并行
→ collect_join → survey enrichment → collect QA
→ analyst 按竞品 × 维度并行 → analyst_join → analyst QA
→ comparator → reflector → writer → QA / 人工审阅 / release gate
→ 最小范围 redo 或结束
```

已有证据准入、来源引用、报告结构化生成、局部 redo、报告版本、trace 与质量门禁。这些能力应继续保留。

RAG 存在两条有实际用途的链路：

| 链路 | 用途 | 当前实现 |
| --- | --- | --- |
| `packages/knowledge` | 全局文档 KB、采集入库、知识搜索、collector warm-start | SQLite/FTS、Qdrant 1024 维、可选 embedding/reranker provider |
| `packages/rag` + enterprise | 项目证据缺口召回、证据上下文 | 项目 evidence、384 维 hashing、BM25、启发式排序 |

这两条链路的输入、隔离范围和来源引用不同。应统一 provider 与检索契约，再通过适配器保留各自职责，不能直接删除其中一套。

## 3. 已验证的阻断与缺陷

以下“复现”表示本次实际执行；“源码确认”表示可从调用链明确判断，未进行对应真实服务部署。

### F01 · 前端构建失败：测试 fixture 落后于来源 DTO

优先级：P0。证据：复现。

- `pnpm build` 在 TypeScript 阶段失败，错误 TS2739。
- `frontend/src/features/run-detail/RunReportReviewStudio.test.tsx:12` 的 `coreSource` 缺少 `candidate_origin`、`fetch_method`、`quality_score`、`metadata`。
- 同一 fixture 引发前端测试读取 `metadata.kb_sync` 时异常。
- OpenAPI JSON 本次重新导出与仓库文件一致；该问题是手写来源类型及 fixture 更新不完整，不能概括成所有 API 已漂移。

处理方向：补全 fixture；核查历史数据进入 UI 的边界默认值；核心 DTO 逐步从生成的 OpenAPI 类型派生。

### F02 · Docker backend 与 worker 的 KB/Qdrant 配置不一致

优先级：P0。证据：源码确认。

- `docker-compose.yml` 的 backend 设置 `QDRANT_URL=http://qdrant:6333`、`KB_DB_PATH=/app/runs/knowledge_docker.db`。
- `temporal-worker.environment` 缺少这两项，也未声明依赖 Qdrant。
- `.env.example` 没有提供对应覆盖项。
- `KnowledgeRepository` 默认 `runs/knowledge.db`；`VectorStore` 默认 `http://localhost:6333`。
- Compose 默认 100% 走 Temporal，因此真正执行 collector 的 worker 可能读取另一个 SQLite 文件，并向自己的容器 localhost 请求 Qdrant。

处理方向：backend/worker 共用明确的 KB 路径与 Qdrant 地址；补齐 readiness 与 worker 启动依赖。SQLite 已有跨进程写锁，不应误诊为完全没有并发保护。

### F03 · sparse 检索返回文档开头，遗漏真正命中的后续 chunk

优先级：P0。证据：内存数据库复现。

- `knowledge/retrieval.py:401` 先搜索文档，随后在 `:413` 只取 `chunks[:3]`，没有在 chunk 层根据关键词匹配排序。
- 7 个 chunk 的测试文档，关键词仅在 chunk_index=6；检索返回 `[0, 1, 2]`，`returned_target=false`。
- `collectors/logic.py:662` 的 KB warm-start 明确使用 `mode="sparse"`，因此缺陷影响实际采集主链路。
- 数据库已有 `chunks_fts`，但该检索路径没有利用它。

处理方向：实现带文档状态和竞品/维度过滤的 chunk 级 FTS 召回；文档层搜索保留给文档列表功能。标题匹配与正文匹配分别处理，避免标题命中时随意选开头。

### F04 · 中文检索与中文向量存在缺口

优先级：P1。证据：复现。

- SQLite FTS 使用默认 tokenizer；正文“该产品支持企业级数据保留策略和安全控制。”查询“数据保留”命中 0 条。
- `enterprise/embedding_index.py:11` 的 tokenizer 只匹配 `[a-z0-9]+`；纯中文“企业数据保留策略”的 embedding 非零维度数为 0。
- 这不是所有中文查询都必然失败，但对中文短语和纯中文项目证据存在明确缺陷。

处理方向：FTS 索引与查询使用一致的中文分词/字符 n-gram 方案；扩展中英混合评测。生产检索接入真实语义 embedding，保留离线 provider 用于确定性测试。

### F05 · 向量写入失败后，重试入库不会修复向量

优先级：P0。证据：故障注入复现。

- `knowledge/ingestion.py:65-99` 先提交文档和 chunks，再进行 embedding/Qdrant 写入。
- Qdrant 写入失败后，文档仍然存在。
- 第二次 ingest 在 `:60-62` 因 content hash 已存在直接返回，跳过向量重试。
- 两次入库仅调用向量写入 1 次，第二次返回了 document_id，但未恢复向量索引。

处理方向：区分“文档已存在”与“索引已就绪”。保存 pending/ready/failed 状态；对失败重试复用 chunk ID，幂等补写向量。需覆盖已有无向量文档的重建，避免只修新数据。

### F06 · 默认 embedding/reranker 与模型降级状态容易误导

优先级：P1。证据：源码确认及故障模拟。

- `knowledge/embeddings.py:150` 默认 hash，`knowledge/reranker.py` 默认 hash。
- BGE 加载失败会返回 hash 向量，但外层 `model_version` 仍为 `BAAI/bge-m3`。
- 本次模拟：reported_model=`BAAI/bge-m3`，effective provider 实际为 hash fallback。
- Qdrant collection 名与 1024 维固定，payload 未包含完整 embedding 模型版本；不能在同一索引中无迁移地混用不同模型的向量。

处理方向：报告 requested/effective provider、模型版本、维度和降级原因；生产配置失败应显式报错或降为 sparse 并告知用户。切换模型采用独立 collection/reindex，不直接混写。

### F07 · Temporal 路径丢失用户选择的输出语言

优先级：P0。证据：activity 请求捕获复现。

- `RunCreateRequest` 有 `output_language`。
- `CompetitiveIntelWorkflowInput` 没有该字段；request 转换和 activity 创建 run 时也未转发。
- 实测用户请求 `en-US`，activity 构造的 RunCreateRequest 变成默认 `zh-CN`。

处理方向：沿 request → workflow input → activity → run 补齐语言契约，新增往返测试；Temporal dataclass 新字段要有兼容默认值。

### F08 · 端口自定义不完整，启停脚本可能误杀其他项目进程

优先级：P0。证据：源码确认；本机绑定检查已执行。

- `dev_start.ps1` 接受 FrontendPort，启动 Vite 的参数却只有 `--host`；实际监听继续由 Vite 默认 5173 决定。
- BackendPort 自定义后，脚本没有同步 `VITE_API_TARGET`，前端代理仍可能指向 8000。
- Vite 未设置 strictPort，占用时可能静默换端口，与健康检查和用户看到的地址不一致。
- `dev_start.ps1:119-128`、`dev_stop.ps1:93-102` 把目标端口所有者加入强制结束列表；进程匹配规则也没有充分限定当前仓库路径。
- 本机 127.0.0.1 上的 8000、5173、8080、6333、55432、7233、8233 本次均可绑定，没有证据说明当前存在旧项目占用这些端口。

处理方向：启动入口统一解析端口；明确传入 Vite port/strictPort/API target；启动前检测冲突并报告占用者；只停止当前项目记录的 PID，并校验命令路径。Compose 宿主端口可配置，容器内部端口保持各服务约定。

### F09 · 主 API 与 KB/crawl 请求身份处理不一致

优先级：P1。证据：源码确认。

- `api/client.ts` 有 bearer 与 workspace/user header 处理。
- `api/knowledge.ts`、`api/crawl.ts`、`api/batch.ts` 及相关 store 存在直接 fetch 路径，没有统一该处理。
- 在仅通过前端 bearer 配置、没有认证 cookie 的部署方式下，部分页面会得到 401；SSE 也需要明确 cookie 或流式 fetch 身份方案。

处理方向：复用公共 request 模块，统一 header、204、错误提示、AbortSignal。认证 cookie 路径仍要兼容，不能声称所有现有部署都无法使用。

### F10 · demo smoke 与质量门禁不一致

优先级：P1。证据：复现。

- `smoke_minimal_run.py` 通过：completed、28 个事件、1429 字符报告。
- `smoke_temporal_thin_shell.py` 失败：要求 completed，但实际 completed_with_blockers。
- 使用独立内存 checkpointer 重跑仍复现；blocker 来自 `report_depth_required`，不是已证实的 Temporal 连接故障。

处理方向：为 smoke 构造满足当前深度门禁的确定性 demo fixture；明确“工作流执行成功”与“报告可发布”的断言，保留门禁的阻断测试。

## 4. Agent 流程优化

### 4.1 现有能力应继续使用

- 保留 LangGraph DAG、按竞品和维度的 fan-out、阶段 QA、人工审阅和 scoped redo。
- 保留来源准入、claim/source 引用、结构化报告及 release gate。
- 真实分析主路径不允许模型记忆或模拟访谈作为未标明的事实证据。
- Demo、schema-first writer、Markdown fallback、Temporal、enterprise projection 都有现有调用方，不能按目录名称判废弃。

### 4.2 本轮建议改变

1. 先修 Temporal 语言和 worker 运行环境的契约缺陷。
2. 给 fan-out 和 writer segments 设置明确并发上限，并记录排队时间。当前 graph invoke 未显式设置 max_concurrency；writer segment 直接 create_task/gather 全量启动。
3. 汇总 run/阶段的 LLM 请求数、token、耗时和 repair 次数；使用总预算控制，避免各层局部重试相乘。
4. 将 fallback 结果、缺证据、低置信与降级原因在 run detail 与报告中展示。当前 analyst 默认分支超时 25s，大 fan-out 时降至 8s；需要用 trace 验证该设置的真实质量影响。
5. Collector 以“证据缺口 → 检索候选 → 核验 → 准入”执行；先修 KB sparse 召回再评估 KB 优先策略。
6. 最小范围 redo 按受影响的竞品、维度、来源和章节执行；用质量增量/成本衡量修复收益。

### 4.3 代码体量与遗留入口

| 文件 | 当前行数 | 建议边界 |
| --- | ---: | --- |
| `agents/writer/logic.py` | 6828 | 生成、证据包、章节、repair、发布契约逐步分离 |
| `orchestrator/service.py` | 5054 | lifecycle、trace、redo、projection 逐步分离 |
| `app/routers/enterprise.py` | 3268 | 按 API 领域拆 router，保持 URL 契约 |
| `agents/collectors/logic.py` | 3133 | KB bridge、来源策略、coverage、主分支执行分離 |
| `agents/analysts/logic.py` | 3072 | 结构化抽取、claim 构造、fallback 分离 |

主 DAG 使用 `_real_collector_branch_step`、`_real_analyst_branch_step`。旧 `_real_collector_step` 和 `_real_analyst_step` 仍被测试直接调用，本次检索未发现它们的生产直接调用。属于清理候选，实施前应补调用覆盖检查，迁移旧测试到生产入口，再移除旧实现。

`STATE.md` 仍以较旧分支和日期描述状态；历史文档的验收结果不能替代当前验证。开发辅助脚本和旧文档应标注用途，按引用与运行入口确认后归档。

## 5. RAG 优化顺序

1. 修复 chunk 级 sparse 召回、中文检索和入库重试一致性。
2. 统一 backend/worker 配置和 provider 能力报告；为索引增加模型版本与 ready 状态。
3. 对价格表、条款、安全文档使用结构化切分，保留标题路径、表格行与出处定位。
4. 扩展现有 eval 集合：长文后部命中、中文、别名、价格改动、功能下线、旧 KB 与 live 冲突、索引失败恢复。
5. 使用 Recall@k/MRR/nDCG、引用正确率、陈旧证据误用率、延迟和成本比较 sparse、hybrid、rerank。
6. 根据真实评测确定 embedding/reranker 的生产配置；不以“装了 BGE/Qdrant”视为质量已达标。

检索 API 和工具每次新建 RetrievalService，实例内缓存难以跨请求复用。后续可以引入有生命周期的服务与版本化缓存键，但必须先设计入库、归档、回滚时的缓存失效规则。

## 6. 像素桌面工作台

用户已确认：网页中的像素风桌面工作台，包含应用窗口、任务栏、文件与分析任务。

建议应用入口：研究任务、任务管理器、知识库、证据文件、竞品档案、报告阅读器、检索与采集、设置/活动中心。

- 桌面图标、像素窗口边框、标题栏、任务栏、窗口聚焦、拖动、缩放、最小化、最大化、关闭和恢复。
- 窗口位置、大小和布局可保存；后台分析任务独立于窗口显示状态。
- 关闭任务窗口只关闭显示，任务继续运行。停止任务必须有后端真实取消契约后才显示可用操作。
- 文件管理器映射现有 document/evidence/report/artifact；打开文件能查看内容、原始出处、版本与导出操作。
- 中文正文使用清晰的正常字体；像素字体仅用于短标题、按钮与桌面标识。
- 支持键盘与触摸，移动端使用单窗口模式，减少动画偏好生效。

前置问题：`frontend/src/stores/run.ts` 只有一份 detail/events，`useRunDetailController` 初始化会 reset。多任务窗口不能直接复用现有单例 store，应改为 runId 隔离状态，并提供每任务唯一的 SSE 订阅。

## 7. 本次验证结果

| 检查 | 结果 |
| --- | --- |
| Git 远端默认分支/HEAD 对照 | 一致，a58ce5d |
| 后端检索/provider/versioning/rollback/graph/collector 测试 | 25 passed |
| 后端 agent/边界/redo/身份/KB bridge/writer contract 测试 | 48 passed |
| 前端 TypeScript + build | 失败，RawSource fixture 缺字段 |
| 前端全部测试（本机 Node 26 默认环境） | 98 passed / 14 failed |
| 前端全部测试（关闭 Node 自带 experimental webstorage，使用 jsdom 存储） | 111 passed / 1 failed；剩余为 RawSource fixture |
| OpenAPI JSON 对照 | 一致，128 条 path |
| 目标 knowledge/workflows 模块 Ruff | 通过 |
| minimal demo smoke | 通过 |
| Temporal thin-shell smoke（无服务器） | 失败，报告深度门禁 blocker |
| RAG/语言/provider 故障与边界探针 | 复现 F03/F04/F05/F06/F07 |
| 本机默认服务端口 | 检查时均可绑定 |

验证环境：Python 3.11.15；后端按 pyproject 安装依赖，未安装大型 BGE 模型。前端使用仓库 frozen lockfile；本机 Node 26.3.0、pnpm 11.19.0，仓库 CI 的 Node 配置为 20。Node 26 webstorage 差异已经单独隔离；不能把其 13 项环境失败都记成业务代码缺陷。

没有执行全量后端测试、真实 LLM/search 或 Docker/Qdrant/Postgres/Temporal 部署验收；当前机器没有 docker 命令。上述通过项是相关测试基线，不代表完整生产链路已经可用。

## 8. 推荐方案

| 方案 | 收益 | 代价 | 选择 |
| --- | --- | --- | --- |
| 沿现有架构分期优化 | 复用已有质量、证据与 redo 能力；变更容易逐项验证 | 需要迁移部分旧入口与状态边界 | 推荐 |
| 重写 agent/RAG/前端 | 可重新统一模型 | 现有引用、redo、审阅、发布能力需要重新实现，回归面大 | 暂不采用 |
| 先仅改像素皮肤 | 较快看到视觉变化 | 构建、索引一致性、端口、多任务状态仍会影响使用 | 暂不采用 |

推荐顺序与验收要求见同目录 `2026-09-28-optimization-design.md`。该文件为待确认设计；确认后再实施业务改动。
