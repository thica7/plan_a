# 01 · 5 阶段执行路线图（v2.0 · 企业骨架前置版）

> **核心节奏（v2.0 修订）**：企业架构骨架前置（Phase 1 直接 PG + Workspace + EvidenceRecord 抽离 + 稳定 ID + AuditLog skeleton），企业级复杂能力后置（RBAC/Temporal/pgvector 在 Phase 4-5）。
>
> **变更说明**：v1.0 是 10 周节奏（先 SQLite 后 PG），v2.0 是 12 周节奏（一开始就用 PG 建完整 schema）。多 2 周换 Phase 4 省 1 月迁移痛苦。详见 [09_SECONDARY_REVIEW.md](./09_SECONDARY_REVIEW.md)。

## 1.1 总览

```
┌──────────────────────────────────────────────────────────────────┐
│ Phase 1 (W0-W4) · 企业骨架 + 最小分析闭环                          │
│   PG schema + Workspace/Project/Evidence + 稳定 ID + AuditLog     │
│ Phase 2 (W4-W6) · 业务情报能力补齐                                 │
│   L1/L2/L3 + ScenarioPack + QA rules + 30 黄金集                  │
│ Phase 3 (W6-W10) · Agent 增强 + Evidence Center 前端              │
│   RedTeam + EvidenceGap + scoring + ReportVersion diff            │
│ Phase 4 (W10-W12) · Temporal 薄壳 + 审批原型                      │
│   CompetitiveIntelWorkflow + approval queue prototype             │
│  ─────────── 12 周交付节点 / 答辩窗口 ────────────────────────  │
│ Phase 5 (W12+ → 12m) · 企业治理和规模化                            │
│   完整 RBAC + Source Registry + pgvector + 监控告警 + Multi-tenant│
└──────────────────────────────────────────────────────────────────┘
```

每阶段独立交付价值。Phase 1 多 2 周建数据骨架，Phase 4 不再做"PG 迁移"，节省 1 月。

## 1.2 优先级总表（v2.0 修订版）

```
P0（必须前置 - Codex §6）：
├─ Postgres schema 初版
├─ 默认 Workspace / Project / User 实例
├─ EvidenceRecord / KnowledgeClaim 独立入库
├─ 稳定 evidence_id / claim_id（sha256-based）
├─ ReportVersion 最小表
├─ AuditLog skeleton（写入框架）
├─ Run 与 Project 绑定
├─ AgentExecutor 接口定义
└─ 工程清理 + 真实 Git

P1（产品闭环增强）：
├─ L1/L2/L3 三层竞品建模
├─ ScenarioPack 动态生成
├─ QA rules yaml 化（8 条规则）
├─ verify_homepage 工具
├─ Evidence quality label
├─ Citation validity checker
├─ 30 条 golden cases + baseline eval
├─ RedTeam Agent（Pydantic-AI）
├─ EvidenceGap Agent（Pydantic-AI）
├─ scoring / recommender
├─ ReportVersion diff 视图
└─ React 业务工作台

P2（企业增强 - Phase 4-5）：
├─ Temporal 薄壳（CompetitiveIntelWorkflow）
├─ Approval queue
├─ Monitor jobs
├─ 完整 RBAC
├─ Source Registry
├─ pgvector
├─ Langfuse / OTel
├─ Notification
└─ Cost governance
```

## 1.3 Phase 1（W0-W4）· 企业骨架 + 最小分析闭环

**目标**：让系统从第一天就是企业产品形状，而不是单机 run demo。

### 1.3.1 真实 Git 初始化（W0 D1）

```bash
cd D:/codex_workspace/plan_a
git init
git branch -M main
git config user.name "<name>"
git config user.email "<email>"

# 扩展 .gitignore
cat >> .gitignore <<EOF
runs/*.db
runs/*.db-shm
runs/*.db-wal
backend/.venv/
backend/.pytest_cache/
.pnpm-store/
**/__pycache__/
node_modules/
dist/
.env
.env.local
*.pyc
docker-data/
EOF

git add .gitignore README.md backend/ frontend/ docs/ docker-compose.yml Makefile
git commit -m "chore: initialize git, baseline at $(date +%F), migrating from local backup"
```

**绝不用 `git commit --date=...` 还原历史**。详见 [04_AI_ASSISTED_DEVELOPMENT.md](./04_AI_ASSISTED_DEVELOPMENT.md)。

### 1.3.2 写 AI_ASSISTED_DEVELOPMENT.md + ADR 框架（W0 D2-D3）

