# 03 · 产品化特性 · Evidence Center / ReportVersion / Workspace

> **核心论点**：v2.5 / v3 缺的是"产品化"，不是"研究方向"。Evidence Center / ReportVersion / scoring / Workspace 这些 Codex 提的特性，比 TLA+ / 因果推理重要 100 倍。

## 3.1 Evidence Center（Phase 3 引入）

### 问题陈述

plan_a 现在的证据是**埋在每个 run 内部的**：
- `RawSource` 落 `kb_cache.db` 但只按 `(competitor, dimension, content_hash)` 索引
- 跨 run 查"我之前看过哪些 Cursor 的 pricing 证据"很困难
- 用户没有"证据库"概念

### Evidence Center 的目标

```
┌──────────────────────────────────────────────────┐
│   Evidence Center · 证据库统一视图                 │
├──────────────────────────────────────────────────┤
│ 跨 run 索引所有 RawSource + KnowledgeClaim       │
│ 支持：                                            │
│   ─ 按 competitor / dimension / source_type 筛选 │
│   ─ 全文检索 snippet                              │
│   ─ 按 reliability_score / confidence 排序        │
│   ─ 标注"质量好"/"过时"/"待复核"                   │
│   ─ 编辑（修正错误）                              │
│   ─ 引用（在新报告里复用旧证据）                   │
└──────────────────────────────────────────────────┘
```

### 后端 Schema

```python
# packages/evidence/center.py（新增模块）
from packages.schema.models import RawSource

class EvidenceRecord(BaseModel):
    """证据库的统一记录"""
    model_config = ConfigDict(extra="forbid")
    
    # 来自 RawSource 的字段
    id: str  # 全局唯一，跨 run
    competitor: str
    dimension: str
    source_type: str
    title: str
    url: HttpUrl | None
    snippet: str
    content_hash: str
    confidence: float
    reliability_score: float
    
    # Evidence Center 新增字段
    first_seen_run_id: str  # 第一次出现在哪个 run
    last_seen_run_id: str   # 最近一次出现
    seen_count: int = 1     # 被多少 run 引用过
    
    # 用户编辑字段
    quality_label: Literal["good", "outdated", "pending_review", "discarded"] | None = None
    user_notes: str = ""
    user_edited_at: datetime | None = None
    
    # 时间戳
    extracted_at: datetime
    indexed_at: datetime = Field(default_factory=datetime.utcnow)
```

### 后端 API

```python
# app/routers/evidence_center.py（新增）
from fastapi import APIRouter, Query
from typing import Literal

router = APIRouter(prefix="/api/evidence-center")

@router.get("/search")
async def search_evidence(
    competitor: str | None = Query(None),
    dimension: str | None = Query(None),
    source_type: str | None = Query(None),
    quality_label: Literal["good", "outdated", "pending_review"] | None = Query(None),
    q: str | None = Query(None, description="full-text query"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    sort_by: Literal["reliability", "confidence", "recency"] = "recency",
    limit: int = 50,
    offset: int = 0,
) -> EvidenceSearchResult:
    """跨 run 检索证据"""
    return await evidence_center.search(...)

@router.patch("/{evidence_id}/quality")
async def update_quality(
    evidence_id: str,
    label: Literal["good", "outdated", "pending_review", "discarded"],
    notes: str = "",
) -> EvidenceRecord:
    """标注证据质量"""

@router.post("/{evidence_id}/cite")
async def cite_in_run(
    evidence_id: str,
    target_run_id: str,
) -> CitationResult:
    """在新 run 中引用旧证据（避免重复采集）"""
```

### 前端视图

```tsx
// frontend/src/features/evidence-center/EvidenceCenterView.tsx
function EvidenceCenterView() {
  const { data, filters, setFilters } = useEvidenceCenter();
  
  return (
    <div className="grid grid-cols-12 gap-4">
      {/* 左侧筛选 */}
      <FilterSidebar 
        filters={filters} 
        onChange={setFilters}
        facets={data.facets}  // 各维度分布
      />
      
      {/* 中间列表 */}
      <EvidenceList
        items={data.items}
        onSelect={setSelected}
      />
      
      {/* 右侧详情 */}
      <EvidenceDetail
        item={selected}
        onUpdateQuality={updateQuality}
        onCiteInRun={citeInRun}
      />
    </div>
  );
}
```

### 实现要点

1. **不重新建数据库**：Evidence Center 是 plan_a 现有 SQLite 的"统一查询视图"
2. **content_hash 去重**：相同 content_hash 不同 run 算同一条
3. **首次出现 vs 最近出现**：跟踪每条证据的生命周期
4. **质量标注是软删除**：`quality_label="discarded"` 不删数据，但默认查询不包含
5. **Phase 4 升级到 Postgres 后保持 API 不变**

