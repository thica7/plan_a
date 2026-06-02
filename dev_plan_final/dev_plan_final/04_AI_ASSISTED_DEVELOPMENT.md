# 04 · AI 辅助开发的真实记录方式

> **核心论点**：不要伪造 TRAE 截图来满足 D4 评分项。**用真实的 ADR + commit message + AI_ASSISTED_DEVELOPMENT.md 三件套，记录真实的 AI 协作过程。**

## 4.1 为什么不伪造

### Codex 评审的判决

> "现在开始初始化 Git / 从现在开始做真实 commits / 补 AI_ASSISTED_DEVELOPMENT.md / 记录真实使用过的 AI 工具 / 不要伪造历史 / 不要为了评分制造开发轨迹。"

### 伪造的代价

| 风险 | 概率 | 后果 |
|---|---|---|
| 评委用 `git log --pretty=format:'%ad %s' --date=relative` 看时间分布 | 高 | 跳跃明显被识破 |
| 评委对比 commit 时间和文件改动行数（巨型 commit）| 中 | 工程纪律质疑 |
| 评委追问"D 月 X 日为什么改了 Y 文件" | 中 | 答不上来 |
| 团队内部 git history 与实际开发不符 | 高 | 后续 git blame / bisect 失效 |
| 工程伦理被质疑 | 低但严重 | 整个团队信誉损失 |

**伪造的最佳结局是评委不细看，最坏结局是项目失分 + 信誉受损。期望值远低于不伪造。**

## 4.2 真实记录的三件套

```
1. AI_ASSISTED_DEVELOPMENT.md  · 总览 + 协作模式 + 工具清单
2. docs/decisions/*.md         · ADR (Architecture Decision Record)
3. Conventional Commits        · commit message 里嵌 AI 协作痕迹
```

这三件套**不需要截图**。

## 4.3 docs/AI_ASSISTED_DEVELOPMENT.md 模板

```markdown
# AI-Assisted Development · 协作记录

> 本文档记录 plan_a 项目使用 AI 工具辅助开发的真实情况。

## 1. 项目背景

- 项目代号：plan_a
- 启动时间：2026-04（最初本地备份开发）
- 迁移到 Git：2026-05-28
- AI 协作时长：占总开发时间约 60%

## 2. 使用的 AI 工具

| 工具 | 用途 | 使用时长（占比） |
|---|---|---|
| Claude Code (CLI) | 架构讨论 + 多步规划 + ADR 撰写 | 30% |
| Cursor IDE | 日常编码 + 单文件 refactor | 20% |
| Copilot Chat | 代码审查 + 测试 case 生成 | 10% |
| 其他（视情况）| - | - |

> 课题原文要求"TRAE 等 AI 编程工具"。"等"字给了灵活性，
> 我们使用 Claude Code / Cursor / Copilot 都属于此范畴。

## 3. 协作模式

我们采用 **Spec → Design → Tasks → Implement → Review** 五阶段：

### 3.1 Spec（问题陈述）

每个非平凡变更先写 spec：
- 问题是什么
- 为什么现在做
- 验收标准

落地为 `.harness/changes/CHANGE-NNN/spec.md`（如有该结构）或 `docs/decisions/NNNN-*.md` (ADR)。

### 3.2 Design（方案选项）

让 AI 给出 2-3 个方案选项，对比 trade-offs：
- 工时
- 风险
- 演化方向

人工选择，落地为 `docs/decisions/NNNN-*.md`。

### 3.3 Tasks（任务分解）

把方案拆为子任务（每个 ≤ 1 天）。AI 生成清单，人工调整。

### 3.4 Implement（编码）

- 简单改动：Cursor 直接生成
- 复杂改动：Claude Code 多步规划 + 引用文件
- TDD：先让 AI 写测试，再写实现

### 3.5 Review

- 自审：让 AI 审查自己的代码（不同 AI 工具交叉评）
- 人工：关键改动至少 1 人外审

## 4. 关键 AI 协作产物

### 4.1 架构决策（ADR）

详见 `docs/decisions/`：
- ADR-0001: 为什么选 LangGraph 而非 CrewAI
- ADR-0002: 为什么 5 级 RedoScope（而非 3 级或 7 级）
- ADR-0003: L1/L2/L3 三层竞品建模的取舍
- ADR-0004: yaml 规则引擎 vs hard-code QA
- ADR-0005: Evidence Center 的数据模型选型
- ...

每个 ADR 包含：
- Context（背景）
- Considered Options（候选方案）
- Decision（决定）
- Consequences（后果）
- AI Conversation Excerpt（关键对话摘录，可选）

### 4.2 关键 prompt 模板

存放在 `prompts/templates/`：
- `architecture_review.md` —— 架构评审 prompt
- `code_review.md` —— 代码审查 prompt
- `test_generation.md` —— 测试用例生成
- `adr_drafting.md` —— ADR 起草

### 4.3 Lesson Learned

`.harness/changes/CHANGE-NNN/lessons.md` 或 `docs/lessons/`：
- 哪些 AI 建议被采纳，效果好的
- 哪些 AI 建议被驳回，理由
- 哪些 AI 误导我们走过弯路

## 5. 度量（每月统计）

| 月 | AI 协作小时 | 总开发小时 | 占比 | AI 建议采纳率 |
|---|---|---|---|---|
| 2026-04 | ~50h | 80h | 62% | 65% |
| 2026-05 | ~60h | 100h | 60% | 60% |
| 2026-06 | TBD | TBD | TBD | TBD |

## 6. 典型案例

### 案例 1: ADR-0003 L1/L2/L3 建模

**背景**：CIMatrix 提出三层竞品模型，我们要不要借鉴。

**与 AI 的关键对话**（摘录）：
- Q（我）："CIMatrix 的 L1/L2/L3 真的有用吗？感觉有点过度工程"
- A（Claude）："L1/L2/L3 不是装饰，是 AI 应用领域的真实结构。直接产品 / 平台基建 / 模型供应商三层是垂直整合的现实。值得借鉴。但要注意：不要硬塞所有竞品到三层，允许 'unknown layer' 兜底。"
- Q："如果用户输入 'AI 编程助手'，怎么决定 layer = product？"
- A："让 planner 先做 web_search 看 top-3 结果，如果都是 IDE / 工具产品，layer = product；如果都是 SDK / API，layer = platform；如果都是大模型，layer = model。"

**结论**：采纳 + 加 'unknown' 兜底。落地为 ADR-0003 + Phase 2 实现。

### 案例 2: 驳回 AI 建议（不要全栈替换 Pydantic-AI）

**背景**：AI 建议把所有 7 个 agent 重写为 Pydantic-AI。

**与 AI 的关键对话**：
- A（Cursor）："建议把 collector / analyst / planner / writer / qa / comparator / reflector 全部用 Pydantic-AI 重写。"
- Q（我）："工时呢？"
- A："7 agent × 2 天 = 14 天"
- Q（我）："但我们 8 周内要交付。重写有 regression 风险。是否可以渐进？"
- A："可以分两批：先重写 collector / analyst（最复杂），后续 7 个 agent 留 Phase 4。"

**结论**：驳回全量重写，采纳渐进方案。落地为 Phase 3 用 Pydantic-AI 写新 agent，Phase 4 再重写复杂的 2 个。

（更多案例略，每个 PR 的关键决策都可写一段）

## 7. 工具配置

### Claude Code 配置

`.claude/settings.json`：
```json
{
  "model": "claude-opus-4-7",
  "allowedTools": ["Read", "Edit", "Write", "Bash", "Grep"],
  "maxTokens": 16000,
  "systemPrompt": "..."
}
```

### Cursor 配置

`.cursor/rules`：
```
- Always follow Pydantic v2 strict schema (extra="forbid")
- All agent outputs must be typed
- Test-driven: write tests before implementation for non-trivial changes
- Use Conventional Commits format
- Reference relevant ADR in commit message
```

## 8. 可追溯证据

### Git 元数据

每个 commit 信息含 AI 协作痕迹：
```
feat(qa): add yaml-driven rule engine

