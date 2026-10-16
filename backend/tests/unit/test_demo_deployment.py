from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from urllib.error import HTTPError

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


def load_deploy():
    spec = importlib.util.spec_from_file_location("demo_deploy", ROOT / "scripts/docker_deploy.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compose_pins_images_and_keeps_redis_internal():
    config = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert config["name"] == "${COMPOSE_PROJECT_NAME:-plan-a-demo}"
    for service in config["services"].values():
        if "image" in service:
            assert ":" in service["image"] and not service["image"].endswith(":latest")
    redis = config["services"]["redis"]
    assert redis["profiles"] == ["redis"]
    assert "ports" not in redis
    assert redis["expose"] == ["6379"]
    assert "${APP_BIND:-127.0.0.1:8080}:80" in config["services"]["nginx"]["ports"]


def test_example_env_bindings_can_start_without_lan():
    deploy = load_deploy()
    values = dict(
        line.split("=", 1)
        for line in (ROOT / ".env.example").read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    selected = {key: value for key, value in values.items() if key.endswith("_BIND")}
    env = deploy.runtime_environment("light", False, False, selected)
    assert env["APP_BIND"] == "127.0.0.1:8080"


def test_modes_share_runtime_and_do_not_depend_on_an_optional_temporal_profile():
    config = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    backend = config["services"]["backend"]
    worker = config["services"]["temporal-worker"]
    assert backend["environment"] == worker["environment"]
    assert "temporal" not in backend["depends_on"]
    assert "profiles" not in config["services"]["temporal"]
    assert "profiles" not in worker
    assert (
        backend["environment"]["RUN_ORCHESTRATION_BACKEND"]
        == "${DEMO_ORCHESTRATION_BACKEND:-temporal}"
    )
    assert (
        backend["environment"]["TEMPORAL_TRAFFIC_PERCENT"]
        == "${DEMO_TEMPORAL_TRAFFIC_PERCENT:-100}"
    )
    assert backend["volumes"] == worker["volumes"]
    assert "run-data:/app/runs" in backend["volumes"]
    assert "artifact-data:/app/data" in backend["volumes"]


def test_light_plan_excludes_temporal_and_forces_consistent_runtime():
    deploy = load_deploy()
    plan = deploy.deployment_plan(mode="light", redis=False, project="plan-a-demo", build=False)
    assert plan["services"] == ["qdrant", "postgres", "backend", "frontend", "nginx"]
    env = deploy.runtime_environment("light", False, False, {})
    assert env["DEMO_ORCHESTRATION_BACKEND"] == "langgraph"
    assert env["DEMO_TEMPORAL_TRAFFIC_PERCENT"] == "0"
    assert "APP_BIND" not in env  # Compose retains .env > declared localhost default.
    assert "--project-name" in plan["command"]
    assert "--volumes" not in plan["command"]


def test_persistent_plan_explicitly_starts_temporal_and_optional_redis():
    deploy = load_deploy()
    plan = deploy.deployment_plan(mode="persistent", redis=True, project="plan-a-demo", build=True)
    assert {"temporal", "temporal-worker", "temporal-ui", "redis"} <= set(plan["services"])
    assert plan["command"][plan["command"].index("--profile") + 1] == "redis"
    assert "--build" in plan["command"]
    env = deploy.runtime_environment("persistent", True, False, {})
    assert env["DEMO_ORCHESTRATION_BACKEND"] == "temporal"
    assert env["DEMO_TEMPORAL_TRAFFIC_PERCENT"] == "100"


@pytest.mark.parametrize("bind", ["8080", "0.0.0.0:8080", "192.168.1.8:8080"])
def test_external_binding_requires_explicit_lan_flag(bind):
    deploy = load_deploy()
    with pytest.raises(ValueError, match="--lan"):
        deploy.runtime_environment("persistent", False, False, {"APP_BIND": bind})


def test_lan_config_requires_auth_and_a_valid_token_subject():
    deploy = load_deploy()
    config = {"services": {"backend": {"environment": {"AUTH_ENABLED": "false"}}}}
    with pytest.raises(ValueError, match="AUTH_ENABLED"):
        deploy.validate_lan_auth(config)
    env = config["services"]["backend"]["environment"]
    env["AUTH_ENABLED"] = "true"
    env["AUTH_TOKEN_SUBJECTS"] = "not-json"
    with pytest.raises(ValueError, match="token"):
        deploy.validate_lan_auth(config)
    env["AUTH_TOKEN_SUBJECTS"] = json.dumps(
        {"secret": {"user_id": "demo-user", "workspace_id": "demo"}}
    )
    deploy.validate_lan_auth(config)


def test_readiness_rejects_http_errors_and_error_rollup(monkeypatch):
    deploy = load_deploy()

    def unavailable(*args, **kwargs):
        raise HTTPError("http://127.0.0.1/api/health", 503, "unavailable", {}, None)

    monkeypatch.setattr(deploy.urllib.request, "urlopen", unavailable)
    with pytest.raises(RuntimeError, match="readiness"):
        deploy.verify_readiness("http://127.0.0.1:8080")

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"status":"error"}'

    monkeypatch.setattr(deploy.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="readiness"):
        deploy.verify_readiness("http://127.0.0.1:8080")


def test_deploy_dry_run_never_calls_docker_or_creates_env(monkeypatch, tmp_path, capsys):
    deploy = load_deploy()
    monkeypatch.setattr(deploy, "ROOT", tmp_path)
    monkeypatch.setattr(
        deploy.subprocess, "run", lambda *args, **kwargs: pytest.fail("Docker was called")
    )
    assert deploy.main(["--dry-run", "--mode", "light"]) == 0
    assert not (tmp_path / ".env").exists()
    assert "plan-a-demo" in capsys.readouterr().out


def test_failed_deploy_does_not_print_resolved_config_or_secret_stderr(
    monkeypatch, tmp_path, capsys
):
    deploy = load_deploy()
    (tmp_path / ".env").write_text("DO_NOT_READ=secret\n")
    monkeypatch.setattr(deploy, "ROOT", tmp_path)
    monkeypatch.setattr(deploy.shutil, "which", lambda *args: "/fake/docker")

    def failure(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["docker"], stderr="sensitive-token")

    monkeypatch.setattr(deploy.subprocess, "run", failure)
    assert deploy.main([]) == 1
    assert "sensitive-token" not in capsys.readouterr().err


def test_nginx_keeps_sse_unbuffered_and_does_not_override_cors_with_wildcard():
    config = (ROOT / "docker/nginx.conf").read_text()
    assert "proxy_buffering off" in config
    assert "Last-Event-ID" in config
    assert "Access-Control-Allow-Origin' '*'" not in config


def test_light_mode_rejects_a_running_temporal_worker_before_up(monkeypatch, tmp_path, capsys):
    deploy = load_deploy()
    (tmp_path / ".env").write_text("not-read\n")
    monkeypatch.setattr(deploy, "ROOT", tmp_path)
    monkeypatch.setattr(deploy.shutil, "which", lambda *args: "/fake/docker")
    monkeypatch.setattr(
        deploy,
        "assert_project_ownership",
        lambda project, **kwargs: [{"service": "temporal-worker", "running": True}],
    )
    config = {
        "services": {
            "nginx": {"ports": [{"target": 80, "published": "8080", "host_ip": "127.0.0.1"}]}
        }
    }
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if "config" in command:
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(config))
        if "ps" in command:
            return subprocess.CompletedProcess(command, 0, stdout="temporal-worker\n")
        pytest.fail("Deployment mutated running services before mode validation")

    monkeypatch.setattr(deploy.subprocess, "run", run)
    assert deploy.main(["--mode", "light"]) == 1
    assert "switch" in capsys.readouterr().err
    assert not any("up" in command for command in commands)


