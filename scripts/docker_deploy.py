#!/usr/bin/env python3
"""Start a local demo, or explicitly enable authenticated LAN access.

--dry-run needs neither Docker nor .env. Real deployments use the existing .env
without displaying its contents. Run this on the intended deployment machine.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    from scripts.demo_data import assert_project_ownership
except ModuleNotFoundError:
    from demo_data import assert_project_ownership

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = "plan-a-demo"


def validate_project(project: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", project):
        raise ValueError("project must contain only lowercase letters, digits, _ or -")
    return project


def compose_command(project: str, redis: bool = False) -> list[str]:
    command = [
        "docker",
        "compose",
        "-f",
        str(ROOT / "docker-compose.yml"),
        "--project-name",
        validate_project(project),
    ]
    if redis:
        command += ["--profile", "redis"]
    return command


def deployment_plan(
    *, mode: str, redis: bool, project: str, build: bool, detach: bool = True
) -> dict:
    if mode not in {"light", "persistent"}:
        raise ValueError("mode must be light or persistent")
    services = ["qdrant", "postgres", "backend", "frontend", "nginx"]
    if mode == "persistent":
        services += ["temporal", "temporal-worker", "temporal-ui"]
    if redis:
        services.append("redis")
    command = compose_command(project, redis) + ["up"]
    if detach:
        command += ["-d", "--wait", "--wait-timeout", "180"]
    if build:
        command.append("--build")
    return {
        "mode": mode,
        "project": project,
        "services": services,
        "command": command + services,
    }


def runtime_environment(mode: str, redis: bool, lan: bool, environ: dict) -> dict:
    env = dict(environ)
    env["DEMO_ORCHESTRATION_BACKEND"] = "langgraph" if mode == "light" else "temporal"
    env["DEMO_TEMPORAL_TRAFFIC_PERCENT"] = "0" if mode == "light" else "100"
    env["DEMO_REDIS_ENABLED"] = "true" if redis else "false"
    # Missing variables must reach Compose unchanged so its .env values win
    # over defaults. Only explicitly supplied process bindings are checked here.
    for name in (
        "APP_BIND",
        "QDRANT_BIND",
        "POSTGRES_BIND",
        "TEMPORAL_BIND",
        "TEMPORAL_UI_BIND",
    ):
        bind = env.get(name)
        if not bind:
            continue
        host, separator, port = bind.rpartition(":")
        if not separator or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError(
                f"{name} requires a host and valid port; external access needs --lan"
            )
        if not is_loopback(host) and not (name == "APP_BIND" and lan):
            if name == "APP_BIND":
                raise ValueError(
                    "External APP_BIND requires explicit --lan and authentication"
                )
            raise ValueError(f"{name} requires a loopback host and valid port")
    return env


def is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return host == "localhost"


def validate_resolved_bindings(config: dict, *, lan: bool) -> None:
    for name in ("nginx", "qdrant", "postgres", "temporal", "temporal-ui", "redis"):
        for port in config.get("services", {}).get(name, {}).get("ports", []):
            host = port.get("host_ip") or "0.0.0.0"
            if not is_loopback(host) and not (name == "nginx" and lan):
                if name == "nginx":
                    raise ValueError(
                        "External APP_BIND requires explicit --lan and authentication"
                    )
                raise ValueError(f"{name} requires a loopback binding")
            if name == "redis":
                raise ValueError("Redis must not publish host ports")


def resolved_config(project: str, redis: bool, env: dict) -> dict:
    result = subprocess.run(
        compose_command(project, redis) + ["config", "--format", "json"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def validate_lan_auth(config: dict) -> None:
    environment = config.get("services", {}).get("backend", {}).get("environment", {})
    if str(environment.get("AUTH_ENABLED", "")).lower() != "true":
        raise ValueError("LAN access requires AUTH_ENABLED=true")
    raw_subjects = environment.get("AUTH_TOKEN_SUBJECTS") or ""
    try:
        subjects = json.loads(raw_subjects) if raw_subjects else {}
    except (ValueError, TypeError):
        subjects = {}
    valid_subjects = isinstance(subjects, dict) and any(
        isinstance(token, str) and token.strip() and isinstance(subject, dict)
        for token, subject in subjects.items()
    )
    tokens = (
        environment.get("AUTH_BEARER_TOKENS")
        or environment.get("AUTH_BEARER_TOKEN")
        or ""
    )
    if not valid_subjects and not any(
        token.strip() for token in str(tokens).split(",")
    ):
        raise ValueError(
            "LAN access requires configured bearer tokens or token subjects"
        )


def compose_urls(config: dict) -> dict:
    urls = {}
    for service, label, target in (
        ("nginx", "App", 80),
        ("temporal-ui", "Temporal UI", 8080),
        ("qdrant", "Qdrant", 6333),
    ):
        for port in config.get("services", {}).get(service, {}).get("ports", []):
            if int(port["target"]) != target:
                continue
            host = port.get("host_ip") or "127.0.0.1"
            if host in {"0.0.0.0", "::"}:
                host = "127.0.0.1"
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            urls[label] = f"http://{host}:{port['published']}"
    if "App" in urls:
        urls["API"] = f"{urls['App']}/api"
    return urls


def verify_readiness(app_url: str) -> None:
    try:
        with urllib.request.urlopen(f"{app_url}/api/readyz", timeout=5) as response:
            status = json.loads(response.read())
            if response.status != 200 or status.get("status") not in {"ok", "warn"}:
                raise RuntimeError("Application readiness failed")
    except (OSError, ValueError, urllib.error.URLError) as error:
        raise RuntimeError(
            "Application readiness failed; inspect container health logs"
        ) from error


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("light", "persistent"), default="persistent")
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--redis", action="store_true")
    parser.add_argument("--lan", action="store_true")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--no-detach", action="store_true")
    parser.add_argument("--urls-only", action="store_true")
    parser.add_argument(
        "--check", action="store_true", help="only check deployed readiness"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        env = runtime_environment(args.mode, args.redis, args.lan, os.environ)
        plan = deployment_plan(
            mode=args.mode,
            redis=args.redis,
            project=args.project,
            build=args.build,
            detach=not args.no_detach,
        )
        if args.dry_run:
            print(json.dumps(plan, indent=2))
            return 0
        if not shutil.which("docker"):
            raise RuntimeError("Docker with Compose v2 is required")
        if not (ROOT / ".env").is_file():
            raise RuntimeError(
                "Create and configure .env from .env.example before deployment"
            )
        config = resolved_config(args.project, args.redis, env)
        if args.lan and not os.environ.get("APP_BIND"):
            ports = config.get("services", {}).get("nginx", {}).get("ports", [])
            app_port = next((port for port in ports if int(port["target"]) == 80), None)
            if app_port and is_loopback(app_port.get("host_ip") or "0.0.0.0"):
                env["APP_BIND"] = f"0.0.0.0:{app_port['published']}"
                config = resolved_config(args.project, args.redis, env)
        validate_resolved_bindings(config, lan=args.lan)
        if args.lan:
            validate_lan_auth(config)
        urls = compose_urls(config)
        if args.mode == "light":
            urls.pop("Temporal UI", None)
        for label, url in urls.items():
            print(f"{label}: {url}", flush=True)
        if args.urls_only:
            return 0
        if not args.check:
            inventory = assert_project_ownership(args.project, root=ROOT)
            if args.mode == "light" and (
                {item["service"] for item in inventory if item["running"]}
                & {
                    "temporal-worker",
                    "temporal",
                    "temporal-ui",
                }
            ):
                raise RuntimeError(
                    "Mode switch requires explicitly stopping existing Temporal services "
                    "after preserving active tasks"
                )
            subprocess.run(
                plan["command"],
                cwd=ROOT,
                env=env,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        if args.check or not args.no_detach:
            verify_readiness(urls["App"])
    except subprocess.CalledProcessError:
        print(
            "[plan_a] Compose failed; inspect container status on the deployment machine",
            file=sys.stderr,
        )
        return 1
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        print(f"[plan_a] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
