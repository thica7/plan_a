from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class SubagentContext:
    run_id: str
    agent: str
    subagent: str
    context_id: str = field(init=False)
    messages: list[dict[str, str]] = field(default_factory=list)
    tool_trace: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.context_id = f"{self.run_id}:{self.agent}:{self.subagent}:{uuid4().hex[:8]}"

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def add_tool_call(self, name: str, detail: str) -> None:
        self.tool_trace.append({"name": name, "detail": detail})

    def metadata(self) -> dict[str, str | int]:
        return {
            "context_id": self.context_id,
            "message_count": len(self.messages),
            "tool_call_count": len(self.tool_trace),
        }

