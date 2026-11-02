"""Closed source relations for v2; proposals require independent whole-source review.

The source grammar constructs one relation, never a free-text verdict. Request
premises remain separately bound to one exact parent and are never evidence.
"""

import re
from copy import deepcopy

from packages.agents.writer.structured_conclusions import _parent, digest

_NAME = r"[A-Za-z][A-Za-z -]{0,60}?"
_DOMAIN = r"(?<![A-Za-z0-9_.-])[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?![A-Za-z0-9_.-])"
_OPERATIONS = {
    "download": ("download card attachments", "下载卡片附件"),
    "export": ("export the board", "导出看板"),
    "vote": ("vote on cards", "投票"),
}
_OBJECTS_ZH = {
    "board": "看板",
    "resource": "资源",
    "project": "项目",
    "vaults": "保险库",
    "containers": "容器",
    "collections": "集合",
}


def _source_text(relation, rule, original, language):
    if language.startswith("en"):
        if relation == "sales_scoped_quote":
            return (
                f"{rule['plan']} pricing is a quote tailored to organization needs and required "
                "capabilities obtained by discussing the environment with official sales."
            )
        if relation == "role_billing_input_gap":
            return (
                f"{rule['role']} is a board member permission rather than a membership type."
                if rule.get("nature")
                else f"{rule['role']} can be a " + " or ".join(rule["possible_memberships"]) + "."
            )
        return original
    if not language.startswith("zh"):
        return None
    role, obj = rule.get("role"), _OBJECTS_ZH.get(rule.get("object"), rule.get("object"))
    if relation == "access_cardinality":
        return f"{role} 账户同时只能访问由你选择的 {rule['maximum']} 个{obj}。"
    if relation in {"atomic_operation", "permission_condition", "modal_non_entailment"}:
        operation = rule["operation"]
        if rule.get("condition"):
            if rule["condition_kind"] == "sufficient":
                return f"本{obj}启用卡片投票时 {role} {obj}成员可投票。"
            return f"仅当本{obj}启用卡片投票时 {role} {obj}成员才可投票。"
        return f"{role} {obj}成员可{_OPERATIONS[operation][1]}。"
    if relation == "permission_scope":
        return f"{role} 角色包含特定域的边缘缓存清除权限。"
    if relation == "grant_scope":
        return "域范围角色作用于同一账户内的给定域。"
    if relation == "role_scope_level":
        return f"目前无法在 {rule['level']} 层级将用户设为 {role}。"
    if relation == "per_resource_configuration":
        return f"每个 {role} 按成员逐{obj}单独设置。"
    if relation == "role_billing_input_gap" and not rule.get("nature"):
        workspace = (
            rule["possible_memberships"][0].removeprefix("billable ").removesuffix(" member")
        )
        return f"{role} 可对应已列的可计费 {workspace} 成员或多看板访客身份。"
    if relation == "sales_scoped_quote":
        return (
            f"{rule['plan']} 的价格为按组织需求及所需能力确定且向官方销售说明环境后获取的定制报价。"
        )
    return original


def _role_in_request(role, parent):
    from packages.agents.writer.answer_resolution import _SUBJECT

    exact = re.search(r"(?<![A-Za-z])" + re.escape(role) + r"s?(?![A-Za-z])", parent, re.I)
    source_roles = {m.lastgroup for m in _SUBJECT.finditer(role)} - {"generic"}
    request_roles = {m.lastgroup for m in _SUBJECT.finditer(parent)} - {"generic"}
    return bool(exact or source_roles and source_roles <= request_roles)


def _source_relation(task, quote, parent):
    """Full source envelopes constrain every supported extraction below."""
    source = " ".join(quote.split())
    relation = task.get("semantic_target", {}).get("relation", task["focus"])
    focus = task["focus"].removeprefix("rule_")
    access = re.fullmatch(
        rf"(?P<role>{_NAME}) accounts are ideal for sharing information "
        r"with people on a limited basis\. "
        r"They don[’\x27]t have their own private vaults and only have access to "
        r"a (?P<maximum>single|one|two|three|\d+) "
        r"(?P<object>vault|container|collection)s?, which you choose\.",
        source,
        re.I,
    )
    if access and relation == "current_access" and _role_in_request(access["role"], parent):
        from packages.agents.writer.subquestion_premises import _NUMBERS, _counts

        counts = _counts(task["question_quote"])
        unit = access["object"].lower() + "s"
        values = counts.get(unit, [])
        maximum = (
            int(access["maximum"])
            if access["maximum"].isdigit()
            else _NUMBERS[access["maximum"].lower()]
        )
        if len(values) != 1 or not re.search(
            r"同时|\bsimultaneously\b|\bat (?:the same|a) time\b", task["question_quote"], re.I
        ):
            return None
        rule = dict(
            role=access["role"],
            object=unit,
            maximum=maximum,
            temporal_scope="simultaneous_current_access",
            selector="chosen_by_you",
            required=values[0],
        )
        return (
            "access_cardinality",
            f"{access['role']} accounts only have access to {maximum} {unit} chosen by you.",
            rule,
        )
    abilities = re.fullmatch(
        rf"(?P<role>{_NAME})s are (?P<scope>board|resource|project) members that are able to "
        r"view a (?P=scope) and the cards within the (?P=scope), download card attachments, "
        r"comment and vote on cards \(if that is enabled for the (?P=scope)\), "
        r"and export the (?P=scope)\.",
        source,
        re.I,
    )
    if abilities and _role_in_request(abilities["role"], parent):
        operation = (
            focus
            if focus in _OPERATIONS
            else "vote"
            if task["focus"] == "permission_not_obligation"
            else None
        )
        if operation:
            verb = _OPERATIONS[operation][0]
            condition = "enabled_for_resource" if operation == "vote" else None
            text = f"{abilities['role']} {abilities['scope']} members can {verb}"
            if condition:
                text += f" if that is enabled for the {abilities['scope']}"
            rule = dict(
                role=abilities["role"],
                object=abilities["scope"],
                operation=operation,
                condition=condition,
                condition_kind="configuration_gate" if condition else None,
            )
            if task["focus"] == "permission_not_obligation":
                return "modal_non_entailment", text + ".", rule
            return "permission_condition" if condition else "atomic_operation", text + ".", rule
    # Generic sufficient conditions never gain a necessary-condition interpretation.
    conditional = re.fullmatch(
        rf"(?P<role>{_NAME})s can vote on cards (?P<condition>only if|if) "
        r"card voting is enabled(?: for the (?P<scope>board|resource|project))?\.",
        source,
        re.I,
    )
    if conditional and focus == "vote" and _role_in_request(conditional["role"], parent):
        rule = dict(
            role=conditional["role"],
            object=conditional["scope"] or "board",
            operation="vote",
            condition="enabled_for_resource",
            condition_kind="necessary"
            if conditional["condition"].lower() == "only if"
            else "sufficient",
        )
        return "permission_condition", source, rule
    per_resource = re.fullmatch(
        rf"Because an? (?P<role>{_NAME}) is a (?P<scope>board|resource|project) member permission "
        r"it isn't currently possible to set a user as an? (?P=role) at the "
        rf"(?P<level>{_NAME}) level, "
        r"and each (?P=role) is set individually per member per (?P=scope)\.",
        source,
        re.I,
    )
    if per_resource and _role_in_request(per_resource["role"], parent):
        rule = dict(
            role=per_resource["role"],
            object=per_resource["scope"],
            level=per_resource["level"],
            temporal_scope="current",
        )
        if relation == "role_scope_level":
            return (
                "role_scope_level",
                f"Setting a user as {rule['role']} at {rule['level']} level "
                "is currently unavailable.",
                rule,
            )
        if relation == "resource_propagation":
            return (
                "per_resource_configuration",
                f"Each {rule['role']} is set individually per member per {rule['object']}.",
                rule,
            )
    permission = re.fullmatch(
        rf"\| (?P<role>{_NAME}) \| Grants access to (?P<operation>purge the edge cache) "
        r"for a specific (?P<scope>domain) and allows the reading of zone settings\. \|",
        source,
        re.I,
    )
    if permission and focus == "purge_cache" and _role_in_request(permission["role"], parent):
        rule = dict(
            role=permission["role"],
            operation="purge_cache",
            object="domain",
            scope="specific_domain",
        )
        return (
            "permission_scope",
            f"{rule['role']} grants access to purge the edge cache for a specific domain.",
            rule,
        )
    if (
        source == "Domain-scoped roles apply for a given domain within an account."
        and task["focus"] == "source_rule"
    ):
        from packages.agents.writer.task_predicates import explicit_scope_assignment

        if explicit_scope_assignment(task["question_quote"]):
            return "grant_scope", source, dict(object="domain", scope="given_domain_within_account")
    billing_roles = re.fullmatch(
        rf"There are no limits to how many (?P<role>{_NAME})s you can have on a board, "
        r"and an? (?P=role) can be a billable (?P<workspace>[A-Za-z]+) member, "
        r"or multi-board guest",
        source,
        re.I,
    )
    membership_distinction = re.fullmatch(
        rf"Because an? (?P<role>{_NAME}) is a board member permission and not a membership "
        r"type\s*, a board admin in a (?P<plan>[A-Za-z]+) Workspace can set both Workspace "
        r"members and guests as an? (?P=role) on a board\.",
        source,
        re.I,
    )
    if (
        membership_distinction
        and relation == "billability"
        and _role_in_request(membership_distinction["role"], parent)
    ):
        rule = dict(
            role=membership_distinction["role"],
            object="board_permission",
            nature="permission_not_membership_type",
        )
        return ("role_billing_input_gap", f"{rule['role']} 是看板成员权限而非成员身份类型。", rule)
    if (
        billing_roles
        and relation == "billability"
        and _role_in_request(billing_roles["role"], parent)
    ):
        rule = dict(
            role=billing_roles["role"],
            object="board_permission",
            possible_memberships=[
                f"billable {billing_roles['workspace']} member",
                "multi-board guest",
            ],
            exhaustive=False,
        )
        return (
            "role_billing_input_gap",
            f"{rule['role']} 可对应已列的 {rule['possible_memberships'][0]} "
            "/ multi-board guest 等身份。",
            rule,
        )
    from packages.research.extraction.billing_rules import sales_quote_scope

    plan = sales_quote_scope(source)
    if plan and task["focus"] == "billing_inputs":
        if re.search(r"(?<![A-Za-z])" + re.escape(plan) + r"(?![A-Za-z])", parent, re.I):
            rule = dict(
                plan=plan,
                pricing_nature="organization_and_capability_scoped_sales_quote",
                determinants=["organization_needs", "required_capabilities"],
                provider="official_sales",
                workflow="discuss_environment_and_receive_quote",
            )
            return (
                "sales_scoped_quote",
                f"{plan} 的价格为按组织需求及所需能力确定的官方销售报价。",
                rule,
            )
    return None


def build_candidates(payload):
    (task,) = payload["generation_tasks"]
    (selected,) = payload["task_support_selections"]
    parent = _parent(payload, task)
    if (
        parent is None
        or selected.get("binding_kind") != "span"
        or not 1 <= len(selected["supports"]) <= 2
    ):
        return []
    if selected["support_refs"] != [support.get("support_ref") for support in selected["supports"]]:
        return []
    proposals, selected_rows = [], []
    for support in selected["supports"]:
        quote = support.get("quote")
        rows = [
            r
            for r in payload["evidence_view"]["facts"]
            if any(
                s.get("support_ref") == support["support_ref"] and s.get("quote") == quote
                for s in r.get("source_span_candidates", ())
            )
        ]
        if len(rows) != 1 or not quote:
            return []
        selected_rows.append(rows[0])
        relation = _source_relation(task, quote, parent["text"])
        if relation is not None:
            proposals.append((support, relation))
    if len(proposals) != 1:
        return []
    support, relation = proposals[0]
    name, text, rule = relation
    language = payload.get("conclusion_language", "zh-CN")
    text = _source_text(name, rule, text, language)
    if text is None:
        return []
    if len(selected["supports"]) == 2:
        # The role rule already states the complete specific-domain scope.
        # A co-selected generic scope restatement contributes no extra premise,
        # claim or source authority. Every other multi-rule pairing stays closed.
        redundant = [s for s in selected["supports"] if s is not support]
        if (
            name != "permission_scope"
            or len(redundant) != 1
            or redundant[0]["quote"]
            != "Domain-scoped roles apply for a given domain within an account."
        ):
            return []
    body = dict(
        question_id=task["question_id"],
        task_id=task["task_id"],
        relation=name,
        language=payload.get("conclusion_language", "zh-CN"),
        source_fact_text=text,
        support_refs=[support["support_ref"]],
        rule=rule,
        source_binding_sha256=digest(dict(selected=selected, facts=selected_rows)),
        request_premises=dict(
            purpose="request_only_not_evidence", parent=parent, task_quote=task["question_quote"]
        ),
        consumption_id=payload["consumption_id"],
        snapshot_id=payload["snapshot_id"],
    )
    return [dict(candidate_ref="conclusion-candidate-" + digest(body)[:24], **body)]


def selected_source(candidate):
    """The source REVIEW checks this entire single relation and its complete quote."""
    result = {
        k: deepcopy(candidate[k])
        for k in (
            "candidate_ref",
            "relation",
            "source_fact_text",
            "support_refs",
            "rule",
            "source_binding_sha256",
        )
    }
    for name in ("required", "actual_membership_known", "input_sufficient", "missing_input"):
        result["rule"].pop(name, None)
    return result


def typed_atom_matches(payload, atom):
    from packages.agents.writer.structured_conclusions import (
        CONTRACT_V2,
        build_candidates,
        checked_contract,
    )

    if checked_contract(payload) != CONTRACT_V2:
        return False
    expected = build_candidates(payload)
    return payload.get("conclusion_candidates") == expected and any(
        atom
        == dict(
            task_id=c["task_id"],
            kind="fact",
            text=c["source_fact_text"],
            support_refs=c["support_refs"],
        )
        for c in expected
    )


def source_review_matches(payload, claims):
    from packages.agents.writer.structured_conclusions import CONTRACT_V2

    selected = payload.get("typed_source_relation")
    return (
        payload.get("structured_conclusions_contract") == CONTRACT_V2
        and isinstance(selected, dict)
        and len(claims) == 1
        and claims[0].text == selected.get("source_fact_text")
        and payload.get("clause_support_refs") == selected.get("support_refs")
    )


def _configuration_state(parent, resource, role):
    """One literal resource configuration clause, with no cross-resource borrowing."""
    clauses = re.split(r"[，,。；;\n]", parent)
    prefix = r"(?:看板\s*|board\s*)?" + re.escape(resource) + r"\s*"
    negative = [
        c
        for c in clauses
        if re.fullmatch(
            prefix + r"(?:(?:未启用|已禁用)(?:卡片)?投票|voting is disabled)", c.strip(), re.I
        )
    ]
    positive = [
        c
        for c in clauses
        if re.fullmatch(
            prefix
            + r"(?:已启用(?:卡片)?投票|已启用且允许该\s*"
            + re.escape(role)
            + r"\s*投票|voting is enabled)",
            c.strip(),
            re.I,
        )
    ]
    return False if negative and not positive else True if positive and not negative else None


def _request_fragment(task):
    fragment = next(
        (s.strip() for s in reversed(re.split(r"[。！？!?]", task["question_quote"])) if s.strip()),
        "",
    )
    return re.split(r"[；;]", fragment)[-1].rsplit("：", 1)[-1].rsplit(":", 1)[-1].strip()


