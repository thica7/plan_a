from __future__ import annotations

import importlib.util
import platform
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from webfetch_v2.paths import cache_dir, profiles_dir


@dataclass(frozen=True)
class PythonStatus:
    executable: str
    version: str
    supported: bool


@dataclass(frozen=True)
class DependencyStatus:
    beautifulsoup4: bool
    playwright: bool


@dataclass(frozen=True)
class BrowserStatus:
    chromium_launchable: bool | None
    error: str | None = None


@dataclass(frozen=True)
class PathStatus:
    profiles_dir: str
    cache_dir: str
    project_dir: str


@dataclass(frozen=True)
class DoctorResult:
    ok: bool
    python: PythonStatus
    optional_dependencies: DependencyStatus
    browsers: BrowserStatus
    paths: PathStatus
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def run_doctor(*, check_browser: bool = False) -> DoctorResult:
    py_status = PythonStatus(
        executable=sys.executable,
        version=platform.python_version(),
        supported=sys.version_info >= (3, 10),
    )
    deps = DependencyStatus(
        beautifulsoup4=_module_available("bs4"),
        playwright=_module_available("playwright"),
    )
    browser = BrowserStatus(chromium_launchable=None)
    if check_browser and deps.playwright:
        browser = await _check_chromium()
    elif check_browser:
        browser = BrowserStatus(chromium_launchable=False, error="playwright_not_installed")

    paths = PathStatus(
        profiles_dir=str(profiles_dir()),
        cache_dir=str(cache_dir()),
        project_dir=str(Path(__file__).resolve().parents[1]),
    )
    recommendations: list[str] = []
    if not py_status.supported:
        recommendations.append("Use Python 3.10+; on this machine try: py -3.10 -m webfetch_v2 ...")
    if not deps.beautifulsoup4:
        recommendations.append("Install extraction dependency: py -3.10 -m pip install beautifulsoup4")
    if not deps.playwright:
        recommendations.append("Install browser support: py -3.10 -m pip install -e .[browser]")
        recommendations.append("Install Chromium: py -3.10 -m playwright install chromium")
    elif browser.chromium_launchable is False:
        recommendations.append("Install Chromium: py -3.10 -m playwright install chromium")

    ok = py_status.supported and (not check_browser or browser.chromium_launchable is not False)
    return DoctorResult(
        ok=ok,
        python=py_status,
        optional_dependencies=deps,
        browsers=browser,
        paths=paths,
        recommendations=recommendations,
    )


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


async def _check_chromium() -> BrowserStatus:
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            await browser.close()
        return BrowserStatus(chromium_launchable=True)
    except Exception as exc:  # noqa: BLE001 - diagnostic output should include setup errors.
        return BrowserStatus(chromium_launchable=False, error=str(exc))
