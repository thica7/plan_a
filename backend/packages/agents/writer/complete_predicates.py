"""Finite rejection checks for complete task predicates; never a support verdict."""

import re

DELIVERY_POLICY = "complete-predicates-v1"


def checked_delivery_policy(payload):
    policy = payload.get("delivery_policy")
    if policy is not None and (type(policy) is not str or policy != DELIVERY_POLICY):
        raise ValueError("Unknown complete-predicate delivery policy")
    return policy


def authority_question(text):
    return bool(
        re.search(r"谁|\bwho\b|\bwhich\s+roles?\b", text, re.I)
        and re.search(
            r"改为|设置为|(?:更改|修改|变更).*(?:身份|状态|角色|权限)"
            r"|\b(?:change|modify|set)\b",
            text,
            re.I,
        )
    )


def _roles(text):
    aliases = {
        "工作区": "workspace",
        "看板": "board",
        "项目": "project",
        "组织": "organization",
        "团队": "team",
        "管理员": "admin",
        "所有者": "owner",
        "管理者": "manager",
    }
    for source, target in aliases.items():
        text = text.replace(source, " " + target + " ")
    text = re.sub(r"\b(admin|owner|manager)s\b", r"\1", text, flags=re.I)
    return tuple(
        sorted(
            re.sub(r"\s+", " ", role).strip().casefold()
            for role in re.split(r"\s+(?:and|or)\s+|[,，、]|和|及|与", text)
            if role.strip()
        )
    )


def authority_source_rule(text, quotes):
    """A closed role list for changing one member status, never access execution.

    Require the complete source sentence, the same resource/member and target,
    and every explicitly authorized actor. Unknown grammar stays behind the
    ordinary operation gate and independent semantic review.
    """
    resource = r"board|workspace|project|organization|team"
    source_pattern = (
        r"\s*(?:Please note that\s+)?only\s+(?P<roles>[^.;!?\n]+?)\s+(?:can|may)\s+"
        r"(?:change|modify|set)\s+(?:a|an|the|current|existing)\s+"
        rf"(?P<resource>{resource})\s+member[’\']s\s+(?:status|role|permissions?)\s+"
        r"to\s+(?P<target>[A-Za-z][A-Za-z -]{0,40})[.!]?\s*"
    )
    claim_pattern = (
        r"\s*(?:只有|仅)\s*(?P<roles>[^。；;!?\n]+?)\s*(?:才能|可以|可|有权)\s*"
        r"(?:将|把)?\s*(?P<resource>看板|工作区|项目|组织|团队|board|workspace|project|organization|team)"
        r"\s*(?:上(?:的)?|的)?\s*(?:现有)?成员(?:的)?(?:权限(?:状态)?|身份|角色|状态)?"
        r"\s*(?:改为|设置为|变更为|更改为)\s*(?P<target>[A-Za-z][A-Za-z -]{0,40})[。.!]?\s*"
    )
    claim = re.fullmatch(claim_pattern, text, re.I)
    if not claim:
        # The unchanged complete English source is also a role-list assertion.
        claim = re.fullmatch(source_pattern, text, re.I)
    if not claim or len(quotes) != 1:
        return False
    source = re.fullmatch(source_pattern, quotes[0], re.I)
    return bool(
        source
        and _roles(claim["roles"]) == _roles(source["roles"])
        and _roles(claim["resource"]) == _roles(source["resource"])
        and claim["target"].strip().casefold() == source["target"].strip().casefold()
    )


def authority_task_claim_ids(payload, claims, plans):
    """Derive admission only from this server's task partition and selected originals."""
    if not checked_delivery_policy(payload):
        return set()
    tasks = {
        t["task_id"]: t
        for t in payload.get("generation_tasks", ())
        if t["focus"] == "source_rule" and authority_question(t["question_quote"])
    }
    ids = {
        cid
        for plan in plans
        for row in plan.get("task_results", ())
        if row["task_id"] in tasks
        for cid in row.get("claim_ids", ())
    }
    return {
        c.id
        for c in claims
        if c.id in ids
        and c.kind == "fact"
        and authority_source_rule(c.text, [s.quote for s in c.source_span_bindings])
    }