def test_drill_project_can_use_distinct_loopback_infrastructure_ports():
    deploy = load_deploy()
    env = deploy.runtime_environment(
        "persistent",
        False,
        False,
        {
            "POSTGRES_BIND": "127.0.0.1:65432",
            "QDRANT_BIND": "127.0.0.1:16333",
            "TEMPORAL_BIND": "127.0.0.1:17233",
            "TEMPORAL_UI_BIND": "127.0.0.1:18233",
        },
    )
    assert env["POSTGRES_BIND"] == "127.0.0.1:65432"
    assert env["QDRANT_BIND"] == "127.0.0.1:16333"
    with pytest.raises(ValueError, match="loopback"):
        deploy.runtime_environment("persistent", False, True, {"POSTGRES_BIND": "0.0.0.0:5432"})


def mock_project_docker(
    deploy,
    monkeypatch,
    tmp_path,
    *,
    labels=None,
    volumes=None,
    app_bind="127.0.0.1:9080",
    dependency_bind="127.0.0.1:9333",
):
    (tmp_path / ".env").write_text("APP_BIND=127.0.0.1:9080\nQDRANT_BIND=127.0.0.1:9333\n")
    monkeypatch.setattr(deploy, "ROOT", tmp_path)
    monkeypatch.setattr(deploy.shutil, "which", lambda *args: "/fake/docker")
    monkeypatch.setattr(deploy, "verify_readiness", lambda url: None)
    calls = []
    project = "plan-a-demo"
    volumes = volumes or {}

    def run(command, **kwargs):
        calls.append((command, kwargs))

        def result(value):
            output = value if kwargs.get("text") else value.encode()
            return subprocess.CompletedProcess(command, 0, stdout=output)

        if "config" in command:
            binding = kwargs.get("env", {}).get("APP_BIND", app_bind)
            host, _, port = binding.rpartition(":")
            dependency_host, _, dependency_port = dependency_bind.rpartition(":")
            config = {
                "services": {
                    "nginx": {"ports": [{"target": 80, "published": port, "host_ip": host}]},
                    "qdrant": {
                        "ports": [
                            {
                                "target": 6333,
                                "published": dependency_port,
                                "host_ip": dependency_host,
                            }
                        ]
                    },
                    "backend": {
                        "environment": {"AUTH_ENABLED": "true", "AUTH_BEARER_TOKENS": "fake-token"}
                    },
                }
            }
            return result(json.dumps(config))
        if command[:2] == ["docker", "ps"]:
            return result("owned-container\n" if labels else "")
        if command[:2] == ["docker", "inspect"]:
            return result("true" if "{{.State.Running}}" in command else json.dumps(labels))
        if command[:3] == ["docker", "volume", "ls"]:
            names = volumes
            if "--filter" in command:
                names = {
                    name: value
                    for name, value in volumes.items()
                    if value.get("com.docker.compose.project") == project
                }
            return result("\n".join(names))
        if command[:3] == ["docker", "volume", "inspect"]:
            return result(json.dumps(volumes[command[-1]]))
        if "up" in command:
            return result("")
        pytest.fail(f"Unexpected command: {command}")

    monkeypatch.setattr(deploy.subprocess, "run", run)
    return calls


