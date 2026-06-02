# 05 · 数据模型 · v2.0 企业骨架前置版

> **v2.0 核心修订**：所有数据骨架在 **Phase 1（W0-W4）就建立**。包括：稳定 ID 算法、Workspace/Project/Competitor 三层、EvidenceRecord 独立入库、ReportVersion 完整分组规则、AuditLog skeleton。
>
> **变更说明**：v1.0 把 Workspace 等延后到 Phase 4，被 Codex 评审指出"早期 SQLite run 工具，后期痛苦迁移"。v2.0 改为骨架前置。详见 [09_SECONDARY_REVIEW.md](./09_SECONDARY_REVIEW.md)。

## 5.1 整体数据模型

```
┌──────────────────────────────────────────────────────┐
│ Workspace · 多租户隔离边界                            │
│ ├─ Phase 1: 默认单 workspace                          │
│ ├─ Phase 4: 启用真多租户                              │
│ └─ Phase 5: 完整 RBAC + 配额                          │
└────────────┬─────────────────────────────────────────┘
             │ 1:N
             ▼
┌──────────────────────────────────────────────────────┐
│ Project · 业务单元                                    │
│ ├─ topic + competitor_layer + scenario_id            │
│ ├─ 关联 Competitors (多对多)                          │
│ ├─ 关联 Runs (一对多)                                 │
│ └─ 关联 ReportVersions (一对多)                       │
└────────────┬─────────────────────────────────────────┘
             │
             ├──── 1:N ────► Run ────► RawSource → EvidenceRecord
             │                                        │
             │                                        │ N:M
             │                                        ▼
             │                                  KnowledgeClaim
             │                                        │
             │                                        │ N:M
             ├──── 1:N ────► ReportVersion ◄──────────┘
             │
             └──── 1:N ────► AuditLog 事件
```

## 5.2 设计原则（v2.0）

1. **稳定 ID 优先** —— evidence_id / claim_id / report_version_id 全部 sha256-based 或 UUID-based，跨 run 跨 Workflow replay 都幂等
2. **预留字段不增成本** —— 所有核心表都有 `workspace_id` / `project_id` / `created_by` / `created_at` / `updated_at`
3. **唯一事实来源** —— 多对多关系只用 join 表，不在主表存数组（避免双重维护）
4. **Pydantic + SQL 双 schema** —— Pydantic 定义 DTO，SQL 定义存储，二者一致
5. **JSONB 替代附属表** —— 灵活但不索引的字段（如 metadata / tags）放 JSONB
6. **不可篡改的关键字段** —— audit_logs / report_versions 不允许 UPDATE 关键字段

## 5.3 稳定 ID 算法（★ v2.0 核心新增）

### 5.3.1 算法设计

