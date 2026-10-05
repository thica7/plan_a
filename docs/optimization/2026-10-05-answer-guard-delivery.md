# 共享事实核验交付记录

本轮基于 `549e5871deef11ed927d6aaf32ffc28f20c9f80b`，执行已确认的Writer与QA共享事实核验计划。规格与最终质量审查通过。

## 范围

复用不可变证据快照，逐项判断已有资料允许陈述哪些事实、哪些需要补条件。检索非空不代表能够给出完整答案；缺项也不要求拒绝全部相关事实。

本轮不更换embedding、不迁移真实知识库、不调用外部或本机模型推理。原候选与reviewed-v2共8份评测资料保持冻结。用户的四条审核决定仍是回答策略，未将缺价格或缺账单的题目升级成完整答案gold。

## 共享内核

`evaluate_answer_boundary(view, requirement)`返回不可变记录，包含允许/扣留事实、缺项、澄清条件与原始所见来源及事实集合。状态为`answer`、`partial`、`clarify`或`insufficient`。

- 当前价格：结构化金额与币种、具体设备或套餐范围、计费与税费口径、真实核验时间及市场；近7日核验不能由近期抓取旧发布价替代。
- 官方展示单价：仅`official_current + listed_unit + tax_scope=unknown`允许有限陈述，并保留税费缺项，不能当含税到手价。
- 渠道比较：固定渠道集合、币种、容量、成色、观察窗口、运费与优惠条件；日期窗口为UTC全天，含时刻窗口及观察需明确时区。不计算均价或换汇。
- 完整成本：要求明确适用费用项、报告期间、币种和实际费用记录；订阅机制不证明全部账单。
- 合规：先明确行业、地区、标准与用途；普通功能说明不能支持合规结论。
- 来源指导：保留可用的核验方法与部分事实，不因没有完整价格矩阵拒答整个方法题。

请求条件不会补造证据字段。异常JSON价格类型、布尔优惠条件、含时刻窗口中的日期观察均有回归测试。

## 回放证据

内核首次RED为61项行为断言失败；追加比较规则9项、优惠条件1项、异常元数据15项均先观察实际失败，再修复。规格与质量审查分别指出优惠条件遗漏和异常输入检查遗漏，已修复并复审通过。

工作流首次RED为7项；追加接点与输出审计6项失败；报告/要求篡改路由3项失败。规格复审再复现币种前负号、币种识别、卡片金额和仅卡片引用撤源，7项失败；常见小写币种2项失败；缺金额币种登记1项失败，均观察实际失败后修复。最终关联回放为399项（111内核、48工作流、240既有证据流程），均通过。

首次全量得到2项失败、2982项通过、1项跳过。两项失败来自引用规范化正例只有裸金额、缺报价条件却期待完整报价通过。仅补齐该测试的本地结构化报价输入，保留全部原断言和全局fixture；该集成文件62项通过。未放宽生产守卫。

交付前最终完整后端：**2984 passed, 1 skipped, 152 warnings in 61.85s，exit 0**。跳过项为未配置独立Postgres的RLS smoke；警告为既有FastAPI `on_event`弃用提示。11份Python文件增量lint无新增诊断；8份冻结资料哈希未改变；本轮提交文件密钥扫描与`git diff --check`通过。外部和本机模型推理调用均为0。

本机验证使用隔离助手`/private/tmp/plan_a_phase2_full_verify.py`：移除外部模型与Postgres凭据、关闭env文件加载，运行目录和KB路径放在临时目录。助手为本机临时文件，不随Git交付；其他环境复现需同等隔离。本轮不读取真实运行目录、知识库或账单。

```text
../plan_a/.venv/bin/python /private/tmp/plan_a_phase2_full_verify.py

../plan_a/.venv/bin/python /private/tmp/plan_a_phase2_full_verify.py -q \
  backend/tests/unit/test_answer_guard.py \
  backend/tests/unit/test_answer_guard_workflow.py \
  backend/tests/unit/test_run_evidence_snapshot.py \
  backend/tests/unit/test_stage_evidence_views.py \
  backend/tests/unit/test_evidence_snapshot_scope.py \
  backend/tests/unit/test_evidence_snapshot_graph.py --tb=short
```

