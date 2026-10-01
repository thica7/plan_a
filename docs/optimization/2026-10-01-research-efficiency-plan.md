# Research Efficiency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 接入真实 DeepSeek，交付按深度分层的审查、可验收重做、Token 预算及谨慎的历史报告复用。

**Architecture:** 沿用现有兼容客户端、RunLLMBudget、release gate、WriterRepairPlan 和企业报告范围。新增小模块实现成本计量及历史事实筛选，元数据提供兼容的验收记录；不另建工作流。

**Tech Stack:** Python/FastAPI/Pydantic/httpx/pytest，React/TypeScript/Vite。

基线 HEAD `ba3c837`，工作树 `/Users/a1/Documents/ChatGPT/竞品分析优化/plan_a_pm_modes`。已批准实施，复用隔离工作树。测试使用 `COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONPATH=backend ../plan_a/.venv/bin/python -m pytest`。

## Task 1：供应商与预算（root，配置/LLM/trace 范围）

Files: `backend/packages/config/settings.py`、`backend/packages/llm/doubao_client.py`、`backend/packages/llm/execution_budget.py`、`backend/packages/orchestrator/llm_execution.py`、`backend/packages/orchestrator/service.py`（仅 trace 计费）、`backend/packages/governance/model_router.py`、`backend/tests/unit/test_llm_client.py`、新增 `test_token_budget.py`。

- [ ] 先测试可配置 primary provider 名称、DeepSeek payload 思考关闭及 max_tokens、缓存 usage 和不泄露 API key。
- [ ] 测试输入/输出预留、并发、重试、预算不足、真实 usage 结算及恢复。
- [ ] 运行定向测试见失败后实施。兼容 ARK 配置并添加 `LLM_PROVIDER_NAME`/`LLM_MAX_OUTPUT_TOKENS`/run token 与美元预算设置；`deepseek` 使用官方兼容格式和 `thinking: {type: disabled}`。
- [ ] usage 解析 `prompt_cache_hit_tokens`/`prompt_cache_miss_tokens`；成本按输入未命中/命中/输出分别计算，官方高峰 USD 单价作为预算保守估计，标记并非账户账单。
- [ ] 最小真模型请求核实模型、非空输出、缓存分项与 Token 用量；记录脱敏结果。

## Task 2：分层门禁与可验收重做（implementer，business_intel/research/writer/enterprise 范围）

Files: `backend/packages/business_intel/release_gate.py`、`backend/packages/research/evaluation/release_gate.py`、`backend/packages/research/repair/strategies.py`、`backend/packages/agents/writer/logic.py`（仅深度提示/修复）、现有 enterprise revision 与 redo 入口；测试 `test_research_modes.py`、`test_writer_repair.py`、新增 `test_research_gate_profiles.py`/`test_repair_acceptance.py`。

- [ ] 阅读现有企业版本、人工 revision 及 redo 入口；先测试内部 quick 缺 SWOT 为提醒，越界引用仍失败，默认正式发布不降低标准。
- [ ] 增加明确 gate purpose 参数（默认正式发布）、深度读取元数据并保留重建计划；内部充分度改 warn，关键完整性检查不降级。writer quick 提示匹配核心内容而非全部深度章节。
- [ ] 补证测试：手机 pricing 不包含 API/token，软件 API 有明确品类才生成对应查询。通过 gap metadata 传产品品类，缺品类采用通用品类。
- [ ] 在既有修复路径记录可序列化验收：issue IDs、mode、sections、before/after 版本/问题数、resolved/remaining、improved 与 no_progress；重复无改善停止，保留受保护内容。
- [ ] 人工 revision 不复制旧 claims/QA；重新提取/验证当前正文与引用，再创建新版本。测试证据删除/新增未支持结论不会沿用旧通过指标。
- [ ] 定向与回归测试，提交；规格审查通过后质量审查。

## Task 3：历史报告复用与评测轨迹（后续 implementer，memory 与 integration 范围）

Files: 新增 `backend/packages/memory/report_reuse.py`、`backend/packages/orchestrator/service.py`（仅新 run advisory 接入）、企业 store 既有查询；新增 `backend/tests/unit/test_report_reuse.py`、`backend/scripts/export_agent_eval.py` 和带 split 的小评测 JSON。

- [ ] 测试 workspace/project/产品相关性过滤、上限三报告/限定事实数、过期价格、缺原始 URL、冲突、旧判断 advisory、不同来源去重。
- [ ] 从既有 store 检索相关报告/事实，保留原始 evidence/source 日期与来源链接；符合条件也仅提供 advisory，当前 collector 重新抓取并 admit 后才可进入证据。
- [ ] 将有长度边界的复用上下文接入计划，记录 selected/skipped/refresh_required；避免整篇旧正文加入 writer prompt。
- [ ] 测试 export 从 trace 提取任务、动作、输入输出摘要、成本及反馈；脱敏密钥/邮箱，过滤 Demo，不凭空产生事实正确奖励。提供 train/validation/holdout 样例及可复现命令。
- [ ] 完成测试、规格/质量审查。

## Task 4：整体验收与演示

- [ ] 跑全部后端单元/合同/回放与 redo 集成测试，前端 vitest、TypeScript/build（必要界面更改有专门测试）。
- [ ] 重启本地后端加载安全配置，保持端口 8000/5173 唯一；真模型极简样例核对报告内容、引用、费用、重做结果。搜索凭据缺失须记录，不能以 Demo 替代实际搜集。
- [ ] 全部 diff 独立 review；修复 Important/Critical 后重验，写 `2026-10-01-research-efficiency-results.md`，更新此清单并提交。
