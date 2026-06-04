from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass(frozen=True)
class TrustedSourceCandidate:
    title: str
    url: str
    rationale: str
    dimension: str
    source_kind: str = "official"


@dataclass(frozen=True)
class CompetitorIdentity:
    canonical_name: str
    homepage_url: str
    aliases: tuple[str, ...] = ()
    trusted_domains: tuple[str, ...] = ()
    identity_terms: tuple[str, ...] = ()
    confusion_terms: tuple[str, ...] = ()
    search_qualifier: str = ""
    sources_by_dimension: dict[str, tuple[TrustedSourceCandidate, ...]] = field(
        default_factory=dict
    )


def _dimension_key(dimension: str) -> str:
    key = dimension.casefold()
    if "pricing" in key:
        return "pricing"
    if any(token in key for token in ("security", "trust", "compliance")):
        return "security"
    if any(token in key for token in ("persona", "user", "buyer", "customer")):
        return "persona"
    return "feature"


def source_candidate(
    title: str,
    url: str,
    dimension: str,
    rationale: str = "Trusted source registry entry.",
    source_kind: str = "official",
) -> TrustedSourceCandidate:
    return TrustedSourceCandidate(
        title=title,
        url=url,
        dimension=_dimension_key(dimension),
        rationale=rationale,
        source_kind=source_kind,
    )