## 接点与接入方式

`AnalysisPlan.answer_requirements`为可选列表，旧计划默认为空；`RunDetail.report_answer_boundaries`保存实际生成边界，旧报告默认为空。默认策略仅依据明确的计划维度类别：定价为`current_price`，完整成本为`total_cost`，合规为`compliance`，其他为`facts`。默认研究日取运行创建日（UTC）；默认市场只有所选资料唯一明确市场时才能采用，多市场不任选一项。

需要只答核验方法时，显式声明`source_guidance`。要求进入已有计划数据结构，本轮未新增前端配置表单。例如：

```python
from datetime import date
from packages.research.evidence.answer_models import AnswerRequirement

plan.answer_requirements = [
    AnswerRequirement(
        competitor="目标产品",       # 与plan.competitors一致
        dimension="pricing",         # 与plan.dimensions一致
        intent="source_guidance",
        market="CN",
        as_of=date(2026, 10, 5),
    )
]
```

比较所需`context_json`是JSON对象字符串，声明`channels`、`currency`、`capacity`、`condition`、`window_start`和`window_end`；完整成本声明`required_components`、`reporting_period`、`currency`；合规声明`industry`、`jurisdiction`、`compliance_standard`和`intended_use`。这些是请求范围，不能替资料提供实际观察或费用。

Writer分段把核验记录和短约束放入实际提示预算，预算不够则明确拒绝，不默默删除边界。最终生成记录与报告producer哈希绑定，随journal持久化；生成失败不提交，保留旧报告不伪造新核验。QA还原原生成视图及原要求后核验，不把后来新增来源视作生成时已见资料。

正文与`ClaimCard.claim`共用金额审计。金额按段落或表行的本地引用核对，正式标题与带符号金额也进入检查。常见13种币种支持大小写，其余登记币种按大写代码识别；静态代码及事实明确声明的币种都可检测，缺金额不会妨碍登记。紧邻币种的负号参与数值核验，Markdown列表的`- CNY 3999`不当作负价；未宣称支持所有语言、科学计数法或会计格式。

结构化审计覆盖`ReportArtifactV2.claim_card_bundles[].cards`中的声明`metadata.fact_ids`，以及明确的完整成本/合规结论类型；依据该卡片实际来源与声明事实重核，不依靠同产品其他来源自动支持。卡片单独引用的来源也进入现有来源有效性检查。`DecisionCard`的任意语义未扩审计。审计附录中的原始金额不作为当前正式结论审计。

新核验违规返回具体`writer_only`修复；真实来源失效仍保留collector路径。缺项本身不会单独生成发布阻断或无穷补采集要求。无边界记录的旧报告保留原producer及引用审核路径，不能因此声称已通过新核验。

## 限制与后续

回答要求的研究日期固定保存；现有`select_evidence_view`及producer回放仍按当前时钟检查资格。证据变旧可能使原producer不再满足发布条件，不能用后来资料替其补认证。离线接点测试固定视图时钟，不代表历史报告在任意时点都可重新发布。本轮未改此既有资格策略。

字段完整性和确定性输出审计不等于对任意自由文本的语义认证。价格数值相同也不能单独证明套餐、税费描述完全正确。本轮不宣称真实LLM报告准确率或RAG已合格。

现有自动价格归一化仍将`NormalizedPricingField.price`保存为字符串，`normalization._pricing_rows`也按文本处理，通常没有保留新守卫需要的金额、币种、税费、席位及核验条件。本轮不会从字符串猜造这些字段。因此完整价格正例只证明固定结构化资料可以通过守卫，不能宣称真实自动采集价格已打通；旧文本报价会成为明确缺项。

下一步优先将真实采集的`price_rows`、归一化字段和证据存储打通为带原文与条件的结构化价格，并做端到端正反例验收。002仍需实际渠道集合、时间窗与逐条报价；038仍需完整账单和适用费用范围。之后增加更大的独立真实检索样本池与答案边界评测，再按单独授权回放真实生成器。
