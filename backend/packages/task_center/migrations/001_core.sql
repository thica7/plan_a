CREATE TABLE task_center.workspace_policies (
    workspace_id text PRIMARY KEY CHECK (workspace_id <> ''),
    run_limit integer NOT NULL CHECK (run_limit >= 0),
    enforcement text NOT NULL CHECK (enforcement IN ('block', 'monitor')),
    policy_version bigint NOT NULL DEFAULT 1 CHECK (policy_version > 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE task_center.quota_buckets (
    workspace_id text NOT NULL REFERENCES task_center.workspace_policies(workspace_id),
    period_start timestamptz NOT NULL,
    period_end timestamptz NOT NULL,
    imported_count integer NOT NULL DEFAULT 0 CHECK (imported_count >= 0),
    reserved_count integer NOT NULL DEFAULT 0 CHECK (reserved_count >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, period_start),
    UNIQUE (workspace_id, period_start, period_end),
    CHECK (period_end > period_start)
);

CREATE TABLE task_center.submissions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id text NOT NULL REFERENCES task_center.workspace_policies(workspace_id),
    project_id text,
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
    request_sha text NOT NULL CHECK (request_sha ~ '^[0-9a-f]{64}$'),
    request_json jsonb NOT NULL CHECK (jsonb_typeof(request_json) = 'object'),
    server_actor text NOT NULL CHECK (server_actor <> ''),
    period_start timestamptz NOT NULL,
    period_end timestamptz NOT NULL,
    expected_run_id text NOT NULL UNIQUE CHECK (expected_run_id <> ''),
    status text NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'dispatching', 'dispatched', 'cancelled', 'dispatch_failed')
    ),
    run_id text UNIQUE,
    workflow_id text UNIQUE,
    dispatched_at timestamptz,
    cancelled_at timestamptz,
    last_error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, idempotency_key),
    UNIQUE (workspace_id, id),
    UNIQUE (workspace_id, id, period_start),
    FOREIGN KEY (workspace_id, period_start, period_end)
        REFERENCES task_center.quota_buckets(workspace_id, period_start, period_end),
    CHECK (run_id IS NULL OR run_id = expected_run_id),
    CHECK (status <> 'dispatched' OR run_id IS NOT NULL)
);

CREATE TABLE task_center.quota_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id text NOT NULL REFERENCES task_center.workspace_policies(workspace_id),
    submission_id uuid NOT NULL,
    period_start timestamptz NOT NULL,
    action text NOT NULL CHECK (action IN ('reserve', 'release')),
    amount integer NOT NULL DEFAULT 1 CHECK (amount = 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (submission_id, action),
    FOREIGN KEY (workspace_id, submission_id, period_start)
        REFERENCES task_center.submissions(workspace_id, id, period_start),
    FOREIGN KEY (workspace_id, period_start)
        REFERENCES task_center.quota_buckets(workspace_id, period_start)
);

CREATE TABLE task_center.outbox (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id text NOT NULL REFERENCES task_center.workspace_policies(workspace_id),
    submission_id uuid NOT NULL UNIQUE,
    epoch bigint NOT NULL DEFAULT 1 CHECK (epoch > 0),
    generation bigint NOT NULL DEFAULT 0 CHECK (generation >= 0),
    owner_token uuid,
    lease_until timestamptz,
    available_at timestamptz NOT NULL DEFAULT now(),
    state text NOT NULL DEFAULT 'pending' CHECK (
        state IN ('pending', 'leased', 'dispatched', 'cancelled', 'failed')
    ),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    sent_intent_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, submission_id),
    FOREIGN KEY (workspace_id, submission_id)
        REFERENCES task_center.submissions(workspace_id, id),
    CHECK (
        (state = 'leased' AND owner_token IS NOT NULL AND lease_until IS NOT NULL AND generation > 0)
        OR (state <> 'leased' AND owner_token IS NULL AND lease_until IS NULL)
    )
);

CREATE TABLE task_center.dispatch_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id text NOT NULL REFERENCES task_center.workspace_policies(workspace_id),
    submission_id uuid NOT NULL,
    generation bigint NOT NULL CHECK (generation > 0),
    epoch bigint NOT NULL CHECK (epoch > 0),
    owner_token uuid NOT NULL,
    outcome text NOT NULL DEFAULT 'claimed' CHECK (
        outcome IN ('claimed', 'sending', 'succeeded', 'failed', 'unknown', 'expired')
    ),
    started_at timestamptz NOT NULL DEFAULT now(),
    sent_intent_at timestamptz,
    finished_at timestamptz,
    error_code text,
    sanitized_error varchar(1000),
    UNIQUE (submission_id, generation),
    FOREIGN KEY (workspace_id, submission_id)
        REFERENCES task_center.outbox(workspace_id, submission_id)
);

CREATE TABLE task_center.audit_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id text NOT NULL REFERENCES task_center.workspace_policies(workspace_id),
    submission_id uuid,
    event_type text NOT NULL CHECK (event_type <> ''),
    actor text NOT NULL CHECK (actor <> ''),
    detail_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(detail_json) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (workspace_id, submission_id)
        REFERENCES task_center.submissions(workspace_id, id)
);

CREATE INDEX submissions_workspace_created_idx
    ON task_center.submissions (workspace_id, created_at DESC, id DESC);
CREATE INDEX submissions_workspace_status_created_idx
    ON task_center.submissions (workspace_id, status, created_at DESC, id DESC);
CREATE INDEX quota_entries_workspace_created_idx
    ON task_center.quota_entries (workspace_id, created_at DESC, id DESC);
CREATE INDEX outbox_available_idx
    ON task_center.outbox (available_at, created_at, submission_id)
    WHERE state IN ('pending', 'leased');
CREATE INDEX dispatch_attempts_workspace_submission_idx
    ON task_center.dispatch_attempts (workspace_id, submission_id, generation);

CREATE FUNCTION task_center.reject_history_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'task center history is immutable' USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER quota_entries_immutable BEFORE UPDATE OR DELETE ON task_center.quota_entries
    FOR EACH ROW EXECUTE FUNCTION task_center.reject_history_mutation();
CREATE TRIGGER audit_events_immutable BEFORE UPDATE OR DELETE ON task_center.audit_events
    FOR EACH ROW EXECUTE FUNCTION task_center.reject_history_mutation();

-- These settings carry server-selected scope. They are not a boundary against
-- arbitrary SQL from a malicious caller able to set PostgreSQL custom GUCs.
DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'workspace_policies', 'quota_buckets', 'submissions', 'quota_entries',
        'outbox', 'dispatch_attempts', 'audit_events'
    ] LOOP
        EXECUTE format('ALTER TABLE task_center.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE task_center.%I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'CREATE POLICY workspace_scope ON task_center.%I USING ('
            'current_setting(''app.service_role'', true) = ''on'' OR '
            'workspace_id = current_setting(''app.current_workspace_id'', true)) '
            'WITH CHECK (current_setting(''app.service_role'', true) = ''on'' OR '
            'workspace_id = current_setting(''app.current_workspace_id'', true))', table_name
        );
    END LOOP;
END;
$$;
