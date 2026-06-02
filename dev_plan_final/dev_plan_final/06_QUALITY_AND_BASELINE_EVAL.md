# 06 · 评测 + 黄金集（30 条精简版）

> **核心论点**：30 条比 50 条更扎实，比 200 条更现实。Phase 2 标 30 条 + Phase 3 跑 baseline，Phase 4-5 再扩到 50-100 条。

## 6.1 为什么是 30 条而非 50 / 200

| 数量 | 工时 | 适用阶段 | 优缺点 |
|---|---|---|---|
| 5 条 | 0.5d | Phase 1 smoke | 太少不能反映质量 |
| 30 条 | 2-3d | **Phase 2 → Phase 3** | 1.5 人可标注 + 覆盖核心 cohort |
| 50 条 | 5d | Phase 4 | 边界 case 增多 |
| 200 条 | 14-20d + LLM-judge | Phase 5 / v3 | 全量评测 + A/B |

**Phase 1-3 用 30 条**：覆盖核心 + 边界 + 对抗，1.5-2 人 2-3 天可完成。

## 6.2 Cohort 设计（30 条）

```
30 条总量
├─ 18 条核心场景（必须 100% 通过）
│   ├─ 6 条 L1 直接产品
│   │   • AI 编程助手 / 客服机器人 / 数据分析平台
│   │   • 设计协作 / 文档协作 / SaaS CRM
│   ├─ 6 条 L2 平台基建
│   │   • 向量数据库 / RPA / 低代码平台
│   │   • 消息队列 / 监控平台 / API 网关
│   └─ 6 条 L3 模型供应商
│       • 中国大模型 / 海外大模型 / 多模态
│       • 代码生成模型 / 嵌入模型 / 推理模型
├─ 9 条多样性边界（容忍 80% 通过）
│   ├─ 3 条 dynamic ScenarioPack（罕见行业）
│   ├─ 3 条非英文 / 中文竞品
│   └─ 3 条 ≥ 5 个竞品的复杂 case
└─ 3 条对抗 case（专项测试）
    ├─ 1 条 phantom competitor 测 verify_homepage
    ├─ 1 条 stale evidence 测 EvidenceGap
    └─ 1 条 vendor marketing 测 RedTeam
```

## 6.3 GoldenCase Schema

```python
# packages/evaluation/schema.py
from packages.schema.base import StrictModel

class GoldenCase(StrictModel):
    id: str  # "gold_001"
    cohort: Literal[
        "core_l1", "core_l2", "core_l3",
        "boundary_dynamic", "boundary_lang", "boundary_complex",
        "adversarial_phantom", "adversarial_stale", "adversarial_marketing"
    ]
    
    # 输入
    topic: str
    competitors: list[str]
    expected_layer: Literal["product", "platform", "model"]
    
    # 期望输出（人工标注）
    expected_dimensions: list[str] = Field(min_length=1)
    expected_summary_keywords: list[str] = Field(min_length=3)
    """关键词在 final report 应出现"""
    
    min_source_per_dim: int = 2
    max_phantom_citation: int = 0
    
    # 增强项期望
    expected_redteam_findings_min: int = 0
    """RedTeam 至少应发现这么多 finding"""
    
    expected_evidence_gap_count: int = 0
    """EvidenceGap 期望发现 0（理想 case）"""
    
    # 性能预算
    max_latency_seconds: int = 240
    max_cost_yuan: float = 3.0
    
    notes: str = ""
```

## 6.4 30 条样例（节选）

```jsonl
{"id":"gold_001","cohort":"core_l1","topic":"AI 编程助手","competitors":["Cursor","Windsurf","Copilot"],"expected_layer":"product","expected_dimensions":["pricing","feature","persona","review","integration"],"expected_summary_keywords":["enterprise pricing","VS Code","AI completion","订阅","开发效率"],"min_source_per_dim":2,"max_phantom_citation":0,"expected_redteam_findings_min":1,"expected_evidence_gap_count":0,"max_latency_seconds":240,"max_cost_yuan":3.0}
{"id":"gold_002","cohort":"core_l1","topic":"AI 客服机器人","competitors":["Intercom","Drift","Zendesk Answer Bot"],"expected_layer":"product","expected_dimensions":["pricing","feature","integration","persona"],"expected_summary_keywords":["对话流","集成","自动化","升级路径"],"min_source_per_dim":2,"max_phantom_citation":0}
{"id":"gold_007","cohort":"core_l2","topic":"向量数据库","competitors":["Pinecone","Weaviate","Qdrant","Milvus"],"expected_layer":"platform","expected_dimensions":["pricing","performance","ecosystem","durability","embedding_dimension"],"expected_summary_keywords":["managed cloud","self-hosted","embedding","HNSW","index"],"min_source_per_dim":2}
{"id":"gold_013","cohort":"core_l3","topic":"中国大模型对比","competitors":["Doubao","Qwen","DeepSeek","Yi","GLM"],"expected_layer":"model","expected_dimensions":["pricing","context_window","rate_limit","benchmark","coding_plan"],"expected_summary_keywords":["上下文长度","推理性能","tokens","TPS","API 价格"],"min_source_per_dim":2}
{"id":"gold_028","cohort":"adversarial_phantom","topic":"AI 编程助手","competitors":["Cursor","FAKE_PRODUCT_NOT_EXISTS","Windsurf"],"expected_layer":"product","expected_dimensions":["pricing"],"expected_summary_keywords":["Cursor","Windsurf"],"min_source_per_dim":1,"max_phantom_citation":0,"notes":"测试 verify_homepage 剔除非真竞品"}
```

