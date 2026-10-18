# 关键证据与条件完整性修复计划

> 用户已确认本方向并允许执行。采用 systematic-debugging、writing-plans、TDD、按独立文件分工和两阶段代码审查；复用 `codex/pastoral-desktop` 工作区。禁止训练、权重下载和 Docker。新产品参考不进入实现代理或生产 Agent。

**Goal:** 修复关键操作证据漏选、来源套餐前提遗漏和中文必要条件句误判，再以用户确认的八题运行独立来源评测。

**Architecture:** 继续使用当前已准入快照、完整事实、Writer v2 主张选择和最终 QA 重放。排序后的选择增加结构覆盖保留；同一能力的来源前提在进入生成视图及逐条审核前保持完整；必要条件句只影响断言识别，不替代语义审核。评测侧保存参考和人工确认，Agent 侧仅接收问题及官方来源身份。

**Tech Stack:** Python/Pydantic/pytest、现有本机 E5、固定官方来源 Collector 与既有 DeepSeek；无新服务。

## 1. 记录人工确认与数据身份（root）

- [x] 保留原 candidate 文件作为构造记录，生成 `eval/agent-readiness-holdout-v1-reviewed.jsonl` 与 reviewed manifest：8 题问题、来源和参考边界不改，仅记录项目用户此次明确确认与 UTC 时间、原始/新文件 SHA。
- [x] 新建 `eval/agent-readiness-trajectory-review-v1-reviewed.json`：T1 仅是单题条件结论成功，T2 排他套餐结论失败，T3 缺精确报价合理拒答；整条工作流、源绑定和新报告尚未因此通过。奖励不赋值，训练 false。
- [x] 官方登记仅添加四产品九个精确文档身份；不添加参考事实、答案或产品特判。更新人审单状态并保留原构造哈希。

## 2. 操作证据选择（独占 question_retrieval.py）

- [x] 重放旧 Miro：所有 13 条 eligible 已入候选池，丢失发生在最终每问 top 3；Guest 来源不存在时仍是缺证。
- [x] 在 `backend/tests/unit/test_question_operation_selection.py` 先写匿名失败用例：唯一 comment/edit 条件被重复背景挤掉、不同角色/套餐不合并、登录事实保留、3/8 容量及已准入范围不放宽。
- [x] `question_retrieval.py` 的排序后选择利用完整原始 `operation_observations` 保留遗漏操作，仍每问三条、总八条；超容量或无法覆盖写入诊断。请求条件只用于选择，不写成产品事实；无合法结构证据不能猜绑定。
- [x] 运行新测试及 `test_question_retrieval.py`，保存 RED/GREEN 和匿名反例；独立规格审查后做质量审查。

## 3. 来源前提完整性（独立调查后限定文件）

- [x] 沿旧 Miro 公开看板密码保护的完整原文、normalized_fields、snapshot、生成视图、claim review 定位前提被拆掉的位置；对照有条件的事实与孤立短句，不猜具体套餐。
- [x] 在最早丢失边界新增匿名失败用例：同一能力的 plan/scope 限定不能被短句覆盖；其他能力/产品/来源不互相继承；来源位置与内容哈希必须重放。
- [x] 最小修复由调查结论限定，不改检索代理独占文件；条件所需完整原文无法放入容量时保留缺口，不裁条件。必要调用处与测试由 root 确认范围后接线。
- [x] 生产与最终 QA 均不能仅因短句逐字命中就放行缺前提主张。保持历史读取和新证据准入规则；记录真实仍缺的来源。

## 4. 中文必要条件句（独占 answer_resolution.py）

- [x] 新 `backend/tests/unit/test_chinese_conditional_resolution.py`：已审核完整“只有后端授权的人才能访问文档”在闭合问句中误报 `answer_body_unresolved`，先匿名 RED。
- [x] 最小修复识别完整的中文必要条件断言；未完成“只有”、问句、建议和背景不能借此放行；错误角色/对象、缺 span、V2 篡改继续拒绝。
- [x] 保留 reason 非答案、来源主体和条件归属守卫；新测试、resolution/coverage/selection 回归与独立审查通过后冻结。

## 5. 正式测试、冻结与独立评测

- [x] 三项匿名修复先 RED→GREEN，完成独立规格与质量审查，修复 Important 后冻结生产源码和评测 runtime；不能用新题结果调实现后仍称同一留出评测。
- [x] 完整后端：`PYTHONPATH=backend:backend/tests/unit ../plan_a/.venv/bin/python -m pytest backend/tests -q --tb=short`；前端 test/build 与 OpenAPI/类型检查按实际 schema 变更执行。变更 Python Ruff E9/F、diff check、只输出路径/计数的实际凭据扫描。
- [x] 新题仅传 id/product/question/sources(id/title/url)；不传 reference、excerpt、expected_resolution、label。按四产品分组，各两题；官方内容独立抓取与准入。
- [x] 第一次独立真实阶段诊断最多四次，每组 24 calls / 80000 token，max output 2048，retry 0；使用既有模型配置，本机 E5 不下载。无来源/抓取失败/预算错误保留为结果，不暗中补跑或改金标。固定 URL 阶段诊断不代表 Planner 自动发现或完整 Graph 验收。
- [x] 逐题审查答案、全部子问、条件与引用，分别统计正确/局部/遗漏/错误/合理不足/澄清；任务或 QA 完成不能生成成功奖励。新报告的人审仍与参考边界人审分开，训练始终关闭。
- [x] 更新 README、Agent 执行说明和交付/结构化结果；按既有授权提交推送当前分支，不合并主分支、不强推、不提交凭据或原始资料。
