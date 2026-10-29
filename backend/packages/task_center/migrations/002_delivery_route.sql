-- Service-selected delivery semantics are immutable across configuration changes.
ALTER TABLE task_center.submissions
    ADD COLUMN delivery_intent text NOT NULL DEFAULT 'runtime'
        CHECK (delivery_intent IN ('create_only', 'runtime', 'temporal', 'activity')),
    ADD COLUMN execution_backend text NOT NULL DEFAULT 'langgraph'
        CHECK (execution_backend IN ('langgraph', 'temporal'));
