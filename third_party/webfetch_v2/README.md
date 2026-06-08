# webfetch_v2

Advanced WebFetch for research agents and `plan_a`.

This project provides:

- a Python CLI: `python -m webfetch_v2 fetch <url>`
- static HTTP fetching with content extraction and quality diagnostics
- optional Playwright browser rendering for JavaScript-heavy public pages
- optional authorized browser profiles for user-approved sessions
- optional browser network capture for document/XHR/fetch responses
- structured JSON output that downstream agents can score, cite, cache, and debug
- extraction candidate diagnostics with optional trafilatura/readability support
- cache/evidence store for result JSON, markdown, rendered HTML, and screenshots
- a subprocess-friendly runtime boundary for `plan_a` collectors

## Safety boundary

`webfetch_v2` is designed to improve compatibility for authorized and public web access. It does **not** bypass CAPTCHA, paywalls, login walls, bot challenges, IP bans, or explicit access controls. When those are detected, it returns a structured failure reason so the agent can use an official API, ask for user authorization, or choose another source.

## Quick start

```powershell
python -m webfetch_v2 doctor --pretty
python -m webfetch_v2 fetch "https://example.com" --mode static --pretty
```

Optional advanced extraction can be installed with:

```powershell
pip install -e .[extraction]
```

Browser rendering requires Playwright:

```powershell
pip install -e .[browser]
python -m playwright install chromium
python -m webfetch_v2 doctor --check-browser --pretty
python -m webfetch_v2 fetch "https://example.com" --mode browser --pretty
```

Capture browser network responses:

```powershell
python -m webfetch_v2 fetch "https://example.com" --mode browser --capture-network --pretty
```



Batch fetch source lists:

```powershell
python -m webfetch_v2 batch path\to\urls.txt --mode static --cache --pretty
python -m webfetch_v2 batch path\to\urls.json --mode static --prefer-cache --pretty
```
Cache results for audit/reuse:

```powershell
python -m webfetch_v2 fetch "https://example.com" --mode static --cache --pretty
python -m webfetch_v2 fetch "https://example.com" --prefer-cache --pretty
python -m webfetch_v2 cache list --pretty
python -m webfetch_v2 cache show <key> --pretty
python -m webfetch_v2 fetch "https://example.com" --mode browser --capture-network --screenshot --cache --pretty
```
Create an authorized persistent profile only when the user has explicitly approved it:

```powershell
python -m webfetch_v2 auth-session --profile authorized-work --url "https://example.com/login" --pretty
python -m webfetch_v2 fetch "https://example.com/account" --mode browser --profile authorized-work --pretty
```

## Output contract

The CLI emits JSON with these major fields:

- `url`, `final_url`, `status_code`, `content_type`
- `title`, `text`, `markdown`, `links`
- `fetch_method`: `static`, `browser`, or `failed`
- `quality`: score, text length, and block/login/captcha/JS/cookie-banner signals
- `diagnostics`: elapsed time, warnings, failure reason, exception text
- `artifacts`: optional screenshot or rendered HTML paths
- `network`: optional document/XHR/fetch response summaries when `--capture-network` is used
- `extraction`: selected extraction method plus candidate scores and text lengths
- `cache`: cache manifest paths when `--cache` is used
- batch output: `summary` plus quality-sorted `results` when using `batch`

## plan_a integration

This is the vendored runtime copy used by `plan_a`. The default collector
fallback runs this directory through `backend/packages/tools/advanced_fetch.py`.
Leave `WEBFETCH_V2_ROOT` unset or empty to use this deployment copy; set it only
when intentionally testing a different checkout.

## Smoke checks

Default static smoke does not require Playwright:

```powershell
cd third_party\webfetch_v2
python -m webfetch_v2 doctor --pretty
python -m webfetch_v2 fetch "https://example.com" --mode static --pretty
```

Optional browser smoke requires Playwright:

```powershell
cd third_party\webfetch_v2
python -m webfetch_v2 doctor --check-browser --pretty
python -m webfetch_v2 fetch "https://example.com" --mode browser --pretty
```

## Tests

The vendored copy is covered from the parent project tests:

```powershell
cd ..\..
python -m pytest backend\tests\unit\test_advanced_fetch.py -q
```

Optional browser test path:

```powershell
cd third_party\webfetch_v2
python -m pip install -e .[browser]
python -m playwright install chromium
$env:WEBFETCH_V2_RUN_BROWSER_TESTS = "1"
```
