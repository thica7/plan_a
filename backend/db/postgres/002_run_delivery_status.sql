-- Preserve the runtime's blocked terminal state in the durable enterprise row.
-- Explicit management migration only; keep the original five states valid.
ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_status_check;
ALTER TABLE runs ADD CONSTRAINT runs_status_check
    CHECK (status IN (
        'queued', 'running', 'interrupted', 'completed', 'failed',
        'completed_with_blockers'
    ));