```python
# packages/identity/stable_ids.py
import hashlib
import re

# ============== Normalization ==============

def normalize_url(url: str) -> str:
    """canonical URL: lowercase + 去 query string / fragment / 末尾斜杠"""
    if not url:
        return ""
    # 去 fragment
    url = re.sub(r'#.*$', '', url)
    # 去常见跟踪参数（utm_*, fbclid, gclid 等）
    url = re.sub(r'[?&](utm_[^=&]+|fbclid|gclid|ref|source)=[^&]*', '', url)
    # 去剩余 query string（保守做法 - 全去）
    url = re.sub(r'\?.*$', '', url)
    # 去末尾斜杠
    url = url.rstrip('/')
    # lowercase host (但保留 path 大小写)
    if '://' in url:
        scheme, rest = url.split('://', 1)
        if '/' in rest:
            host, path = rest.split('/', 1)
            url = f"{scheme}://{host.lower()}/{path}"
        else:
            url = f"{scheme}://{rest.lower()}"
    return url


def normalize_text(text: str) -> str:
    """归一化文本：小写、去多空格、保留中英文"""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def normalize_dimension_key(dimension: str) -> str:
    """归一化维度键名：用于稳定 evidence_id 计算"""
    return dimension.lower().strip().replace(' ', '_')

# ============== Stable IDs ==============

def compute_evidence_id(
    canonical_url: str,
    content_hash: str,
    competitor_id: str,
    dimension_key: str,
) -> str:
    """全局稳定 evidence_id
    
    保证同一 (URL, 内容, 竞品, 维度) 在任何 run / workflow / replay 都得到同一 ID。
    
    用途：
    - 跨 run 去重（INSERT ... ON CONFLICT DO NOTHING）
    - Evidence Center 检索
    - Temporal Activity replay 幂等
    - source reliability 统计聚合
    """
    raw = "|".join([
        canonical_url or "",
        content_hash or "",
        competitor_id or "",
        normalize_dimension_key(dimension_key or ""),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_claim_id(
    evidence_id: str,
    claim_text: str,
    claim_type: str,
) -> str:
    """全局稳定 claim_id
    
    保证同一证据下提取的同一文本同一类型 claim 是同一 ID。
    
    用途：
    - 跨 run 同一 claim 去重
    - ReportVersion diff（是同一 claim 还是新 claim）
    - Citation tracking
    """
    raw = "|".join([
        evidence_id or "",
        normalize_text(claim_text),
        (claim_type or "").lower().strip(),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_competitor_set_hash(competitor_ids: list[str]) -> str:
    """竞品集合 hash，用于 ReportVersion 分组
    
    保证 [A, B, C] 和 [C, B, A] 得到同一 hash（顺序无关）。
    
    用途：
    - ReportVersion 分组：(workspace, project, topic, layer, competitor_set_hash)
    - 跨 run 识别"是同一组竞品的不同次扫描"
    """
    if not competitor_ids:
        return hashlib.sha256(b"").hexdigest()
    sorted_ids = sorted(set(competitor_ids))
    raw = "|".join(sorted_ids)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_topic_normalized(topic: str) -> str:
    """归一化 topic 用于跨 run 聚合
    
    例：'AI 编程助手' / 'AI编程助手' / 'ai 编程助手' 都归一化为同一 key。
    """
    text = normalize_text(topic)
    # 去常见停顿词（可选）
    text = re.sub(r'[、，。！？\s]+', ' ', text).strip()
    return text


# ============== Test ==============
if __name__ == "__main__":
    # 同一 URL 不同 utm 参数应该归一化为同一 canonical_url
    assert normalize_url("https://Cursor.sh/pricing/?utm_source=ad") == normalize_url("https://cursor.sh/pricing")
    
    # 同一 (URL, content, competitor, dim) 应得到同一 evidence_id
    e1 = compute_evidence_id("https://cursor.sh/pricing", "abc123", "comp-1", "pricing")
    e2 = compute_evidence_id("https://cursor.sh/pricing", "abc123", "comp-1", "Pricing")  # 大写
    assert e1 == e2
    
    # 顺序无关
    h1 = compute_competitor_set_hash(["A", "B", "C"])
    h2 = compute_competitor_set_hash(["C", "A", "B"])
    assert h1 == h2
```

### 5.3.2 单测套件（W1 D5）

```python
# tests/unit/test_stable_ids.py
import pytest
from packages.identity.stable_ids import (
    normalize_url,
    compute_evidence_id,
    compute_claim_id,
    compute_competitor_set_hash,
)

class TestNormalizeUrl:
    def test_strips_fragment(self):
        assert normalize_url("https://x.com/a#section") == "https://x.com/a"
    
    def test_strips_utm(self):
        assert normalize_url("https://x.com/a?utm_source=fb") == "https://x.com/a"
    
    def test_lowercase_host(self):
        assert normalize_url("https://Cursor.SH/Pricing") == "https://cursor.sh/Pricing"
    
    def test_trailing_slash(self):
        assert normalize_url("https://x.com/a/") == "https://x.com/a"

class TestEvidenceId:
    def test_idempotent(self):
        a = compute_evidence_id("https://x.com/a", "hash1", "comp-1", "pricing")
        b = compute_evidence_id("https://x.com/a", "hash1", "comp-1", "pricing")
        assert a == b
    
    def test_dimension_case_insensitive(self):
        a = compute_evidence_id("https://x.com/a", "h", "c", "pricing")
        b = compute_evidence_id("https://x.com/a", "h", "c", "Pricing")
        assert a == b
    
    def test_different_competitors_get_different_ids(self):
        a = compute_evidence_id("https://x.com/a", "h", "comp-1", "pricing")
        b = compute_evidence_id("https://x.com/a", "h", "comp-2", "pricing")
        assert a != b

class TestCompetitorSetHash:
    def test_order_independent(self):
        assert compute_competitor_set_hash(["A", "B", "C"]) == \
               compute_competitor_set_hash(["C", "A", "B"])
    
    def test_dedup(self):
        assert compute_competitor_set_hash(["A", "A", "B"]) == \
               compute_competitor_set_hash(["A", "B"])
    
    def test_empty_list(self):
        assert compute_competitor_set_hash([]) == compute_competitor_set_hash([])
```

