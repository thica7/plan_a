# Competiscope v2

Plan A 实现脚手架：面向竞争情报分析的图驱动系统，包含 schema-first Agent 输出、基于 skill 的分析维度、局部 QA 重跑、混合 RAG 检索、多源爬虫，以及 React 运维控制台。

## Phase 9 亮点

Phase 9 已完成从爬虫到知识库填充的闭环：

- 8 种爬虫源类型：`sitemap`、`rss`、`web_search`、`manual`、`pricing`、`official_docs`、`changelog`、`review_site`
- KB 治理：SimHash 近重复检测、过期文档权重、crawl-run 可追踪性、retrieval trace
- 检索预设：`general`、`pricing`、`comparison`
- 评估集：`eval/competitor-analysis-eval.jsonl` 中包含 30 条标注过的竞品分析 query
- 文档：中文用户指南、架构图、E2E 演示设计、演示视频脚本

建议阅读顺序：

- `docs/USER_GUIDE.md`：面向操作者和开发者的完整使用指南
- `docs/ARCHITECTURE_DIAGRAM.md`：爬虫、入库、RAG 检索架构图
- `docs/E2E_DEMO_DESIGN.md`：端到端演示流程设计
- `docs/DEMO_VIDEO_SCRIPT.md`：录屏或现场演示旁白脚本

## 快速启动

最简单的启动方式是 Docker。复制环境变量模板，填入 API 凭证，然后启动完整服务栈：

```bash
cp .env.example .env
docker compose up --build
```

启动完成后打开 `http://localhost:8080`。

如需调用真实 API，至少在 `.env` 中设置 `ARK_API_KEY`、`ARK_MODEL`，并将 `DEMO_MODE=false`。`PPLX_API_KEY` 是可选项，配置后可启用 Perplexity 驱动的联网搜索。如果没有 API 凭证，系统会降级到 demo-mode 行为。

本地开发时，可以分别安装后端和前端依赖，然后运行：

```bash
make dev-backend
make dev-frontend
```

后端运行在 `http://localhost:8000`。前端运行在 `http://localhost:5173`，并将 `/api` 代理到后端。Makefile 默认使用名为 `bd-competiscope-v2` 的 Conda 环境；如果你使用其他 Python 环境，请按需调整命令。

## 真实 API 测试

在仓库根目录创建本地 `.env`：

```bash
ARK_API_KEY=your_key
ARK_MODEL=your_model_or_endpoint_id
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
PPLX_API_KEY=your_perplexity_key
PPLX_BASE_URL=https://api.perplexity.ai
WEB_SEARCH_PROVIDER=perplexity
DEMO_MODE=false
MAX_ITERATIONS=2
AUTO_REDO_ENABLED=true
AUTO_REDO_WARN_ENABLED=false
HITL_ENABLED=false
HITL_TIMEOUT_SECONDS=60
COLLECTOR_REACT_ENABLED=true
COLLECTOR_REACT_MAX_TURNS=3
ANALYST_REACT_ENABLED=true
ANALYST_REACT_MAX_TURNS=3
```

然后使用 `make dev-backend` 重启后端。New Run 页面会显示后端是否检测到 `ARK_API_KEY` 和 `ARK_MODEL`；选择 `Real API` 后，浏览器会通过后端发送真实 chat completion 请求，API Key 不会暴露给前端。

Competitors 保持 `Auto-discover` 时，只需要输入主题；planner 会先搜索并选择直接竞品，再进入证据采集。当 `PPLX_API_KEY` 存在时，collector 子 Agent 会优先使用 Perplexity `web_search` 结果，抓取并 hash 返回页面；如果搜索不可用，则回退到 LLM 生成的候选证据。

M0 冒烟检查：

```bash
make m0-check
make smoke-llm
make smoke-search
make smoke-fetch
```

`m0-check` 除本地包执行外是离线安全的。真实冒烟命令需要 `.env` 中有对应 key，并且只打印非敏感元数据。

如果本地开发时 `8000` 端口被占用，可以换端口启动后端，并让 Vite 指向新的后端地址：

```powershell
conda run -n bd-competiscope-v2 uvicorn app.main:app --port 8010 --app-dir backend
cd frontend
$env:VITE_API_TARGET="http://localhost:8010"
pnpm dev
```

## 当前能力切片

- FastAPI 后端，包含 `/api/runs`、`/api/runs/{id}/stream`、`/api/skills`、`/api/runtime`、`/api/runs/{id}/resume`
- M0 健康检查和冒烟端点：`/api/health`、`/api/smoke/llm`、`/api/smoke/search`、`/api/smoke/fetch`
- Pydantic schema 扩展：`RedoScope`、`QCIssue`、`ReflectionRecord`、`RevisionRecord`、结构化 KB、对比矩阵、run DTO
- YAML skill registry，用于管理首批分析维度
- LangGraph real-run DAG 和 scoped redo graph，SQLite checkpoint 存放在 `runs/graph_checkpoints.db`
- LangGraph 节点内部支持 collector 与 analyst 维度并发 fan-out
- collect join 会归一化并去重 `RawSource` 证据，包括结构化 `covered_competitors`
- 独立 collector 与 analyst 子 Agent 上下文，并在 trace metadata 中记录 context ID
- 有界 collector ReAct runner：`web_search -> fetch_page -> finish`，带确定性 fallback
- 有界 analyst ReAct runner：`inspect_sources -> validate_citations -> finish`，带一次性 fallback
- collector ReAct finish URL 的可信源处理、多竞品来源归因，以及矩阵引用一致性 QA
- React + Vite + TypeScript 前端控制台，包含 New Run、Run Detail、KB/matrix、trace、revision 等视图
- 后端和前端共享概念一致的 SSE event 类型
- 真实运行 trace span 会记录 LLM/search/fetch 调用、延迟和 token 估算
- 对比矩阵 QA 一致性检查，以及有界 scoped redo 迭代
- blocker 级 QA finding 可触发自动 scoped redo；当 HITL 开启时自动 redo 会禁用；warn 级 redo 需要 `AUTO_REDO_WARN_ENABLED` 或 New Run 开关启用
- 可选 HITL 中断，用于 planner 和 QA 审核，通过 `HITL_ENABLED=true` 启用
- 爬虫源扩展支持 pricing page、official docs、changelog、review site，并支持 include/exclude 过滤
- 知识入库治理支持 SimHash 近重复检测、freshness 权重、crawl-run 可追踪性
- 检索预设和 retrieval trace 记录，让 RAG 行为可观察
- Docker 和 Makefile 脚手架支持计划中的演示路径

## 项目结构

```text
backend/    FastAPI 应用、schema、skill registry、编排服务
frontend/   React/Vite 应用、API client、run 页面、实时泳道视图
docs/       架构、API 契约、用户指南、架构图、演示说明
docker/     Nginx 反向代理配置
eval/       标注过的 RAG 评估 query
```