### 评分加成
- C2 业务价值（产品形态贴合工作流）+0.5
- C3 交互设计（业务工作台）+0.3
- C4 业务闭环（人工修正率可观测）+0.3

## 3.2 ReportVersion（Phase 3 引入）

### 问题陈述

plan_a 现在每次 run 输出 `report.md` 但**没有版本概念**。同一个 topic 跑两次，第二次覆盖第一次。无法看到"竞品分析在 3 个月前 vs 现在"的演变。

### ReportVersion 的目标

```
┌──────────────────────────────────────────────────┐
│   ReportVersion · 报告版本管理                    │
├──────────────────────────────────────────────────┤
│ 同一个 topic 的多次 run 都落版本                 │
│ ─ v1: 2026-04-15 (Cursor v0.9 时代)              │
│ ─ v2: 2026-05-20 (Cursor v0.10 + Windsurf 加入)  │
│ ─ v3: 2026-06-10 (新增 enterprise pricing)       │
│                                                   │
│ 支持：                                            │
│ ─ 浏览所有版本                                    │
│ ─ Diff 任意两个版本（左右对照）                   │
│ ─ 标注关键变更（"Cursor 涨价" / "新增 dim"）      │
│ ─ 导出 PDF / Markdown                             │
│ ─ 引用具体版本（不是最新）                        │
└──────────────────────────────────────────────────┘
```

### 后端 Schema

```python
# packages/reporting/version.py（新增模块）
class ReportVersion(BaseModel):
    """同 topic 的报告版本"""
    model_config = ConfigDict(extra="forbid")
    
    id: str  # "report-v3-uuid"
    topic_normalized: str  # 归一化后的 topic（用于聚合相同主题）
    competitor_layer: Literal["product", "platform", "model"]
    competitors: list[str]
    
    version_number: int  # 同 topic 内递增
    parent_version_id: str | None = None  # 上一版
    
    run_id: str  # 关联的 run
    report_md: str  # 完整报告 markdown
    summary: str  # 一段话摘要
    
    # 版本元数据
    key_changes: list[str] = Field(default_factory=list)
    """如 ["Cursor 涨价 50%", "新增 Codeium"]"""
    
    competitor_diff: dict[str, Literal["added", "removed", "kept"]] = Field(default_factory=dict)
    dimension_diff: dict[str, Literal["added", "removed", "kept"]] = Field(default_factory=dict)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_published: bool = False  # 草稿 vs 正式
```

### 后端 API

```python
# app/routers/report_versions.py
@router.get("/topics/{topic_normalized}/versions")
async def list_versions(topic_normalized: str) -> list[ReportVersion]:
    """列出某 topic 的所有版本"""

@router.get("/versions/{v1_id}/diff/{v2_id}")
async def diff_versions(v1_id: str, v2_id: str) -> ReportDiff:
    """两个版本的 diff"""

@router.post("/versions/{version_id}/publish")
async def publish_version(version_id: str) -> ReportVersion:
    """从草稿发布为正式版本"""

@router.get("/versions/{version_id}/export")
async def export_version(
    version_id: str,
    format: Literal["pdf", "markdown", "docx"] = "markdown",
) -> Response:
    """导出版本"""
```

### 前端视图

```tsx
// frontend/src/features/report-versions/VersionsView.tsx
function VersionsView({ topic }: { topic: string }) {
  const versions = useReportVersions(topic);
  const [v1, setV1] = useState<string>();
  const [v2, setV2] = useState<string>();
  
  return (
    <div>
      {/* 时间轴 */}
      <Timeline versions={versions} onSelect={(v) => setV2(v.id)} />
      
      {/* Diff 视图 */}
      {v1 && v2 && <ReportDiffView v1={v1} v2={v2} />}
      
      {/* 关键变更摘要 */}
      <KeyChangesPanel versions={versions} />
    </div>
  );
}
```

### 与 plan_a RevisionRecord 的关系

不冲突。`RevisionRecord` 是**单 run 内**的迭代记录（同一份报告的 v1 → v2，因为 QA 打回修正）。`ReportVersion` 是**跨 run** 的版本（同一个 topic 的多次扫描）。两者分别落不同表。

### 评分加成
- C2 业务价值 +0.5
- C3 交互设计 +0.3
- C4 业务闭环（演变可视化）+0.5

## 3.3 scoring / recommender（Phase 3 引入）

### 问题陈述

plan_a 现在输出 `ComparisonMatrix` 但没有"打分 + 推荐"。用户看到一堆数据要自己脑补"谁更好"。

### scoring 的目标

