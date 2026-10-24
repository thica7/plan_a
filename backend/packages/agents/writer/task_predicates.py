"""Finite sibling-property checks, not a general entailment classifier."""

import re

_COUNT = r"(?:\d+|one|two|three|four|一|两|二|三|四)"
_PROPERTIES = {
    "personal_area": r"(?:没有|不(?:能|可)?拥有|有自己的)[^，。;；]{0,30}(?:私人|个人|Private)"
    r"|\b(?:have\s+no|do\s+not\s+have|don't\s+have|own)\b[^,;.!?]{0,30}\b(?:personal|private)\b",
    "container_limit": r"(?:\b(?:only|at\s+most|up\s+to)\b|最多|至多|只能)"
    r"[^，。;；]{0,30}" + _COUNT + r"\s*(?:个\s*)?(?:shared\s+)?"
    r"(?:collections?|containers?|vaults?|共享保险库|保险库|集合|容器)",
    "people_limit": r"(?:\b(?:at\s+most|up\s+to|only)\b|最多|至多|只能)[^，,。;；]{0,20}"
    + _COUNT
    + r"\s*(?:other\s+)?(?:名|位|个)?\s*(?:users?|people|用户|人)",
    "recipient_sharing": r"(?:组织|计划|套餐|账户)[^，,。;；]{0,12}"
    r"(?:可以|可|能够|能)与另(?:外)?一(?:名|位|个)用户[^，,。;；]{0,12}共享"
    r"|\b(?:organizations?|plans?|accounts?)\s+(?:can|may)\s+(?:securely\s+)?share\b"
    r"[^,;.!?]{0,30}\bwith\s+one\s+other\s+user\b",
    "core_features": r"(?:提供|支持)[^，。;；]{0,30}(?:全部|所有|全部的)?核心功能"
    r"|\b(?:offer|provide)[^,;.!?]{0,40}\bcore\s+features\b",
    "billing": r"\$|\b(?:costs?|charged?|billing|per\s+million)\b|计费|收费|超额|每月包含",
    "runtime": r"(?:每次|每个)[^，。;；]{0,35}(?:调用|执行)[^，。;；]{0,30}(?:最多|上限|分钟|秒)"
    r"|\b(?:each|per)\s+(?:invocation|execution|request)\b[^;.!?]{0,65}"
    r"\b(?:limit|minutes?|seconds?)\b",
    "level_denial": r"(?:无法|不能|不支持)[^，。;；]{0,30}(?:Workspace|工作区)"
    r"[^，。;；]{0,15}(?:层级|级别)",
    "individual_setup": r"每(?:位|个)[^，。;；]{0,30}(?:需|必须)[^，。;；]{0,20}"
    r"(?:按成员|逐人)[^，。;；]{0,20}(?:按看板|逐板)",
}


def contains_sibling_properties(assertion):
    """Reject only the known independent property pairs in assertion text."""
    properties = {
        name for name, pattern in _PROPERTIES.items() if re.search(pattern, assertion, re.I)
    }
    return bool(
        {"personal_area", "container_limit"} <= properties
        or len(properties & {"people_limit", "container_limit", "core_features"}) > 1
        or {"recipient_sharing", "container_limit"} <= properties
        or {"recipient_sharing", "core_features"} <= properties
        or {"billing", "runtime"} <= properties
        or {"level_denial", "individual_setup"} <= properties
    )


def explicit_scope_assignment(text):
    """Exact scenario fragment used only to request a separate sourced scope rule."""
    match = re.search(r"(?:只|仅)(?:被)?(?:授予|分配)[^。；;，,]{1,130}角色", text)
    if match and re.search(r"[A-Za-z0-9-]+\.[A-Za-z0-9.-]+|域名|domain", match[0], re.I):
        return match[0]
    return None