_IDENTITIES: tuple[CompetitorIdentity, ...] = (
    CompetitorIdentity(
        canonical_name="Cursor",
        homepage_url="https://cursor.com",
        aliases=("cursor", "cursor ai"),
        trusted_domains=("cursor.com", "www.cursor.com"),
        identity_terms=("cursor.com", "cursor ai", "ai code editor", "code editor"),
        confusion_terms=(
            "cursor extractor",
            "database cursor",
            "pagination cursor",
            "sql cursor",
            "css cursor",
            "mouse cursor",
        ),
        search_qualifier="AI code editor",
        sources_by_dimension={
            "pricing": (
                source_candidate(
                    "Cursor official pricing", "https://cursor.com/pricing", "pricing"
                ),
            ),
            "feature": (
                source_candidate(
                    "Cursor official features", "https://www.cursor.com/features", "feature"
                ),
            ),
            "persona": (
                source_candidate("Cursor official product page", "https://cursor.com", "persona"),
            ),
            "security": (
                source_candidate(
                    "Cursor official security", "https://cursor.com/security", "security"
                ),
            ),
        },
    ),
    CompetitorIdentity(
        canonical_name="GitHub Copilot",
        homepage_url="https://github.com/features/copilot",
        aliases=("github copilot", "copilot"),
        trusted_domains=("github.com", "docs.github.com", "github.blog"),
        identity_terms=(
            "github.com/features/copilot",
            "docs.github.com/en/copilot",
            "github copilot",
            "copilot",
        ),
        search_qualifier="GitHub Copilot coding assistant",
        sources_by_dimension={
            "feature": (
                source_candidate(
                    "GitHub Copilot official feature docs",
                    "https://docs.github.com/en/copilot/get-started/features",
                    "feature",
                ),
                source_candidate(
                    "GitHub Copilot official product page",
                    "https://github.com/features/copilot",
                    "feature",
                ),
            ),
            "pricing": (
                source_candidate(
                    "GitHub Copilot official plans and pricing",
                    "https://github.com/features/copilot/plans",
                    "pricing",
                ),
            ),
            "persona": (
                source_candidate(
                    "GitHub Copilot official product page",
                    "https://github.com/features/copilot",
                    "persona",
                ),
            ),
            "security": (
                source_candidate(
                    "GitHub Copilot enterprise approval resources",
                    "https://docs.github.com/en/enterprise-cloud@latest/copilot/tutorials/roll-out-at-scale/govern-at-scale/resources-for-approval",
                    "security",
                ),
                source_candidate(
                    "GitHub Copilot compliance changelog",
                    "https://github.blog/changelog/2024-06-03-github-copilot-compliance-soc-2-type-1-report-and-iso-iec-270012013-certification-scope/",
                    "security",
                ),
            ),
        },
    ),
    CompetitorIdentity(
        canonical_name="Windsurf",
        homepage_url="https://windsurf.com",
        aliases=("windsurf", "codeium"),
        trusted_domains=("windsurf.com", "docs.windsurf.com", "docs.devin.ai"),
        identity_terms=(
            "windsurf.com",
            "docs.windsurf.com",
            "docs.devin.ai/desktop",
            "windsurf",
            "codeium",
            "ai code editor",
        ),
        confusion_terms=("devin.ai", "devin desktop", "cognition devin"),
        search_qualifier="Windsurf AI code editor",
        sources_by_dimension={
            "pricing": (
                source_candidate(
                    "Windsurf official plans and usage",
                    "https://docs.windsurf.com/windsurf/accounts/usage",
                    "pricing",
                ),
            ),
            "feature": (
                source_candidate(
                    "Windsurf official Cascade docs",
                    "https://docs.windsurf.com/plugins/cascade/cascade-overview",
                    "feature",
                ),
                source_candidate(
                    "Windsurf official plugin docs",
                    "https://docs.windsurf.com/plugins",
                    "feature",
                ),
            ),
            "persona": (
                source_candidate(
                    "Windsurf official getting started docs",
                    "https://docs.windsurf.com/windsurf/getting-started",
                    "persona",
                ),
            ),
            "security": (
                source_candidate(
                    "Windsurf official trust page", "https://windsurf.com/trust", "security"
                ),
                source_candidate(
                    "Windsurf official compliance page",
                    "https://windsurf.com/compliance",
                    "security",
                ),
            ),
        },
    ),
    CompetitorIdentity(
        canonical_name="Claude Code",
        homepage_url="https://www.anthropic.com/product/claude-code",
        aliases=("claude code", "claudecode", "anthropic claude code"),
        trusted_domains=(
            "anthropic.com",
            "docs.anthropic.com",
            "docs.claude.com",
            "code.claude.com",
            "claude.com",
        ),
        identity_terms=(
            "claude-code",
            "claude code",
            "code.claude.com",
            "anthropic.com/product/claude-code",
        ),
        confusion_terms=("generic claude",),
        search_qualifier="Claude Code coding agent",
        sources_by_dimension={
            "feature": (
                source_candidate(
                    "Claude Code official product page",
                    "https://www.anthropic.com/product/claude-code",
                    "feature",
                ),
                source_candidate(
                    "Claude Code official overview docs",
                    "https://docs.anthropic.com/en/docs/claude-code/overview",
                    "feature",
                ),
            ),
            "pricing": (
                source_candidate(
                    "Claude Code cost management docs",
                    "https://code.claude.com/docs/en/costs",
                    "pricing",
                ),
                source_candidate(
                    "Claude official pricing", "https://claude.com/pricing", "pricing"
                ),
            ),
            "persona": (
                source_candidate(
                    "Claude Code official product page",
                    "https://www.anthropic.com/product/claude-code",
                    "persona",
                ),
            ),
            "security": (
                source_candidate(
                    "Claude Code official security docs",
                    "https://docs.claude.com/en/docs/claude-code/security",
                    "security",
                ),
            ),
        },
    ),
    CompetitorIdentity(
        canonical_name="OpenAI",
        homepage_url="https://openai.com",
        aliases=("openai", "chatgpt", "gpt", "gpt5", "gpt55", "gpt-5", "gpt-5.5"),
        trusted_domains=(
            "openai.com",
            "developers.openai.com",
            "platform.openai.com",
            "help.openai.com",
        ),
        identity_terms=("openai", "chatgpt", "gpt", "developers.openai.com", "platform.openai.com"),
        search_qualifier="OpenAI GPT model",
        sources_by_dimension={
            "pricing": (
                source_candidate(
                    "OpenAI API pricing",
                    "https://developers.openai.com/api/docs/pricing",
                    "pricing",
                ),
                source_candidate(
                    "OpenAI platform model reference",
                    "https://platform.openai.com/docs/models",
                    "pricing",
                    rationale="Official model reference used as pricing fallback context.",
                ),
            ),
            "feature": (
                source_candidate(
                    "OpenAI model documentation",
                    "https://developers.openai.com/api/docs/guides/latest-model",
                    "feature",
                ),
                source_candidate(
                    "OpenAI API models reference",
                    "https://platform.openai.com/docs/models",
                    "feature",
                ),
                source_candidate("OpenAI product updates", "https://openai.com/news/", "feature"),
            ),
            "persona": (
                source_candidate(
                    "OpenAI business solutions", "https://openai.com/business/", "persona"
                ),
                source_candidate(
                    "ChatGPT Enterprise",
                    "https://openai.com/chatgpt/enterprise/",
                    "persona",
                ),
                source_candidate(
                    "OpenAI customer stories",
                    "https://openai.com/customer-stories/",
                    "persona",
                ),
                source_candidate(
                    "ChatGPT Enterprise help center",
                    "https://help.openai.com/en/collections/3742473-chatgpt-enterprise",
                    "persona",
                ),
            ),
            "security": (
                source_candidate(
                    "OpenAI security and privacy", "https://openai.com/security/", "security"
                ),
            ),
        },
    ),
    CompetitorIdentity(
        canonical_name="Claude",
        homepage_url="https://claude.com",
        aliases=("claude", "anthropic claude", "claude 4", "claude opus", "claude sonnet"),
        trusted_domains=(
            "anthropic.com",
            "docs.anthropic.com",
            "support.claude.com",
            "claude.com",
            "claude.ai",
        ),
        identity_terms=("claude", "anthropic", "docs.anthropic.com", "claude.com", "claude.ai"),
        search_qualifier="Anthropic Claude model",
        sources_by_dimension={
            "pricing": (
                source_candidate("Claude pricing", "https://claude.com/pricing", "pricing"),
                source_candidate(
                    "Anthropic API pricing",
                    "https://docs.anthropic.com/en/docs/about-claude/pricing",
                    "pricing",
                ),
            ),
            "feature": (
                source_candidate(
                    "Claude model overview",
                    "https://docs.anthropic.com/en/docs/about-claude/models/overview",
                    "feature",
                ),
                source_candidate(
                    "Claude product page", "https://www.anthropic.com/claude", "feature"
                ),
            ),
            "persona": (
                source_candidate(
                    "Claude enterprise plan",
                    "https://support.claude.com/en/articles/9797531-what-is-the-enterprise-plan",
                    "persona",
                ),
                source_candidate(
                    "Claude product page", "https://www.anthropic.com/claude", "persona"
                ),
                source_candidate(
                    "Claude for Enterprise",
                    "https://www.anthropic.com/enterprise",
                    "persona",
                ),
            ),
            "security": (
                source_candidate(
                    "Anthropic trust center", "https://trust.anthropic.com/", "security"
                ),
            ),
        },
    ),
    CompetitorIdentity(
        canonical_name="Gemini",
        homepage_url="https://gemini.google",
        aliases=("gemini", "google gemini", "gemini ai", "google ai"),
        trusted_domains=(
            "gemini.google",
            "ai.google.dev",
            "cloud.google.com",
            "docs.cloud.google.com",
            "blog.google",
        ),
        identity_terms=("gemini", "google", "ai.google.dev", "cloud.google.com", "gemini.google"),
        search_qualifier="Google Gemini model",
        sources_by_dimension={
            "pricing": (
                source_candidate(
                    "Gemini API pricing",
                    "https://ai.google.dev/gemini-api/docs/pricing",
                    "pricing",
                ),
                source_candidate(
                    "Google Cloud Gemini pricing",
                    "https://cloud.google.com/products/gemini/pricing",
                    "pricing",
                ),
            ),
            "feature": (
                source_candidate(
                    "Gemini API docs",
                    "https://ai.google.dev/gemini-api/docs",
                    "feature",
                ),
                source_candidate("Gemini overview", "https://gemini.google/overview/", "feature"),
            ),
            "persona": (
                source_candidate(
                    "Gemini enterprise use cases",
                    "https://docs.cloud.google.com/gemini/enterprise/docs/example-use-cases",
                    "persona",
                ),
                source_candidate(
                    "Gemini for Google Cloud",
                    "https://cloud.google.com/products/gemini",
                    "persona",
                ),
                source_candidate(
                    "Gemini customer stories",
                    "https://cloud.google.com/customers?products=Gemini",
                    "persona",
                ),
            ),
            "security": (
                source_candidate(
                    "Google Cloud security and compliance",
                    "https://cloud.google.com/security/compliance",
                    "security",
                ),
            ),
        },
    ),
    CompetitorIdentity(
        canonical_name="Llama",
        homepage_url="https://www.llama.com",
        aliases=("llama", "llama 4", "meta llama", "meta ai llama", "llama4"),
        trusted_domains=("llama.com", "ai.meta.com", "about.fb.com", "developers.facebook.com"),
        identity_terms=("llama", "meta ai", "ai.meta.com", "llama.com", "meta-llama"),
        search_qualifier="Meta Llama model",
        sources_by_dimension={
            "pricing": (
                source_candidate(
                    "Llama official download and license",
                    "https://www.llama.com/llama-downloads/",
                    "pricing",
                    rationale=(
                        "Official model access and license page; Llama is commonly "
                        "distributed without API seat pricing."
                    ),
                ),
                source_candidate(
                    "Llama license",
                    "https://www.llama.com/llama4/license/",
                    "pricing",
                    rationale="Official license page used when no seat/API pricing exists.",
                ),
                source_candidate(
                    "Meta Llama 4 announcement",
                    "https://ai.meta.com/blog/llama-4-multimodal-intelligence/",
                    "pricing",
                    rationale="Official announcement fallback for open model availability context.",
                ),
            ),
            "feature": (
                source_candidate(
                    "Meta Llama 4 announcement",
                    "https://ai.meta.com/blog/llama-4-multimodal-intelligence/",
                    "feature",
                ),
                source_candidate("Llama product site", "https://www.llama.com/", "feature"),
                source_candidate(
                    "Llama docs",
                    "https://www.llama.com/docs/",
                    "feature",
                ),
            ),
            "persona": (
                source_candidate(
                    "Llama official product site", "https://www.llama.com/", "persona"
                ),
                source_candidate(
                    "Meta Llama 4 announcement",
                    "https://ai.meta.com/blog/llama-4-multimodal-intelligence/",
                    "persona",
                ),
                source_candidate(
                    "Llama docs",
                    "https://www.llama.com/docs/",
                    "persona",
                ),
            ),
            "security": (
                source_candidate(
                    "Llama responsible use guide",
                    "https://www.llama.com/responsible-use-guide/",
                    "security",
                ),
            ),
        },
    ),
)


