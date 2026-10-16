# 新产品官方来源到 Writer 的实施计划

> 按用户本轮“允许继续”执行。使用 writing-plans、systematic-debugging、test-driven-development 与 verification-before-completion；在当前已隔离的 `codex/pastoral-desktop` worktree 实施。

**目标**：以用户已确认的官方来源为登记锚点，支持配置驱动的新产品身份，实际抓取并验证文档，经 Collector、canonical snapshot、Analyst、Comparator、Reflector、Writer、逐条审核和 QA 测试真实报告。

## 已知根因与方案

- `resolve_competitor_identity` 只读静态 Python 登记；新产品不能进入有界语义提取。
- 上轮手工短节选缺少实际抓取与结构化操作事实，Writer 没有发起模型调用。不得用升高置信度或伪造来源类型解决。
- 选择“人工核验来源登记 + 实际抓取验证”。自动把搜索结果视为官方会混淆权威与相关性；继续按产品改 Python 则无法通用复用。
- 新登记存放部署者控制的 JSON 文件，产品名/别名精确匹配，授权只覆盖明确登记的 URL（包括 query，不扩展整个域名）。每条保存审核人、时间与核验依据。不从请求 metadata、提示词、模型输出建立可信登记。
- 实际抓取必须通过已有 SSRF/robots/capture 检查，再核对请求/最终 URL、typed full_source、正文哈希、页面产品标题和质量。失败明确保留阻断；证据原文、坐标、条件绑定继续走原生产准入。
- 初始资料仅使用已人审的四产品官方链接，不导入参考答案、禁止推断或期望结果。新产品不自动获得其他域名/同品牌其他产品权限。

## 实施与测试

- [x] 1. 写失败测试：通用加载器、审核元数据/非法 URL/重复身份拒绝、精确 URL/查询隔离、新产品与旧产品身份隔离。实现最小只读登记加载及 resolver 对接。
  - 文件：`backend/packages/business_intel/official_registry.py`、`entity_resolver.py`、`official_sources.json`；测试 `backend/tests/unit/test_official_registry.py`。
  - 执行 `PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m pytest backend/tests/unit/test_official_registry.py -q`。
- [x] 2. 写失败测试：真实 capture 通过后语义提取可用；跨源重定向、错误标题、未知材料、哈希错配、缺失页面拒绝；核验回执进入实际 RawSource。实现 capture 校验并保持旧产品行为。
  - 文件：`research/capture/webfetch_adapter.py`、`research/extraction/semantic.py`，以及独立核验函数；测试同上及 `test_semantic_extraction.py`、`test_research_pipeline.py`。
- [x] 3. 新建默认零调用的实际抓取诊断入口，严格隔离参考答案，限制产品/来源/调用/token/超时/重试/输出目录。复用真实 Collector 持久化、快照和下游执行，不修改历史短节选诊断。
  - 文件：`backend/scripts/eval_official_writer.py`；测试 `backend/tests/unit/test_official_writer_eval.py`。
  - 正式模式先检查 8 题已人审及冻结输入 hash；真实调用额外要求 `--live` 和 hash。仅测试 Miro/Airtable 四条来源，其他四题列为未覆盖。
- [x] 4. 先抓取记录来源核验，再运行有界真实模型链，保存 trace、原文、快照、正文和审核。失败按产物定位；不把空正文/部分草稿当交付成功。
- [x] 5. 相关测试、后端全量测试、代码审查、秘密扫描，更新 README 与交付记录；本轮真实报告仍需独立人工语义审核，不自动标记人审通过。

## 验收口径

工程：新产品确实解析、实际抓取核验、Collector 语义提取调用、正式结构化事实在 snapshot、Writer 及逐条审核真实调用、QA 状态与正文一致，调用和 token 不超限。

语义：操作对象、角色、套餐、访问前提不得从题设偷渡；每条主张引用同产品且支持完整条件。根据实际正文逐条检查已确认参考边界，记录人工判断与未覆盖题。工程通过不替代用户报告人审。

## 本轮执行结果

实现与工程验证完成。最终完整后端 4293 通过、1 跳过；相关 67 测试通过。实际三轮共 16 次模型调用、57082 token，最终 Writer/逐条审核真实执行且生产者依赖通过，但 QA 有 2 个覆盖阻断，语义条件遗漏仍在。实施完成不表示报告交付验收通过；详见同目录 official-writer-delivery 记录。
