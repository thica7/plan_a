# Backend

FastAPI application for Competiscope v2.

Run locally with the project Conda environment:

```bash
conda run -n bd-competiscope-v2 uvicorn app.main:app --reload --port 8000 --app-dir backend
```

Foundation checks:

```bash
conda run -n bd-competiscope-v2 pytest backend/tests -q
conda run -n bd-competiscope-v2 python backend/scripts/smoke_minimal_run.py
conda run -n bd-competiscope-v2 python backend/scripts/smoke_llm.py
conda run -n bd-competiscope-v2 python backend/scripts/smoke_search.py
conda run -n bd-competiscope-v2 python backend/scripts/smoke_fetch.py
```

Enterprise store:

```bash
# default local mode
ENTERPRISE_STORE_BACKEND=memory

# durable enterprise mode
ENTERPRISE_STORE_BACKEND=postgres
ENTERPRISE_DATABASE_URL=postgresql://competiscope:competiscope@127.0.0.1:55432/competiscope?connect_timeout=5
```

`EnterpriseMemoryStore` and `EnterprisePostgresStore` implement the same repository boundary,
so local development can stay lightweight while Docker deployments can use Postgres/pgvector.