详见 [04_AI_ASSISTED_DEVELOPMENT.md](./04_AI_ASSISTED_DEVELOPMENT.md)。

需要 W0 末完成的 ADR：
- ADR-0001: LangGraph vs CrewAI
- ADR-0002: 5 级 RedoScope
- ADR-0003: L1/L2/L3 三层建模
- ADR-0006: 不伪造 git history
- ADR-0007: Temporal 包外层
- ADR-0011: 企业骨架前置（v2.0 新增，详见 08）

### 1.3.3 起 Postgres + 设计完整 schema（W1）★ 核心新增

```yaml
# docker-compose.yml 新增 PG 服务
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: competiscope
      POSTGRES_USER: app
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports: ["5432:5432"]
    volumes:
      - ./docker-data/pg:/var/lib/postgresql/data
```

**Phase 1 表清单**（详见 [05_DATA_MODELS.md](./05_DATA_MODELS.md)）：

```sql
-- 1. 多租户基础
CREATE TABLE workspaces (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(200) NOT NULL,
  ...
);

-- 2. 用户（Phase 1 单 user 默认）
CREATE TABLE users (
  id UUID PRIMARY KEY,
  email VARCHAR(255),
  ...
);

-- 3. 项目（业务单元）
CREATE TABLE projects (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL REFERENCES workspaces(id),
  name VARCHAR(200),
  topic VARCHAR(200),
  topic_normalized VARCHAR(200),
  competitor_layer VARCHAR(20),
  competitor_set_hash VARCHAR(64),  -- 用于 ReportVersion 分组
  ...
);

-- 4. 竞品库
CREATE TABLE competitors (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL,
  name VARCHAR(200),
  layer VARCHAR(20),
  homepage VARCHAR(500),
  ...
);

-- 5. Project ↔ Competitor 多对多（唯一事实来源）
CREATE TABLE project_competitors (
  project_id UUID NOT NULL REFERENCES projects(id),
  competitor_id UUID NOT NULL REFERENCES competitors(id),
  PRIMARY KEY (project_id, competitor_id)
);
-- 注意：Project 表里不存 competitor_ids 列表，避免双重维护

-- 6. Run（与 Project 绑定）
CREATE TABLE runs (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL,
  project_id UUID REFERENCES projects(id),
  status VARCHAR(20),
  topic VARCHAR(200),
  competitor_layer VARCHAR(20),
  scenario_id VARCHAR(100),
  ...
);

-- 7. EvidenceRecord（从 RunDetail 抽离）
CREATE TABLE evidence_records (
  id VARCHAR(64) PRIMARY KEY,  -- sha256(canonical_url + content_hash + competitor_id + dimension_key)
  workspace_id UUID NOT NULL,
  competitor_id UUID NOT NULL REFERENCES competitors(id),
  run_id UUID REFERENCES runs(id),  -- 首次发现的 run
  
  source_type VARCHAR(50),
  url VARCHAR(1000),
  canonical_url VARCHAR(1000),
  title VARCHAR(500),
  snippet TEXT,
  content_hash VARCHAR(64),
  
  dimension VARCHAR(50),
  reliability_score NUMERIC(3,2),
  confidence NUMERIC(3,2),
  
  quality_label VARCHAR(20),  -- good / outdated / pending_review / discarded
  user_notes TEXT,
  
  first_seen_run_id UUID,
  last_seen_run_id UUID,
  seen_count INT DEFAULT 1,
  
  extracted_at TIMESTAMPTZ,
  indexed_at TIMESTAMPTZ DEFAULT NOW()
);

-- 8. KnowledgeClaim
CREATE TABLE knowledge_claims (
  id VARCHAR(64) PRIMARY KEY,  -- sha256(evidence_id + normalized_claim_text + claim_type)
  workspace_id UUID NOT NULL,
  competitor_id UUID NOT NULL,
  
  claim_text TEXT,
  normalized_claim_text TEXT,
  claim_type VARCHAR(50),
  layer VARCHAR(20),
  dimension VARCHAR(50),
  
  confidence NUMERIC(3,2),
  
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 9. Claim ↔ Evidence 多对多（一个 claim 可有多个证据）
CREATE TABLE claim_evidence (
  claim_id VARCHAR(64) NOT NULL REFERENCES knowledge_claims(id),
  evidence_id VARCHAR(64) NOT NULL REFERENCES evidence_records(id),
  PRIMARY KEY (claim_id, evidence_id)
);

-- 10. ReportVersion（最小版本表）
CREATE TABLE report_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL,
  project_id UUID NOT NULL REFERENCES projects(id),
  
  version_number INT,
  parent_version_id UUID REFERENCES report_versions(id),
  
  topic_normalized VARCHAR(200),
  competitor_layer VARCHAR(20),
  competitor_set_hash VARCHAR(64),  -- 配合 (workspace, project, topic, layer) 分组
  
  run_id UUID REFERENCES runs(id),
  report_md TEXT,
  summary TEXT,
  
  is_published BOOLEAN DEFAULT FALSE,
  
  created_at TIMESTAMPTZ DEFAULT NOW(),
  
  UNIQUE (workspace_id, project_id, topic_normalized, competitor_layer, competitor_set_hash, version_number)
);

-- 11. ReportVersion 引用的 claims
CREATE TABLE report_version_claims (
  report_version_id UUID NOT NULL REFERENCES report_versions(id) ON DELETE CASCADE,
  claim_id VARCHAR(64) NOT NULL REFERENCES knowledge_claims(id),
  PRIMARY KEY (report_version_id, claim_id)
);

-- 12. AuditLog skeleton（Phase 1 写入框架，Phase 5 完整 RBAC）
CREATE TABLE audit_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL,
  
  actor_id UUID,
  actor_type VARCHAR(20) DEFAULT 'system',
  
  action VARCHAR(100) NOT NULL,
  target_type VARCHAR(50),
  target_id VARCHAR(64),
  
  payload JSONB,
  request_metadata JSONB,
  
  occurred_at TIMESTAMPTZ DEFAULT NOW()
);

-- 13. 默认实例（Phase 1 初始化脚本）
INSERT INTO workspaces (id, name) VALUES 
  ('00000000-0000-0000-0000-000000000001', 'default workspace');
INSERT INTO users (id, email) VALUES
  ('00000000-0000-0000-0000-000000000001', 'system@local');
```

