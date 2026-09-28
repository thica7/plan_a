# plan_a 分期优化设计草案

日期：2026-09-28。基线：main / a58ce5d。

状态：待用户确认。当前仅完成拉取与审计，未实施业务改动。

## 目标与已确认偏好

提高竞品分析流程的证据质量、稳定性与可维护性；修复 RAG 和运行配置的实际缺陷；将前端改造成可操作的像素桌面工作台。

用户已选定像素风桌面工作台：应用窗口、任务栏、文件与分析任务。

## 方案选择

推荐沿现有架构增量优化。保留 FastAPI、LangGraph、Temporal、React、Zustand 和现有证据/报告模型，每阶段单独通过验收。

其他路径：整体重写需要重建引用、局部 redo、人工审阅、发布门禁；仅做视觉改造无法解决现有构建、入库与多窗口状态问题。两者暂不作为实施方案。

## 第一阶段：工程基线、端口与运行契约

### A1. 恢复前端可验证基线

文件：`frontend/src/features/run-detail/RunReportReviewStudio.test.tsx`、来源兼容边界、前端运行版本文档。

- 补齐来源 fixture 必需字段，并判断历史 API 数据是否需要边界归一化。
- 在项目约定的 Node 环境运行测试；本机 Node 26 差异不通过修改业务状态管理来掩盖。
- 建立 build、前端全部测试、API 类型同步的明确验收命令。

验收：TypeScript/build 成功；前端 112 项现有测试无剩余业务失败。

### A2. 统一 Docker KB 执行环境

文件：`docker-compose.yml`、`.env.example`、`backend/tests/unit/test_temporal_compose.py`、部署文档。

- backend 和 temporal-worker 使用同一 Qdrant URL、KB 数据库路径和明确 provider 配置。
- worker 的依赖包含 Qdrant；readiness 区分服务启动与真正可访问。
- 新配置能解释运行时使用哪个 KB、哪个模型以及是否降级。

验收：结构化解析 Compose 验证两个环境一致；Docker 可用时从实际 worker 执行入库和检索，前端能够查到相同文档。

### A3. 统一端口并收窄进程管理

文件：`scripts/dev_start.ps1`、`scripts/dev_stop.ps1`、`scripts/dev_status.ps1`、`scripts/start.sh`、`scripts/start.ps1`、`scripts/docker_deploy.ps1`、`frontend/vite.config.ts`、Makefile、启动文档。

- 前端传入实际 FrontendPort 与 strictPort；后端端口同步到 VITE_API_TARGET。
- 健康检查和输出地址使用解析后的配置，Compose 宿主端口可覆盖。
- 进程记录保存当前项目 PID、启动命令和路径；停止前核对归属。
- 端口被其他项目占用时明确失败并提示，不直接杀进程或静默换端口。
- Windows 路径使用环境探测或显式参数；Mac/Linux 提供本地启动入口，使用现有工具链。

验收：默认端口和自定义端口均走通；占用端口时明确失败；不终止无关进程；状态命令与实际监听一致。Windows 验收需在可用 PowerShell/Windows 环境执行。

### A4. 修复 Temporal 请求往返

文件：`backend/packages/workflows/models.py`、`service.py`、`activities.py`、`backend/tests/unit/test_temporal_workflows.py`、`test_workflow_service.py`。

- 补齐 output_language，使用兼容默认值。
- 同时核查同一 RunCreateRequest 在 LangGraph 和 Temporal 路径的字段传递。

验收：en-US/zh-CN 从 request 到 activity 创建 run 保持不变；idempotency 和原有 workflow 测试通过。

## 第二阶段：RAG 正确性与可恢复索引

### B1. chunk 级 sparse 检索

文件：`knowledge/repository.py`、`knowledge/retrieval.py`、`test_retrieval_params.py`、新增检索边界测试。

- 使用 chunks_fts 直接召回实际命中的 chunk，保留 active/stale、竞品与维度过滤。
- 标题命中和正文命中独立，保留 document diversity。
- 先覆盖长文尾部命中，再调整 top_k、RRF 和 rerank。

验收：7-chunk 文档尾部关键词被召回；归档/删除/回滚、竞品/维度隔离回归通过。

### B2. 中文索引与混合语义支持

文件：`knowledge/repository.py` 索引迁移、`enterprise/embedding_index.py`、`rag/bm25.py`、检索 eval 数据与 runner。

