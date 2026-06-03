# Seed Cases

Run `python backend/scripts/seed_cases.py` from the repository root to exercise
three demo-mode presentation cases with the same LangGraph topology as real
runs. The script prints `topic,status,sources,revisions` so the demo can show
end-to-end completion and redo evidence without spending real API quota.

The current cases cover:

- AI coding assistant
- Customer support chatbot
- Product analytics platform

## Evidence Seed Corpus

`data/evidence_seed.jsonl` is a validated offline evidence corpus, not just a
static fixture. Use `POST /api/enterprise/projects/{project_id}/evidence/seed`
with optional `topic`, `competitors`, `dimensions`, `run_id`, and `limit` fields
to ingest matching seed rows into the enterprise evidence store. Ingested rows
become `EvidenceRecord` objects, are indexed immediately, and can be retrieved by
the RAG gap-fill pipeline when live web collection is unavailable.