完整 schema 详见 [05_DATA_MODELS.md](./05_DATA_MODELS.md)。

**预留字段原则**：所有核心表都有 `workspace_id` / `created_by` / `updated_at`，Phase 5 启用 RBAC 时无需 ALTER TABLE。

### 1.3.4 稳定 ID 算法实现（W1 D5）★ 核心新增

```python
# packages/identity/stable_ids.py（新增）
import hashlib
import re

def normalize_url(url: str) -> str:
    """canonical URL: 去 query string / fragment / 末尾斜杠"""
    url = re.sub(r'\?.*$', '', url)
    url = re.sub(r'#.*$', '', url)
    url = url.rstrip('/')
    return url.lower()

def normalize_text(text: str) -> str:
    """归一化文本：小写、去多空格、去标点"""
    text = text.lower()
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def compute_evidence_id(
    canonical_url: str,
    content_hash: str,
    competitor_id: str,
    dimension_key: str,
) -> str:
    """全局稳定 evidence_id"""
    raw = f"{canonical_url}|{content_hash}|{competitor_id}|{dimension_key}"
    return hashlib.sha256(raw.encode()).hexdigest()

def compute_claim_id(
    evidence_id: str,
    claim_text: str,
    claim_type: str,
) -> str:
    """全局稳定 claim_id"""
    normalized = normalize_text(claim_text)
    raw = f"{evidence_id}|{normalized}|{claim_type}"
    return hashlib.sha256(raw.encode()).hexdigest()

def compute_competitor_set_hash(competitor_ids: list[str]) -> str:
    """ReportVersion 分组用"""
    sorted_ids = sorted(competitor_ids)
    raw = "|".join(sorted_ids)
    return hashlib.sha256(raw.encode()).hexdigest()
```

**关键性质**：
- 同一 (url, hash, competitor, dim) 在任何 run 都得到同一 evidence_id
- 跨 run 去重 / Evidence Store 检索 / ReportVersion diff 全部依赖此 ID

### 1.3.5 EvidenceRecord 从 RunDetail 抽离独立入库（W2）★ 核心改造

**当前 plan_a 现状**：
```python
# packages/orchestrator/service.py（现状）
record.detail.raw_sources = [
    RawSource(id="src_001", url=..., ...),  # 埋在 run detail 里
    ...
]
```

