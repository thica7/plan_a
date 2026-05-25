from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.config import Settings
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest
from packages.skills.registry import SkillRegistry


CASES = [
    ("ai coding assistant", ["pricing", "feature", "persona"]),
    ("customer support chatbot", ["pricing", "feature", "persona"]),
    ("product analytics platform", ["pricing", "feature", "persona"]),
]


async def run_case(topic: str, dimensions: list[str]) -> tuple[str, str, int, int]:
    checkpoint_path = Path("runs") / f"seed_case_{uuid4().hex}.db"
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key=None,
            ark_model=None,
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=30,
            llm_temperature=0.2,
        ),
        graph_checkpointer=GraphCheckpointer(checkpoint_path),
    )
    try:
        detail = await service.create_run(
            RunCreateRequest(topic=topic, competitors=[], dimensions=dimensions, execution_mode="demo")
        )
        await service.run_pipeline(detail.id)
        updated = service.get_run(detail.id)
        assert updated is not None
        return topic, updated.status, len(updated.raw_sources), len(updated.revisions)
    finally:
        await service._graph_checkpointer.aclose()
        for path in Path("runs").glob(f"{checkpoint_path.stem}*"):
            path.unlink(missing_ok=True)


async def main() -> None:
    rows = [await run_case(topic, dimensions) for topic, dimensions in CASES]
    print("topic,status,sources,revisions")
    for row in rows:
        print(",".join(str(item) for item in row))


if __name__ == "__main__":
    asyncio.run(main())
