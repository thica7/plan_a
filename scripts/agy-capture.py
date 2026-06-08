"""Recover agy -p output on Windows when stdout is empty.

This is an orchestration-only wrapper for agy 1.0.6 on Windows. It invokes the
real agy.exe in print mode, then reads the conversation SQLite DB that agy
creates and writes the recovered assistant response to stdout.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path


DEFAULT_AGY = Path.home() / "AppData" / "Local" / "agy" / "bin" / "agy.exe"
CONVERSATIONS_DIR = Path.home() / ".gemini" / "antigravity-cli" / "conversations"
UUID_RE = re.compile(
    r"(?:Created conversation|Print mode: conversation=)\s*"
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run agy print mode and recover output from its conversation DB."
    )
    parser.add_argument("prompt_arg", nargs="?", help="Prompt text, unless -p/--print is used.")
    parser.add_argument("-p", "--print", "--prompt", dest="prompt", help="Prompt text.")
    parser.add_argument("--agy", default=str(DEFAULT_AGY), help="Path to agy.exe.")
    parser.add_argument("--cwd", default=os.getcwd(), help="Working directory for agy.")
    parser.add_argument("--timeout", default=300, type=int, help="agy timeout in seconds.")
    parser.add_argument("--model", help="Optional model passed through to agy.")
    parser.add_argument("--add-dir", action="append", default=[], help="Extra workspace dir for agy.")
    parser.add_argument(
        "--dangerously-skip-permissions",
        action="store_true",
        help="Pass through agy's auto-approve flag.",
    )
    parser.add_argument(
        "--keep-log",
        action="store_true",
        help="Keep the temporary agy log file and print its path to stderr.",
    )
    parser.add_argument(
        "--debug-db",
        action="store_true",
        help="Print extraction diagnostics to stderr.",
    )
    return parser.parse_args()


def read_prompt(args: argparse.Namespace) -> str:
    prompt = args.prompt if args.prompt is not None else args.prompt_arg
    if prompt:
        return prompt
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    raise SystemExit("agy-capture: no prompt supplied")


def run_agy(args: argparse.Namespace, prompt: str, log_path: Path) -> subprocess.CompletedProcess[str]:
    cmd = [str(Path(args.agy)), "--log-file", str(log_path)]
    for add_dir in args.add_dir:
        cmd.extend(["--add-dir", add_dir])
    if args.model:
        cmd.extend(["--model", args.model])
    if args.dangerously_skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    cmd.extend(["--print", prompt, "--print-timeout", f"{args.timeout}s"])

    return subprocess.run(
        cmd,
        cwd=args.cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=args.timeout + 30,
    )


def conversation_id_from_log(log_path: Path) -> str | None:
    if not log_path.exists():
        return None
    text = log_path.read_text(encoding="utf-8", errors="replace")
    matches = UUID_RE.findall(text)
    return matches[-1].lower() if matches else None


def wait_for_db(conversation_id: str, timeout: float = 10.0) -> Path | None:
    db_path = CONVERSATIONS_DIR / f"{conversation_id}.db"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if db_path.exists() and db_path.stat().st_size > 0:
            return db_path
        time.sleep(0.1)
    return db_path if db_path.exists() else None


def decode_varint(data: bytes, offset: int) -> tuple[int, int] | None:
    value = 0
    shift = 0
    for index in range(offset, min(offset + 10, len(data))):
        byte = data[index]
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, index + 1
        shift += 7
    return None


def looks_like_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if "\x00" in stripped:
        return False
    printable = sum(1 for char in stripped if char.isprintable() or char in "\r\n\t")
    return printable / max(len(stripped), 1) > 0.9


def unique_append(items: list[str], value: str) -> None:
    value = value.replace("\r\n", "\n").strip()
    if value and value not in items:
        items.append(value)


def extract_proto_texts(data: bytes) -> list[str]:
    texts: list[str] = []
    for match in re.finditer(rb"\x10\x02\x1a", data):
        decoded = decode_varint(data, match.end())
        if decoded is None:
            continue
        length, start = decoded
        if length <= 0 or length > 2_000_000:
            continue
        end = start + length
        if end > len(data):
            continue
        try:
            text = data[start:end].decode("utf-8")
        except UnicodeDecodeError:
            continue
        if looks_like_text(text):
            unique_append(texts, text)
    return texts


def extract_db_bytes(db_path: Path) -> list[bytes]:
    payloads: list[bytes] = [db_path.read_bytes()]
    uri = f"file:{db_path}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as con:
            tables = [
                row[0]
                for row in con.execute(
                    "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
                )
            ]
            for table in tables:
                quoted = '"' + table.replace('"', '""') + '"'
                for row in con.execute(f"select * from {quoted}"):
                    for value in row:
                        if isinstance(value, bytes):
                            payloads.append(value)
                        elif isinstance(value, str):
                            payloads.append(value.encode("utf-8", errors="replace"))
    except sqlite3.Error:
        pass
    return payloads


def recover_response(db_path: Path, prompt: str, debug: bool = False) -> str | None:
    candidates: list[str] = []
    for payload in extract_db_bytes(db_path):
        for text in extract_proto_texts(payload):
            if text == prompt or text.startswith("<USER_SETTINGS_CHANGE>"):
                continue
            unique_append(candidates, text)

    if debug:
        print(f"agy-capture: db={db_path}", file=sys.stderr)
        print(f"agy-capture: candidates={len(candidates)}", file=sys.stderr)
        for index, candidate in enumerate(candidates[-10:], start=max(len(candidates) - 9, 1)):
            preview = candidate.replace("\n", "\\n")
            print(f"agy-capture: candidate[{index}]={preview[:300]}", file=sys.stderr)

    return candidates[-1] if candidates else None


def newest_conversation_after(start_time: float) -> Path | None:
    if not CONVERSATIONS_DIR.exists():
        return None
    dbs = [
        path
        for path in CONVERSATIONS_DIR.glob("*.db")
        if path.stat().st_mtime >= start_time - 2
    ]
    return max(dbs, key=lambda path: path.stat().st_mtime, default=None)


def main() -> int:
    args = parse_args()
    prompt = read_prompt(args)
    agy_path = Path(args.agy)
    if not agy_path.exists():
        print(f"agy-capture: agy executable not found: {agy_path}", file=sys.stderr)
        return 127

    start_time = time.time()
    log_path = Path(tempfile.gettempdir()) / f"agy-capture-{uuid.uuid4().hex}.log"
    try:
        proc = run_agy(args, prompt, log_path)
    except subprocess.TimeoutExpired as exc:
        print(f"agy-capture: agy timed out after {exc.timeout}s", file=sys.stderr)
        return 124

    def cleanup_log() -> None:
        if args.keep_log:
            print(f"agy-capture: log={log_path}", file=sys.stderr)
        else:
            log_path.unlink(missing_ok=True)

    direct_output = (proc.stdout or "").strip()
    if direct_output:
        print(direct_output)
        cleanup_log()
        return proc.returncode

    conversation_id = conversation_id_from_log(log_path)
    db_path = wait_for_db(conversation_id) if conversation_id else None
    if db_path is None:
        db_path = newest_conversation_after(start_time)

    response = recover_response(db_path, prompt, args.debug_db) if db_path else None
    if response:
        print(response)
        cleanup_log()
        return 0

    stderr = (proc.stderr or "").strip()
    if stderr:
        print(stderr, file=sys.stderr)
    elif log_path.exists():
        tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-20:])
        print("agy-capture: no stdout and no recoverable response; log tail:", file=sys.stderr)
        print(tail, file=sys.stderr)
    else:
        print("agy-capture: no stdout and no recoverable response", file=sys.stderr)

    cleanup_log()
    return proc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