```python
# packages/scoring/engine.py（新增模块）

class CompetitorScorer:
    def score(
        self,
        kb: CompetitorKB,
        weights: dict[str, float] | None = None,
        scenario_id: str | None = None,
    ) -> CompetitorScore:
        """规则化打分"""
        # weights 来源：
        # 1. 用户显式传入
        # 2. ScenarioPack 推荐（如 ai_coding_assistant 默认 pricing 0.3 + feature 0.4 ...）
        # 3. 全局默认（pricing 0.25 + feature 0.25 + persona 0.25 + review 0.25）
        
        weights = weights or self._infer_weights(scenario_id)
        
        scores = {}
        for dim in kb.dimensions:
            scores[dim] = self._score_dimension(kb, dim)
        
        weighted_total = sum(scores[d] * weights[d] for d in scores)
        
        return CompetitorScore(
            competitor=kb.competitor,
            dimension_scores=scores,
            weights=weights,
            total=weighted_total,
            confidence=self._compute_confidence(kb),
            rationale=self._explain(scores, weights),
        )

class CompetitorRecommender:
    def recommend(
        self,
        scores: list[CompetitorScore],
        user_pref: UserPreference | None = None,
    ) -> Recommendation:
        """根据打分 + 用户偏好推荐"""
        ranked = sorted(scores, key=lambda s: s.total, reverse=True)
        
        if user_pref and user_pref.constraint:
            # 应用硬约束（如 must_have_enterprise_pricing）
            ranked = [s for s in ranked if self._satisfies_constraint(s, user_pref.constraint)]
        
        return Recommendation(
            top_choice=ranked[0],
            runners_up=ranked[1:3],
            rationale=...,
        )
```

### 评分公式（per dimension）

```python
def _score_dimension(self, kb: CompetitorKB, dim: str) -> float:
    """单维度打分 0-1"""
    
    # 1. 证据充分度（30%）
    evidence_score = min(1.0, len(kb.sources_by_dim[dim]) / 3)
    
    # 2. 维度内 claim 平均 confidence（30%）
    claims = kb.claims_by_dim[dim]
    confidence_score = sum(c.confidence for c in claims) / max(1, len(claims))
    
    # 3. 关键属性命中（40%，按 dim 不同）
    if dim == "pricing":
        attribute_score = self._score_pricing(kb.pricing_model)
    elif dim == "feature":
        attribute_score = self._score_feature(kb.feature_tree)
    # ...
    
    return 0.3 * evidence_score + 0.3 * confidence_score + 0.4 * attribute_score
```

### 前端视图

```tsx
// frontend/src/features/scoring/ScoringPanel.tsx
function ScoringPanel({ run }: { run: RunDetail }) {
  const scores = useScores(run.id);
  const recommendation = useRecommendation(run.id);
  
  return (
    <div>
      {/* 打分对照表 */}
      <ScoreTable scores={scores} />
      
      {/* 雷达图（跨竞品维度对比） */}
      <RadarChart data={scores} />
      
      {/* 推荐卡片 */}
      <RecommendationCard rec={recommendation} />
      
      {/* 权重调整面板 */}
      <WeightSlider 
        initial={scores[0].weights}
        onChange={(w) => recomputeScores(w)}
      />
    </div>
  );
}
```

### 评分加成
- C1 可量化提升 +0.5
- C2 业务价值 +0.3

## 3.4 业务工作台前端（Phase 3 引入）

### 问题陈述

plan_a 当前前端是"评估视图集合"（10 个 features）。但用户用的不是"评估视图"，而是"竞品分析工作台"。

### 业务工作台的目标