def owned_labels(root, project="plan-a-demo"):
    return {
        "com.docker.compose.project": project,
        "com.docker.compose.service": "backend",
        "com.docker.compose.project.working_dir": str(root),
        "com.docker.compose.project.config_files": str(root / "docker-compose.yml"),
    }


@pytest.mark.parametrize("field", ["working_dir", "config_files"])
def test_up_rejects_same_project_from_foreign_checkout(monkeypatch, tmp_path, capsys, field):
    deploy = load_deploy()
    labels = owned_labels(tmp_path)
    labels[f"com.docker.compose.project.{field}"] = "/foreign/checkout"
    calls = mock_project_docker(deploy, monkeypatch, tmp_path, labels=labels)
    assert deploy.main(["--project", "plan-a-demo"]) == 1
    assert "ownership" in capsys.readouterr().err
    assert not any("up" in command for command, _ in calls)


@pytest.mark.parametrize("field", ["project", "volume"])
def test_up_rejects_mislabeled_existing_volume_before_up(monkeypatch, tmp_path, capsys, field):
    deploy = load_deploy()
    labels = {"com.docker.compose.project": "plan-a-demo", "com.docker.compose.volume": "run-data"}
    labels[f"com.docker.compose.{field}"] = "foreign"
    calls = mock_project_docker(
        deploy, monkeypatch, tmp_path, volumes={"plan-a-demo_run-data": labels}
    )
    assert deploy.main(["--project", "plan-a-demo"]) == 1
    assert "ownership" in capsys.readouterr().err
    assert not any("up" in command for command, _ in calls)