def _task_resource(task):
    if task.get("resource"):
        return task["resource"]
    names = set(
        re.findall(r"(?<![A-Za-z0-9_])[A-Z](?:\d{1,3})?(?![A-Za-z0-9_])", _request_fragment(task))
    )
    return next(iter(names)) if len(names) == 1 else None


def _actor(subject, role):
    from packages.agents.writer.answer_resolution import _SUBJECT

    subject = subject.rsplit("：", 1)[-1].rsplit(":", 1)[-1].strip()
    marks = list(_SUBJECT.finditer(subject))
    if marks and marks[0].start() == 0:
        mark = marks[0]
        if mark.lastgroup != "generic" and not _role_in_request(role, mark.group()):
            return None
        name = subject[mark.end() :].strip()
        return name.casefold() if name else "role:" + role.casefold()
    match = re.match(re.escape(role) + r"s?(?![A-Za-z])", subject, re.I)
    if match:
        return subject[match.end() :].strip().casefold() or "role:" + role.casefold()
    return (
        subject.casefold() if re.fullmatch(r"[A-Za-z0-9_\u3400-\u9fff -]{1,40}", subject) else None
    )


def _requested_actor(task, parent, subjects, role):
    from packages.agents.writer.answer_resolution import _SUBJECT

    actors = {_actor(s, role) for s in subjects} - {None}
    asked = _request_fragment(task)
    modal = re.search(r"能否|是否|可否|可以|能够|能|\b(?:can|could|may|must)\b", asked, re.I)
    if modal is None:
        return None
    subject = asked[: modal.start()].rsplit("：", 1)[-1].rsplit(":", 1)[-1].strip()
    subject = re.sub(r"^(?:分别|逐项)?判断[:：]?", "", subject).strip()
    if subject in {"仅凭该权限标签", "只凭该权限标签", "仅凭该角色", "只凭该标签"}:
        referred = re.search(r"(?:确定|判断|核实)(他|她|该用户)", asked[modal.end() :])
        subject = referred[1] if referred else subject
    inverted = re.match(r"\s*(?:can|could|may)\s+([A-Za-z][A-Za-z0-9_-]*)", asked, re.I)
    if inverted:
        subject = inverted[1]
    if subject in {"", "他", "她", "该用户", "该访客", "he", "she", "they"}:
        # Even another explicitly named role in a sibling request makes this
        # pronoun unsafe. No nearest-name or product-specific coreference.
        for match in _SUBJECT.finditer(parent):
            if match.group() == "成员" and parent[match.end() :].startswith("身份"):
                owner = re.search(
                    r"(?:^|[。；;，,：:])\s*([^，,。；;\n]{1,50}?)实际$",
                    parent[: match.start()],
                )
                if owner:
                    actor = _actor(owner[1], role)
                    if actor is None:
                        return None
                    actors.add(actor)
                    continue
            named = re.match(
                r"\s*(?!已|未|尚|没|不|被|在|能|可|是)"
                r"([A-Za-z\u3400-\u9fff][A-Za-z0-9_\u3400-\u9fff-]{0,30}?)"
                r"(?=已|未|尚|没|不|能|可以|[。；;，,]|\s+(?:can|has|is)\b)",
                parent[match.end() :],
                re.I,
            )
            if named:
                actors.add(named[1].casefold())
        for match in re.finditer(
            r"(?:^|[。；;，,：:])\s*"
            r"([A-Za-z0-9_\u3400-\u9fff-]{1,30})\s*"
            r"(?:在看板|在board\b|已分别被设为|是\s*[A-Za-z])",
            parent,
        ):
            actors.add(match[1].casefold())
        return next(iter(actors)) if len(actors) == 1 else None
    actor = _actor(subject, role)
    return actor if actor in actors else None


def _role_assignments(parent, role):
    label = r"[A-Z](?:\d{1,3})?"
    names = rf"(?P<names>{label}(?:\s*(?:和|与|、|and)\s*{label})?)"
    assignments = []
    for clause in re.split(r"[，,。；;\n]", parent):
        declaration = re.fullmatch(
            r"(?P<actor>[^，,。；;\n]{1,100}?)(?:在(?:看板\s*|board\s*)?"
            + names
            + r"\s*(?:都是|是)|已分别被设为(?:看板\s*|board\s*)?"
            + names.replace("?P<names>", "?P<assigned>")
            + r"\s*的)\s*"
            + re.escape(role),
            clause.strip(),
            re.I,
        )
        if declaration and not re.search(r"是否|可能|未知|未|不", declaration["actor"]):
            assignments.append(
                (
                    declaration["actor"],
                    re.findall(label, declaration["names"] or declaration["assigned"]),
                )
            )
        change = re.fullmatch(
            r"(?P<operator>[^，,。；;\n]{1,60}?)把看板\s*(?P<resource>[A-Z](?:\d{1,3})?)"
            r"\s*上(?:现有)?(?:协作者|成员|用户)\s*"
            r"(?P<recipient>[A-Za-z0-9_\u3400-\u9fff-]{1,40})\s*的权限改成了\s*" + re.escape(role),
            clause.strip(),
            re.I,
        )
        if change and not re.search(
            r"是否|可能|未知|未|不|没|如果|若|计划|准备", change["operator"]
        ):
            assignments.append((change["recipient"], [change["resource"].upper()]))
    return assignments