## 5.4 完整 Postgres Schema（Phase 1 全部建立）

### 5.4.1 多租户基础

```sql
-- ============== Workspaces ==============
CREATE TABLE workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    
    -- 配额（Phase 5 使用，Phase 1-4 不强制）
    monthly_run_quota INT NOT NULL DEFAULT 1000,
    monthly_llm_budget_yuan NUMERIC(10,2) NOT NULL DEFAULT 10000,
    
    -- 集成（Phase 4-5）
    notification_config JSONB DEFAULT '{}',
    
    -- 元数据
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============== Users ==============
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE,
    display_name VARCHAR(200),
    
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============== Workspace Members（Phase 5 启用 RBAC 用） ==============
CREATE TABLE workspace_members (
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    role VARCHAR(20) NOT NULL CHECK (role IN ('owner', 'admin', 'editor', 'viewer')),
    invited_by UUID REFERENCES users(id),
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (workspace_id, user_id)
);

CREATE INDEX idx_workspace_members_user ON workspace_members(user_id);

-- ============== 默认实例（Phase 1 init script） ==============
INSERT INTO workspaces (id, name, description) VALUES 
  ('00000000-0000-0000-0000-000000000001', 'Default Workspace', 'Phase 1 默认工作空间')
  ON CONFLICT DO NOTHING;

INSERT INTO users (id, email, display_name) VALUES
  ('00000000-0000-0000-0000-000000000001', 'system@local', 'System')
  ON CONFLICT DO NOTHING;

INSERT INTO workspace_members (workspace_id, user_id, role) VALUES
  ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'owner')
  ON CONFLICT DO NOTHING;
```

### 5.4.2 业务实体

```sql
-- ============== Projects ==============
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    
    name VARCHAR(200) NOT NULL,
    description TEXT,
    
    -- 业务字段
    topic VARCHAR(200) NOT NULL,
    topic_normalized VARCHAR(200) NOT NULL,
    competitor_layer VARCHAR(20) CHECK (competitor_layer IN ('product', 'platform', 'model', 'unknown')),
    scenario_id VARCHAR(100),
    
    -- 派生字段（从 project_competitors 计算）
    competitor_count INT DEFAULT 0,
    competitor_set_hash VARCHAR(64),  -- 用于 ReportVersion 分组
    
    -- 监控配置（Phase 5 启用）
    monitor_enabled BOOLEAN DEFAULT FALSE,
    monitor_cron VARCHAR(100),
    monitor_alert_threshold JSONB,
    
    -- 审批配置（Phase 4-5）
    require_approval BOOLEAN DEFAULT FALSE,
    approver_ids JSONB DEFAULT '[]',
    
    -- 状态
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'archived', 'deleted')),
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_projects_workspace ON projects(workspace_id, status);
CREATE INDEX idx_projects_topic ON projects(workspace_id, topic_normalized);

-- ============== Competitors（Workspace 级竞品库） ==============
CREATE TABLE competitors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    
    name VARCHAR(200) NOT NULL,
    aliases JSONB DEFAULT '[]',
    
    layer VARCHAR(20) CHECK (layer IN ('product', 'platform', 'model', 'unknown')),
    
    homepage VARCHAR(500),
    homepage_verified_at TIMESTAMPTZ,
    
    description TEXT,
    tags JSONB DEFAULT '[]',
    
    priority VARCHAR(5) DEFAULT 'P2' CHECK (priority IN ('P0', 'P1', 'P2', 'P3')),
    
    -- 关联（去重指针）
    merged_into_id UUID REFERENCES competitors(id),
    
    -- 元数据（派生）
    first_analyzed_at TIMESTAMPTZ DEFAULT NOW(),
    last_analyzed_at TIMESTAMPTZ DEFAULT NOW(),
    analysis_count INT DEFAULT 0,
    
    -- 状态
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'deprecated', 'merged')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_competitors_workspace_name ON competitors(workspace_id, lower(name)) WHERE status != 'merged';
CREATE INDEX idx_competitors_priority ON competitors(workspace_id, priority);

-- ============== Project ↔ Competitor (★ 唯一事实来源) ==============
-- v2.0 修订：删除 Project.competitor_ids 字段，避免双重维护
CREATE TABLE project_competitors (
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    competitor_id UUID NOT NULL REFERENCES competitors(id),
    added_at TIMESTAMPTZ DEFAULT NOW(),
    added_by UUID REFERENCES users(id),
    PRIMARY KEY (project_id, competitor_id)
);

CREATE INDEX idx_pc_competitor ON project_competitors(competitor_id);

-- 触发器：维护 Project 派生字段
CREATE OR REPLACE FUNCTION update_project_competitor_metrics() RETURNS TRIGGER AS $$
BEGIN
    -- 用 PL/pgSQL 直接 SELECT 维护 competitor_count + competitor_set_hash
    UPDATE projects p
    SET 
        competitor_count = (
            SELECT count(*) FROM project_competitors WHERE project_id = COALESCE(NEW.project_id, OLD.project_id)
        ),
        -- competitor_set_hash 由应用层算（Postgres 算 sha256 复杂）
        updated_at = NOW()
    WHERE p.id = COALESCE(NEW.project_id, OLD.project_id);
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_pc_metrics
AFTER INSERT OR DELETE ON project_competitors
FOR EACH ROW EXECUTE FUNCTION update_project_competitor_metrics();
```

