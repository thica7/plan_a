from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


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
        'BACKUP_LLM_API_KEY = "OPENROUTER_TEST_KEY_REDACTED"\n',
        encoding="utf-8",
    )

    findings = module.scan_paths([target], root=tmp_path)

    assert len(findings) == 1
    assert findings[0].pattern_name == "openai_like_key"
    assert "sk-or-" in findings[0].preview


def test_secret_scan_ignores_placeholders_and_test_fixtures(tmp_path: Path) -> None:
    module = _load_scan_module()
    placeholder = tmp_path / "README.md"
    placeholder.write_text("OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz1234567890\n", encoding="utf-8")
    fixture = tmp_path / "backend" / "tests" / "unit" / "test_fixture.py"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(
        'key = "OPENROUTER_TEST_KEY_REDACTED"\n',
        encoding="utf-8",
    )

    findings = module.scan_paths([placeholder, fixture], root=tmp_path)

    assert findings == []
