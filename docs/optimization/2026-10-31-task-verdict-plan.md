# 按任务结构化审核与统一交付计划

继续执行用户已授权的 Writer 子任务选证、原子写作、正文／问答／QA一致性修复。复用 codex/pastoral-desktop；不新增基础设施、Docker、训练或前端功能。v1／v2真实原件和失败语义保留，不通过修改旧数据宣称交付。

## 已有证据

v2最终工程9300通过／1跳过，但四家固定快照真实回放仍0/4，8原题仅1通过／4部分／3失败；83次真实传输、291776已知token。44条任务传输中43条JSON合法，Cloudflare尾答有多余闭合对象。67个已查枚举字段没有错误，不能把所有失败归于模型格式。

Trello的B投票推论已审核，却因正文“故可对B的卡片投票”未被语言识别器识别而丢失。Bitwarden数量凭证真实签发，但尾答把另一题的澄清字段混入数量题，父字段组合导致已审结果不交付。Cloudflare角色能力描述还被旧fallback误当改权操作；CPU混入运行上限、1Password混合或强化主张的拒绝仍合理。

当前complete_json仅追加Prompt并宽松提取首对象，并非提供方结构化传输。[官方JSON模式](https://api-docs.deepseek.com/guides/json_mode/)与[Chat参数](https://api-docs.deepseek.com/api/create-chat-completion/)确认标准接口支持json_object；它不代替字段、引用或事实审核，也须处理空白及截断。本轮不迁移Responses／Beta端点。

## 选择的有界方案

保持SELECT→原子GEN→独立REVIEW；最终ANSWER改成同canonical原题的task批次审核，服务端只用这一份认证结果聚合父状态、正文及QA。相比只补JSON或继续扩大中文词表，该方案同时解决跨题父字段污染和已审核结论被词形漏识别的问题。相比通用推理框架，它只增加一个Writer内部合同模块。

1. 显式新增selected-task-atoms-v3及task-outcomes-v1。V1／V2实际SYSTEM、传输、解析和失败结果保持；新执行才走新路径，两个实验开关默认仍关闭。
2. 新task_answer_outcomes.py只处理server task_id、同题明确白名单已审claim/完整quote refs、typed outcome和本题允许的澄清字段。模型不再生成父status/resolution/missing_fields，不复制问题分段。不把普通规则合格自动当成场景判断完成。
3. 独立ANSWER仍真实执行。一个task坏行不吞同行；缺失、重复、跨task/qid、未审核claim或原始source quote冒充claim均拒。可用有界失败反馈局部重审坏task，成功peer保留，修复次数与总预算明确记录。
4. 数量纯AND否定复用reviewed_quantity_conjunction-v1的原限定关系，新任务批准从真实新wire签发并复验现有有界凭证；OR／混合任务不适用。不得删掉v2错误父字段后升级旧Bitwarden结果。
5. 结构化已审task outcome绑定任务对象及完整出处，正文的中文词形不再成为唯一权威；矛盾、角色／套餐条件、来源完整性和独立语义审核仍保留。正文、coverage与QA重建同一结果，历史finding及模型keep不强清。
6. 新模式显式发送response_format={type:json_object}，保留原始响应并严格解析完整根对象。HTTP模式、提供方、合同摘要进入trace、receipt/replay及相关缓存身份；默认旧请求不改。重复键、额外根、空白、length和不支持模式的provider明示失败，不能宽松取首对象或静默降级。
7. 仅v3原子REVIEW明确独立谓词数与精确子句审核；完整支持但明确多谓词的稿件不能发表，可局部重写。模型报单谓词不等于完美证明，原有条件、情态与来源守卫继续执行。
8. 已证Cloudflare源端误门做有限隔离：server任务不是改权，既有主谓词识别无真实改权断言，只有fallback把角色能力描述猜成manage_access时，必须取得实际子句REVIEW后才可判断资格。真实share/manage_access、额外改权子句、错角色／对象仍要求原operation或拒绝；不全局开放inference。

## 预算、范围与验收

诊断runner显式改为64calls／240000tokens、温度0、默认输出2048、transport retries=0，费用上限保持0.25美元。生产默认额度不改。每个局部生成或ANSWER审核的修复阶段有明确一次上限，不能隐藏重试；实际总数受全局上限、完整尾答与最终QA预留约束。该profile与48／160k不同，不能作同条件因果或降本比较。

预计源范围：新task_answer_outcomes.py，必要接线selected_task_delivery、question_atomic_delivery、task_decision_witnesses、dimension_writer、doubao_client、llm_execution，有限source资格需要时触report_claims；QA只做必要认证适配。允许在现有answer_review_contract枚举增加task-outcomes-v1并用标准工具同步OpenAPI／TypeScript；不新增DTO字段／端点或UI改版。实际新合同必须在audit、payload、receipt及trace一致披露，禁止把新raw伪装成subquestion-premises-v6，旧新标签混用必须拒绝。

唯一生产作者，先自包含红测试、最小实现、绿与旧记录回放；规格通过后独立质量审查。关键负例包括跨题／未审引用、错误澄清字段、OR／错误数量上限、错误role/SKU、真实改权无op、谓词数2仍supported、JSON模式HTTP缺失／篡改、空白／截断／多根、缓存模式混用和预算恢复。覆盖Trello已审A/B、Bitwarden真实数量凭证、局部坏task保peer及实际QA入口，不以mock存在代替生产接线。

新目录data/artifacts/writer-task-verdict-2026-10-31保存本轮；既有v1、v2原件及原样公开报告锁定。冻结后最终工程回归、同8题／22分支四家七生产阶段真实回放，再独立读正文与精确所选引用。固定2026-10-21快照仍不证明新抓取、完整Graph或未见样本泛化。更新交付、README、Agent文档并按既有授权推送原分支，不强推或合并main。

## 真实回归后的局部极性修正

第三轮已完成四家真实回归、独立正文审核及9335项后端检查，整报告仍0/4。只读诊断确认一个机械P2：任务allowed_outcomes根据父题是否封闭提问判定，把Cloudflare题设source_rule的“只被授予example.com角色”当作可回答yes/no的独立问题，no因此挂错任务。真正other.example任务仍未完成，不能借题设no补通过。

本次只修当前任务的极性资格：非问句题设/辅助规则不继承父题yes/no；真正场景子问仍可判断。保留角色/资源/数量前提、独立审核、原子性和未知，不顺便调整预算或扩大推理资格。先真实CF任务与通用双题设负例红→绿，补真正Workspace/跨资源及1Password子问正例；旧V1/V2合同不变，旧V3错误原件不升级，源SHA和失败重放差异明确记录。

新目录 `data/artifacts/writer-task-verdict-scopefix-2026-10-31` 锁1192份此前原件，包括第三轮V3结果和公开原样报告。增量规格/质量审查后，冻结、完整后端和同64calls/240k四家真实回放再验；不能改旧报告。新结果另写scopefix结果及报告，README/交付明确区分各轮。Docker与训练范围不变。