### 5.4.3 Run + Evidence + Claim

```sql
-- ============== Runs ==============
CREATE TABLE runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    project_id UUID REFERENCES projects(id),
    
    -- 幂等键（Temporal 用）
    idempotency_key VARCHAR(64) UNIQUE,
    
    status VARCHAR(20) NOT NULL DEFAULT 'pending' 
        CHECK (status IN ('pending', 'running', 'awaiting_hitl', 'completed', 'failed', 'cancelled')),
    
    -- 业务字段
    topic VARCHAR(200),
    competitor_layer VARCHAR(20),
    scenario_id VARCHAR(100),
    
    -- 元数据
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    elapsed_seconds INT,
    
    -- 度量（聚合从 trace_spans）
    metrics_summary JSONB DEFAULT '{}',
    
    -- 关联
    initiating_workflow_id VARCHAR(100),  -- Temporal Phase 4+
    
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_runs_workspace_status ON runs(workspace_id, status);
CREATE INDEX idx_runs_project ON runs(project_id, created_at DESC);
CREATE INDEX idx_runs_idempotency ON runs(idempotency_key) WHERE idempotency_key IS NOT NULL;

-- ============== EvidenceRecord（独立入库，跨 run 唯一） ==============
CREATE TABLE evidence_records (
    -- ★ 稳定 ID = sha256(canonical_url + content_hash + competitor_id + dimension_key)
    id VARCHAR(64) PRIMARY KEY,
    
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    competitor_id UUID NOT NULL REFERENCES competitors(id),
    
    -- 来源
    source_type VARCHAR(50) NOT NULL,
    url VARCHAR(1000),
    canonical_url VARCHAR(1000),
    title VARCHAR(500),
    snippet TEXT,
    content_hash VARCHAR(64) NOT NULL,
    
    -- 维度
    dimension VARCHAR(50) NOT NULL,
    
    -- 质量
    reliability_score NUMERIC(3,2) NOT NULL DEFAULT 0.7 CHECK (reliability_score >= 0 AND reliability_score <= 1),
    confidence NUMERIC(3,2) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    
    -- 用户编辑
    quality_label VARCHAR(20) CHECK (quality_label IN ('good', 'outdated', 'pending_review', 'discarded')),
    user_notes TEXT,
    user_edited_at TIMESTAMPTZ,
    user_edited_by UUID REFERENCES users(id),
    
    -- 跨 run 跟踪
    first_seen_run_id UUID REFERENCES runs(id),
    last_seen_run_id UUID REFERENCES runs(id),
    seen_count INT DEFAULT 1,
    
    -- 时间
    extracted_at TIMESTAMPTZ NOT NULL,
    indexed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_evidence_workspace ON evidence_records(workspace_id);
CREATE INDEX idx_evidence_competitor_dim ON evidence_records(workspace_id, competitor_id, dimension);
CREATE INDEX idx_evidence_quality ON evidence_records(workspace_id, quality_label) WHERE quality_label IS NOT NULL;
CREATE INDEX idx_evidence_seen ON evidence_records(workspace_id, last_seen_run_id);

-- 全文检索
ALTER TABLE evidence_records 
ADD COLUMN search_vector TSVECTOR GENERATED ALWAYS AS (
    to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(snippet, ''))
) STORED;
CREATE INDEX idx_evidence_search ON evidence_records USING GIN(search_vector);

-- ============== Run-Evidence 关联（一个 evidence 可能在多个 run 出现） ==============
CREATE TABLE run_evidence (
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    evidence_id VARCHAR(64) NOT NULL REFERENCES evidence_records(id),
    extracted_in_iteration INT DEFAULT 0,
    PRIMARY KEY (run_id, evidence_id)
);

CREATE INDEX idx_re_evidence ON run_evidence(evidence_id);

-- ============== KnowledgeClaim（结构化结论） ==============
CREATE TABLE knowledge_claims (
    -- ★ 稳定 ID = sha256(evidence_id + normalized_claim_text + claim_type)
    -- 注：单 claim 可能引用多个 evidence。计算 ID 时用 primary evidence_id。
    id VARCHAR(64) PRIMARY KEY,
    
    workspace_id UUID NOT NULL,
    competitor_id UUID NOT NULL REFERENCES competitors(id),
    
    -- 内容
    claim_text TEXT NOT NULL,
    normalized_claim_text TEXT NOT NULL,
    claim_type VARCHAR(50) NOT NULL,  -- 'pricing_tier' / 'feature' / 'persona_segment' / ...
    
    layer VARCHAR(20),  -- product / platform / model
    dimension VARCHAR(50),
    
    -- 度量
    confidence NUMERIC(3,2) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    
    -- 跨 run 跟踪
    first_seen_run_id UUID REFERENCES runs(id),
    last_seen_run_id UUID REFERENCES runs(id),
    seen_count INT DEFAULT 1,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_claims_workspace ON knowledge_claims(workspace_id);
CREATE INDEX idx_claims_competitor_dim ON knowledge_claims(workspace_id, competitor_id, dimension);

-- ============== Claim ↔ Evidence 多对多 ==============
CREATE TABLE claim_evidence (
    claim_id VARCHAR(64) NOT NULL REFERENCES knowledge_claims(id) ON DELETE CASCADE,
    evidence_id VARCHAR(64) NOT NULL REFERENCES evidence_records(id),
    is_primary BOOLEAN DEFAULT FALSE,  -- 用于计算 claim_id 的主 evidence
    PRIMARY KEY (claim_id, evidence_id)
);

CREATE INDEX idx_ce_evidence ON claim_evidence(evidence_id);

-- ============== Run-Claim 关联 ==============
CREATE TABLE run_claims (
    run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    claim_id VARCHAR(64) NOT NULL REFERENCES knowledge_claims(id),
    iteration INT DEFAULT 0,
    PRIMARY KEY (run_id, claim_id)
);

CREATE INDEX idx_rc_claim ON run_claims(claim_id);
```