def _premise_states(parent, role):
    """Conservative actor-owned states; conflicts never certify current permission."""
    states = dict(roles={}, other_roles={}, memberships={}, grants=[])

    def add(kind, subject, value, resource=None):
        actor = _actor(subject, role) if subject is not None else None
        if actor is not None:
            key = (actor, resource) if kind == "roles" else actor
            states[kind].setdefault(key, set()).add(value)
        return actor

    for subject, resources in _role_assignments(parent, role):
        for resource in resources:
            add("roles", subject, "positive", resource)
    carrier = None
    for original in re.split(r"[，,。；;\n]", parent):
        clause = original.strip().rsplit("：", 1)[-1].rsplit(":", 1)[-1].strip()
        grant = re.fullmatch(
            r"(?P<actor>[^，,。；;\n]{1,100}?)(?:只|仅)(?:被)?(?:授予|分配)\s*"
            r"(?P<domain>[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)\s*的\s*" + re.escape(role) + r"\s*角色",
            clause,
            re.I,
        )
        if grant and not re.search(r"如果|若|不|无法|可能|是否|未知", grant["actor"]):
            carrier = add("roles", grant["actor"], "positive", grant["domain"].lower())
            states["grants"].append((grant["actor"], grant["domain"].lower()))
            continue
        other = re.fullmatch(
            r"(?P<actor>[^，,。；;\n]{0,50}?)(?P<state>没有(?:任何)?其他角色|无其他角色|"
            r"的其他角色(?:未知|未确认)|(?:还有|另有|有)其他角色)",
            clause,
            re.I,
        )
        if other:
            subject = other["actor"].strip() or carrier
            value = (
                "none"
                if other["state"].startswith(("没有", "无"))
                else "unknown"
                if "未知" in other["state"] or "未确认" in other["state"]
                else "some"
            )
            carrier = add("other_roles", subject, value)
            continue
        negative = re.fullmatch(
            r"(?:当前|目前|现在)?(?P<actor>[^，,。；;\n]{1,50}?)(?:当前|目前|现在)?在"
            r"\s*(?:看板\s*)?(?P<resource>[A-Z](?:\d{1,3})?)\s*(?:上)?\s*"
            r"(?:不是|不再是)\s*" + re.escape(role),
            clause,
            re.I,
        )
        unknown = re.fullmatch(
            r"(?P<actor>[^，,。；;\n]{1,50}?)(?:当前|目前|现在)?在\s*(?:看板\s*)?"
            r"(?P<resource>[A-Z](?:\d{1,3})?)\s*的\s*"
            + re.escape(role)
            + r"\s*角色(?:未知|未确认)",
            clause,
            re.I,
        )
        revoked = re.fullmatch(
            r"(?P<operator>[^，,。；;\n]{0,60}?)(?:已取消|取消了)\s*"
            r"(?P<actor>[^，,。；;\n]{1,50}?)在\s*(?:看板\s*)?"
            r"(?P<resource>[A-Z](?:\d{1,3})?)\s*的\s*" + re.escape(role) + r"\s*角色",
            clause,
            re.I,
        )
        if revoked and re.search(r"未|没|不|是否|可能|如果|若|准备|计划", revoked["operator"]):
            revoked = None
        restriction = negative or unknown or revoked
        if restriction:
            add(
                "roles",
                restriction["actor"],
                "unknown" if unknown else "negative",
                restriction["resource"].upper(),
            )
            carrier = None
            continue
        membership = re.fullmatch(
            r"(?P<actor>[^，,。；;\n]{1,50}?)(?:实际成员身份(?:为|是)\s*"
            r"(?P<identity>[^，,。；;\n]{1,80})"
            r"|实际为\s*(?:billable\s+[A-Za-z ]+member|multi-board guest))",
            clause,
            re.I,
        )
        if membership and not re.search(
            r"未知|未确认|\bunknown\b", membership["identity"] or "", re.I
        ):
            carrier = add("memberships", membership["actor"], "provided")
            continue
        assigned = _role_assignments(clause, role)
        if assigned:
            owners = {_actor(subject, role) for subject, _ in assigned} - {None}
            carrier = next(iter(owners)) if len(owners) == 1 else None
            continue
        resource_declaration = re.fullmatch(
            r"(?P<actor>[^，,。；;\n]{1,50}?)在\s*(?:看板\s*)?"
            r"(?P<resource>[A-Z](?:\d{1,3})?)\s*(?:上)?\s*是\s*"
            rf"(?P<role>{_NAME})",
            clause,
            re.I,
        )
        if resource_declaration:
            carrier = _actor(resource_declaration["actor"], role)
            if resource_declaration["role"].strip().casefold() == role.casefold():
                add(
                    "roles",
                    resource_declaration["actor"],
                    "positive",
                    resource_declaration["resource"].upper(),
                )
            else:
                add("other_roles", resource_declaration["actor"], "some")
            continue
        declaration = re.fullmatch(
            r"(?P<actor>[^，,。；;\n]{1,50}?)\s*是\s*"
            rf"(?P<role>{_NAME})",
            clause,
            re.I,
        )
        if declaration:
            carrier = _actor(declaration["actor"], role)
            if declaration["role"].strip().casefold() == role.casefold():
                add("roles", declaration["actor"], "positive")
            else:
                add("other_roles", declaration["actor"], "some")
            continue
        carrier = None
    return states