- 选择索引和查询一致的中文分词或 n-gram；补齐重建旧 FTS 索引的迁移流程。
- 项目 hashing tokenizer 支持中文，作为确定性离线方案。
- 真实语义 provider 与离线 provider 独立声明，避免把 hash 当语义质量结果。

验收：纯中文与中英混合命中案例通过；英文原基线无回退；记录索引重建成本与查询延迟。

### B3. 入库失败恢复

文件：`knowledge/ingestion.py`、`models.py`、`repository.py`、`vector_store.py`、入库/版本化测试。

- 持久化 indexing pending/ready/failed 及有效模型版本。
- 文档存在但索引失败时，重试复用 chunks 补写向量。
- embedding 与 upsert 失败分别记录；不返回误导性的“索引完成”。
- 可重建已有未完成索引的文档；版本、rollback 和新索引状态协同。

验收：第一次向量写入失败、第二次成功时，文档 ID 稳定且确实补写；未就绪文档不被当成 dense ready；状态可查询。

### B4. provider 与检索契约

文件：`knowledge/embeddings.py`、`reranker.py`、`vector_store.py`、`tools/rag_retrieve.py`、`rag/embedder.py`、运行配置与 API DTO。

- 暴露 requested/effective provider、模型版本、维度、降级状态和原因。
- 同一索引只能使用匹配的模型/维度；切模型需 reindex/独立 collection。
- KB 与项目 evidence 通过适配器保留 provenance、project/workspace 范围与引用关系。
- 检索服务缓存若共享，缓存键包含索引版本；入库/归档/回滚显式失效。

验收：模型加载失败不会继续以 BGE 名义报告 hash 向量；稀疏降级可见；切模型不会污染原索引；两个检索入口使用一致的结果契约。

### B5. 实际质量评测

复用 `eval/rag-kb-quality-gate-eval.jsonl`，扩展长文、中文、别名、过期资料、价格和功能变化、索引恢复案例。

每次比较报告 Recall@k、MRR/nDCG、引用正确率、陈旧来源误用、延迟、模型调用数。现有 eval 字段完整性测试继续保留，补充真正执行检索→证据准入→引用的案例。

验收：同一固定语料和查询下可比较 sparse/hybrid/rerank；没有证据的结论仍被标记为不足；改动收益以评测结果记录。

## 第三阶段：Agent 可靠性、成本与遗留入口

### C1. 有界执行

文件：`orchestrator/service.py`、`graph.py`、`config/settings.py`、writer 分段执行、trace/eval。

- 为图 fan-out、LLM 请求、writer segments 设置配置化并发上限。
- 汇总每阶段耗时、请求数、token、重试与修复次数。
- 总预算耗尽时产出可解释的中断/不足状态；已有阶段门禁和 scoped redo 继续生效。
- 复核 analyst 8s/25s 超时策略，使用受控延迟模拟和真实 trace 决定是否调整。

验收：并发上限实际被遵守；失败分支的 trace 可定位；repair 不能无限放大请求数；引用和质量门禁不回退。

### C2. 迁移旧入口与缩小大文件职责

- 先将旧 collector/analyst 测试迁移到 DAG 使用的 branch 入口。
- 确认无生产调用后移除旧整维度路径；不依赖函数名或静态“未引用”直接删除。
- 优先抽出 collector KB bridge、writer 执行预算、redo 和 trace 服务。
- 已在执行的 schema-first writer、Markdown fallback、Temporal、enterprise 和 project RAG 保留兼容。
- 更新 STATE.md 与启动文档；开发辅助脚本按调用清单归档。

验收：生产分支入口测试覆盖旧行为；各阶段结果契约、引用 ID、API URL 和事件类型兼容；不存在失去调用方的孤立实现。

### C3. smoke 与发布门禁一致

- 更新确定性 demo fixture，使 thin-shell 成功案例满足当前 release gate。
- 保留 completed_with_blockers 的独立测试，明确执行完成和可发布的区别。

验收：minimal demo 与 Temporal thin-shell smoke 通过；门禁仍能阻止缺深度或缺证据的报告。

## 第四阶段：像素桌面与真实操作

### D1. 桌面外壳

建议新增 `frontend/src/features/desktop/`，包含 Desktop、DesktopWindow、Taskbar、AppLauncher、应用注册和窗口状态。替换 AppShell 的表现层，继续复用业务视图。

