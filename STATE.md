# Project State Board

更新时间：2026-06-17  
更新粒度：按“一个功能/一组相关能力”更新一次，不按每个 commit 逐条更新。  
范围：当前分支 `codex/github-ready-20260610`；`f63dc594` 之前做整体基线，之后按功能主题汇总。

## 怎么读这个状态板

每个功能条目都回答三个问题：

- 功能解释：这个功能是给谁用、解决什么问题。
- 具体改了什么：这轮代码/文档/测试主要动了哪些能力。
- 现在效果：项目现在因此多了什么、变稳了什么。

## f63dc594 之前的总体状态

`Competiscope v2` 已经是一个竞争情报工作台，能从一个研究主题出发，自动规划竞品、采集证据、分析比较、生成报告，并把过程记录在企业工作台里。

已有能力：

- 后端服务：FastAPI 提供 run、stream、HITL、health、metrics、skills、runtime、trace、crawl、knowledge、KB、revision、enterprise、eval、workflow 等接口。
- 智能体流程：planner、collector、analyst、comparator、reflector、writer、QA 已经串成多阶段 DAG，支持 redo、审计、trace、run journal 和结构化消息。
- 证据与知识库：支持网页抓取、文档解析、来源归一化、SimHash 去重、Qdrant 向量检索、KB 缓存、source registry、retrieval trace 和证据准入。
- 企业治理：已有 workspace、project、competitor、evidence、claim、report version、audit log、auth/RBAC、compliance、Postgres 等边界。
- 工作流：Temporal thin shell、report approval、scheduled scan、monitor job 等企业运行流程已经成型。
- 前端工作台：React/Vite/TypeScript 控制台已经覆盖新建 run、run detail、history、crawl/search/knowledge、enterprise workbench、evidence、competitor、report studio、trace、revision、governance 等视图。
- 部署工程：已有 Docker Compose、Nginx、frontend、backend、Qdrant、Postgres、Temporal、Temporal UI、worker，以及本地一键启动脚本、OpenAPI 同步、测试、smoke、secret scan。

边界前最近一段重点是：清理 GitHub 发布快照、加强 API auth 与前端交互真实性、设计双语输出语言契约、实现 planner competitor review，并把 HITL 竞品编辑接入前后端。

## 边界提交

### `f63dc594` 报告核心内容深度设计

- 功能解释：报告不能只是“有结构、有结论”，还要有足够分析深度，尤其是核心章节不能太薄。
- 具体改了什么：新增 `docs/superpowers/specs/2026-06-10-report-core-content-depth-design.md`，定义后续 writer 和 report quality 要围绕“核心内容深度”改造。
- 现在效果：后续一系列 writer budget、报告质量评分、薄报告修复都以这个规格为起点。

## f63dc594 之后的功能状态

### 1. 启动、部署、本地化和鉴权更稳

- 功能解释：项目在真实环境启动时，需要提前发现配置问题；用户打开前端和调用 API 时，也需要稳定的鉴权、本地化和部署入口。
- 具体改了什么：修复 i18n UI 回归；补强 API auth middleware、Nginx、Dockerfile、docker-compose；后端启动时校验 ARK、PPLX、BACKUP LLM 等关键环境变量；writer 的 RAG 调用补齐 competitors 和 dimensions；collector 会把归一化后的来源自动写入全局 KB。
- 现在效果：部署和启动失败更早暴露；RAG/KB 链路更完整；中文/本地化报告和前端文案不容易回退。
- 相关提交：`f7f98646`, `4887abae`, `c66a36ce`, `c59e881b`

### 2. 报告从“堆信息”改成“先给分析”

- 功能解释：最终报告要像咨询分析，不只是把收集到的信息罗列出来；用户应该先看到判断、比较和建议。
- 具体改了什么：writer 生成逻辑改成 analysis-first；报告质量规则和输出语言测试同步更新；enterprise run snapshot 扩展 analyst、collector、QA、writer、release gate、enterprise projection、orchestrator、API DTO 和前端 OpenAPI/types。
- 现在效果：run 结果能保存更完整的企业报告状态，报告也更偏“分析结论驱动”。
- 相关提交：`1833609e`, `edeb6e77`, `7fa35ef6`

### 3. Run history 和 HITL 审阅流程更稳定

- 功能解释：用户在工作台里查看历史 run、处理人工审阅、恢复流程时，不应该遇到状态丢失或前后端不同步。
- 具体改了什么：修复 runs、stream、runtime、run journal、Postgres、report quality 等后端路径；前端 QA review、plan review modal、run detail controller 对齐后端状态；补充 workflow/run service 测试。
- 现在效果：历史记录、HITL 审阅弹窗、run detail 页面和后端流程更一致，审阅流不容易断。
- 相关提交：`f3c4ec15`

### 4. Review 和 SWOT 进入知识模型与正式报告