def _role_current(states, actor, resource):
    values = states["roles"].get((actor, resource), set()) | states["roles"].get(
        (actor, None), set()
    )
    return values == {"positive"}


def _role_resources(parent, role, task):
    assignments = _role_assignments(parent, role)
    actor = _requested_actor(task, parent, [s for s, _ in assignments], role)
    states = _premise_states(parent, role)
    return {
        resource
        for subject, resources in assignments
        if actor is not None and _actor(subject, role) == actor
        for resource in resources
        if _role_current(states, actor, resource)
    }


def _membership_label_binding(parent, role, task):
    """A resource/role label refers to its unique recipient, never its operator."""
    asked = _request_fragment(task).rsplit("，", 1)[-1].rsplit(",", 1)[-1].strip()
    references = [
        match
        for match in re.finditer(
            rf"(?:只|仅)凭\s*(?:看板\s*)?(?P<resource>[A-Z](?:\d{{1,3}})?)\s*上的\s*"
            rf"(?P<role>{_NAME})\s*标签[，,]\s*(?P<question>[^。！？!?]+)",
            parent,
            re.I,
        )
        if match["question"].strip() == asked
    ]
    if not references:
        return False, None
    if len(references) != 1 or references[0]["role"].strip().casefold() != role.casefold():
        return True, None
    reference = references[0]
    query = re.fullmatch(
        r"(?:能否|是否)(?:确定|判断|核实)\s*(?P<who>[^，,。！？!?]{1,40}?)"
        r"\s*一定免费或一定计费",
        asked,
    )
    if query is None:
        return True, None
    resource = reference["resource"].upper()
    states = _premise_states(parent, role)
    actors = {
        _actor(subject, role)
        for subject, resources in _role_assignments(parent, role)
        if resource in resources and _role_current(states, _actor(subject, role), resource)
    } - {None}
    who = query["who"].strip()
    if who not in {"他", "她", "该用户"}:
        actor = _actor(who, role)
        actors = {actor} if actor in actors else set()
    if len(actors) != 1:
        return True, None
    return True, dict(
        kind="application",
        actor=next(iter(actors)),
        resource=resource,
        role=role,
        premise="given_resource_role_recipient",
    )


def _given_lifecycle(parent, task, role):
    clauses = re.split(r"[，,。；;\n]", parent)
    subjects = [
        match[1]
        for c in clauses
        if (
            match := re.fullmatch(
                r"([^，,。；;\n]{1,100}?)已接受邀请(?:并|且)(?:已|被)?确认", c.strip()
            )
        )
        and not re.search(r"如果|若|未|不|可能|是否|尚", c)
        and _role_in_request(role, match[1])
    ]
    actor = _requested_actor(task, parent, subjects, role) if subjects else None
    return actor is not None and _access_role_current(parent, actor, role)


def _access_role_current(parent, actor, role):
    """A past invitation cannot override this actor's explicit current identity."""
    from packages.agents.writer.answer_resolution import _SUBJECT

    for clause in re.split(r"[，,。；;\n]", parent):
        match = re.fullmatch(
            r"(?:后来)?([^，,。；;\n]{1,80}?)(?:当前|目前|现在)?"
            r"(?P<change>不再是|不是|已升级为|已转为|已成为)"
            r"(?P<identity>[^，,。；;\n]{1,60})", clause.strip(),
        )
        if not match:
            continue
        subject = match[1].rsplit("：", 1)[-1].rsplit(":", 1)[-1].strip()
        owner = actor if subject in {"他", "她", "该用户", "该访客"} else _actor(subject, role)
        if owner != actor:
            continue
        identity = match['identity'].removesuffix('身份').removesuffix('角色').strip()
        same_role = _role_in_request(role, identity)
        if match['change'] in {'不再是', '不是'}:
            if same_role:
                return False
        elif not same_role and _SUBJECT.search(identity):
            return False
    return True


def source_application_allowed(candidate, task):
    """A reviewed role rule is not primary application support for another identity."""
    return (candidate['relation'] != 'access_cardinality'
            or _application_binding(candidate, task) is not None)


def _sole_domain_grant(parent, role, task):
    states = _premise_states(parent, role)
    grants = states["grants"]
    actor = _requested_actor(task, parent, [s for s, _ in grants], role)
    return (
        grants[0][1]
        if len(grants) == 1
        and actor == _actor(grants[0][0], role)
        and states["other_roles"].get(actor) == {"none"}
        and _role_current(states, actor, grants[0][1])
        else None
    )


