from __future__ import annotations

import sqlite3
from pathlib import Path

from packages.schema.models import AgentMessage, ToolCallMessage, TraceSpan


class TraceStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @classmethod
    def from_default_path(cls) -> "TraceStore":
        return cls(Path("runs") / "traces.db")

    def append_span(self, run_id: str, span: TraceSpan) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                insert or replace into trace_spans (
                    run_id, span_id, agent, subagent, kind, name, status, span_json, created_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    span.id,
                    span.agent,
                    span.subagent,
                    span.kind,
                    span.name,
                    span.status,
                    span.model_dump_json(),
                    span.created_at.isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def append_agent_message(self, message: AgentMessage) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                insert or replace into agent_messages (
                    run_id, message_id, from_agent, to_agent, message_type, message_json, created_at
                )
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.run_id,
                    message.id,
                    message.from_agent,
                    message.to_agent,
                    message.message_type,
                    message.model_dump_json(),
                    message.created_at.isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def append_tool_call_message(self, message: ToolCallMessage) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                insert or replace into tool_call_messages (
                    run_id, message_id, agent, subagent, tool_name, status, message_json, created_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.run_id,
                    message.id,
                    message.agent,
                    message.subagent,
                    message.tool_name,
                    message.status,
                    message.model_dump_json(),
                    message.created_at.isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def list_spans(self, run_id: str) -> list[TraceSpan]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "select span_json from trace_spans where run_id = ? order by span_id",
                (run_id,),
            ).fetchall()
        finally:
            conn.close()
        return [TraceSpan.model_validate_json(row[0]) for row in rows]

    def list_agent_messages(self, run_id: str) -> list[AgentMessage]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "select message_json from agent_messages where run_id = ? order by message_id",
                (run_id,),
            ).fetchall()
        finally:
            conn.close()
        return [AgentMessage.model_validate_json(row[0]) for row in rows]

    def list_tool_call_messages(self, run_id: str) -> list[ToolCallMessage]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "select message_json from tool_call_messages where run_id = ? order by message_id",
                (run_id,),
            ).fetchall()
        finally:
            conn.close()
        return [ToolCallMessage.model_validate_json(row[0]) for row in rows]

    def stats(self) -> dict[str, int]:
        conn = self._connect()
        try:
            spans = conn.execute("select count(*) from trace_spans").fetchone()[0]
            agent_messages = conn.execute("select count(*) from agent_messages").fetchone()[0]
            tool_messages = conn.execute("select count(*) from tool_call_messages").fetchone()[0]
        finally:
            conn.close()
        return {
            "trace_spans": int(spans),
            "agent_messages": int(agent_messages),
            "tool_call_messages": int(tool_messages),
        }

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                create table if not exists trace_spans (
                    run_id text not null,
                    span_id text not null,
                    agent text not null,
                    subagent text,
                    kind text not null,
                    name text not null,
                    status text not null,
                    span_json text not null,
                    created_at text not null,
                    primary key (run_id, span_id)
                )
                """
            )
            conn.execute(
                """
                create table if not exists agent_messages (
                    run_id text not null,
                    message_id text not null,
                    from_agent text not null,
                    to_agent text not null,
                    message_type text not null,
                    message_json text not null,
                    created_at text not null,
                    primary key (run_id, message_id)
                )
                """
            )
            conn.execute(
                """
                create table if not exists tool_call_messages (
                    run_id text not null,
                    message_id text not null,
                    agent text not null,
                    subagent text,
                    tool_name text not null,
                    status text not null,
                    message_json text not null,
                    created_at text not null,
                    primary key (run_id, message_id)
                )
                """
            )
            conn.execute("create index if not exists idx_trace_spans_run on trace_spans(run_id, span_id)")
            conn.execute("create index if not exists idx_agent_messages_run on agent_messages(run_id, message_id)")
            conn.execute("create index if not exists idx_tool_messages_run on tool_call_messages(run_id, message_id)")
            conn.commit()
        finally:
            conn.close()
