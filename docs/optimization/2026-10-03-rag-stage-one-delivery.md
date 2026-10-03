# RAG 第一阶段交付说明

日期：2026-10-03。仓库：`thica7/plan_a`。交付分支：`codex/pastoral-desktop`。

本阶段实现提交：`68e100f`。交付文档随该分支提交。用户已授权推送 GitHub；本次交付保留开发分支，不合并 `main`。

## 1. 本次交付解决什么

产品调研应复用可回查的原始资料，并区分产品型号、市场、来源时间与资料归属。本阶段完善已有 SQLite / Qdrant 知识链的存储与检索契约，为各 Agent 后续共享证据建立基础。

| 交付项 | 实际行为 | 主要代码 |
| --- | --- | --- |
| 完整正文持久化 | 清理后的抓取正文入库；Agent 继续接收短片段与引用；摘要不能覆盖全文 | `backend/packages/agents/collectors/kb_bridge.py`、`backend/packages/knowledge/ingestion.py` |
| 工作区与项目隔离 | 服务端授权注入范围，SQLite 在 LIMIT 前过滤，Qdrant 在 top_k 前过滤 | `backend/app/knowledge_access.py`、`backend/packages/knowledge/repository.py`、`backend/packages/knowledge/vector_store.py` |
| 产品与来源约束 | 检索保留完整型号、市场、资料角色和来源出版 / 更新 / 核验时间 | `backend/packages/knowledge/models.py`、`backend/packages/knowledge/retrieval.py` |
| 缓存与索引一致性 | 按范围和模型索引契约隔离缓存，命中回读当前版本 / hash / 活动状态 | `backend/packages/knowledge/retrieval.py` |
| 抓取与后台任务接线 | 保存可信归属；删除或取消后的抓取不能再次发布正文或新子任务 | `backend/packages/crawler/`、`backend/app/routes/crawl.py` |
| 知识接口与企业同步 | 列表、详情、版本、回滚、任务和同步遵循同一范围；旧报告不升格为实时事实 | `backend/app/routes/knowledge.py`、`backend/app/routers/enterprise.py` |
| 前端引用回查 | 项目资料、公共库和未知归属分别处理；详情、版本操作与上传轮询保持原范围 | `frontend/src/pages/KnowledgePage.tsx`、`frontend/src/features/version/VersionDrawer.tsx` |
| 旧索引清理 | 初始化幂等移除旧全库唯一索引，保留范围内唯一约束 | `backend/packages/knowledge/repository.py` |

范围隔离属于数据访问控制，不能靠模型提示词代替。检索相关度也不等同于事实已核验。

## 2. 验收依据与边界

第一阶段最终记录：后端 **2317 项通过、1 项跳过**；前端 **51 个文件 / 250 项通过**；TypeScript 和 Vite 构建通过；OpenAPI JSON 与生成类型逐字同步。规格、质量和最终集成审查全部放行。

- 跳过项需要独立 PostgreSQL RLS 测试环境 `ENTERPRISE_RLS_SMOKE_DATABASE_URL`。
- 后端的 152 条提示属于既有 FastAPI `on_event` 弃用提示。
- 真实 Qdrant 本地持久化测试覆盖写入、过滤、重开、版本切换和删除；测试使用离线 hash embedding。
- 各测试禁用本地 `.env`，使用临时数据库，没有调用付费模型或搜索服务。
- Linux / macOS OpenAPI 同步脚本已实际执行；PowerShell 版本未在本机执行。
- 本次交付前重新运行完整后端：**2317 通过、1 跳过、152 条既有提示，50.55 秒**；详细过程与问题修复见[验收记录](2026-10-02-rag-stage-one-results.md)。

本地持久化测试证明客户端适配和过滤行为，**没有完成 HTTP Qdrant 服务部署验收或真实语义检索质量验收**。

## 3. 获取与启动

```bash
git clone --branch codex/pastoral-desktop https://github.com/thica7/plan_a.git
cd plan_a
```

若已有仓库，先保存自己的未提交改动，再获取并切换该分支：

```bash
git fetch origin
git switch codex/pastoral-desktop
git pull --ff-only
```

依赖安装、完整服务启动和端口管理见[仓库 README](../../README.md)及[Docker 部署说明](../docker_deployment.md)。完整开发脚本依赖 Docker、PostgreSQL、Temporal 和 Qdrant；本次验收机器没有启用这套服务。

### 不依赖 Docker 的界面演示

在安装了项目 Python / 前端依赖的仓库根目录，分别打开两个终端：