def unsupported_numeric_restriction(text, quotes):
    """A descriptive count cannot supply a same-unit maximum absent that modal."""
    count = r"(?:\d+|one|two|three|four|five|一|两|二|三|四|五)"
    units = {
        "people": r"(?:名|位|个)?\s*(?:users?|people|用户|人)",
        "collections": r"(?:个)?\s*(?:collections?|集合)",
        "vaults": r"(?:个)?\s*(?:vaults?|保险库)",
    }
    modal = (r"(?:\b(?:up\s+to|at\s+most|maximum(?:\s+of)?|only)\b"
             r"|最多|至多|上限为?|仅允许|仅支持|只能|不超过)")
    for unit in units.values():
        pattern = modal + r"[^,，。;；.!?\n]{0,25}?" + count + r"\s*(?:other\s+)?" + unit
        if re.search(pattern, text, re.I) and not any(re.search(pattern, q, re.I) for q in quotes):
            return True
    return False


def classification_non_entailment(binding, selected):
    """Reject a label-to-billing implication using explicit contrasting source cases."""
    question = binding.question_quote
    label = re.search(r"(?P<label>[A-Za-z][A-Za-z0-9_-]*)\s*标签", question)
    if (
        binding.conclusion != "no"
        or len(selected) != 1
        or label is None
        or not re.search(
            r"(?:仅|只)凭[^。；;？?]{0,100}标签[^。；;？?]{0,30}"
            r"(?:能否|是否|能|可否)(?:确定|判断)",
            question,
        )
        or not re.search(r"免费.*(?:计费|收费)|(?:计费|收费).*免费", question)
    ):
        return False
    claim = selected[0]
    text = claim["text"]
    name = re.escape(label["label"])
    if (
        claim.get("kind") != "fact"
        or not re.search("可计费", text)
        or not re.search("不可计费", text)
        or not re.search(
            r"(?:仅|只)凭\s*" + name + r"\s*标签(?:无法|不能)确定"
            r"[^。；;]{0,30}免费[^。；;]{0,15}(?:计费|收费)[。.!]?\s*$",
            text,
            re.I,
        )
    ):
        return False
    quotes = [span["quote"] for span in claim.get("source_span_bindings", ())]
    if len(quotes) != 1:
        return False
    source = quotes[0]
    # Match the complete assertion, not a span from one subject to a later
    # sentence's different subject. Every alternative belongs to this label.
    # Unknown conditions and quoted examples stay with ordinary review.
    word = (r'(?!(?:if|when|provided|unless|except|after|before|while|can|may|must|'
            r'not|unconfirmed|unverified)\b)[A-Za-z][A-Za-z-]*')
    category = rf'(?:(?:a|an)\s+)?(?:{word}\s+){{0,4}}(?:members?|guests?|users?|seats?)'
    prefix = (rf'(?:There are no limits to how many {name}s you can have on '
              rf'(?:a|an|the) (?:{word}\s+){{0,3}}{word},\s+and\s+)?')
    rule = re.fullmatch(
        prefix + rf'(?:a|an|the)\s+{name}\s+can\s+be\s+'
        rf'(?P<alternatives>{category}(?:\s*,?\s+or\s+{category})+)\s*[.!]?\s*',
        source.strip(), re.I)
    if not rule:
        return False
    alternatives = re.split(r'\s*,?\s+or\s+', rule['alternatives'], flags=re.I)
    return (any(re.match(r'(?:a|an)\s+billable\b', value, re.I) for value in alternatives)
            and any(re.match(r'(?:a|an)\s+non-billable\b', value, re.I)
                    for value in alternatives))