- 功能解释：竞争情报报告不仅要看官网和产品信息，也要能总结用户评论，并形成 SWOT 分析。
- 具体改了什么：新增 review/SWOT schema；analyst 可以总结 review themes；comparator 可以从竞品证据推导 SWOT；writer 新增 review 和 SWOT 报告章节；QA 和 report quality 开始检查这些章节；无引用的评论或 SWOT 项会进入 evidence gaps。
- 现在效果：报告能展示评论主题、SWOT 矩阵和相关证据缺口；没有证据的评论/SWOT 结论不会被默默放进报告。
- 相关提交：`7045b8a7`, `3704a76b`, `e7ca1d9b`, `06668665`, `5eb01ace`, `3830275f`, `61aee1b4`

### 5. Persona 调研证据质量提高

- 功能解释：系统会模拟或整理用户访谈/persona 证据，但这些证据必须有质量门槛，不能只是生成几句泛泛画像。
- 具体改了什么：新增 persona evidence quality gate；collector、QA、survey interview agent 都接入 persona 证据检查；增强 synthetic persona generation，让分段、访谈信号和 persona claim 更具体；限制 boost 只影响 persona 相关 claim。
- 现在效果：persona 调研内容更可用，报告里的用户画像和访谈证据更不容易空泛。
- 相关提交：`09cfa85e`, `664ac121`, `ea8c1def`, `83bd684c`, `ef1a5571`, `9ed70474`

### 6. Writer redo 支持分层修复

- 功能解释：报告出问题时，不一定要整篇重写；有些只需要修一行，有些需要修一个章节，有些才需要整稿重来。
- 具体改了什么：新增 writer repair planner；支持 line repair、section repair、full rewrite；补齐修复 metadata、生产路由、上游问题映射、redo recovery、review/source cleanup；加入防报告变薄和 anti-regression 检查。
- 现在效果：writer 修复更精确，减少“为了修一个小问题把整篇报告改坏”的风险。
- 相关提交：`30bf4fc1`, `b0481dca`, `e8f6a995`, `e100bfe2`, `42824c07`, `34e559c5`, `7bb94c2a`, `6e684775`

### 7. 薄报告和核心章节深度开始被治理

- 功能解释：报告不能只有标题和几句浅层总结，核心章节必须有足够内容、证据和比较分析。
- 具体改了什么：建立 report core budget layering；writer 预算向核心章节倾斜；report quality 能识别核心章节深度不足；薄核心章节会触发 writer repair；严重深度不足会走 full rewrite；blocked release gate 状态会暴露出来。
- 现在效果：报告过薄会被系统发现、拦截和修复，不会轻易作为合格报告发布。
- 相关提交：`c729c7de`, `403216c8`, `8251ccf0`, `9c86f70d`, `187cc26a`, `faa34256`, `e351bf34`

### 8. 引用、来源和本地化修复更可靠

- 功能解释：报告修复时最容易出问题的是引用错位、来源丢失、语言回退，这会直接影响可信度。
- 具体改了什么：修复 analyst cache 的 review source hygiene；修复本地化 citation fallback；处理重叠引用排序；保护 user research 引用；清理 scoped redo source dependency；加强 writer section anti-regression。
- 现在效果：redo 或局部修复后，引用和来源更稳定，本地化报告也不容易被修成混合语言。
- 相关提交：`390dddb5`, `3a62f050`, `ee7e0b9a`, `024ddd73`, `a38f2f90`, `6e68a741`, `932c508b`

### 9. Community triangulation 社区证据三角验证

- 功能解释：除了官方资料，系统也会看社区讨论、用户反馈和非官方来源，但这类证据必须被分类、聚合和谨慎使用。
- 具体改了什么：新增 community query planner、source classifier、raw sources、claims/scoring；collector 能采集 community evidence；analyst/comparator 能标注 community claim clusters；writer 能使用社区证据；QA、report quality 和 release gate 会检查社区证据是否被正确使用。
- 现在效果：报告可以引用社区信号来补充真实用户反馈，同时避免把社区观点误当成官方事实。
- 相关提交：`7ada1c96`, `5343e940`, `76f26b2d`, `d26b8c41`, `71613abb`, `c85de4dc`, `c7f4bc76`, `f2b47017`, `919245fd`, `726c3e44`

### 10. 报告章节索引用于质量识别和修复定位

- 功能解释：如果系统不知道报告每一段属于哪个章节，就很难准确判断哪里缺内容、哪里该修。
- 具体改了什么：新增 report section index；QA、report quality、repair 可以基于统一章节识别工作；RAG、SWOT 等新章节能被质量规则识别；community official guard 不再误读 audit lines。
- 现在效果：报告质量检查和 writer repair 的定位更准确，不容易把问题归到错误章节。
- 相关提交：`96e9d804`, `ea3d2bfd`, `c2c5d0e0`, `f3ba0e90`

### 11. 多模块质量收束