```bash
# 终端 1：演示 API，不加载本地凭据
COMPETISCOPE_LOAD_ENV_FILES=0 DEMO_MODE=true ENTERPRISE_STORE_BACKEND=memory \
RUN_ORCHESTRATION_BACKEND=langgraph TEMPORAL_TRAFFIC_PERCENT=0 \
.venv/bin/python -m uvicorn app.main:app --app-dir backend \
  --host 127.0.0.1 --port 8000
```

```bash
# 终端 2：前端
pnpm --dir frontend dev --host 127.0.0.1 --port 5173 --strictPort
```

访问 `http://127.0.0.1:5173/`。演示模式使用合成数据，不能据此判断真实产品报告质量。端口占用时先检查进程归属，或显式选择其他端口；不要停止不属于本项目的服务。

### 当前机器的真实服务

当前工作区后端使用 8000，前端使用 5173。真实服务会加载本机已有配置；凭据不写入交付文档、Git 或浏览器参数。启动 API 不等于调用模型；完整真实报告需要另行验收。

`GET /api/health` 的 HTTP 状态为 200，但当前汇总为 `error`：既有 Phase 4 检查要求 Temporal，实际后端是 langgraph，本机 7233 也没有 Temporal。这是明确保留的运行配置问题，不能把该 HTTP 200 当成全环境健康。

## 4. 运行数据与升级注意事项

更新前已用 SQLite backup API 保存：

```text
runs/backups/knowledge-pre-rag-stage-one-20261003T033554Z.db
```

备份为本机忽略的运行数据，不随 GitHub 分支分发。最新服务启动后核对数据库完整性为 `ok`，**132 条原资料的全部原字段与备份一致**。

- 124 条旧资料的工作区未知，继续隔离保留。
- 另外 8 条属于其他范围；当前默认工作区公共库显示 0 条，是隔离结果。
- 不通过修改默认范围、放宽接口授权或批量填入当前工作区来让旧资料重新出现。
- 确认归属和补索引需要后续受控迁移工具，以及迁移前备份、预览、结果审计。
- 同一运行库应使用最新后端，避免旧进程重新创建全库唯一索引。

本阶段没有改变旧资料的正文、来源 URL、版本或时间。曾被旧进程错误归档的一条资料，已按备份恢复原活动标志。

## 5. 建议核对步骤

| 操作 | 预期结果 |
| --- | --- |
| 打开企业工作台与知识库 | 中文界面正常；当前无项目 / 无可见资料时显示空状态 |
| 查看运行列表 | 当前机器原有 7 条运行仍可读取 |
| 在未授权项目范围请求资料 | 服务端返回 404，不暴露其他范围数据 |
| 打开具有可信项目归属的新资料引用 | 详情、分块与版本操作沿用引用的项目范围 |
| 同 URL / 正文分别保存到不同合法范围 | 各自独立存在；范围内仍执行去重 |
| 当前成功抓取一篇带历史价格日期的旧页面 | 保留原事实日期，不能把价格宣称为当前价格 |

删除、回滚与上传的权限行为已在临时库回归中验证。真实库人工核对优先使用只读操作，不为演示删除原资料。

## 6. 尚未交付与下一阶段

| 剩余项 | 下一步 |
| --- | --- |
| 全 Agent 共享证据版本 | 保存每次运行的证据快照，按职责选择有预算的事实与片段，并按证据 ID 回查 |
| 中文 / 跨语言语义召回 | 接入真实 embedding / reranker，独立新索引，不混用旧 hash 空间 |
| 检索质量证明 | 至少 50 条人工标注保留查询，覆盖型号、市场、时间、无答案和跨范围拒绝 |
| 旧资料归属与补索引 | 提供预览、明确授权范围、迁移结果审计；不自动共享未知旧资料 |
| 完整联网与历史报告复用 | 同任务成对验收，比较正确性、来源、token、耗时和外部请求量 |
| HTTP Qdrant 与 Temporal 环境 | 单独部署及验证；本地适配测试不代替环境验收 |

下一阶段优先实现共享证据快照：Collector 生成一份可信资料 / 事实清单，Analyst、Comparator、Writer 和 QA 读取同一版本；事实更正产生新版本，并定位需重新处理的依赖。全文继续保存在资料库，按 Agent 职责选短片段，控制提示 token。

## 7. 文档索引

- [RAG 升级设计](2026-10-02-rag-evidence-design.md)：整体方案、Agent 职责和验收目标。
- [第一阶段计划](2026-10-02-rag-stage-one-plan.md)：具体任务与审查完成状态。
- [第一阶段验收记录](2026-10-02-rag-stage-one-results.md)：测试证据、修复历史、数据核对与未验收项。
- [RAG 架构](../rag-architecture.md)：实际启用能力与后续语义目标。
