-- Keep the client's canonical identity separate from the server-resolved payload.
-- Existing resolved rows cannot reveal whether their original mode was auto:
-- leave NULL and retain comparison against their known stored payload only.
ALTER TABLE task_center.submissions
    ADD COLUMN client_request_sha text
        CHECK (client_request_sha IS NULL OR client_request_sha ~ '^[0-9a-f]{64}$');
