from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from webfetch_v2.fetcher import USER_AGENT
from webfetch_v2.paths import profile_dir


@dataclass(frozen=True)
class AuthSessionResult:
    ok: bool
    profile: str
    profile_dir: str
    url: str
    message: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def open_auth_session(
    *,
    profile: str,
    url: str,
    timeout_seconds: float = 0,
) -> AuthSessionResult:
    """Open a headed persistent browser profile for user-authorized login.

    The user performs any login or MFA manually. The tool does not read passwords,
    submit forms automatically, or bypass access controls.
    """

    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # noqa: BLE001 - optional dependency may be absent.
        return AuthSessionResult(
            ok=False,
            profile=profile,
            profile_dir=str(profile_dir(profile)),
            url=url,
            message="Playwright is not installed. Install with: pip install -e .[browser]; python -m playwright install chromium",
            error=str(exc),
        )

    try:
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir(profile)),
                headless=False,
                user_agent=USER_AGENT,
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000 if timeout_seconds else 0)
            print(
                "Browser opened for authorized session setup. Complete login manually, "
                "then return here and press Enter to save/close the profile."
            )
            input()
            final_url = page.url
            await context.close()
        return AuthSessionResult(
            ok=True,
            profile=profile,
            profile_dir=str(profile_dir(profile)),
            url=final_url,
            message="Authorized browser profile saved. Use it with fetch --mode browser --profile <name>.",
        )
    except Exception as exc:  # noqa: BLE001 - setup failures should be actionable.
        return AuthSessionResult(
            ok=False,
            profile=profile,
            profile_dir=str(profile_dir(profile)),
            url=url,
            message="Failed to open authorized browser session.",
            error=str(exc),
        )
