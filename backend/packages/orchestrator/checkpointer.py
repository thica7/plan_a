from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


class GraphCheckpointer:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._context: Any | None = None
        self.saver: AsyncSqliteSaver | None = None

    @classmethod
    def from_default_path(cls) -> "GraphCheckpointer":
        return cls(Path("runs") / "graph_checkpoints.db")

    async def open(self) -> AsyncSqliteSaver:
        if self.saver is None:
            self._context = AsyncSqliteSaver.from_conn_string(str(self._db_path))
            self.saver = await self._context.__aenter__()
        return self.saver

    async def aclose(self) -> None:
        if self._context is not None:
            await self._context.__aexit__(None, None, None)
        self._context = None
        self.saver = None