def _application_binding(candidate, task):
    """One gate separates role rules from actor-owned applications in every relation."""
    relation, role = candidate["relation"], candidate["rule"].get("role")
    protected = {
        "access_cardinality",
        "permission_scope",
        "atomic_operation",
        "permission_condition",
        "role_billing_input_gap",
    }
    if relation not in protected:
        return {"kind": "rule"}
    asked = _request_fragment(task)
    generic = re.match(
        re.escape(role) + r"s?\s*(?:权限标签|权限|标签)?\s*"
        r"(?:能否|能|可以|是否|can\b)",
        asked,
        re.I,
    )
    if task["focus"].startswith("rule_") or generic and relation != "access_cardinality":
        return {"kind": "rule"}
    parent = candidate["request_premises"]["parent"]["text"]
    if relation == "access_cardinality":
        return (
            {"kind": "application", "given_lifecycle": True}
            if _given_lifecycle(parent, task, role)
            else None
        )
    if relation == "permission_scope":
        domain = _sole_domain_grant(parent, role, task)
        return {"kind": "application", "granted_domain": domain} if domain else None
    if relation in {"atomic_operation", "permission_condition"}:
        resource = _task_resource(task)
        return (
            {"kind": "application", "resource": resource}
            if resource and resource in _role_resources(parent, role, task)
            else None
        )
    handled, label_binding = _membership_label_binding(parent, role, task)
    if handled:
        return label_binding
    subjects = [subject for subject, _ in _role_assignments(parent, role)]
    for clause in re.split(r"[，,。；;\n]", parent):
        match = re.fullmatch(
            r"([^，,。；;\n]{1,50}?)\s*是\s*" + re.escape(role), clause.strip(), re.I
        )
        if match:
            subjects.append(match[1])
    actor = _requested_actor(task, parent, subjects, role)
    states = _premise_states(parent, role)
    current = actor and any(
        _role_current(states, actor, resource)
        for owner, resource in states["roles"]
        if owner == actor
    )
    return {"kind": "application", "actor": actor} if current else None


def derive(candidate, task):
    """Return a bounded task cell; nothing here grants source authority."""
    relation, rule = candidate["relation"], candidate["rule"]
    binding = _application_binding(candidate, task)
    if binding is None:
        return None
    parent = candidate["request_premises"]["parent"]["text"]
    obj = _OBJECTS_ZH.get(rule.get("object"), rule.get("object"))
    outcome, observation, derived, missing = None, None, True, []
    if (
        relation == "access_cardinality"
        and rule["required"] > rule["maximum"]
        and binding.get("given_lifecycle")
    ):
        outcome = "no"
        observation = (
            f"在已接受邀请且已确认的题设下同时访问 {rule['required']} 个{obj} "
            f"超过该角色 {rule['maximum']} 个的当前访问上限。此结论不限制移出后改换访问对象。"
        )
    elif relation == "atomic_operation":
        outcome, observation, derived = "yes", candidate["source_fact_text"], False
    elif relation == "permission_condition":
        if not task.get("resource"):
            outcome, observation, derived = "rule", candidate["source_fact_text"], False
        else:
            state = _configuration_state(parent, task["resource"], rule["role"])
            if state is True and rule["condition_kind"] in {"configuration_gate", "sufficient"}:
                outcome = "yes"
                observation = (
                    f"在题设 {task['resource']} 已启用投票且该用户具有 "
                    f"{rule['role']} 角色的条件下可投票。"
                )
            elif state is False and rule["condition_kind"] in {"configuration_gate", "necessary"}:
                outcome = "no"
                observation = f"题设 {task['resource']} 已禁用投票时该项投票许可不生效。"
    elif relation == "modal_non_entailment":
        outcome = "no"
        observation = f"这条 {rule['role']} 投票许可本身不构成必须投票的依据。"
    elif relation == "role_scope_level":
        outcome, observation, derived = "no", candidate["source_fact_text"], False
    elif relation == "grant_scope":
        outcome, observation, derived = "rule", candidate["source_fact_text"], False
    elif relation == "per_resource_configuration":
        resources = tuple(
            dict.fromkeys(
                re.findall(
                    r"(?<![A-Za-z0-9_])[A-Z](?:\d{1,3})?(?![A-Za-z0-9_])", task["question_quote"]
                )
            )
        )
        if len(resources) == 2:
            outcome = "no"
            observation = (
                f"根据逐成员逐{obj}配置规则对 {resources[0]} 的角色设置不决定 "
                f"{resources[1]} 的角色。{resources[1]} 的实际角色仍须单独核实。"
            )
    elif relation == "permission_scope":
        domains = tuple(dict.fromkeys(d.lower() for d in re.findall(_DOMAIN, parent)))
        target = task.get("resource", "").lower()
        # Only an exact two-domain request, an explicit sole grant, and no other
        # roles can close the scenario. Related domains remain unresolved.
        granted = binding.get("granted_domain")
        if len(domains) == 2 and granted and target in domains:
            unrelated = (
                target != granted
                and not target.endswith("." + granted)
                and not granted.endswith("." + target)
                and target.rsplit(".", 2)[-2:] != granted.rsplit(".", 2)[-2:]
            )
            if unrelated:
                outcome = "no"
                observation = (
                    f"在仅对 {granted} 授予 {rule['role']} 且无其他角色的题设内该授权不提供 "
                    f"{target} 的清缓存权限。此判断限于已给授权。"
                )
    elif relation == "sales_scoped_quote":
        outcome = "limitation"
        missing = ["official_scoped_quote"]
        observation = (
            f"{rule['plan']} 采用按组织需求及所需能力确定的销售报价；"
            "下一步是联系官方销售说明环境并取得报价。"
            "当前无法核实所问精确含税总额。报价时保留题设已给条件。"
        )
    elif relation == "role_billing_input_gap":
        actor = binding.get("actor")
        if actor and _premise_states(parent, rule["role"])["memberships"].get(actor):
            return None
        outcome, missing = "limitation", ["actual_membership_type"]
        observation = (
            f"仅凭 {rule['role']} 权限标签无法核实实际收费身份。"
            "需另行核实实际成员身份及适用计费规则；这里不推定免费或具体收费。"
        )
    if outcome is None:
        return None
    if derived and candidate["language"].startswith("en"):
        if relation == "access_cardinality":
            observation = (
                f"Under the given accepted and confirmed lifecycle {rule['required']} "
                f"simultaneous {rule['object']} exceed the verified maximum "
                f"{rule['maximum']}. This does not rule out changing objects later."
            )
        elif relation == "permission_condition":
            observation = (
                f"Under the given {task['resource']} configuration and the bound "
                f"{rule['role']} actor the voting permission is "
                + ("available." if outcome == "yes" else "not active.")
            )
        elif relation == "modal_non_entailment":
            observation = "This permission alone does not establish a duty to vote."
        elif relation == "per_resource_configuration":
            observation = (
                f"The individual {rule['object']} configuration for {resources[0]} "
                f"does not determine {resources[1]}; its actual role remains unverified."
            )
        elif relation == "permission_scope":
            observation = (
                f"Under the sole {rule['role']} grant for {granted} and no other roles "
                f"that grant does not authorize cache purging for {target}."
            )
        elif relation == "sales_scoped_quote":
            observation = (
                f"{rule['plan']} requires an organization/capability-scoped sales quote. "
                "Discuss the environment with official sales and retain given inputs. "
                "The requested exact tax-inclusive total remains unverified."
            )
        elif relation == "role_billing_input_gap":
            observation = (
                f"The {rule['role']} label alone does not establish actual billing "
                "status. Verify membership and applicable billing rules separately."
            )
    return dict(
        task_id=task["task_id"],
        operation=rule.get("operation"),
        resource=_task_resource(task),
        question_quote=task["question_quote"],
        outcome=outcome,
        observation=observation,
        task_sha256=digest(task),
        request_binding=binding,
        derived=derived,
        missing_fields=missing,
        support_refs=candidate["support_refs"],
    )


