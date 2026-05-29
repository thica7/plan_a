-- Enterprise core schema for the Phase 1 Postgres cutover.
-- The current runtime uses EnterpriseMemoryStore behind the same repository
-- boundary; these tables are the target durable projection.

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'analyst', 'reviewer', 'viewer')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    name TEXT NOT NULL,
    topic TEXT NOT NULL,
    topic_normalized TEXT NOT NULL,
    competitor_layer TEXT NOT NULL DEFAULT 'unknown'
        CHECK (competitor_layer IN ('L1', 'L2', 'L3', 'unknown')),
    competitor_set_hash TEXT NOT NULL DEFAULT '',
    scenario_id TEXT,
    created_by TEXT REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS competitors (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    layer TEXT NOT NULL DEFAULT 'unknown' CHECK (layer IN ('L1', 'L2', 'L3', 'unknown')),
    homepage_url TEXT,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, normalized_name)
);

CREATE TABLE IF NOT EXISTS project_competitors (
    project_id TEXT NOT NULL REFERENCES projects(id),
    competitor_id TEXT NOT NULL REFERENCES competitors(id),
    role TEXT NOT NULL DEFAULT 'target' CHECK (role IN ('target', 'baseline', 'adjacent')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, competitor_id)
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    project_id TEXT REFERENCES projects(id),
    topic TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'interrupted', 'completed', 'failed')),
    execution_mode TEXT NOT NULL CHECK (execution_mode IN ('demo', 'real')),
    detail_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_records (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    run_id TEXT REFERENCES runs(id),
    raw_source_id TEXT NOT NULL,
    competitor_id TEXT NOT NULL REFERENCES competitors(id),
    dimension TEXT NOT NULL,
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    canonical_url TEXT NOT NULL DEFAULT '',
    snippet TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,
    reliability_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    freshness_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    quality_label TEXT NOT NULL DEFAULT 'unreviewed'
        CHECK (quality_label IN ('unreviewed', 'accepted', 'rejected', 'stale')),
    first_seen_run_id TEXT REFERENCES runs(id),
    last_seen_run_id TEXT REFERENCES runs(id),
    seen_count INTEGER NOT NULL DEFAULT 1 CHECK (seen_count >= 1),
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS source_registry (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    domain TEXT NOT NULL,
    source_type TEXT NOT NULL,
    display_name TEXT NOT NULL,
    homepage_url TEXT,
    trust_level TEXT NOT NULL DEFAULT 'unknown'
        CHECK (trust_level IN ('official', 'verified', 'community', 'synthetic', 'unknown')),
    robots_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (robots_status IN ('unknown', 'allowed', 'blocked', 'error')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_run_id TEXT REFERENCES runs(id),
    last_seen_run_id TEXT REFERENCES runs(id),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seen_count INTEGER NOT NULL DEFAULT 1 CHECK (seen_count >= 1),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (workspace_id, domain, source_type)
);

CREATE TABLE IF NOT EXISTS knowledge_claims (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    run_id TEXT REFERENCES runs(id),
    competitor_id TEXT NOT NULL REFERENCES competitors(id),
    claim_type TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    evidence_ids TEXT[] NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'proposed'
        CHECK (status IN ('proposed', 'accepted', 'disputed', 'rejected', 'deprecated')),
    created_by_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS claim_evidence (
    claim_id TEXT NOT NULL REFERENCES knowledge_claims(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES evidence_records(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (claim_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS report_versions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    run_id TEXT REFERENCES runs(id),
    parent_version_id TEXT REFERENCES report_versions(id),
    version_number INTEGER NOT NULL CHECK (version_number >= 1),
    topic_normalized TEXT NOT NULL,
    competitor_layer TEXT NOT NULL DEFAULT 'unknown'
        CHECK (competitor_layer IN ('L1', 'L2', 'L3', 'unknown')),
    competitor_set_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'in_review', 'approved', 'published', 'archived')),
    report_md TEXT NOT NULL DEFAULT '',
    claim_ids TEXT[] NOT NULL DEFAULT '{}',
    evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    UNIQUE (
        workspace_id,
        project_id,
        topic_normalized,
        competitor_layer,
        competitor_set_hash,
        version_number
    )
);

CREATE TABLE IF NOT EXISTS report_version_claims (
    report_version_id TEXT NOT NULL REFERENCES report_versions(id) ON DELETE CASCADE,
    claim_id TEXT NOT NULL REFERENCES knowledge_claims(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    ordinal INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (report_version_id, claim_id)
);

CREATE TABLE IF NOT EXISTS report_version_evidence (
    report_version_id TEXT NOT NULL REFERENCES report_versions(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES evidence_records(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    ordinal INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (report_version_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'agent', 'workflow', 'system')),
    actor_id TEXT,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    before JSONB,
    after JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_projects_workspace ON projects(workspace_id);
CREATE INDEX IF NOT EXISTS idx_competitors_workspace ON competitors(workspace_id);
CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_id);
CREATE INDEX IF NOT EXISTS idx_evidence_project_dimension
    ON evidence_records(project_id, dimension);
CREATE INDEX IF NOT EXISTS idx_source_registry_workspace_domain
    ON source_registry(workspace_id, domain);
CREATE INDEX IF NOT EXISTS idx_source_registry_workspace_trust
    ON source_registry(workspace_id, trust_level);
CREATE INDEX IF NOT EXISTS idx_claims_project_competitor
    ON knowledge_claims(project_id, competitor_id);
CREATE INDEX IF NOT EXISTS idx_claim_evidence_evidence
    ON claim_evidence(evidence_id);
CREATE INDEX IF NOT EXISTS idx_report_versions_project_group
    ON report_versions(project_id, topic_normalized, competitor_layer, competitor_set_hash);
CREATE INDEX IF NOT EXISTS idx_report_version_claims_claim
    ON report_version_claims(claim_id);
CREATE INDEX IF NOT EXISTS idx_report_version_evidence_evidence
    ON report_version_evidence(evidence_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_workspace_created
    ON audit_logs(workspace_id, created_at DESC);

INSERT INTO workspaces (id, name, description)
VALUES ('default-workspace', 'Default Workspace', 'Phase 1 default workspace')
ON CONFLICT (id) DO NOTHING;

INSERT INTO users (id, email, display_name, role)
VALUES ('system-user', 'system@local', 'System', 'owner')
ON CONFLICT (id) DO NOTHING;

ALTER TABLE runs ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
UPDATE runs SET idempotency_key = id WHERE idempotency_key IS NULL OR idempotency_key = '';
ALTER TABLE runs ALTER COLUMN idempotency_key SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_idempotency_key ON runs(idempotency_key);

ALTER TABLE evidence_records ADD COLUMN IF NOT EXISTS canonical_url TEXT NOT NULL DEFAULT '';
ALTER TABLE evidence_records ADD COLUMN IF NOT EXISTS first_seen_run_id TEXT REFERENCES runs(id);
ALTER TABLE evidence_records ADD COLUMN IF NOT EXISTS last_seen_run_id TEXT REFERENCES runs(id);
ALTER TABLE evidence_records ADD COLUMN IF NOT EXISTS seen_count INTEGER NOT NULL DEFAULT 1;
UPDATE evidence_records
SET canonical_url = COALESCE(NULLIF(canonical_url, ''), url, '')
WHERE canonical_url = '';
CREATE INDEX IF NOT EXISTS idx_evidence_canonical_url
    ON evidence_records(workspace_id, canonical_url);

CREATE UNIQUE INDEX IF NOT EXISTS idx_report_versions_workspace_group_unique
    ON report_versions (
        workspace_id,
        project_id,
        topic_normalized,
        competitor_layer,
        competitor_set_hash,
        version_number
    );