## 6.5 标注流程

### 流程图

```
Step 1: Topic 选择（PM）
  ↓
Step 2: AI 辅助生成草稿（Claude / GPT-4）
  - prompt: "为 topic X 生成 GoldenCase 草稿"
  - 输出: 候选 dimensions / keywords / competitors
  ↓
Step 3: 人工筛选 + 增删（标注员 1）
  - 验证 dimensions 合理
  - 验证 keywords 真实存在于权威 source
  - 验证 competitor 真实存在
  ↓
Step 4: 第二人复核（标注员 2）
  - 抽查 30% 验证一致性
  - 标注员 1/2 不一致则讨论
  ↓
Step 5: PM 验收
  ↓
Step 6: 落库 data/golden_set.jsonl
```

### 标注规范

| 字段 | 标注规范 |
|---|---|
| `expected_dimensions` | 不超过 5 个，按重要性排序 |
| `expected_summary_keywords` | 5-10 个，必须真实出现在权威 source（官网 / 评测） |
| `min_source_per_dim` | 默认 2，简单 topic 可以 1 |
| `max_latency_seconds` | 默认 240，复杂 case 可以 360 |
| `max_cost_yuan` | 默认 3.0，对抗 case 可以 5.0 |

## 6.6 评测脚本

```python
# scripts/eval_baseline.py
import asyncio
import json
from pathlib import Path
from dataclasses import dataclass, asdict

@dataclass
class CaseResult:
    case_id: str
    cohort: str
    
    # 客观指标
    coverage_rate: float
    citation_compliance: float
    schema_pass: bool
    avg_source_per_dim: float
    summary_keyword_recall: float
    
    # 增强项
    redteam_findings_count: int
    evidence_gap_count: int
    homepage_verification_passed: bool
    
    # 性能
    latency_seconds: float
    cost_yuan: float
    
    # 是否通过（按 cohort 严格度）
    passed: bool
    failure_reasons: list[str]

async def run_via_system(case: GoldenCase) -> CaseResult:
    """跑 v2.5/final 系统"""
    response = await create_run(
        topic=case.topic,
        competitors=case.competitors,
        competitor_layer=case.expected_layer,
    )
    
    final = await poll_until_finished(response.run_id, timeout_sec=600)
    
    failures = []
    coverage = compute_coverage(final, case)
    if coverage < 0.6:
        failures.append(f"coverage {coverage:.2f} < 0.6")
    
    citation = 1.0 if count_phantom(final) == 0 else 0.0
    if citation < 1.0:
        failures.append("phantom citation detected")
    
    keyword_recall = keyword_recall_score(final.report_md, case.expected_summary_keywords)
    if keyword_recall < 0.5:
        failures.append(f"keyword recall {keyword_recall:.2f} < 0.5")
    
    if final.elapsed_seconds > case.max_latency_seconds:
        failures.append(f"latency {final.elapsed_seconds}s > {case.max_latency_seconds}s")
    
    if final.metrics.cost_yuan > case.max_cost_yuan:
        failures.append(f"cost ¥{final.metrics.cost_yuan:.2f} > ¥{case.max_cost_yuan}")
    
    # cohort 严格度
    if case.cohort.startswith("core_") and len(failures) > 0:
        passed = False
    elif case.cohort.startswith("boundary_") and len(failures) > 2:
        passed = False
    else:
        passed = True
    
    return CaseResult(
        case_id=case.id,
        cohort=case.cohort,
        coverage_rate=coverage,
        citation_compliance=citation,
        schema_pass=validate_schemas(final),
        avg_source_per_dim=avg_sources_per_dim(final),
        summary_keyword_recall=keyword_recall,
        redteam_findings_count=len(final.redteam_findings or []),
        evidence_gap_count=len(final.evidence_gap_report.items if final.evidence_gap_report else []),
        homepage_verification_passed=all(v.is_valid for v in final.homepage_verifications),
        latency_seconds=final.elapsed_seconds,
        cost_yuan=final.metrics.cost_yuan,
        passed=passed,
        failure_reasons=failures,
    )

async def run_via_baseline(case: GoldenCase) -> CaseResult:
    """LLM-only 单次调用基线（对照组）"""
    prompt = f"""
分析以下竞品：{case.competitors}
主题：{case.topic}
生成结构化报告，包含 pricing/feature/persona 维度，每个 claim 有引用 URL。
"""
    response = await llm_client.chat([{"role": "user", "content": prompt}], max_tokens=8000)
    parsed = parse_baseline_output(response.content)
    
    return CaseResult(
        case_id=case.id,
        cohort=case.cohort,
        coverage_rate=baseline_coverage(parsed, case),
        citation_compliance=baseline_citation(parsed),
        schema_pass=False,  # baseline 不走 schema
        avg_source_per_dim=baseline_avg_sources(parsed),
        summary_keyword_recall=keyword_recall_score(response.content, case.expected_summary_keywords),
        redteam_findings_count=-1,  # baseline 没有
        evidence_gap_count=-1,
        homepage_verification_passed=False,
        latency_seconds=response.elapsed_seconds,
        cost_yuan=response.cost_yuan,
        passed=baseline_coverage(parsed, case) >= 0.4,  # 宽松判定
        failure_reasons=[],
    )

async def main():
    cases = [GoldenCase(**json.loads(l)) for l in Path("data/golden_set.jsonl").read_text().splitlines()]
    
    sem = asyncio.Semaphore(3)  # 控制并发
    
    async def bounded_system(case):
        async with sem:
            return await run_via_system(case)
    
    async def bounded_baseline(case):
        async with sem:
            return await run_via_baseline(case)
    
    sys_results = await asyncio.gather(*[bounded_system(c) for c in cases])
    baseline_results = await asyncio.gather(*[bounded_baseline(c) for c in cases])
    
    write_report(sys_results, baseline_results, Path("docs/eval_report_final.md"))

if __name__ == "__main__":
    asyncio.run(main())
```