### 5.4.4 ReportVersion + 分组规则

```sql
-- ============== ReportVersion ==============
CREATE TABLE report_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    
    -- ★ 分组键（v2.0 修订：5 维分组）
    topic_normalized VARCHAR(200) NOT NULL,
    competitor_layer VARCHAR(20) NOT NULL,
    competitor_set_hash VARCHAR(64) NOT NULL,
    
    -- 版本号（同一分组内递增）
    version_number INT NOT NULL,
    parent_version_id UUID REFERENCES report_versions(id),
    
    -- 内容
    run_id UUID REFERENCES runs(id),
    report_md TEXT NOT NULL,
    summary TEXT,
    
    -- 关键变更（Phase 3 ReportVersion diff）
    key_changes JSONB DEFAULT '[]',
    
    -- 状态
    is_published BOOLEAN DEFAULT FALSE,
    published_at TIMESTAMPTZ,
    published_by UUID REFERENCES users(id),
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- ★ 唯一约束：分组内版本号唯一（保证幂等）
    CONSTRAINT uq_report_version 
        UNIQUE (workspace_id, project_id, topic_normalized, competitor_layer, competitor_set_hash, version_number)
);

CREATE INDEX idx_rv_workspace ON report_versions(workspace_id, project_id, created_at DESC);
CREATE INDEX idx_rv_grouping 
    ON report_versions(workspace_id, project_id, topic_normalized, competitor_layer, competitor_set_hash);
CREATE INDEX idx_rv_published 
    ON report_versions(workspace_id, is_published, published_at DESC) WHERE is_published;

-- ============== ReportVersion 引用的 claims ==============
CREATE TABLE report_version_claims (
    report_version_id UUID NOT NULL REFERENCES report_versions(id) ON DELETE CASCADE,
    claim_id VARCHAR(64) NOT NULL REFERENCES knowledge_claims(id),
    citation_position INT,  -- 在报告中的引用位置（用于 hover card）
    PRIMARY KEY (report_version_id, claim_id)
);

CREATE INDEX idx_rvc_claim ON report_version_claims(claim_id);
```

