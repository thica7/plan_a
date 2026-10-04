# 真实问题检索意图设计

基线：`b1cb4d2`。用户已确认真实样本核查、检索意图分离及多语模型比较方向。本文件具体化本轮离线内容；模型下载范围待用户选择，未变更时沿用离线约束。

## 选择与范围

采用结构化事实查询，配合只识别完整格式后缀的保守处理。仅删后缀无法拆解多重事实；继续扩充词典无法提供一般语义理解。原问题、事实子查询、格式要求和硬限制分别记录。执行授权不视为事实人审。

## 请求合同

- `RetrievalIntent` 只含 `fact_queries`（1–5条，每条1–500字）、`required_terms`（最多10条，每条1–80字）、`output_language`（可空，最多40字）、`require_citations`；禁止额外字段，不承载 scope、产品、市场、角色或时间授权。
- `RetrievalRequest` 增加 `intent_policy=raw|structured`，默认 structured；增加可空 `retrieval_intent`。raw 与显式 intent 同时提供时拒绝。没有格式后缀或显式 intent 的旧请求不改变实际查询。
- 纯函数 `resolve_retrieval_plan` 保留原问题，只将分句边界后的完整格式后缀移入诊断，例如“输出中文并保留出处”和“answer in Chinese and include citations”。未知格式保留；正文中的“中文支持”“消息保留”“引用功能”不删除；不读 gold、proof 或来源元数据。
- 显式事实查询由调用者声明，结构校验不能证明其原意完整。required_terms 和原问题中的阿拉伯数字（完整已知产品名称内部数字除外）带入每条查询。单位、否定及复杂限制仍需调用者声明并接受事实核查，不声称自动理解所有限制。
- 不扩大旧词典，不加入候选品牌或答案。计划含 version、origin、original_query、queries、格式要求及保留限制。

## 检索执行

计划改变查询或提供显式意图时，直接执行有界事实查询，不调用 LLM rewrite。每条查询沿用同一请求的 SQL scope / product / market / role / freshness 过滤，多列表使用既有 RRF，单列表保持排序；精排使用事实查询。response.query 仍为原问题。

缓存包含 intent 与计划版本，命中仍验证 canonical 文档、块和版本。诊断不来自来源字段，不写回来源；每个子查询分组只列最终保留 chunk ID，命中数量不代表事实完整性。

知识搜索 API 使用新增请求字段；LangGraph RAG tool 明确传入可选意图。现有 collector 和共享证据快照不进行无依据的自动拆题或重构。本轮提供生产入口能力，不声称所有 agent 自动生成正确子问题。

## 评测与人审

benchmark 默认 intent_policy=raw，保留旧基线；显式 structured 可执行安全格式分离或独立 JSONL 意图文件。文件只含 query_id 和意图字段，拒绝未知ID、重复ID、额外答案字段及raw+intent。原 evaluation 文件与正式人审门槛保持不变。

新虚构测试覆盖格式分离、两事实、数字、required_terms、无关主题、scope 与缓存。冻结后原候选只做一次政策对照，不按 gold 调参。主指标与支持片段覆盖继续分离。

5条真实样本补充官方证据核查：Pixel 更新起点、Notion计费周期、Figma席位和Dev Mode、Slack可见历史与删除期限。AI来源检查不是人审，reviewed仍为0。

## 模型与验收

本机没有 torch / sentence-transformers / FlagEmbedding / transformers 或模型缓存。若继续离线，真实模型比较记录未执行；若允许下载，另明确依赖、版本、缓存与设备后实施，不以 hash 冒充语义模型。Qdrant HTTP 和真实 Postgres 既有未验收状态不变。

采用真实临时SQLite失败测试、最小实现、SPEC后QUALITY、独立完整后端回归、增量Ruff、密钥模式扫描与diff check。按已有授权推送现有分支，交付区分入口合同、候选召回、真实模型与正式人审质量。