- 8 rules covering phantom citation, schema, coverage, consistency
- Replaces hard-coded checks in qa/logic.py
- Maintains 5-level RedoScope routing

Refs: ADR-0004
Co-authored-by: Claude <noreply@anthropic.com>
```

### Conventional Commits 元数据

我们使用：
- `Co-authored-by: Claude` 当 AI 主导设计
- `Refs: ADR-NNNN` 引用决策
- `Closes #NN` 关联 issue

### Issue / PR 评论

PR 评论里附 AI 评审 + 人工答复：
- AI Reviewer Bot 自动评论
- 团队成员 reply 采纳或驳回

## 9. 文档审计

定期检查（每月）：
- ADR 数量与 commit 数量比例（健康：每 5-10 个 commit 有 1 个 ADR）
- AI 协作时长是否符合预期
- 是否有重要决策遗漏 ADR

## 10. 致工程伦理

我们不伪造工具使用痕迹。所有截图（如有）来自真实开发过程，不为评分单独制造。

---

最后更新：2026-XX-XX
作者：项目团队
```

## 4.4 docs/decisions/ ADR 模板

```markdown
# ADR-NNNN: 标题（动词 + 决定）

- 状态：[Proposed | Accepted | Deprecated | Superseded by ADR-XXXX]
- 日期：YYYY-MM-DD
- 决策者：@username1, @username2
- 相关：ADR-XXXX, Issue #NN, PR #MM

## Context

问题陈述（2-3 段）。
- 当前情况
- 为什么需要决定
- 已知约束

## Considered Options

### Option A: ...
- 优点
- 缺点
- 工时

### Option B: ...
- 优点
- 缺点
- 工时

### Option C: ...
（可选）

## Decision

我们选择 **Option X**，因为...

## Consequences

### Good
- 预期收益 1
- 预期收益 2

### Bad
- 预期代价 1
- 预期代价 2

### Neutral
- 中性影响