**Phase 1 改造**：
```python
# packages/evidence/store.py（新增）
class EvidenceStore:
    async def upsert(self, source: RawSource, run_id: str, competitor_id: str) -> str:
        evidence_id = compute_evidence_id(
            canonical_url=normalize_url(str(source.url)),
            content_hash=source.content_hash,
            competitor_id=competitor_id,
            dimension_key=source.dimension,
        )
        
        # INSERT ... ON CONFLICT DO UPDATE
        await self.pg.execute("""
            INSERT INTO evidence_records (
                id, workspace_id, competitor_id, run_id,
                source_type, url, canonical_url, title, snippet, content_hash,
                dimension, reliability_score, confidence,
                first_seen_run_id, last_seen_run_id, seen_count,
                extracted_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                $11, $12, $13, $14, $14, 1, $15
            )
            ON CONFLICT (id) DO UPDATE SET
                last_seen_run_id = EXCLUDED.last_seen_run_id,
                seen_count = evidence_records.seen_count + 1
        """, evidence_id, ...)
        
        return evidence_id

# packages/orchestrator/service.py（改造）
async def _on_collector_branch_complete(self, record, ...):
    raw_sources = ...
    for source in raw_sources:
        evidence_id = await self.evidence_store.upsert(source, run_id, competitor_id)
        # 同时记录到 run.detail（兼容）+ 独立表（新）
        record.detail.raw_sources.append(source)  # 兼容现有代码
```

**关键性质**：
- 同一 source 跨 run 看到时不会重复入库（INSERT ON CONFLICT）
- evidence_id 是稳定的（Phase 4 引入 Temporal 时幂等性自动满足）
- Evidence Center 跨 run 检索是 SELECT FROM evidence_records WHERE workspace_id = ...

### 1.3.6 ReportVersion 最小表（W2 D5）

```python
# packages/reporting/version_store.py（新增）
class ReportVersionStore:
    async def create_version(
        self,
        workspace_id: str,
        project_id: str,
        topic_normalized: str,
        competitor_layer: str,
        competitor_set_hash: str,
        run_id: str,
        report_md: str,
        summary: str,
    ) -> str:
        # 找上一版本
        prev = await self.pg.fetchrow("""
            SELECT id, version_number FROM report_versions
            WHERE workspace_id = $1 AND project_id = $2 
              AND topic_normalized = $3 AND competitor_layer = $4
              AND competitor_set_hash = $5
            ORDER BY version_number DESC LIMIT 1
        """, workspace_id, project_id, topic_normalized, competitor_layer, competitor_set_hash)
        
        version_number = (prev['version_number'] + 1) if prev else 1
        parent_version_id = prev['id'] if prev else None
        
        version_id = await self.pg.fetchval("""
            INSERT INTO report_versions (
                workspace_id, project_id, version_number, parent_version_id,
                topic_normalized, competitor_layer, competitor_set_hash,
                run_id, report_md, summary
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10
            ) RETURNING id
        """, ...)
        
        return version_id
```

**Phase 1 不做**：
- ReportVersion diff 视图（Phase 3）
- 审批工作流（Phase 4）
- 跨 Workspace 检索（Phase 5）

### 1.3.7 AuditLog skeleton 写入框架（W2 D6-D7）

```python
# packages/audit/logger.py（新增）
class AuditLogger:
    async def log(
        self,
        action: str,
        target_type: str,
        target_id: str,
        actor_id: str | None = None,
        actor_type: str = "system",
        payload: dict | None = None,
        request_metadata: dict | None = None,
    ):
        await self.pg.execute("""
            INSERT INTO audit_logs (
                workspace_id, actor_id, actor_type, action,
                target_type, target_id, payload, request_metadata
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, self.workspace_id, actor_id, actor_type, action, 
             target_type, target_id, payload, request_metadata)

# 用法
await audit.log(
    action="run.create",
    target_type="Run",
    target_id=run_id,
    actor_type="user",
    actor_id=user_id,
    payload={"topic": topic, "competitors": competitors},
)
```

**Phase 1 不做**：完整 RBAC + 不可篡改约束 + 审计 UI（Phase 5）。

### 1.3.8 AgentExecutor 接口定义（W3 D1）