@pytest.mark.parametrize("existing", [False, True])
def test_up_allows_new_project_or_resources_owned_by_current_checkout(
    monkeypatch, tmp_path, existing
):
    deploy = load_deploy()
    labels = owned_labels(tmp_path) if existing else None
    volumes = (
        {
            "plan-a-demo_run-data": {
                "com.docker.compose.project": "plan-a-demo",
                "com.docker.compose.volume": "run-data",
            }
        }
        if existing
        else {}
    )
    calls = mock_project_docker(deploy, monkeypatch, tmp_path, labels=labels, volumes=volumes)
    assert deploy.main(["--project", "plan-a-demo"]) == 0
    assert any("up" in command for command, _ in calls)


def test_resolved_env_ports_survive_when_not_overridden_by_process(monkeypatch, tmp_path):
    deploy = load_deploy()
    monkeypatch.delenv("APP_BIND", raising=False)
    monkeypatch.delenv("QDRANT_BIND", raising=False)
    calls = mock_project_docker(deploy, monkeypatch, tmp_path)
    assert deploy.main([]) == 0
    environments = [
        kwargs["env"] for command, kwargs in calls if "config" in command or "up" in command
    ]
    assert all("APP_BIND" not in environment for environment in environments)
    assert all("QDRANT_BIND" not in environment for environment in environments)


def test_resolved_env_public_binding_cannot_bypass_lan_requirement(monkeypatch, tmp_path, capsys):
    deploy = load_deploy()
    calls = mock_project_docker(deploy, monkeypatch, tmp_path, app_bind="0.0.0.0:9080")
    assert deploy.main([]) == 1
    assert "--lan" in capsys.readouterr().err
    assert not any("up" in command for command, _ in calls)


def test_lan_reuses_configured_env_port_and_validates_dependency_bindings(
    monkeypatch, tmp_path, capsys
):
    deploy = load_deploy()
    calls = mock_project_docker(deploy, monkeypatch, tmp_path)
    assert deploy.main(["--lan"]) == 0
    up_environment = next(kwargs["env"] for command, kwargs in calls if "up" in command)
    assert up_environment["APP_BIND"] == "0.0.0.0:9080"
    calls = mock_project_docker(deploy, monkeypatch, tmp_path, dependency_bind="0.0.0.0:9333")
    assert deploy.main(["--lan"]) == 1
    assert "loopback" in capsys.readouterr().err
    assert not any("up" in command for command, _ in calls)


def test_compose_file_is_explicit_even_with_inherited_compose_file(monkeypatch):
    deploy = load_deploy()
    monkeypatch.setenv("COMPOSE_FILE", "/foreign/docker-compose.yml")
    command = deploy.compose_command("plan-a-demo")
    assert command[command.index("-f") + 1] == str(ROOT / "docker-compose.yml")


def test_process_binding_retains_precedence_over_resolved_env_default(monkeypatch, tmp_path):
    deploy = load_deploy()
    monkeypatch.setenv("APP_BIND", "127.0.0.1:10080")
    calls = mock_project_docker(deploy, monkeypatch, tmp_path)
    assert deploy.main([]) == 0
    environments = [
        kwargs["env"] for command, kwargs in calls if "config" in command or "up" in command
    ]
    assert all(environment["APP_BIND"] == "127.0.0.1:10080" for environment in environments)
