"""ccg-antigravity-write.py - Write-capable antigravity wrapper (project-local).

This is a project-local wrapper that invokes `agy -i --dangerously-skip-permissions`
via `codeagent-wrapper --backend antigravity`. It exists because the global
ccg-antigravity.py at C:/Users/huang/.claude/bin/ hardcodes -p (read-only) mode.

Usage:
    CCG_AGY_MODE=write python ccg-antigravity-write.py <workdir> [timeout]

The role is always `builder`; for read-only analysis use the global wrapper
with CCG_AGY_MODE=read-only.
"""

import os
import subprocess
import sys

WRAPPER = r"C:\Users\huang\.claude\bin\codeagent-wrapper.exe"


def main():
    workdir = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    timeout_seconds = _parse_timeout_seconds(sys.argv[2] if len(sys.argv) > 2 else "10m")
    task = sys.stdin.read().strip()
    task = task.encode("utf-8", errors="replace").decode("utf-8")

    role = os.environ.get("CCG_AGY_ROLE", "builder")
    output_tag = os.environ.get("CCG_AGY_OUTPUT", "implementation")

    stdin_content = (
        f"ROLE_FILE: C:/Users/huang/.claude/.ccg/prompts/antigravity/{role}.md\n"
        f"<TASK>\n{task}\n</TASK>\n"
        f"OUTPUT: {output_tag}\n"
    )

    args = [WRAPPER, "--progress", "--backend", "antigravity", "-", workdir]
    proc = subprocess.run(
        args,
        input=stdin_content.encode("utf-8"),
        cwd=workdir,
        timeout=timeout_seconds,
    )
    sys.exit(proc.returncode)


def _parse_timeout_seconds(value: str) -> int:
    unit = value[-1:].lower()
    amount_text = value[:-1] if unit in {"s", "m", "h"} else value
    amount = int(amount_text)
    if amount <= 0:
        raise ValueError("timeout must be positive")
    if unit == "h":
        return amount * 3600
    if unit == "m":
        return amount * 60
    return amount


if __name__ == "__main__":
    main()
