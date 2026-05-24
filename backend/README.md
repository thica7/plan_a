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