```python
# packages/agents/protocol.py（新增）
from typing import Protocol, TypeVar
from pydantic import BaseModel

I = TypeVar("I", bound=BaseModel)
O = TypeVar("O", bound=BaseModel)

class AgentContext(BaseModel):
    """Agent 运行上下文"""
    run_id: str
    project_id: str | None = None
    workspace_id: str
    iteration: int = 0
    parent_subagent: str | None = None
    qa_feedback: list[dict] = []
    
class AgentExecutor(Protocol[I, O]):
    """所有 Agent 实现这个协议"""
    
    name: str
    
    async def execute(self, input: I, ctx: AgentContext) -> O:
        """运行 Agent"""
        ...
    
    async def warmup(self):
        """启动时预热（如加载 prompt）"""
        ...

# Phase 1 实现：适配现有手搓 Agent
class LegacyAgentExecutor:
    def __init__(self, name: str, legacy_func):
        self.name = name
        self._legacy_func = legacy_func
    
    async def execute(self, input, ctx: AgentContext):
        return await self._legacy_func(input, ctx)

# Phase 3 实现：Pydantic-AI Agent
class PydanticAIExecutor:
    def __init__(self, name: str, pydantic_ai_agent):
        self.name = name
        self._agent = pydantic_ai_agent
    
    async def execute(self, input, ctx: AgentContext):
        result = await self._agent.run(...)
        return result.data
```

Phase 1 只定接口 + 适配现有实现。Phase 3 用 Pydantic-AI 实现 RedTeam / EvidenceGap。Phase 4+ 替换现有手搓 Agent。

### 1.3.9 LangGraph 接入新数据模型（W3）★ 关键改造

让现有 LangGraph 节点写入新表：

```python
# packages/orchestrator/service.py 改造
async def _on_run_start(self, request: NewRunRequest):
    # 1. 找/创建 Project
    project_id = await self.project_store.find_or_create(
        workspace_id=request.workspace_id or DEFAULT_WORKSPACE_ID,
        topic=request.topic,
        competitor_layer=request.competitor_layer,
        competitor_ids=request.competitor_ids,
    )
    
    # 2. 创建 Run
    run_id = await self.run_store.create(
        workspace_id=...,
        project_id=project_id,
        topic=request.topic,
        ...
    )
    
    # 3. 审计
    await self.audit.log(
        action="run.create",
        target_type="Run",
        target_id=run_id,
        payload={"topic": request.topic},
    )
    
    # 4. 启 LangGraph
    return await self.graph.ainvoke({"run_id": run_id, ...})

async def _on_collector_branch_complete(self, record, ...):
    # 同时双写：兼容现有 RunDetail + 新 EvidenceRecord 表
    for source in raw_sources:
        evidence_id = await self.evidence_store.upsert(...)
        record.detail.raw_sources.append(source)  # 兼容

async def _on_writer_complete(self, record):
    # 创建 ReportVersion
    version_id = await self.version_store.create_version(
        workspace_id=...,
        project_id=...,
        topic_normalized=normalize(record.detail.topic),
        competitor_layer=record.detail.plan.competitor_layer,
        competitor_set_hash=compute_competitor_set_hash(competitor_ids),
        run_id=record.run_id,
        report_md=record.detail.report_md,
        summary=record.detail.summary,
    )
```

### 1.3.10 FastAPI CRUD（W4 D1-D3）

```python
# app/routers/projects.py（新增）
@router.get("/projects")
async def list_projects(workspace_id: str = "default") -> list[ProjectDTO]:
    return await project_service.list(workspace_id)

@router.get("/projects/{project_id}")
async def get_project(project_id: str) -> ProjectDTO:
    return await project_service.get(project_id)

# app/routers/evidence.py（新增）
@router.get("/evidence")
async def list_evidence(
    workspace_id: str = "default",
    competitor_id: str | None = None,
    dimension: str | None = None,
    limit: int = 50,
) -> list[EvidenceDTO]:
    return await evidence_service.list(...)

# app/routers/report_versions.py（新增）
@router.get("/projects/{project_id}/versions")
async def list_versions(project_id: str) -> list[ReportVersionDTO]:
    return await version_service.list(project_id)
```

### 1.3.11 baseline eval 骨架（W4 D4）

```python
# scripts/eval_baseline.py（骨架）
async def main():
    cases = load_cases("data/golden_set.jsonl")  # Phase 2 才填到 30 条
    cases = cases[:5]  # Phase 1 只跑 5 条 smoke
    
    for case in cases:
        sys_result = await run_via_system(case)
        baseline_result = await run_llm_only_baseline(case)
        compare_and_log(sys_result, baseline_result)
```

### 1.3.12 Phase 1 Exit Criteria

- ✅ `.git/` 存在 + ≥ 10 个真实 commits
- ✅ `docs/AI_ASSISTED_DEVELOPMENT.md` 写完
- ✅ 13 张 Postgres 表创建完毕
- ✅ 默认 workspace + user 实例就位
- ✅ 稳定 evidence_id / claim_id 算法 + 单测
- ✅ EvidenceRecord 双写过渡（旧 RunDetail + 新表）
- ✅ ReportVersion 最小表 + writer 节点写入
- ✅ AuditLog skeleton + run.create 等 5+ 动作埋点
- ✅ AgentExecutor 接口 + LegacyAgentExecutor 适配
- ✅ FastAPI CRUD: /projects, /evidence, /report-versions
- ✅ baseline eval 骨架能跑 3-5 条 smoke

### Phase 1 工时分配（4 周）

| 周 | 任务 | 工时 |
|---|---|---|
| W0 | git init + 工程清理 + AI_ASSISTED + ADR-0001~0011 | 5d |
| W1 | PG 部署 + schema 设计 + 13 张表 + 默认实例 + 稳定 ID 算法 | 5d |
| W2 | EvidenceStore / ClaimStore / ReportVersionStore / AuditLogger | 5d |
| W3 | AgentExecutor 接口 + LangGraph 接入新数据模型 | 5d |
| W4 | FastAPI CRUD + baseline eval 骨架 + 集成测试 | 5d |

**总计 25 工日 ≈ 4-5 周（1.5 人）**。Phase 1 是最重的阶段。

## 1.4 Phase 2（W4-W6）· 业务情报能力补齐

**目标**：把 CIMatrix 有价值的业务能力迁入 plan_a。

### 任务清单

- L1/L2/L3 三层竞品建模（Codex §4 Phase 2 第 1 项）
- ScenarioPack 动态生成（Codex 第 2 项）
- layer-specific dimensions（Codex 第 3 项）
- evidence_seed.jsonl 50 条（Codex 第 4 项）
- QA rules yaml（8 条规则）
- source reliability 初版
- Evidence quality label
- Citation validity checker
- 30 条 golden cases

### v2.0 调整点

**指标重排**（Codex §4）：
- 主指标：layer 判断准确率 / evidence coverage / citation validity / schema pass rate / source freshness / human override rate
- 辅助指标：keyword_recall（不再作主指标）

详见 [06_QUALITY_AND_BASELINE_EVAL.md](./06_QUALITY_AND_BASELINE_EVAL.md)。

### Phase 2 Exit Criteria

- ✅ AnalysisPlan 含 competitor_layer 字段（已写入 PG schema）
- ✅ L1/L2/L3 三个 demo 都跑通
- ✅ ScenarioPack 5 静态 + 动态生成跑通
- ✅ verify_homepage 集成到 planner
- ✅ 8 条 QA rules yaml 加载并触发 5 路 RedoScope
- ✅ 30 条黄金集评测通过
- ✅ Evidence quality label UI（最简版）

### Phase 2 工时（2 周，2 人）

| 任务 | 工时 |
|---|---|
| L1/L2/L3 schema + skill 路由 + planner 改造 | 3d |
| Evidence schema 模块化 + evidence_seed.jsonl 50 条 | 3d |
| ScenarioPack 5 静态 + 动态生成 + 落盘复用 | 2d |
| verify_homepage 工具 + planner 集成 | 1d |
| QA rules yaml × 8 条 + 引擎重构 + 替换 hard-code | 4d |
| 5 路 RedoScope 回归测试 | 2d |
| 30 条黄金集标注 + eval_baseline.py | 3d |
| 集成测试 + 修复 | 2d |

总计 20 工日 = 2 周（2 人）。

## 1.5 Phase 3（W6-W10）· Agent 能力增强 + 前端工作台

**目标**：增强情报质量 + 业务工作台前端。

### 任务清单

- RedTeam Agent（**Pydantic-AI 实现**，30 行 vs 手搓 200 行）
- EvidenceGap Agent（**Pydantic-AI 实现**）
- Competitor scoring / recommender
- Report diff 视图（基于 Phase 1 已有的 ReportVersion 表）
- AgentExecutor 接口已就位（Phase 1）→ 直接挂新 Pydantic-AI 实现
- React 业务工作台（Competitor Library / Evidence Center / Reports History）

### Phase 3 Exit Criteria