def normalize_competitor_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


_IDENTITY_BY_KEY: dict[str, CompetitorIdentity] = {}
for _identity in _IDENTITIES:
    for _value in (_identity.canonical_name, *_identity.aliases):
        _IDENTITY_BY_KEY.setdefault(normalize_competitor_key(_value), _identity)


def resolve_competitor_identity(competitor: str) -> CompetitorIdentity | None:
    key = normalize_competitor_key(competitor)
    if not key:
        return None
    if identity := _IDENTITY_BY_KEY.get(key):
        return identity
    for alias_key, identity in _IDENTITY_BY_KEY.items():
        if len(alias_key) >= 4 and key.startswith(alias_key):
            return identity
        if len(key) >= 6 and alias_key.startswith(key):
            return identity
    return None


def trusted_source_candidates(
    competitor: str,
    dimension: str,
) -> list[TrustedSourceCandidate]:
    identity = resolve_competitor_identity(competitor)
    if identity is None:
        return []
    dimension_key = _dimension_key(dimension)
    candidates = [
        *identity.sources_by_dimension.get(dimension_key, ()),
        *identity.sources_by_dimension.get("feature", ()),
    ]
    if dimension_key != "persona":
        candidates.append(
            source_candidate(
                f"{identity.canonical_name} official homepage",
                identity.homepage_url,
                dimension_key,
                rationale="Trusted identity homepage fallback.",
            )
        )
    return _dedupe_candidates(candidates)


def identity_terms_for_competitor(competitor: str) -> tuple[str, ...]:
    identity = resolve_competitor_identity(competitor)
    return identity.identity_terms if identity is not None else ()


def confusion_terms_for_competitor(competitor: str) -> tuple[str, ...]:
    identity = resolve_competitor_identity(competitor)
    return identity.confusion_terms if identity is not None else ()


def search_qualifier_for_competitor(competitor: str) -> str:
    identity = resolve_competitor_identity(competitor)
    return identity.search_qualifier if identity is not None else ""


def is_trusted_url_for_competitor(competitor: str, url: str) -> bool:
    identity = resolve_competitor_identity(competitor)
    if identity is None:
        return False
    host = _host(url)
    return any(host == domain or host.endswith(f".{domain}") for domain in identity.trusted_domains)


def _host(url: str) -> str:
    if not url:
        return ""
    return (urlparse(url).hostname or "").casefold().removeprefix("www.")


def _dedupe_candidates(
    candidates: list[TrustedSourceCandidate],
) -> list[TrustedSourceCandidate]:
    seen: set[str] = set()
    deduped: list[TrustedSourceCandidate] = []
    for candidate in candidates:
        key = candidate.url.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped
