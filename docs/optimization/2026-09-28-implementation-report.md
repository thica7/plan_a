# plan_a 优化实施报告

日期：2026-09-28。分支：`codex/optimization-desktop`。基线：`main/a58ce5d`。

本轮已按用户确认的“工程与端口 → RAG → Agent → 像素桌面”顺序完成本地实现。改动位于独立分支；没有推送、合并或发布。

## 实际交付

| 模块 | 已实施 | 主要入口 |
| --- | --- | --- |
| 运行与端口 | backend/worker 共用 Qdrant 与 KB 路径；Qdrant readiness；自定义端口传入 Vite/代理并启用 strictPort；项目 PID 归属校验，只报告外部端口占用者 | `docker-compose.yml`、`scripts/dev_runtime.py`、`frontend/vite.config.ts` |
| RAG | chunk 级 FTS 召回、中文 bigram、向量索引状态及失败重试、按模型/维度/版本隔离检索、provider 降级诊断、重建 API | `backend/packages/knowledge/`、`backend/packages/enterprise/embedding_index.py`、`backend/app/routes/knowledge.py` |
| Agent | Temporal 输出语言往返；LangGraph fan-out、LLM 与 writer 分段并发上限；run 级调用/修复预算与 trace；删除只在旧测试调用的整维度 collector/analyst 路径；确定性 demo 满足现行门禁 | `backend/packages/orchestrator/`、`backend/packages/llm/execution_budget.py`、`backend/packages/agents/` |
| 前端 | 像素桌面、窗口/任务栏/应用入口、窗口位置与大小恢复、任务 `runId` 状态隔离、同任务共享 SSE、项目证据/报告/附件文件管理器、统一 API 身份、设置与错误状态 | `frontend/src/features/desktop/`、`frontend/src/stores/run.ts`、`frontend/src/api/http.ts` |

文件管理器直接读取现有项目 evidence、report version 和 artifact；知识、检索、采集、竞品、报告和活动应用复用现有业务页面。窗口关闭只停止该窗口订阅，后端运行继续。任务栏或任务管理器可再次打开任务。尚无可信的后端取消契约，因此没有放置假的“停止分析”按钮。

已移除前端无生产引用的旧 AppShell、Sidebar、Topbar、nav 及其旧测试。`_real_collector_step` 与 `_real_analyst_step` 的旧整维度路径也已迁移测试并移除。Demo graph、schema-first writer、Markdown fallback、Temporal thin shell、enterprise projection 与两套不同范围的 RAG 仍有生产或测试契约，按引用检查后保留。

## 检索质量的可重复证据

同一固定离线语料与 14 个查询，使用 deterministic hash provider、`top_k=3`，无收费模型调用：

| 检索模式 | 变更前 Recall@3 | 变更后 Recall@3 | 变更前 MRR | 变更后 MRR |
| --- | ---: | ---: | ---: | ---: |
| sparse | 0.643 | 0.857 | 0.571 | 0.714 |
| hybrid | 0.857 | 0.929 | 0.821 | 0.893 |
| rerank | 0.929 | 0.929 | 0.857 | 0.857 |

这套数据覆盖长文尾部、中文、旧 KB 与 live 冲突、别名及索引恢复。两个报告均记录逐查询命中、引用、延迟与来源准入：

- `docs/optimization/rag-eval-baseline-2026-09-28.json`
- `docs/optimization/rag-eval-2026-09-28.json`

本次三种模式在这套样本上的引用正确率均为 1.0、陈旧来源误用 0、scope leak 0；样本较小，不能推断真实生产语义检索质量。延迟毫秒数只作本机观察，不作为线上性能结论。评测入口为 `python -m packages.knowledge.benchmark`，可固定 `--top-k` 和 `--output`；`--legacy-sparse` 复现旧路径用于对照。

## 验证

| 检查 | 本机结果 |
| --- | --- |
| 全量后端 tests | `1441 passed, 1 skipped`；含安全 PID 测试，读取测试自建进程信息时使用沙箱外批准运行 |
| contract + integration + replay | `7 passed, 1 skipped`；真实 Postgres RLS 测试缺数据库 URL，按设计跳过 |
| 前端全量测试 | `120 passed`；Node 26 测试入口自动隔离实验性 webstorage |
| 前端生产构建 | `pnpm build` 通过，TypeScript + Vite 均成功 |
| 前端交互审计 | `pnpm verify:interactions` 通过；0 错误、87 条历史过渡警告 |
| CI 指定 Ruff 文件 | 通过；修复相关文件及一处旧测试 fixture 的已有 lint 问题 |
| OpenAPI | 重新生成，130 条路径；导出 JSON 与仓库文件一致 |
| secret scan | 通过 |
| minimal demo smoke | completed，28 个事件，5820 字符报告 |
| Temporal thin-shell smoke | completed，31 个事件，2 份证据、2 条 claim |
| 工程端口与 PID 回归 | 20 passed（dev_runtime 16 + Temporal compose 4）；包括对测试自建进程的归属校验和停止；任务状态不可读时拒停 |

前端曾在浏览器中完成宽屏桌面、窗口最大化、最小化后打开知识库的视觉检查。之后浏览器工具的 URL 安全策略拒绝再次打开本地预览，故最终文件管理器和移动端样式没有得到新的浏览器视觉验收；使用组件交互测试、构建和 CSS 容器响应规则补充验证。被拒绝的是浏览器访问本地 URL，原因是浏览器 URL 安全策略；未尝试绕过。

全仓库 Ruff 仍有约 189 处既有格式/长行问题，本轮确保 CI 指定文件和新增核心模块通过；未为消除无关 diff 对所有旧文件批量格式化。FastAPI `on_event` 旧写法产生弃用警告，未影响本轮测试结果。

## 尚需外部环境验收

1. **Docker/Windows**：当前 Mac 没有 Docker 或 Windows/PowerShell，无法运行真实 Compose worker/Qdrant/Postgres/Temporal 和 Windows CIM 启停。工程验收记录见 `2026-09-28-engineering-verification.md`。正式部署前执行容器健康、跨 worker 入库检索与端口冲突演练。
2. **真实模型**：默认 hash embedding/reranker 是确定性离线方案。生产需配置所选模型，并在真实竞品语料上比较 Recall、引用正确率、陈旧证据率、成本和延迟。BGE 加载失败会显式报告 hash 降级，不能把 hash 结果当 BGE 质量。
3. **存量向量**：SQLite 旧 KB 文档迁移后为 `pending`，须按文档调用 reindex API；项目级 Postgres evidence 也需在新 hashing 模型下重建。查询只使用当前模型/维度，重建前可召回条目会减少。
4. **旧前端控件**：交互审计还有 87 条过渡警告，相关文件级 allowlist 延至 2026-12-31；新增桌面控件已直接标注操作契约。旧 shell 样式与部分历史 i18n 字符串还留在代码中，待可视回归环境逐步清理。
5. **全局 KB 范围**：全局 KB 与项目 evidence RAG 仍分开；前者用于可复用知识，后者按 workspace/project 隔离。若要把私有手动文档放进全局 KB 并开放给多个租户，应先设计文档级 workspace 隔离，不能把目前的全局索引视为私有空间。

以上限制属于真实服务和环境验收，代码与本地可运行验证已完成。改动尚未推送远端。