- ✅ RedTeam ≥ 2 条 high severity finding
- ✅ EvidenceGap 检测 ≥ 1 个 (competitor, dim) 缺证据
- ✅ scoring 输出 CompetitorScore，前端展示
- ✅ ReportVersion diff 视图：同 Project 多次 run 可 diff
- ✅ React 工作台：Competitor Library + Evidence Center + Reports History 三视图
- ✅ 30 条黄金集评测：v2.0 系统覆盖度 vs baseline +50%

### Phase 3 工时（4 周，2 人）

| 任务 | 工时 |
|---|---|
| Evidence Center 后端 API + 前端视图 | 4d |
| ReportVersion diff 视图 | 3d |
| RedTeam Agent（Pydantic-AI） | 1.5d |
| EvidenceGap Agent（Pydantic-AI） | 1.5d |
| scoring / recommender 引擎 | 2d |
| 前端业务工作台（3 视图整合） | 4d |
| 集成测试 + 评测 + 文档 | 4d |

总计 20 工日 = 4 周（1 人）/ 2 周（2 人）。

## 1.6 Phase 4（W10-W12）· Temporal 薄壳 + 审批原型

**目标**：引入 Temporal 但不替代 LangGraph。

### 关键 Workflow（Codex §4 Phase 4）

```python
# workflows/competitive_intel.py
@workflow.defn
class CompetitiveIntelWorkflow:
    """Phase 4 第一个 Workflow"""
    
    @workflow.run
    async def run(self, request: AnalysisRequest) -> RunResult:
        # 1. 创建 Run（幂等 - 用 request.idempotency_key 作 run_id）
        run_id = await workflow.execute_activity(
            create_run_activity,
            request,
            schedule_to_close_timeout=timedelta(seconds=30),
        )
        
        # 2. 跑 LangGraph（容忍重跑，因为下游 ID 都是稳定的）
        result = await workflow.execute_activity(
            run_langgraph_activity,
            run_id,
            schedule_to_close_timeout=timedelta(hours=2),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        
        # 3. 持久化 evidence（幂等 - INSERT ... ON CONFLICT DO NOTHING）
        await workflow.execute_activity(
            persist_evidence_activity,
            run_id,
            schedule_to_close_timeout=timedelta(minutes=5),
        )
        
        # 4. 创建 ReportVersion（幂等）
        version_id = await workflow.execute_activity(
            create_report_version_activity,
            run_id,
            schedule_to_close_timeout=timedelta(minutes=2),
        )
        
        # 5. 通知（如果配置）
        if request.notify_webhook:
            await workflow.execute_activity(
                notify_activity,
                version_id, request.notify_webhook,
            )
        
        return RunResult(run_id=run_id, report_version_id=version_id)
```

**关键设计**（详见 [02_ARCHITECTURE_LAYERED.md](./02_ARCHITECTURE_LAYERED.md) Temporal replay 章节）：
- run_id 幂等（来自 request.idempotency_key 或 deterministic 派生）
- evidence_id / claim_id / report_version_id 都是稳定 ID
- Activity retry 不会重复写（INSERT ON CONFLICT）
- 长时间审批用 Signal，不让 Activity 阻塞

### Approval Queue 原型

```python
@workflow.defn
class ReportApprovalWorkflow:
    """Phase 4 原型版，仅审批队列骨架"""
    
    def __init__(self):
        self.decision: str | None = None
    
    @workflow.run
    async def run(self, version_id: str, approver_ids: list[str]) -> str:
        await workflow.execute_activity(
            send_approval_request,
            version_id, approver_ids,
        )
        
        await workflow.wait_condition(
            lambda: self.decision is not None,
            timeout=timedelta(days=3),
        )
        
        if self.decision == "approved":
            await workflow.execute_activity(publish_version, version_id)
            return "published"
        return "rejected"
    
    @workflow.signal
    async def approve(self, approver_id: str): self.decision = "approved"
    
    @workflow.signal
    async def reject(self, approver_id: str): self.decision = "rejected"
```

### Phase 4 Exit Criteria

- ✅ Temporal Server 部署 + 监控
- ✅ CompetitiveIntelWorkflow 跑通 + replay 验证幂等
- ✅ ApprovalWorkflow 原型跑通（手动 approve / reject）
- ✅ 100% v2.0 流量走 Workflow（双栈 1 周后切流）
- ✅ 答辩材料就位（PPT + 演示视频 + 黄金集评测报告）

### Phase 4 工时（2 周，2 人）