窗口状态包含 appId、instanceId、资源 ID、bounds、focused/minimized/maximized、z-order。布局持久化，不保存密钥或完整报告副本。

默认视觉方向：深青绿色桌面，灰米色窗口，深色像素边框，暖黄色选中状态；短标题使用像素/等宽字形，长报告保持正常中文字体。窗口控制采用清晰的方形按钮，减少圆角和装饰渐变。

### D2. 多任务状态与导航

文件：`stores/run.ts`、`useRunDetailController.ts`、`App.tsx`、业务链接与桌面应用适配。

- detail/events 以 runId 存储，页面控制器接收明确资源 ID。
- 每个 run 只有一个 SSE 订阅；两个分析窗口的事件和报告互不覆盖。
- 路由深链接可打开对应应用与资源，浏览器刷新后能恢复已保存布局。
- 最小化/关闭显示不结束后台 run；不提供尚无后端契约的假停止按钮。

验收：两个 run 并发更新时数据隔离；任务栏恢复、关闭和重新打开正确；既有报告/证据深链接继续可用。

### D3. 应用功能映射

| 桌面应用 | 复用能力 | 应有操作 |
| --- | --- | --- |
| 研究任务 | NewRun / RunDetail | 新建、查看阶段、处理人工审阅、局部 redo |
| 任务管理器 | History / trace / metrics | 活跃任务、阶段、错误、成本、打开任务 |
| 知识库 | KnowledgePage | 文档、chunk、版本、搜索、回滚、入库 |
| 证据文件 | evidence/artifacts | 筛选、预览、出处、质量标记、导出 |
| 竞品档案 | CompetitorLibrary | 竞品范围、关联证据、比较 |
| 报告阅读器 | ReportStudio / ReportView | 阅读、引用定位、版本对比、发布/导出 |
| 检索与采集 | SearchPage / CrawlPage | 搜索、创建抓取、队列状态、失败处理 |
| 设置与活动 | governance/runtime/notifications | 可用设置、语言/主题、活动与提醒 |

仅在后端有真实能力时提供可点击操作。现有顶栏通知入口虽禁用，后端已有 notification API，可接入桌面活动应用；其他占位项按能力清单隐藏或说明不可用。

### D4. API 一致性与交互验收

- 将 KB/crawl/batch/store 的网络请求复用公共身份、错误和取消处理。
- 核心类型从 OpenAPI 派生，增加历史来源数据的适配边界。
- 普通窗口使用非模态语义；人工审阅 dialog 的焦点与层级正确。
- 拖动/缩放不超出可恢复边界；键盘、触摸可操作；移动端切换单窗口。

验收：所有桌面入口能完成真实操作；用户在后端运行或断线时得到准确状态；窗口管理、两任务隔离、来源跳转、认证、刷新恢复、移动端视图通过交互验证；build 与现有测试通过。

## 验证命令与执行约定

后端使用项目虚拟环境，前端使用 frozen lockfile。执行时按阶段补充必要的回归用例，先复现再修复。

```bash
.venv/bin/python -m pytest backend/tests/unit/test_retrieval_params.py backend/tests/unit/test_embeddings.py backend/tests/unit/test_reranker.py backend/tests/unit/test_document_versioning.py backend/tests/unit/test_knowledge_rollback.py backend/tests/unit/test_graph_send.py backend/tests/unit/test_rag_kb_collector_chain.py -q
.venv/bin/python -m pytest backend/tests/unit/test_temporal_workflows.py backend/tests/unit/test_workflow_service.py backend/tests/unit/test_temporal_compose.py -q
.venv/bin/python backend/scripts/smoke_minimal_run.py
.venv/bin/python backend/scripts/smoke_temporal_thin_shell.py
.venv/bin/python backend/scripts/export_openapi.py /private/tmp/plan-a-openapi.json
```

前端在 frontend 目录运行：

```bash
pnpm build
node scripts/test-wrapper.js
```

本机 Node 26 使用 `NODE_OPTIONS=--no-experimental-webstorage` 隔离 jsdom 存储；正式验证按项目记录的 Node 版本执行。Docker/Windows 无法在当前机器验收的项目必须明确记录，不能标记为已通过。

用户确认后，将每个阶段进一步写为具体修改与回归任务，按上述顺序在本任务执行；提交或发布动作单独遵循用户授权。
