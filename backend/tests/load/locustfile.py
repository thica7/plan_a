from __future__ import annotations

import os
import uuid

from locust import HttpUser, between, events, task

AUTH_TOKEN = os.getenv("LOCUST_AUTH_TOKEN", "")
WORKSPACE_ID = os.getenv("LOCUST_WORKSPACE_ID", "default-workspace")
RUN_EXECUTION_MODE = os.getenv("LOCUST_RUN_EXECUTION_MODE", "demo")
CREATE_RUN_WEIGHT = int(os.getenv("LOCUST_CREATE_RUN_WEIGHT", "1"))


class CompetiscopeApiUser(HttpUser):
    wait_time = between(1.0, 4.0)

    def on_start(self) -> None:
        self.headers = {"Content-Type": "application/json"}
        if AUTH_TOKEN:
            self.headers["Authorization"] = f"Bearer {AUTH_TOKEN}"

    @task(8)
    def runtime_status(self) -> None:
        self.client.get("/api/runtime", headers=self.headers, name="/api/runtime")

    @task(6)
    def list_runs(self) -> None:
        self.client.get("/api/runs", headers=self.headers, name="/api/runs")

    @task(CREATE_RUN_WEIGHT)
    def create_demo_run(self) -> None:
        key = f"locust-run:{uuid.uuid4()}"
        payload = {
            "workspace_id": WORKSPACE_ID,
            "idempotency_key": key,
            "topic": "Locust smoke competitive analysis",
            "competitors": ["Cursor", "GitHub Copilot"],
            "dimensions": ["pricing", "feature", "persona"],
            "execution_mode": RUN_EXECUTION_MODE,
            "output_language": "zh-CN",
            "auto_redo_warn_enabled": False,
            "hitl_enabled": False,
        }
        self.client.post(
            "/api/runs",
            json=payload,
            headers=self.headers,
            name="/api/runs:create",
        )


@events.init_command_line_parser.add_listener
def _(parser) -> None:
    parser.epilog = (
        "Recommended smoke: locust -f backend/tests/load/locustfile.py "
        "--host http://127.0.0.1:8000 --users 10 --spawn-rate 2 --run-time 5m"
    )