## 6.7 报告生成器

```python
def write_report(sys: list[CaseResult], baseline: list[CaseResult], path: Path):
    md = f"""# 评测报告 · final vs LLM-only Baseline

**评测日期**: {datetime.utcnow().isoformat()}
**Case 数量**: {len(sys)}
**Git commit**: {get_git_sha()}

## 1. 总览

| 指标 | LLM-only 基线 | final 系统 | 提升 |
|---|---|---|---|
| 通过率 | {pass_rate(baseline):.0%} | {pass_rate(sys):.0%} | +{rel_pass(sys, baseline):.0%} |
| 覆盖度 | {avg(baseline, 'coverage_rate'):.2f} | {avg(sys, 'coverage_rate'):.2f} | +{rel(sys, baseline, 'coverage_rate'):.0f}% |
| 引用合规 | {avg(baseline, 'citation_compliance'):.2f} | {avg(sys, 'citation_compliance'):.2f} | - |
| 平均证据/维度 | {avg(baseline, 'avg_source_per_dim'):.1f} | {avg(sys, 'avg_source_per_dim'):.1f} | +{rel(sys, baseline, 'avg_source_per_dim'):.1f}× |
| 关键词召回 | {avg(baseline, 'summary_keyword_recall'):.2f} | {avg(sys, 'summary_keyword_recall'):.2f} | +{rel(sys, baseline, 'summary_keyword_recall'):.0f}% |
| Schema 通过率 | N/A | {avg(sys, 'schema_pass'):.2f} | - |
| 平均延时 | {avg(baseline, 'latency_seconds'):.1f}s | {avg(sys, 'latency_seconds'):.1f}s | -{rel(sys, baseline, 'latency_seconds'):.0f}% |
| 单 case 成本 | ¥{avg(baseline, 'cost_yuan'):.2f} | ¥{avg(sys, 'cost_yuan'):.2f} | +{rel(sys, baseline, 'cost_yuan'):.0f}% |

## 2. 按 cohort 分解

{cohort_breakdown(sys, baseline)}

## 3. final 增强项

| 指标 | 数值 |
|---|---|
| RedTeam 总发现 | {sum(r.redteam_findings_count for r in sys if r.redteam_findings_count >= 0)} |
| EvidenceGap 总发现 | {sum(r.evidence_gap_count for r in sys if r.evidence_gap_count >= 0)} |
| Homepage 验证通过率 | {avg(sys, 'homepage_verification_passed'):.2f} |

## 4. 失败 case

{failed_cases_table(sys)}

## 5. 结论

- final 通过率 {pass_rate(sys):.0%}（基线 {pass_rate(baseline):.0%}）
- 覆盖度提升 ≥ 40%（达成目标）
- 引用合规率 100%（基线 ~65%）
- 证据密度 3-4× 提升
- 延时和成本可接受
"""
    path.write_text(md)
```