| 周 | 任务 | 工时 |
|---|---|---|
| W10 | Temporal Server 部署 + CompetitiveIntelWorkflow + Activity 幂等性测试 | 5d |
| W11 | ApprovalWorkflow 原型 + 双栈共存验证 + 切流 | 5d |
| W12 | 答辩材料 + 演示视频 + 排练 | 5d |

注：Phase 4 是 W10-W12（3 周），含答辩材料。

## 1.7 ────────── 12 周交付节点 ──────────

W12 末交付物：
- ✅ Phase 1+2+3+4 全部完成
- ✅ 真实 git history（12 周 ≥ 100 个 commits）
- ✅ AI_ASSISTED_DEVELOPMENT.md
- ✅ 30 条黄金集评测报告
- ✅ Temporal 薄壳跑通
- ✅ 业务工作台 + Evidence Center + ReportVersion + scoring
- ✅ 答辩 PPT + 演示视频 + 排练

**评分预期**：90-92 分（v2.0 比 v1.0 同期高 1-2 分，因为数据骨架更扎实）

## 1.8 Phase 5（W12+ → 12m）· 企业治理和规模化

**目标**：从企业产品骨架升级为企业级可运营系统。

### 关键模块（Codex §4 Phase 5）

- 完整 RBAC（OPA / Cerbos）
- Multi-tenant isolation（真启用）
- Source Registry
- AuditLog 强化（不可篡改 + 完整事件覆盖）
- pgvector + 全文检索（Meilisearch）
- 对象存储（S3 / 阿里云 OSS）
- Langfuse / OTel
- Token / cost governance
- PII redaction（Microsoft Presidio）
- Model policy
- Report publish workflow（含合规检查）

### Phase 5 时间盒

约 6-12 个月，团队扩到 4-5 人。

### Phase 5 工时

详见 [07_ENTERPRISE_ROADMAP.md](./07_ENTERPRISE_ROADMAP.md)。

## 1.9 周级 Go/No-Go 决策

每周 Friday 16:00 决策：

| 周 | 关键节点 | 不达标行动 |
|---|---|---|
| W2 | PG schema + 默认 Workspace + 稳定 ID 算法 | 推迟 Phase 1 完成到 W5 |
| W4 | EvidenceRecord 抽离 + AgentExecutor 接口 + FastAPI CRUD | 推迟 Phase 2 一周 |
| W6 | L1/L2/L3 + ScenarioPack 完成 | 砍 ScenarioPack 动态生成 |
| W10 | Phase 3 全部完成 | 砍 EvidenceGap，保 Evidence Center + RedTeam |
| W12 | Temporal 薄壳跑通 + 答辩材料 | 砍 ApprovalWorkflow，保 CompetitiveIntelWorkflow |

## 1.10 应急预案库（v2.0 调整）

### EP-1: Phase 1 末进度滞后（4 周做不完）

```
保留：PG schema + 默认 Workspace + EvidenceRecord 抽离 + 稳定 ID
砍：AgentExecutor 接口（推迟到 Phase 3）
砍：FastAPI CRUD（推迟到 Phase 2）
砍：React 工作台骨架（推迟到 Phase 3）
预期评分：83（vs 完整 84）
工时节省：1 周
```

### EP-2: Phase 2 末进度滞后

```
保留：L1/L2/L3 + verify_homepage + QA rules（5 条而非 8 条）
砍：ScenarioPack 动态生成（保静态）
砍：30 条黄金集 → 18 条核心
预期评分：86
工时节省：1 周
```

### EP-3: Phase 3 末进度滞后

```
保留：Evidence Center 后端 API + 简易前端 + RedTeam
砍：EvidenceGap（保留 schema 不实现）
砍：scoring/recommender
预期评分：87
工时节省：1.5 周
```

### EP-4: Phase 4 末 Temporal 跑不通

```
保留：CompetitiveIntelWorkflow 简化版（仅 1 个 Activity）
砍：ApprovalWorkflow（推迟到 Phase 5）
答辩词："Temporal 薄壳已建立，完整 Workflow 在 Phase 5"
预期评分：89
```

## 1.11 一句话执行策略

> **每周 Friday 严守 Go/No-Go，按 P0 → P1 → P2 顺序推进；任何阶段做不完，立即触发应急预案，绝不"边赶边删功能"。Phase 1 的企业骨架是不可砍的红线，因为后期补的代价远大于一开始就做。**

---

> 下一步：阅读 [02_ARCHITECTURE_LAYERED.md](./02_ARCHITECTURE_LAYERED.md) 了解 Temporal 外层 + LangGraph 内层 + replay 限制说明。