```
┌─────────────────────────────────────────────────────────┐
│   ┌──────────────────────────────────────────────────┐  │
│   │ Workspace 选择器（Phase 4 引入多租户后启用）       │  │
│   │ 当前：Workspace = "默认"                          │  │
│   └──────────────────────────────────────────────────┘  │
│                                                          │
│   ┌────────────────┬──────────────────┬─────────────┐  │
│   │  Competitor    │  Evidence        │  Reports    │  │
│   │  Library       │  Center          │  History    │  │
│   ├────────────────┼──────────────────┼─────────────┤  │
│   │ ─ Cursor       │ 跨 run 证据      │ ─ v3 (5/20) │  │
│   │ ─ Windsurf     │ 库               │ ─ v2 (4/15) │  │
│   │ ─ Copilot      │                  │ ─ v1 (3/10) │  │
│   │ ─ Codeium      │ 筛选 / 编辑      │             │  │
│   │                │ 标注质量         │ 版本 diff   │  │
│   │ +新增 → run    │                  │             │  │
│   └────────────────┴──────────────────┴─────────────┘  │
│                                                          │
│   ┌──────────────────────────────────────────────────┐  │
│   │ 当前 run 详情（如果有进行中的 run）                │  │
│   │ ─ swimlane / report / scoring / redteam / ...     │  │
│   └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 三大核心视图

1. **Competitor Library**（竞品库）
   - 列出所有曾经分析过的 competitor
   - 每条显示：名称 / 分析次数 / 最近报告 / 平均评分
   - 点击 → 跳转最新 ReportVersion

2. **Evidence Center**（证据库）
   - 跨 run 检索（详见 §3.1）

3. **Reports History**（报告库）
   - 按 topic 聚合的 ReportVersion 时间轴
   - 支持版本 diff / 导出 / 引用

### 前端路由结构

```
/                          (Dashboard - 三视图入口)
/competitors               (Competitor Library)
/competitors/:id           (单个 competitor 历史)
/evidence                  (Evidence Center)
/evidence/:id              (单条证据详情)
/reports                   (Reports History)
/reports/:topic            (某 topic 的版本时间轴)
/reports/:topic/diff       (版本 diff)
/runs                      (运行中 / 历史 runs，plan_a 现有)
/runs/:id                  (单 run 详情，plan_a 现有 10 视图)
/new                       (NewRun 表单，plan_a 现有)
```

### 实现要点

1. **不丢 plan_a 现有 10 视图**：保留 `/runs/:id` 下所有 swimlane / trace / kb 视图
2. **新增 3 个顶层入口**：Competitor Library / Evidence Center / Reports History
3. **Dashboard 是入口**：替代当前的"上来就看 run 列表"
4. **Phase 4 引入 Workspace**：在顶部加 Workspace 选择器

### 评分加成
- C2 业务价值 +0.5
- C3 交互设计 +0.5

## 3.5 Phase 3 整体评分加成

```
Evidence Center:           +1.1 分
ReportVersion:             +1.3 分
scoring / recommender:     +0.8 分
业务工作台前端:             +1.0 分
─────────────────────────────────
Phase 3 累计加成:           +4.2 分

Phase 1 + 2 累计:          +3.5 分

Phase 1+2+3 总评分:         88-90 分（plan_a 80 + 8-10 提升）
```

## 3.6 与 v3 研究方向的对比

```
v3 研究方向                  final 产品化特性          哪个加分多？
─────────────              ──────────────             ─────────
TLA+ 形式化验证             ReportVersion             ReportVersion 100x
因果推理 do-calculus        scoring / recommender     scoring 100x
联邦协作 + DP + HE          Workspace / RBAC          Workspace 100x
自适应 Schema 演化          Evidence Center           Evidence Center 100x
多 Agent 互评博弈           RedTeam（已有）           平
跨 run KG 累积              Evidence Center 雏形      Evidence Center 100x（更落地）
```

**结论**：v3 研究方向都不应该做。final 的产品化特性才是真正的"业务价值 + 业务闭环"加分。

## 3.7 用户反馈采集（Phase 3 末加）

### 简单 feedback 表单（不做 MemoryAgent）

```tsx
// frontend/src/features/feedback/FeedbackPanel.tsx
function FeedbackPanel({ run }: { run: RunDetail }) {
  return (
    <Form onSubmit={submitFeedback}>
      <RatingSlider name="overall_quality" min={1} max={5} />
      <Checkbox name="cite_compliance">引用都对</Checkbox>
      <Checkbox name="coverage_complete">覆盖度足够</Checkbox>
      <Checkbox name="useful_for_decision">能支持决策</Checkbox>
      <Textarea name="comment" placeholder="改进建议" />
      <Button type="submit">提交</Button>
    </Form>
  );
}
```

落到 `runs/feedback.db` 简单记录，**不做 MemoryAgent 偏好提取**（v2.5 草案的过度设计）。Phase 4-5 再考虑。

### 评分加成
- C4 业务闭环 +0.3
- 人工修正率（acceptance_rate）可观测

## 3.8 总结：Phase 3 的"产品化"成果

```
W6-W10 完成后，plan_a 从"评估工具"升级为"业务工作台"：

┌────────────────────────────────────────┐
│  之前（plan_a v2）                      │
│  ─ 单次 run 工具                        │
│  ─ 跑完即丢                             │
│  ─ 无证据库                             │
│  ─ 无版本概念                           │
│  ─ 无打分                               │
│  ─ 工程评估视图                         │
└────────────────────────────────────────┘
                ↓ Phase 3
┌────────────────────────────────────────┐
│  之后（final Phase 3 末）                │
│  ─ 业务工作台                            │
│  ─ Competitor Library 跨 run            │
│  ─ Evidence Center 证据库               │
│  ─ ReportVersion 版本管理               │
│  ─ scoring / recommender                │
│  ─ RedTeam / EvidenceGap                │
│  ─ 用户反馈采集                          │
└────────────────────────────────────────┘
```

这才是"产品形态贴合企业竞品分析真实工作流"（C2 评分原文）。

---

> 下一步：阅读 [04_AI_ASSISTED_DEVELOPMENT.md](./04_AI_ASSISTED_DEVELOPMENT.md) 了解真实的 AI 协作记录方式。