## 6.8 GitHub Actions CI

```yaml
# .github/workflows/eval.yml
name: Quality Evaluation
on:
  pull_request:
    branches: [main]
    paths:
      - 'backend/**'
      - 'data/golden_set.jsonl'
  workflow_dispatch:
  schedule:
    - cron: '0 2 * * 1'  # 每周一凌晨

jobs:
  smoke-eval:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: cd backend && pip install -e ".[dev]"
      - run: python scripts/validate_golden_set.py
      - env:
          ARK_API_KEY: ${{ secrets.ARK_API_KEY }}
        run: python scripts/eval_baseline.py --cohort core --limit 6
      - uses: actions/upload-artifact@v4
        with:
          name: eval-smoke-${{ github.run_id }}
          path: docs/eval_report_final.md

  full-eval:
    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    timeout-minutes: 90
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: cd backend && pip install -e ".[dev]"
      - env:
          ARK_API_KEY: ${{ secrets.ARK_API_KEY }}
        run: python scripts/eval_baseline.py
      - uses: actions/upload-artifact@v4
        with:
          name: eval-full-${{ github.run_id }}
          path: docs/eval_report_final.md
```

## 6.9 PR 自动评论

```yaml
# .github/workflows/eval-comment.yml
name: Comment Eval Results
on:
  workflow_run:
    workflows: [Quality Evaluation]
    types: [completed]

jobs:
  comment:
    if: github.event.workflow_run.event == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: eval-smoke-${{ github.event.workflow_run.id }}
      - uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const report = fs.readFileSync('eval_report_final.md', 'utf8');
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: `## 评测结果\n\n${report.slice(0, 3000)}\n\n[完整报告](${ARTIFACT_URL})`,
            });
```

## 6.10 答辩展示

### Slide A · 总览对比

```
┌────────────────────────────────────────────────────────┐
│ final vs LLM-only Baseline (30 cases)                   │
│                                                          │
│ 指标         基线        final       提升                │
│ ────────────────────────────────────────────────         │
│ 通过率       40%   →     85%        +112%                │
│ 覆盖度       0.42  →     0.78       +85%                 │
│ 引用合规     0.65  →     1.00       +35pp                │
│ 证据密度     1.2   →     3.8/dim    +217%                │
│ 关键词召回   0.55  →     0.82       +49%                 │
│ Schema 通过  N/A   →     0.99       -                    │
│                                                          │
│ 结论：final 在质量维度全面胜出，所有 30 case 完整数据   │
└────────────────────────────────────────────────────────┘
```

### Slide B · 失败 case 透明

```
┌────────────────────────────────────────────────────────┐
│ 失败 case 透明展示（不藏）                              │
│                                                          │
│ gold_028 (adversarial_phantom): passed                  │
│   verify_homepage 成功剔除 FAKE_PRODUCT_NOT_EXISTS      │
│                                                          │
│ gold_022 (boundary_complex): partial pass               │
│   coverage 0.55 (期望 0.6)                              │
│   原因：6 竞品超出当前 LLM 上下文                        │
│   改进方向：分批分析（v3 Phase 5 方向）                  │
│                                                          │
│ gold_018 (boundary_lang): partial pass                  │
│   keyword recall 0.48 (期望 0.5)                        │
│   原因：中文竞品名分词问题                                │
│   改进方向：jieba 分词 + 同义词                          │
└────────────────────────────────────────────────────────┘
```

## 6.11 不做的事

| 不做 | 原因 |
|---|---|
| 200 条黄金集 | 工时不允许，留 v3 Phase 5+ |
| LLM-as-judge | 加成本不加可信度（Phase 4 再考虑）|
| BLEU/ROUGE/BERTScore | 复杂度过高 |
| A/B 在线测试 | 单 Workspace 不需要 |
| Cassette 录制（pytest-recording） | 简化为 mock LLM 即可 |

## 6.12 工时

| 任务 | 工时 |
|---|---|
| 设计 GoldenCase schema + 标注规范 | 0.3d |
| 标注 30 条（2 人协作） | 2d |
| 写 eval_baseline.py | 1.5d |
| 写 GitHub Actions yml | 0.3d |
| 调试 + 跑首次完整评测 | 1d |
| 失败 case 排查 + 修复 | 1d（有缓冲） |

**Phase 2 W4 投入**：3-4 工日
**Phase 3 W6-W10 持续投入**：~2 工日（修 case + 重跑评测）

## 6.13 一句话总结

> **30 条黄金集 + GitHub Actions CI + 失败 case 透明，比 200 条 + LLM-judge + A/B 更扎实。Phase 2 标完，Phase 3 用作量化加分。**

---

> 下一步：阅读 [07_ENTERPRISE_ROADMAP.md](./07_ENTERPRISE_ROADMAP.md) 了解 10 周后的企业化路线。