**ReportVersion 分组规则示意**：

```
同一 Project 下，按 (topic_normalized, competitor_layer, competitor_set_hash) 分组，
每个分组独立版本号递增。

例：
Project "AI 编程助手扫描"
├─ Group A: (topic="AI 编程助手", layer=product, hash=H1[Cursor,Windsurf,Copilot])
│   ├─ v1 (run_id=r1, 2026-04-15)
│   ├─ v2 (run_id=r2, 2026-05-20)  ← 同 3 个竞品再扫描
│   └─ v3 (run_id=r3, 2026-06-10)
└─ Group B: (topic="AI 编程助手", layer=product, hash=H2[Cursor,Windsurf,Copilot,Codeium])
    └─ v1 (run_id=r4, 2026-06-15)  ← 加入 Codeium 后是新分组
```

**v1.0 错误**：v1.0 草案只用 topic_normalized 分组，会导致 Cursor+Windsurf vs Cursor+Windsurf+Copilot 混在同一版本系列。

**v2.0 修订**：用 5 维分组 `(workspace_id, project_id, topic_normalized, competitor_layer, competitor_set_hash)` 严格区分。

### 5.4.5 AuditLog Skeleton

```sql
-- ============== AuditLog（Phase 1 skeleton，Phase 5 强化） ==============
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL,
    
    actor_id UUID,
    actor_type VARCHAR(20) DEFAULT 'system' CHECK (actor_type IN ('user', 'system', 'agent', 'workflow')),
    
    action VARCHAR(100) NOT NULL,
    target_type VARCHAR(50),
    target_id VARCHAR(64),
    
    payload JSONB,
    request_metadata JSONB,
    
    occurred_at TIMESTAMPTZ DEFAULT NOW()
);

-- 索引
CREATE INDEX idx_audit_workspace_time ON audit_logs(workspace_id, occurred_at DESC);
CREATE INDEX idx_audit_actor ON audit_logs(actor_id, occurred_at DESC);
CREATE INDEX idx_audit_target ON audit_logs(target_type, target_id);
CREATE INDEX idx_audit_action ON audit_logs(action);

-- ★ Phase 5 启用：不可篡改约束
-- REVOKE UPDATE, DELETE ON audit_logs FROM PUBLIC;
-- ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
```

**Phase 1 必须 emit 的事件清单**：

```python
PHASE_1_AUDIT_ACTIONS = [
    # Workspace
    "workspace.create",
    
    # Project
    "project.create",
    "project.update",
    
    # Run
    "run.create",
    "run.complete",
    "run.fail",
    
    # Evidence
    "evidence.upsert",
    "evidence.quality.update",
    
    # ReportVersion
    "report_version.create",
    "report_version.publish",
]
```

Phase 4-5 加更多事件（详见 [05_DATA_MODELS.md](./05_DATA_MODELS.md) §5.8）。

## 5.5 Pydantic Schema（应用层）

```python
# packages/schema/v2.py（新增）
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

# ============== Workspace / Project ==============

class Workspace(StrictModel):
    id: str
    name: str
    description: str = ""
    monthly_run_quota: int = 1000
    monthly_llm_budget_yuan: float = 10000.0
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

class Project(StrictModel):
    id: str
    workspace_id: str
    name: str
    description: str = ""
    topic: str
    topic_normalized: str
    competitor_layer: Literal["product", "platform", "model", "unknown"] = "unknown"
    scenario_id: str | None = None
    
    # 派生字段（v2.0 修订：不存 competitor_ids 列表）
    competitor_count: int = 0
    competitor_set_hash: str | None = None
    
    monitor_enabled: bool = False
    monitor_cron: str | None = None
    
    require_approval: bool = False
    approver_ids: list[str] = Field(default_factory=list)
    
    status: Literal["active", "archived", "deleted"] = "active"
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

class Competitor(StrictModel):
    id: str
    workspace_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    layer: Literal["product", "platform", "model", "unknown"] = "unknown"
    homepage: HttpUrl | None = None
    homepage_verified_at: datetime | None = None
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    priority: Literal["P0", "P1", "P2", "P3"] = "P2"
    merged_into_id: str | None = None
    first_analyzed_at: datetime
    last_analyzed_at: datetime
    analysis_count: int = 0
    status: Literal["active", "deprecated", "merged"] = "active"
    created_at: datetime
    updated_at: datetime

# ============== Evidence / Claim ==============

class EvidenceRecord(StrictModel):
    """v2.0 核心：稳定 ID + 跨 run 入库"""
    id: str  # sha256-based
    workspace_id: str
    competitor_id: str
    
    source_type: str
    url: HttpUrl | None = None
    canonical_url: str
    title: str
    snippet: str
    content_hash: str
    
    dimension: str
    reliability_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    
    quality_label: Literal["good", "outdated", "pending_review", "discarded"] | None = None
    user_notes: str = ""
    user_edited_at: datetime | None = None
    
    first_seen_run_id: str | None = None
    last_seen_run_id: str | None = None
    seen_count: int = 1
    
    extracted_at: datetime
    indexed_at: datetime

class KnowledgeClaim(StrictModel):
    """v2.0 核心：稳定 ID + 跨 run 入库"""
    id: str  # sha256-based
    workspace_id: str
    competitor_id: str
    
    claim_text: str
    normalized_claim_text: str
    claim_type: str
    
    layer: Literal["product", "platform", "model", "unknown"] | None = None
    dimension: str | None = None
    
    confidence: float = Field(ge=0.0, le=1.0)
    
    evidence_ids: list[str] = Field(min_length=1)  # 一个 claim 至少 1 个 evidence
    
    first_seen_run_id: str | None = None
    last_seen_run_id: str | None = None
    seen_count: int = 1
    
    created_at: datetime

# ============== Run / ReportVersion ==============

class Run(StrictModel):
    id: str
    workspace_id: str
    project_id: str | None = None
    idempotency_key: str | None = None
    status: Literal["pending", "running", "awaiting_hitl", "completed", "failed", "cancelled"]
    topic: str
    competitor_layer: Literal["product", "platform", "model", "unknown"]
    scenario_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    elapsed_seconds: int | None = None
    metrics_summary: dict = Field(default_factory=dict)
    initiating_workflow_id: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

class ReportVersion(StrictModel):
    """v2.0 核心：5 维分组规则"""
    id: str
    workspace_id: str
    project_id: str
    
    # 分组键（v2.0 必填）
    topic_normalized: str
    competitor_layer: Literal["product", "platform", "model", "unknown"]
    competitor_set_hash: str
    
    version_number: int = Field(ge=1)
    parent_version_id: str | None = None
    
    run_id: str | None = None
    report_md: str
    summary: str = ""
    
    key_changes: list[str] = Field(default_factory=list)
    
    is_published: bool = False
    published_at: datetime | None = None
    published_by: str | None = None
    
    created_at: datetime

# ============== AgentExecutor 接口 ==============

class AgentContext(StrictModel):
    """Agent 运行上下文"""
    run_id: str
    project_id: str | None = None
    workspace_id: str
    iteration: int = 0
    parent_subagent: str | None = None
    qa_feedback: list[dict] = Field(default_factory=list)
```

## 5.6 与现有 plan_a 的迁移路径

### 当前 plan_a 现状（v1）

```python
# 当前所有数据埋在 RunDetail JSON 里
class RunDetail(BaseModel):
    raw_sources: list[RawSource]  # 没有 evidence_id
    competitor_kbs: dict[str, CompetitorKB]
    claims: list[KnowledgeClaim]  # 没有 claim_id
    report_md: str
```

