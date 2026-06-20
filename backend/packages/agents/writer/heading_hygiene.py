from __future__ import annotations

import re

from packages.agents.writer.structured_renderer import STRUCTURED_REPORT_EN_LABELS
from packages.i18n.language import REPORT_LABELS

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_heading_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip().casefold()


ENGLISH_STRUCTURAL_HEADINGS = frozenset(
    normalize_heading_text(heading)
    for heading in (
        *REPORT_LABELS["en-US"].values(),
        *STRUCTURED_REPORT_EN_LABELS.values(),
        "Pricing and Packaging",
        "Feature and Workflow Capability",
        "User Persona and Adoption",
        "Cross-Competitor Risks and Implications",
        "Direct User / Community Signals",
        "Simulated Survey and Interview Signals",
        "Adoption Blockers",
        "Switching Triggers",
        "Evidence Gaps",
        "Official Facts vs Community Observations",
        "Repeated Signals",
        "Contested or Low-Confidence Signals",
        "Positioning and Core Value",
        "Feature Capabilities",
        "Community Feedback, Adoption Blockers, and Switching Triggers",
        "Competitive Plays and Evidence Gaps",
        "Strengths",
        "Weaknesses",
        "Opportunities",
        "Threats",
        "Attack Point",
        "Defense / Rebuttal",
        "Best-Fit Buyer Scenario",
        "Proof Needed Before Use",
        "Workflow Overlap",
        "Enterprise Buying Risk",
        "Switching Cost and Controls",
        "Category Segments",
        "Strategic Clusters",
        "Trend Signals and Uncertainty",
        "Decision Implications",
        "Operating Risks",
        "Next Validation Tasks",
        "Battlecard",
        "Source Appendix",
        "Claim Support Audit",
    )
)
