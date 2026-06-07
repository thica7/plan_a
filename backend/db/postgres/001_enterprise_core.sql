-- Enterprise core schema for the Phase 1 Postgres cutover.
-- The current runtime uses EnterpriseMemoryStore behind the same repository
-- boundary; these tables are the target durable projection.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    monthly_run_quota INTEGER NOT NULL DEFAULT 1000 CHECK (monthly_run_quota >= 0),
    monthly_token_quota INTEGER NOT NULL DEFAULT 2000000 CHECK (monthly_token_quota >= 0),
    monthly_cost_quota_usd DOUBLE PRECISION NOT NULL DEFAULT 100
        CHECK (monthly_cost_quota_usd >= 0),
    quota_enforcement TEXT NOT NULL DEFAULT 'block'
        CHECK (quota_enforcement IN ('monitor', 'block')),
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

CREATE TABLE IF NOT EXISTS workspace_members (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'viewer'
        CHECK (role IN ('owner', 'admin', 'analyst', 'reviewer', 'viewer')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, user_id)
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
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    notification_type TEXT NOT NULL
        CHECK (
            notification_type IN (
                'scheduled_scan_summary',
                'scheduled_scan_failure',
                'approval_request',
                'approval_timeout',
                'anomaly_alert',
                'quota_warning',
                'release_gate_blocked'
            )
        ),
    channel TEXT NOT NULL DEFAULT 'in_app'
        CHECK (channel IN ('in_app', 'email', 'webhook', 'feishu')),
    severity TEXT NOT NULL DEFAULT 'info'
        CHECK (severity IN ('info', 'success', 'warning', 'critical')),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'sent', 'failed', 'read')),
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    resource_type TEXT,
    resource_id TEXT,
    created_by TEXT REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at TIMESTAMPTZ,
    read_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
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

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    evidence_id TEXT REFERENCES evidence_records(id) ON DELETE SET NULL,
    run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
    report_version_id TEXT,
    artifact_type TEXT NOT NULL DEFAULT 'raw_text'
        CHECK (
            artifact_type IN (
                'web_snapshot',
                'pdf',
                'screenshot',
                'raw_text',
                'report_export',
                'survey_response',
                'interview_record',
                'manual_transcript',
                'other'
            )
        ),
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    storage_backend TEXT NOT NULL DEFAULT 'local'
        CHECK (storage_backend IN ('local', 'external', 's3', 'oss')),
    uri TEXT NOT NULL,
    byte_size INTEGER NOT NULL DEFAULT 0 CHECK (byte_size >= 0),
    content_hash TEXT NOT NULL,
    source_url TEXT,
    created_by TEXT REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    retention_policy TEXT NOT NULL DEFAULT 'workspace_default',
    compliance_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE artifacts
    ADD COLUMN IF NOT EXISTS report_version_id TEXT;
ALTER TABLE artifacts
    ADD COLUMN IF NOT EXISTS retention_policy TEXT NOT NULL DEFAULT 'workspace_default';
ALTER TABLE artifacts
    ADD COLUMN IF NOT EXISTS compliance_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE artifacts
    DROP CONSTRAINT IF EXISTS artifacts_artifact_type_check;
ALTER TABLE artifacts
    ADD CONSTRAINT artifacts_artifact_type_check
    CHECK (
        artifact_type IN (
            'web_snapshot',
            'pdf',
            'screenshot',
            'raw_text',
            'report_export',
            'survey_response',
            'interview_record',
            'manual_transcript',
            'other'
        )
    );
ALTER TABLE artifacts
    DROP CONSTRAINT IF EXISTS artifacts_storage_backend_check;
ALTER TABLE artifacts
    ADD CONSTRAINT artifacts_storage_backend_check
    CHECK (storage_backend IN ('local', 'external', 's3', 'oss'));

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
    policy_review_status TEXT NOT NULL DEFAULT 'not_required'
        CHECK (policy_review_status IN ('not_required', 'pending', 'approved', 'rejected')),
    policy_review_reason TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_run_id TEXT REFERENCES runs(id),
    last_seen_run_id TEXT REFERENCES runs(id),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seen_count INTEGER NOT NULL DEFAULT 1 CHECK (seen_count >= 1),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (workspace_id, domain, source_type)
);