def task_label(task):
    """Internal display projection; the original quote remains in the bound cell."""
    focus = task["focus"].removeprefix("rule_")
    if focus in _OPERATIONS:
        label = _OPERATIONS[focus][1]
        resource = _task_resource(task)
        return label + (f"（{resource}）" if resource else "")
    return task["question_quote"]


def merge_answers(context, questions, entries, generated, current, snapshot_id):
    """Merge per task once; one typed source cannot erase an unknown sibling."""
    from packages.agents.writer.atomic_question_projection import generation_tasks
    from packages.agents.writer.task_answer_outcomes import aggregate, obligation_tasks

    results = dict(current)
    for question in questions:
        qid = question["question_id"]
        local_entries = [e for e in entries if e["question_id"] == qid and "task_cell" in e]
        if not local_entries:
            continue
        tasks = obligation_tasks(
            generation_tasks(question, f"{context.competitor}/{context.dimension}"), context.compact
        )
        accepted = deepcopy(context.compact.get("task_answer_results", {}))
        for entry in local_entries:
            cell = entry["task_cell"]
            if cell["outcome"] != "limitation":
                accepted[cell["task_id"]] = dict(
                    task_id=cell["task_id"],
                    outcome=cell["outcome"],
                    claim_ids=[entry["claim_id"]],
                    support_refs=cell["support_refs"],
                    missing_fields=[],
                    reason="Authenticated source relation with bounded request premises.",
                )
        answer = aggregate([question], tasks, accepted, list(generated.values()))[qid]
        requested = [t for t in tasks if t.get("obligation_role") != "support_dependency"]
        bindings = [
            b.model_copy(update={"question_quote": task_label(t)})
            for t, b in zip(requested, answer.subquestion_bindings, strict=False)
        ]
        ids = list(answer.claim_ids)
        for e in local_entries:
            if e["claim_id"] not in ids:
                ids.append(e["claim_id"])
        observations = [
            e["task_cell"]["observation"] for e in local_entries if e["task_cell"]["derived"]
        ]
        body = "\n".join([*(generated[c].text for c in ids), *observations])
        missing = sorted({m for e in local_entries for m in e["task_cell"]["missing_fields"]})
        limitation_tasks = {
            e["task_id"] for e in local_entries if e["task_cell"]["outcome"] == "limitation"
        }
        complete_delivery = all(
            t["task_id"] in limitation_tasks
            or accepted.get(t["task_id"], {}).get("outcome") in {"yes", "no", "rule"}
            for t in requested
        )
        for entry in local_entries:
            entry["task_cell"]["limitation_delivery_complete"] = complete_delivery
        updates = dict(
            answer=body,
            claim_ids=ids,
            subquestion_bindings=bindings,
            evidence_spans=[dict(claim_id=c, quote=generated[c].text) for c in ids],
            basis_snapshot_id=snapshot_id,
        )
        if missing:
            updates.update(
                status="partial",
                conclusion="unknown" if answer.conclusion == "unknown" else "depends",
                resolution="insufficient",
                missing_fields=missing,
            )
        # Revalidate the public bounds rather than silently truncating source facts.
        from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage

        results[qid] = ReportAnswerCoverage(**(answer.model_dump(mode="json") | updates))
    return results
