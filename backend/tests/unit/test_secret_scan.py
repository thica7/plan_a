from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

GITLAB_PREFIX = "glpat" + "-"
OPENROUTER_PREFIX = "sk" + "-or-v1-"
OPENAI_PROJECT_PREFIX = "sk" + "-proj-"
PERPLEXITY_PREFIX = "pplx" + "-"

FAKE_GITLAB_TOKEN = GITLAB_PREFIX + "gitlabtoken" * 3
FAKE_OPENROUTER_KEY = OPENROUTER_PREFIX + "livekey" * 8
FIXTURE_OPENROUTER_KEY = OPENROUTER_PREFIX + "redacted_fixture_1234567890" * 2
FAKE_PERPLEXITY_KEY = PERPLEXITY_PREFIX + "perplexity" * 3


def _load_scan_module():
    path = Path(__file__).parents[2] / "scripts" / "scan_secrets.py"
    spec = importlib.util.spec_from_file_location("scan_secrets", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_secret_scan_flags_provider_key_shapes(tmp_path: Path) -> None:
    module = _load_scan_module()
    target = tmp_path / "app.py"
    target.write_text(
        "\n".join(
            [
                f'BACKUP_LLM_API_KEY = "{FAKE_OPENROUTER_KEY}"',
                f'PPLX_API_KEY = "{FAKE_PERPLEXITY_KEY}"',
                f'GITLAB_TOKEN = "{FAKE_GITLAB_TOKEN}"',
            ]
        ),
        encoding="utf-8",
    )

    findings = module.scan_paths([target], root=tmp_path)

    assert {finding.pattern_name for finding in findings} == {
        "gitlab_token",
        "openai_like_key",
        "perplexity_key",
    }
    assert any("sk-or-" in finding.preview for finding in findings)


def test_secret_scan_ignores_placeholders_and_test_fixtures(tmp_path: Path) -> None:
    module = _load_scan_module()
    placeholder = tmp_path / "README.md"
    placeholder.write_text(
        f"OPENAI_API_KEY={OPENAI_PROJECT_PREFIX}abcdefghijklmnopqrstuvwxyz1234567890\n",
        encoding="utf-8",
    )
    fixture = tmp_path / "backend" / "tests" / "unit" / "test_fixture.py"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(
        f'key = "{FIXTURE_OPENROUTER_KEY}"\n',
        encoding="utf-8",
    )

    findings = module.scan_paths([placeholder, fixture], root=tmp_path)

    assert findings == []


def test_secret_scan_flags_unmarked_provider_keys_in_tests(tmp_path: Path) -> None:
    module = _load_scan_module()
    fixture = tmp_path / "backend" / "tests" / "unit" / "test_leaked_key.py"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(
        f'key = "{FAKE_OPENROUTER_KEY}"\n',
        encoding="utf-8",
    )

    findings = module.scan_paths([fixture], root=tmp_path)

    assert [(item.path.replace("\\", "/"), item.pattern_name) for item in findings] == [
        ("backend/tests/unit/test_leaked_key.py", "openai_like_key")
    ]
