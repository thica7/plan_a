# Agent Evidence and Fetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增加事实支持、时效和网页抓取质量，减少错误证据进入报告。

**Architecture:** 沿用现有 DAG 与来源准入，先在 fetch 边界输出清晰质量状态，再将发布时间、更新时间和核验时间传到 QA。搜索参数按来源与事实类型选择，未知状态显式可见。

**Tech Stack:** FastAPI、httpx、webfetch_v2、Playwright 可选、pytest。

---

### Task 1: 抓取内容质量和明确降级

**Files:** `backend/packages/tools/evidence_fetch.py`、`backend/packages/research/capture/policy.py`、`backend/tests/unit/test_evidence_fetch_quality.py`。

- [ ] 先写失败测试：超过 120 字符的登录、验证码、软 404 不能通过快速路径；普通正文仍走快速路径；低质量结果不能获得 1.0 质量分。
- [ ] 运行 `.venv/bin/python -m pytest backend/tests/unit/test_evidence_fetch_quality.py -q` 观察预期失败。
- [ ] 抓取成功后复用统一内容质量分类，按 `good/weak/blocked` 决定接受或进入浏览器降级，并保留失败原因。
- [ ] 重跑质量测试、`test_advanced_fetch.py` 和研究采集测试。

### Task 2: WebFetch 子进程总超时与证据输出

**Files:** `backend/packages/tools/advanced_fetch.py`、`backend/packages/tools/evidence_fetch.py`、`backend/packages/research/capture/webfetch_adapter.py`、`backend/tests/unit/test_advanced_fetch.py`。

- [ ] 先写失败测试：模拟子进程 `communicate()` 不结束，调用需在总时限内返回 `advanced_fetch_timeout` 并清理进程；已有静态/浏览器结果保留最终 URL、抓取方式和结构化质量状态。
- [ ] 运行目标测试确认当前进程没有总超时。
- [ ] 为子进程加总 timeout、终止和排空；为可选网络/快照参数提供受限传递；下游保存可追溯抓取元数据。
- [ ] 重跑 fetch、SSRF、防回归和 collector 链测试。

### Task 3: 事实时效和搜索约束

**Files:** `backend/packages/search/perplexity_client.py`、`backend/packages/agents/qa/logic.py`、`backend/packages/agents/collectors/kb_bridge.py`、`backend/tests/unit/test_source_currentness.py`。

- [ ] 先写失败测试：2020 年发布且今日抓取但未经核验的价格资料触发时效问题；带今日 `last_verified_at` 的资料保持可用；搜索请求可携带官方域名、语言、地区和日期过滤。
- [ ] 运行目标测试确认旧发布日期被忽略、搜索参数未传递。
- [ ] 分别记录发布日期、页面更新、抓取和核验时间；QA 对易变维度优先采用核验时间；搜索只在支持的情况下传过滤参数。
- [ ] 重跑 QA、KB 复用、Perplexity 客户端测试。

### Task 4: 质量评测和端到端回归

**Files:** `eval/product-evidence-eval.jsonl`、`backend/tests/unit/test_product_evidence_eval.py`、`docs/optimization/2026-09-28-agent-quality-results.md`。

- [ ] 建固定案例：登录壳、历史价格、动态页面、PDF/非 HTML、来源冲突和普通产品功能；每个案例记期望抓取分类与质量门禁。
- [ ] 测试关键事实支持率、陈旧证据误用和抓取成功/降级状态。
- [ ] 完整后端测试、前端测试/build、OpenAPI 同步和 demo/Temporal smoke；记录真实未覆盖环境。