## AI Conversation Excerpt（可选）

```
Q: ...
A: ...
Q: ...
A: ...
```

## Implementation Notes

- 关键文件：`packages/...`
- 关键测试：`tests/...`
- 迁移影响：...

## Review

[ ] 技术负责人审批
[ ] 至少 1 人外审
[ ] ADR 落库
```

## 4.5 Conventional Commits + AI 痕迹

### Commit message 格式

```
<type>(<scope>): <subject>

<body 详细说明>

<footer>
- Refs: ADR-NNNN
- Closes: #NN
- Co-authored-by: Claude <noreply@anthropic.com>
```

### 常见 type

```
feat: 新功能
fix: 修 bug
docs: 文档
chore: 杂项（依赖更新 / 配置）
refactor: 重构（无功能变化）
test: 测试
perf: 性能优化
style: 格式（不影响逻辑）
```

### Scope（plan_a 项目）

```
schema: Pydantic 模型
orchestrator: LangGraph 图
agents/{collector,analyst,planner,...}: 各 agent
qa: QA 模块
skills: 维度 yaml
tools: 工具
frontend: 前端
docs: 文档
```

### 实例

```
feat(qa): add yaml rule engine with 8 rules

- R001 phantom citation detection
- R002 minimum evidence per claim
- R003-R005 matrix consistency rules
- R006-R008 coverage / staleness rules
- Replaces hard-coded checks in qa/logic.py
- Maintains 5-level RedoScope routing

Refs: ADR-0004
Co-authored-by: Claude <noreply@anthropic.com>
```

```
fix(planner): verify_homepage now retries 3 candidate TLDs

Bug: when user inputs 'Cursor' without URL, hardcoded 
to https://cursor.sh which sometimes 404s.

Fix: try .com / .io / .ai / .co in sequence, return first valid.

Refs: #45
```

## 4.6 关键案例：D3 评分如何最大化

### 现状（plan_a v2）
```
Git history: 0 commits → D3 = 0 分（满分 8）
```

### Phase 1 末（W2）
```
Git history: ~30 commits across 2 weeks
- 真实 commit
- 规范 message
- 引用 ADR
- Co-authored-by 标记
→ D3 ≈ 5 分
```

### Phase 3 末（W10）
```
Git history: ~120 commits across 10 weeks
- 5+ feature 分支
- ADR-0001 ~ ADR-0010
- AI_ASSISTED_DEVELOPMENT.md
- 每个 PR 有 review 评论
→ D3 ≈ 6-7 分
```

### 答辩话术

如果评委问"git history 为什么只有 10 周"：

```
"我们之前用本地备份开发了几个月，2026-05-28 迁移到 Git。
迁移时我们做了几个决定：
1. 不伪造历史 commit 时间
2. 写 AI_ASSISTED_DEVELOPMENT.md 说明开发流程
3. 之前的关键决策追溯写成 ADR

虽然 Git history 短，但工程纪律是真实的。可以提供：
- 本地备份的 changelog（如有）
- 历次 ADR 的真实日期
- AI 协作的对话记录摘录

我们认为真实 + 短 history 比伪造长 history 更符合工程伦理。"
```

**评委如果是真工程师，这个回答会得到尊重而不是扣分。**

## 4.7 D4 评分如何最大化

### 现状（plan_a v2）
```
TRAE / AI 工具痕迹: 0 → D4 = 0 分（满分 ~6）
```

### Phase 1 末（W2）
```
- AI_ASSISTED_DEVELOPMENT.md ✅
- ADR-0001 ~ ADR-0003 ✅
- Cursor / Claude Code 真实使用 ✅
- 不伪造截图
→ D4 ≈ 3-4 分
```

### Phase 3 末（W10）
```
- AI_ASSISTED_DEVELOPMENT.md（10 周累积）✅
- ADR-0001 ~ ADR-0010 ✅
- prompts/templates/ ✅
- Co-authored-by 痕迹 ✅
- lessons.md / 案例分析 ✅
→ D4 ≈ 4-5 分
```

**比伪造截图能拿到的 5 分更扎实，且没有信誉风险。**

## 4.8 工时估算

| 任务 | 工时 |
|---|---|
| 写 AI_ASSISTED_DEVELOPMENT.md 初版 | 0.5d |
| ADR 模板 + ADR-0001 ~ ADR-0003 | 1d |
| 配置 Conventional Commits（git hook 检查）| 0.3d |
| Cursor / Claude Code 配置文件 | 0.2d |
| 后续每周维护 | 0.5d/周 |

**Phase 1 总投入**：~2 工日
**全周期持续投入**：~5-7 工日

## 4.9 一句话总结

> **真实的 AI 协作记录三件套（AI_ASSISTED_DEVELOPMENT.md + ADR + Conventional Commits）能为 D3+D4 拿到 8-12 分，比伪造的 10-12 分更稳，且没有信誉风险。**

---

> 下一步：阅读 [05_DATA_MODELS.md](./05_DATA_MODELS.md) 了解 Workspace/Project/Competitor Library 三层数据模型。
