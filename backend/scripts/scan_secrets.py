from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_EXCLUDES = (
    ".git/",
    ".venv/",
    "node_modules/",
    "frontend/dist/",
    "frontend/openapi.json",
    "frontend/src/api/openapi.ts",
    "runs/",
    "logs/",
    "backups/",
    "review/",
    "dev_plan_final/",
    "backend/.test-artifacts/",
)

SECRET_PATTERNS = (
    ("openai_like_key", re.compile(r"\bsk-(?:or-v1-|proj-|ant-api03-)?[A-Za-z0-9_-]{32,}\b")),
    ("aws_access_key", re.compile(r"\bA(?:KIA|SIA)[A-Z0-9]{16}\b")),
    ("github_token", re.compile(r"\bgh[opusr]_[A-Za-z0-9_]{36,}\b")),
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("huggingface_token", re.compile(r"\bhf_[A-Za-z0-9]{32,}\b")),
    ("perplexity_key", re.compile(r"\bpplx-[A-Za-z0-9_-]{20,}\b")),
)

PLACEHOLDER_MARKERS = (
    "dummy",
    "your_key",
    "your-api-key",
    "example",
    "fixture",
    "placeholder",
    "redacted",
    "test",
    "abcdef",
    "123456",
)


@dataclass(frozen=True)
class SecretFinding:
    path: str
    line_number: int
    pattern_name: str
    preview: str


def scan_paths(paths: list[Path], *, root: Path) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for path in paths:
        if not path.is_file() or _is_excluded(path, root=root):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        relative = _relative_path(path, root=root)
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern_name, pattern in SECRET_PATTERNS:
                for match in pattern.finditer(line):
                    token = match.group(0)
                    if _looks_like_fixture(relative, token):
                        continue
                    findings.append(
                        SecretFinding(
                            path=relative,
                            line_number=line_number,
                            pattern_name=pattern_name,
                            preview=_redacted_preview(token),
                        )
                    )
    return findings


def default_scan_paths(root: Path) -> list[Path]:
    try:
        output = subprocess.check_output(
            ["git", "ls-files"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return [path for path in root.rglob("*") if path.is_file()]
    return [root / line.strip() for line in output.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan tracked project files for accidental provider secrets."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional files or directories to scan instead of tracked files.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root. Defaults to the current directory.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    paths = _expand_cli_paths(args.paths, root=root) if args.paths else default_scan_paths(root)
    findings = scan_paths(paths, root=root)
    if not findings:
        print("Secret scan passed: no provider key patterns found.")
        return 0

    print("Secret scan failed: possible provider secrets found.", file=sys.stderr)
    for finding in findings:
        print(
            f"{finding.path}:{finding.line_number}: {finding.pattern_name} {finding.preview}",
            file=sys.stderr,
        )
    return 1


def _expand_cli_paths(values: list[str], *, root: Path) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        path = (root / value).resolve() if not Path(value).is_absolute() else Path(value)
        if path.is_dir():
            paths.extend(item for item in path.rglob("*") if item.is_file())
        else:
            paths.append(path)
    return paths


def _is_excluded(path: Path, *, root: Path) -> bool:
    relative = _relative_path(path, root=root).replace("\\", "/")
    return any(
        relative == item.rstrip("/") or relative.startswith(item)
        for item in DEFAULT_EXCLUDES
    )


def _relative_path(path: Path, *, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def _looks_like_fixture(path: str, token: str) -> bool:
    lowered = token.casefold()
    has_placeholder_marker = any(marker in lowered for marker in PLACEHOLDER_MARKERS)
    if has_placeholder_marker:
        return True
    return False


def _redacted_preview(token: str) -> str:
    if len(token) <= 12:
        return "[redacted]"
    return f"{token[:6]}...{token[-4:]}"


if __name__ == "__main__":
    raise SystemExit(main())
