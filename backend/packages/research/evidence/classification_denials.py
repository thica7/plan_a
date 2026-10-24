"""Finite classification negatives must occur in the selected support itself.

This is an overreach guard, not a general entailment or translation checker.
"""

import re

_CATEGORIES = (
    r"(?:成员|会员)(?:身份)?类型|membership\s+type|member\s+type",
    r"用户类型|user\s+type",
    r"账户类型|账号类型|account\s+type",
    r"席位类型|seat\s+type",
    r"套餐类型|plan\s+type",
)
_NEGATIVE = r"(?:而非|并非|不是|不属于|并不是|\bnot\s+(?:an?\s+)?|\bnot\s+(?:a\s+)?type\s+of\s+)"


def classification_denial_reasons(text, support_quotes):
    """A parent sentence with a denial cannot repair a narrower citation."""
    support = " ".join(support_quotes)
    for category in _CATEGORIES:
        pattern = _NEGATIVE + r"(?:一种|某种|任何)?\s*(?:" + category + r")"
        if re.search(pattern, text, re.I) and not re.search(pattern, support, re.I):
            return ("classification_denial_outside_support",)
    return ()