CREATE TABLE IF NOT EXISTS evidence_embeddings (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    evidence_id TEXT NOT NULL REFERENCES evidence_records(id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL,
    embedding_dimensions INTEGER NOT NULL DEFAULT 384 CHECK (embedding_dimensions > 0),
    embedding_hash TEXT NOT NULL,
    embedding_text TEXT NOT NULL,
    embedding VECTOR(384) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (evidence_id, embedding_model)
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
        CHECK (status IN ('draft', 'in_review', 'approved', 'rejected', 'published', 'archived')),
    report_md TEXT NOT NULL DEFAULT '',
    claim_ids TEXT[] NOT NULL DEFAULT '{}',
    evidence_ids TEXT[] NOT NULL DEFAULT '{}',
    quality_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
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
CREATE INDEX IF NOT EXISTS idx_workspace_members_user
    ON workspace_members(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_workspace_created
    ON notifications(workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_workspace_status
    ON notifications(workspace_id, status);
CREATE INDEX IF NOT EXISTS idx_competitors_workspace ON competitors(workspace_id);
CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_id);
CREATE INDEX IF NOT EXISTS idx_evidence_project_dimension
    ON evidence_records(project_id, dimension);
CREATE INDEX IF NOT EXISTS idx_artifacts_workspace_project
    ON artifacts(workspace_id, project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_artifacts_evidence
    ON artifacts(evidence_id);
CREATE INDEX IF NOT EXISTS idx_source_registry_workspace_domain
    ON source_registry(workspace_id, domain);
CREATE INDEX IF NOT EXISTS idx_source_registry_workspace_trust
    ON source_registry(workspace_id, trust_level);
CREATE INDEX IF NOT EXISTS idx_evidence_embeddings_workspace
    ON evidence_embeddings(workspace_id, project_id);
CREATE INDEX IF NOT EXISTS idx_evidence_embeddings_vector
    ON evidence_embeddings USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
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

ALTER TABLE workspaces
    ADD COLUMN IF NOT EXISTS monthly_run_quota INTEGER NOT NULL DEFAULT 1000;
ALTER TABLE workspaces
    ADD COLUMN IF NOT EXISTS monthly_token_quota INTEGER NOT NULL DEFAULT 2000000;
ALTER TABLE workspaces
    ADD COLUMN IF NOT EXISTS monthly_cost_quota_usd DOUBLE PRECISION NOT NULL DEFAULT 100;
ALTER TABLE workspaces
    ADD COLUMN IF NOT EXISTS quota_enforcement TEXT NOT NULL DEFAULT 'block';
ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS workspaces_monthly_run_quota_check;
ALTER TABLE workspaces
    ADD CONSTRAINT workspaces_monthly_run_quota_check CHECK (monthly_run_quota >= 0);
ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS workspaces_monthly_token_quota_check;
ALTER TABLE workspaces
    ADD CONSTRAINT workspaces_monthly_token_quota_check CHECK (monthly_token_quota >= 0);
ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS workspaces_monthly_cost_quota_usd_check;
ALTER TABLE workspaces
    ADD CONSTRAINT workspaces_monthly_cost_quota_usd_check CHECK (monthly_cost_quota_usd >= 0);
ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS workspaces_quota_enforcement_check;
ALTER TABLE workspaces
    ADD CONSTRAINT workspaces_quota_enforcement_check
        CHECK (quota_enforcement IN ('monitor', 'block'));

ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_notification_type_check;
ALTER TABLE notifications
    ADD CONSTRAINT notifications_notification_type_check CHECK (
        notification_type IN (
            'scheduled_scan_summary',
            'scheduled_scan_failure',
            'approval_request',
            'approval_timeout',
            'anomaly_alert',
            'quota_warning',
            'release_gate_blocked'
        )
    );

INSERT INTO workspaces (id, name, description)
VALUES ('default-workspace', 'Default Workspace', 'Phase 1 default workspace')
ON CONFLICT (id) DO NOTHING;

INSERT INTO users (id, email, display_name, role)
VALUES ('system-user', 'system@local', 'System', 'owner')
ON CONFLICT (id) DO NOTHING;

INSERT INTO workspace_members (workspace_id, user_id, role)
VALUES ('default-workspace', 'system-user', 'owner')
ON CONFLICT (workspace_id, user_id) DO NOTHING;

ALTER TABLE runs ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
UPDATE runs SET idempotency_key = id WHERE idempotency_key IS NULL OR idempotency_key = '';
ALTER TABLE runs ALTER COLUMN idempotency_key SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_idempotency_key ON runs(idempotency_key);

ALTER TABLE evidence_records ADD COLUMN IF NOT EXISTS canonical_url TEXT NOT NULL DEFAULT '';
ALTER TABLE evidence_records ADD COLUMN IF NOT EXISTS first_seen_run_id TEXT REFERENCES runs(id);
ALTER TABLE evidence_records ADD COLUMN IF NOT EXISTS last_seen_run_id TEXT REFERENCES runs(id);
ALTER TABLE evidence_records ADD COLUMN IF NOT EXISTS seen_count INTEGER NOT NULL DEFAULT 1;
ALTER TABLE report_versions
    ADD COLUMN IF NOT EXISTS quality_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE source_registry
    ADD COLUMN IF NOT EXISTS policy_review_status TEXT NOT NULL DEFAULT 'not_required';
ALTER TABLE source_registry
    ADD COLUMN IF NOT EXISTS policy_review_reason TEXT NOT NULL DEFAULT '';
ALTER TABLE source_registry DROP CONSTRAINT IF EXISTS source_registry_policy_review_status_check;
ALTER TABLE source_registry
    ADD CONSTRAINT source_registry_policy_review_status_check CHECK (
        policy_review_status IN ('not_required', 'pending', 'approved', 'rejected')
    );
CREATE INDEX IF NOT EXISTS idx_source_registry_workspace_review
    ON source_registry(workspace_id, policy_review_status);
UPDATE evidence_records
SET canonical_url = COALESCE(NULLIF(canonical_url, ''), url, '')
WHERE canonical_url = '';
CREATE INDEX IF NOT EXISTS idx_evidence_canonical_url
    ON evidence_records(workspace_id, canonical_url);
ALTER TABLE evidence_records
ADD COLUMN IF NOT EXISTS search_vector TSVECTOR GENERATED ALWAYS AS (
    to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(snippet, ''))
) STORED;
CREATE INDEX IF NOT EXISTS idx_evidence_search
    ON evidence_records USING GIN(search_vector);

CREATE UNIQUE INDEX IF NOT EXISTS idx_report_versions_workspace_group_unique
    ON report_versions (
        workspace_id,
        project_id,
        topic_normalized,
        competitor_layer,
        competitor_set_hash,
        version_number
    );

-- Phase 5 tenant isolation guardrail.
-- Production connection pools should set:
--   SET app.current_workspace_id = '<workspace-id>';
-- Background jobs and migrations may set:
--   SET app.service_role = 'on';
-- Table owners still bypass RLS unless FORCE ROW LEVEL SECURITY is enabled by deployment.
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_workspaces ON workspaces;
CREATE POLICY tenant_isolation_workspaces ON workspaces
    FOR ALL
    USING (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR id = NULLIF(current_setting('app.current_workspace_id', true), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR id = NULLIF(current_setting('app.current_workspace_id', true), '')
    );

ALTER TABLE workspace_members ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_workspace_members ON workspace_members;
CREATE POLICY tenant_isolation_workspace_members ON workspace_members
    FOR ALL
    USING (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    );

ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_projects ON projects;
CREATE POLICY tenant_isolation_projects ON projects
    FOR ALL
    USING (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    );

ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_notifications ON notifications;
CREATE POLICY tenant_isolation_notifications ON notifications
    FOR ALL
    USING (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    );

ALTER TABLE competitors ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_competitors ON competitors;
CREATE POLICY tenant_isolation_competitors ON competitors
    FOR ALL
    USING (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    );

ALTER TABLE project_competitors ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_project_competitors ON project_competitors;
CREATE POLICY tenant_isolation_project_competitors ON project_competitors
    FOR ALL
    USING (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR EXISTS (
            SELECT 1 FROM projects
            WHERE projects.id = project_competitors.project_id
              AND projects.workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
        )
    )
    WITH CHECK (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR EXISTS (
            SELECT 1 FROM projects
            WHERE projects.id = project_competitors.project_id
              AND projects.workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
        )
    );

ALTER TABLE runs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_runs ON runs;
CREATE POLICY tenant_isolation_runs ON runs
    FOR ALL
    USING (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    );

ALTER TABLE evidence_records ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_evidence_records ON evidence_records;
CREATE POLICY tenant_isolation_evidence_records ON evidence_records
    FOR ALL
    USING (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    );

ALTER TABLE artifacts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_artifacts ON artifacts;
CREATE POLICY tenant_isolation_artifacts ON artifacts
    FOR ALL
    USING (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    );

ALTER TABLE source_registry ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_source_registry ON source_registry;
CREATE POLICY tenant_isolation_source_registry ON source_registry
    FOR ALL
    USING (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    );

ALTER TABLE evidence_embeddings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_evidence_embeddings ON evidence_embeddings;
CREATE POLICY tenant_isolation_evidence_embeddings ON evidence_embeddings
    FOR ALL
    USING (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    );

ALTER TABLE knowledge_claims ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_knowledge_claims ON knowledge_claims;
CREATE POLICY tenant_isolation_knowledge_claims ON knowledge_claims
    FOR ALL
    USING (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    );

ALTER TABLE claim_evidence ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_claim_evidence ON claim_evidence;
CREATE POLICY tenant_isolation_claim_evidence ON claim_evidence
    FOR ALL
    USING (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    );

ALTER TABLE report_versions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_report_versions ON report_versions;
CREATE POLICY tenant_isolation_report_versions ON report_versions
    FOR ALL
    USING (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    );

ALTER TABLE report_version_claims ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_report_version_claims ON report_version_claims;
CREATE POLICY tenant_isolation_report_version_claims ON report_version_claims
    FOR ALL
    USING (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    );

ALTER TABLE report_version_evidence ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_report_version_evidence ON report_version_evidence;
CREATE POLICY tenant_isolation_report_version_evidence ON report_version_evidence
    FOR ALL
    USING (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    );

ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_audit_logs ON audit_logs;
CREATE POLICY tenant_isolation_audit_logs ON audit_logs
    FOR ALL
    USING (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    )
    WITH CHECK (
        COALESCE(current_setting('app.service_role', true), 'off') IN ('on', 'true', '1')
        OR workspace_id = NULLIF(current_setting('app.current_workspace_id', true), '')
    );