- 功能解释：前面多条功能落地后，需要把 writer、reflector、release gate、来源解析、LLM、trace UI 等模块的细节统一收口。
- 具体改了什么：收束 writer、reflector、release gate、source resolver、LLM、orchestrator 和 trace UI 的剩余改动；补齐报告质量、来源对齐、定价单位、Langfuse/LLM、trace message 等测试覆盖。
- 现在效果：跨模块联动更一致，很多边界行为有测试兜底。
- 相关提交：`bd801f19`

### 12. Collector admission、Comparator fallback 和定价单位修复

- 功能解释：证据进入系统、比较器失败降级、价格单位保留，都会影响最终分析质量。
- 具体改了什么：加固 collector evidence admission 和 writer recovery；comparator 在 deterministic fallback 前先重试；analyst 保留 usage-based pricing units。
- 现在效果：低质量证据更难进入报告；comparator 不会过早降级；按量计费等价格单位更容易保留到分析和报告里。
- 相关提交：`93b90077`, `5c633dda`, `e592f018`

### 13. Writer evidence pack 成为统一写作证据输入层

- 功能解释：writer 写报告或修报告时，需要一个统一、可检查、可追踪的证据包，而不是临时从各处拼输入。
- 具体改了什么：新增 writer evidence pack registry；支持 metrics、fact projection、事实去重、residual signals、KB context/provenance、source appendix、prompt segmentation、canonical citation validation；writer prompt 和 writer repair 都改用 evidence pack；新增 writer preflight / writer segment preflight events；证据预检失败时 writer 会 fail-fast，而不是继续生成。
- 本轮收口：把大 prompt 从“完整 source digest 直塞 writer”改成预算化 evidence segment；segment 会覆盖全部 raw source，并在单个 source 或单个 fact 超预算时显式标记；repair 也会拆成预算内的 child segment，不再把完整巨型 pack 塞回单次 writer；分段 writer 和 repair 都会校验 canonical citation，失败会重试一次，仍失败则报错。
- 最新修复：writer prompt / segment prompt 现在使用 citation-safe evidence pack projection，不再把 `fact:raw-source...`、`signal:raw-source...`、`kb:...`、`represented_by` 这类内部追踪 ID 暴露给 LLM；报告引用仍只允许真实 raw source ID，派生 token 如 `[source:raw-source-X:community:1]` 继续被判 invalid。
- 现在效果：写作输入更规范，引用来源更可追踪，大 prompt 可分段处理，坏证据不会继续污染报告；像 run-58 那类 source digest 膨胀问题现在会走分段输入，保留 source 覆盖和追溯信息，同时避免 writer/repair 被单条超长 source 拖垮；像 run-2d751... 这种内部 fact ID 诱导错误 citation 的失败也被堵住。
- 相关提交：`a590e490`, `ba5844d8`, `516bc63a`, `a12c4f92`, `94732231`, `910c0299`, `b2764be5`, `0ef617fd`, `58912b7e`, `6018346d`, `526ba4c8`, `6a289108`, `fce9fe5e`, `72870a62`, `0623c13d`, `5a53a0cc`, `d62d05c3`, `515518c5`, `6a25355e`, `73d4e41e`, `e774b3b9`, `140d40ad`, `f537eb01`, `8fa4a4f9`, `361352c1`

## 当前重点状态

- 报告能力：已经从“能生成”推进到“分析优先、章节可索引、核心深度可评分、薄弱章节可自动修复”。
- 证据能力：Review、SWOT、persona、community evidence 已经进入分析、QA、writer 和 release gate。
- 修复能力：Writer redo 已支持行级、章节级和整稿级修复，并带防变薄、引用保留、来源清理和证据预检。
- 写作输入：Writer evidence pack 已成为写作和修复的统一证据输入层，支持事实投影、KB 上下文、来源附录、预算化 prompt 分段、repair 分段、citation-safe prompt projection 和规范引用校验。
- 工程稳定性：部署、API auth、本地化、HITL/run detail 展示和 SSE 事件契约在这段历史中持续补强。

## 2026-06-19 Schema-First Writer

- Added structured writer models, renderer, validator, publication contract, regression-shape adapter, structured section generation, and structured repair target telemetry.
- `report_md` remains the frontend-visible output; no database migration or frontend change was added.
- Markdown writer remains a trace-visible fallback.
- Focused verification commands:
  - `python -m pytest backend/tests/unit/test_writer_structured_report.py backend/tests/unit/test_writer_structured_renderer.py backend/tests/unit/test_writer_structured_validation.py backend/tests/unit/test_writer_publication_contract.py backend/tests/unit/test_writer_structured_adapter.py backend/tests/unit/test_writer_structured_generation.py backend/tests/unit/test_writer_structured_repair.py backend/tests/unit/test_enterprise_postgres_config.py -v`
  - `python -m pytest backend/tests/unit/test_run_service.py -k "writer" -v`