### Phase 1 改造步骤

```
W1: 起 PG + 13 张表
W2: EvidenceStore 双写（旧 RunDetail.raw_sources + 新 evidence_records 表）
W3: 验证双写一致性 + 切流到主读新表
W4: ReportVersionStore + AuditLogger 接入

切流后：
- RunDetail.raw_sources 字段保留为兼容（前端继续用）
- 但权威数据在 evidence_records 表
- 跨 run 检索都走新表
```

### v1.0 RawSource 升级到 v2.0 EvidenceRecord

```python
# packages/evidence/migrate.py
def upgrade_raw_source_to_evidence_record(
    raw: RawSource,
    workspace_id: str,
    competitor_id: str,
    run_id: str,
) -> EvidenceRecord:
    canonical_url = normalize_url(str(raw.url) if raw.url else "")
    
    evidence_id = compute_evidence_id(
        canonical_url=canonical_url,
        content_hash=raw.content_hash,
        competitor_id=competitor_id,
        dimension_key=raw.dimension,
    )
    
    return EvidenceRecord(
        id=evidence_id,
        workspace_id=workspace_id,
        competitor_id=competitor_id,
        source_type=raw.source_type,
        url=raw.url,
        canonical_url=canonical_url,
        title=raw.title,
        snippet=raw.snippet,
        content_hash=raw.content_hash,
        dimension=raw.dimension,
        reliability_score=0.7,  # Phase 2 由 Source Registry 决定
        confidence=raw.confidence,
        first_seen_run_id=run_id,
        last_seen_run_id=run_id,
        extracted_at=raw.extracted_at,
        indexed_at=datetime.utcnow(),
    )
```

## 5.7 关键查询示例

### 跨 run 查 Cursor 的 pricing 证据

```sql
SELECT 
    er.id, er.url, er.title, er.snippet, er.confidence,
    er.first_seen_run_id, er.last_seen_run_id, er.seen_count,
    er.quality_label
FROM evidence_records er
JOIN competitors c ON er.competitor_id = c.id
WHERE er.workspace_id = $1
  AND c.name ILIKE 'cursor'
  AND er.dimension = 'pricing'
  AND (er.quality_label IS NULL OR er.quality_label != 'discarded')
ORDER BY er.confidence DESC, er.last_seen_run_id DESC
LIMIT 50;
```

### ReportVersion diff（同 Project 同 topic 同 layer 同竞品集合）

```sql
SELECT v.* 
FROM report_versions v
WHERE v.workspace_id = $1
  AND v.project_id = $2
  AND v.topic_normalized = $3
  AND v.competitor_layer = $4
  AND v.competitor_set_hash = $5
ORDER BY v.version_number DESC;
```

### 找 ReportVersion v3 vs v2 的 claim 增量

```sql
-- v3 有但 v2 没有的 claims（新增）
SELECT c.id, c.claim_text
FROM report_version_claims rvc3
JOIN knowledge_claims c ON rvc3.claim_id = c.id
WHERE rvc3.report_version_id = $1  -- v3 id
  AND NOT EXISTS (
      SELECT 1 FROM report_version_claims rvc2
      WHERE rvc2.report_version_id = $2  -- v2 id
        AND rvc2.claim_id = c.id
  );
```

## 5.8 不做的（v2.0 克制）

| 项 | 不做原因 |
|---|---|
| Activity feed | 用 audit_logs 即可 |
| Comments / Threads | Phase 5 再考虑 |
| 多语言 i18n | YAGNI |
| Custom fields | JSONB 已够灵活 |
| 全文搜索高级查询 | Phase 5 加 Meilisearch |

## 5.9 一句话总结

> **v2.0 把所有数据骨架（13 张表 + 稳定 ID + 5 维分组规则 + 唯一事实来源）在 Phase 1 一次建立，避免后期 ALTER TABLE / 数据迁移的痛苦。Phase 2-5 逐步填充复杂能力（RBAC、Source Registry、pgvector、Temporal）。**

---

> 下一步：阅读 [02_ARCHITECTURE_LAYERED.md](./02_ARCHITECTURE_LAYERED.md) 了解 Temporal replay 限制和幂等性设计。
