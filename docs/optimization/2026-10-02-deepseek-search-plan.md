# DeepSeek 原生搜索接入与验收计划

> 执行方式：当前已隔离的 `codex/pastoral-desktop` 工作区内按任务执行，使用 executing-plans；完成后使用 requesting-code-review 独立审查。

**目标：** 竞品发现、采集和 RAG 补充检索复用 DeepSeek 原生搜索，并完成预算、来源、真实联网与报告验收。

**架构：** 主报告模型继续使用现有 Chat Completions。新增 Python 搜索适配器，通过官方 Anthropic Messages 的 `web_search_20250305` 获取结构化候选；正文继续走项目现有抓取、证据准入和引用流程。运行内缓存成功搜索，刷新证据时绕过缓存。

**技术：** Python / httpx / FastAPI / pytest；既有 RunLLMBudget 与 TraceSpan。

## 官方依据与已验证事实

- [官方搜索实现](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/web/web-search-deepseek/src/provider.ts)：`https://api.deepseek.com/anthropic/v1/messages`、`web_search_20250305`，读取 `web_search_tool_result`。
- [官方抓取说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/web/web-fetch-http/README.md)：web_fetch 由应用 HTTP provider 执行。
- 2026-10-02 真实账户探测：HTTP 200、10 个结构化候选、1 次服务器搜索。原始 usage：input 9977、cache read 256、output 838；输出达到上限仍有可用结构化候选。
- 原生搜索内部提示上下文无法由客户端精确预知。默认预留每次搜索 16384 个输入 token，实际 usage 校正；超预估时仍按实际记账并阻止超预算后续调用。不能承诺供应商硬账单封顶。

## 任务 1：搜索协议与配置（先失败测试）

文件：新增 `backend/packages/search/deepseek_client.py`、`backend/packages/search/client.py`、`backend/tests/unit/test_deepseek_search.py`；修改 `settings.py`、搜索导出、`web_search.py`、`.env.example`。

- [x] 写配置、结构化候选、引用片段按 URL 合并、去重、非法 URL、无搜索块、错误脱敏、usage 和过滤契约测试；运行确认功能缺失。
- [x] 最小适配器契约：

```python
class SearchClient(Protocol):
    @property
    def is_enabled(self) -> bool: ...
    async def search(self, query: str, max_results: int = 3,
                     *, filters: SearchFilters | None = None) -> list[SearchResult]: ...

def create_search_client(settings: Settings) -> SearchClient:
    if settings.web_search_provider == "deepseek":
        return DeepSeekSearchClient(settings)
    return PerplexitySearchClient(settings)
```

- [x] 配置 `DEEPSEEK_API_KEY` 可单独使用；只有已标记 DeepSeek 且主端点为 api.deepseek.com 时才回用 ARK_API_KEY。默认搜索模型 deepseek-flash、max_tokens 1024、max_uses 1；限制配置上界。
- [x] 请求采用官方工具定义：

```python
payload = {
    "model": settings.deepseek_search_model,
    "max_tokens": settings.deepseek_search_max_tokens,
    "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
    "tools": [{"type": "web_search_20250305", "name": "web_search",
               "max_uses": settings.deepseek_search_max_uses}],
}
```

- [x] 仅解析结构化搜索候选；无搜索结果块报错，不从模型正文猜 URL。禁用重定向；错误只返回状态/稳定错误码，不回显供应商正文或认证信息。请求不自动重试，避免超时后重复付费。
- [x] 域名过滤在本地执行；国家、语言、时效作为检索偏好，并在 trace 标记过滤能力，不能声称得到供应商强过滤保证。
- [x] 原生 usage 的总输入为 input_tokens + cache_read_input_tokens + cache_creation_input_tokens；cached 部分按命中价格结算。
- [x] 运行 `COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONPATH=backend ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_deepseek_search.py backend/tests/unit/test_search_filters.py -q`，要求全通过。

## 任务 2：统一入口、预算与缓存（先失败测试）

文件：`orchestrator/service.py`、`orchestrator/llm_execution.py`、`research/models.py`、`research/discovery/providers.py`、`research/discovery/constants.py`、`research/pipeline.py`，新增 `test_deepseek_search_runtime.py`。

- [x] 测试 RunService 选对客户端、请求前预算阻断、成功/错误/取消结算、实际 search usage trace、并发去重、过滤隔离、刷新绕过、恢复预算和来源标签。
- [x] 原生搜索使用与生成模型相同的运行预算及并发信号量；请求前 reserve，结束 settle，超时未知费用保留预估；预算元数据写搜索 span。
- [x] 运行内按查询/结果上限/过滤缓存，成功结果五分钟有效；相同查询的并发调用共用锁。缓存命中不计费；失败不缓存；证据刷新禁用复用。
- [x] SearchResult 新增默认 provider 字段，不破坏旧构造；流水线依据结果 provider 标记候选，旧未标记结果维持 Perplexity 兼容。
- [x] 运行新增 runtime 测试与现有 token/research/report reuse 测试，要求全通过。

## 任务 3：就绪状态与 smoke 统一

文件：`app/routers/health.py`、`scripts/smoke_search.py`、`config/settings.py`、`tests/conftest.py`、`test_health_router.py`。

- [x] 新增 DeepSeek 无 PPLX 凭据时搜索就绪和 smoke 走 DeepSeek 的失败测试。
- [x] health、smoke 和启动检查使用同一配置判断；补充测试环境凭据隔离。
- [x] 通过测试后在 ignored `.env` 切 `WEB_SEARCH_PROVIDER=deepseek`；仅重启本项目后端，保持 8000 / 5173。

## 任务 4：验收与审查

- [x] 后端完整回归、前端测试及构建，记录实际结果，不沿用旧计数。
- [x] 真实搜索 → 正文抓取，验证 provider usage、状态、正文哈希与候选 provenance。
- [x] 新建一个非 AI 产品的极简真实任务，自动发现竞品 → 采集 → 报告；记录终态、报告内容、引用、门禁与费用。真实失败继续定位，不把 HTTP 200 或演示结果当作端到端通过。
- [x] 使用 requesting-code-review 独立审查，修复重要问题并回归。
- [x] 保存验收文档，区分完成、已知问题、未验收；说明下一阶段优先级。RL 训练仍不在本轮范围。


## 执行结果

2026-10-02 已完成上述接入、修复、回归与独立审查；详见 [验收记录](2026-10-02-deepseek-search-results.md)。

任务 4 的勾选表示已执行真实验收并记录结果：原生搜索和正文抓取通过，三次完整任务均未达到可发布报告终态。最终任务因两个竞品缺少可用功能证据而阻断，不能视为端到端通过。后续采集通用化、草稿与定向修复流程需另一个明确阶段实施。
