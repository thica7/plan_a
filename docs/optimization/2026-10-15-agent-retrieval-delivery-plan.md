# Agent 检索接线与 GitHub 交付计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. 按复现、实施、规格审查、质量审查、验证、交付的顺序执行。用户已确认接入实际入口并推送 GitHub。

**Goal:** 修复复杂中英文问题在稀疏检索中零候选的问题，使生产 Agent 和离线评测走同一查询规划路径，补齐中文使用与执行说明并提交当前分支。

**Architecture:** 共享检索入口保留原始问题，规划有界事实查询及输出要求，按实体和主题组织词法召回。Collector 将合格资料写入共享证据快照，Analyst、Comparator、Reflector、Writer 和 QA 消费快照及上游产物；写作与审核不能绕过准入自行替换引用。保留 raw 基线、项目隔离、来源版本和哈希校验。

**Tech Stack:** Python、SQLite FTS5/BM25、Qdrant、现有本机 E5 embedding 与 BGE reranker、pytest、React/Vite。

## 1. 复现与最小实施

涉及 `backend/packages/knowledge/{query_intent,lexical,retrieval,product_benchmark}.py`、`backend/packages/agents/collectors/kb_bridge.py`、`backend/packages/tools/rag_retrieve.py`、`backend/scripts/eval_independent_retrieval.py` 及对应测试。只改复现所需文件；若不改变分词存储，不新增索引迁移。

- [x] 写失败测试：复杂中文查询英文资料、多个事实维度、型号数字锚点、长句 fallback、格式指令不入事实查询。
- [x] 用 `PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_retrieval_intent.py backend/tests/unit/test_knowledge_lexical_recall.py -q` 确认相关失败。
- [x] 实施确定性查询规划、实体锚点与有界主题匹配；新增策略版本使缓存失效，raw 模式仍可复现原基线。
- [x] 在共享 RetrievalService 与 Collector 的真实 RAG 调用处接线，覆盖快照准入与下游消费。不要为 Writer/QA 新增无约束检索。
- [x] 回归项目隔离、型号误匹配、来源过期、拒答/澄清控制及 Collector→快照→Agent 证据链。

## 2. 离线比较

- [x] 保持独立样本 corpus/query/label 字节不变，保留 raw sparse、hybrid、hybrid+reranker 对照，并新增生产查询规划路径对照。
- [x] 单进程串行使用已下载的本机模型，禁止外部模型与网络调用；记录候选覆盖、最终 top-3、输入哈希、失败与退化原因。
- [x] 补充通用回归例子，明确其未经过独立人审，不能称为新的盲测验收集。
- [x] 运行对应检索与 Agent 测试；规格审查通过后再做代码质量审查，修复实际发现的问题。

## 3. 中文说明与安全交付

涉及 `README.md`、`docs/agent-execution.md`、`.gitignore`、本计划及验证记录。父 Agent 负责这些文件，与业务实现分开。

- [x] README 写清产品调研定位、研究模式、启动配置、像素桌面、真实流水线和 RAG 验证边界。
- [x] Agent 文档列出每阶段输入、输出、执行入口、RAG/证据权限、人工节点、重做和回退状态。
- [x] 忽略 `data/artifacts/`，保留本机真实报告与改稿，不推送运行资料、环境变量或模型权重。
- [x] 执行后端全量测试；核对前端测试与构建记录对应当前源码，检查 OpenAPI 和变更格式。
- [x] 对提交候选执行密钥扫描，按明确清单暂存本阶段授权源码、测试、评测与文档。
- [x] 提交并推送 `codex/pastoral-desktop`，核对远端 SHA；不强推、不合并 main。

## 验收边界

1. 原 6 道已人审答案题已曝光；改善结果属于回归验证，不等同于未知问题上的 RAG 合格证明。
2. 四家联网报告复测被工作区月度额度阻断；本轮不提高额度、不绕过配额、不调用付费模型。
3. Qdrant 本地持久化与 HTTP 多人部署验收分别记录；不将本机通过写成生产部署通过。
4. 文档与结果必须区分真实执行、回退、跳过和历史记录。
