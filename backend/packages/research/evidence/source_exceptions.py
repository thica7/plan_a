"""Finite, source-local exception receipts; unknown scope never grants support.

These predicates detect omission, not general textual entailment. Copy retention,
ongoing synchronization and link access remain different outcomes. No product or
question supplies a source predicate, role or exception.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

MAX_RULE_CHARS = 1600
_START = re.compile(
    r"\b(?:if|when|unless|except(?:\s+if)?|for\s+[^:\n]{1,160}:)|除非|除外|如果", re.I
)
_AUTH = re.compile(r"\b(?:SSO|single sign.on|trusted devices?)\b|单点登录|受信任设备", re.I)
_ACCESS = re.compile(r"\baccess\b|\b(?:log|sign)(?:ged|ned)?[ -]?in\b|访问|登录|登入", re.I)
_COPY = re.compile(r"\bkeep\s+(?:a\s+)?copy\b|保留.{0,5}副本", re.I)
_NO_SYNC = re.compile(r"\b(?:no longer|not|stop\w*)\s+sync\w*\b|停止同步|不再同步", re.I)
_RECOVERY = re.compile(r"\baccount recovery\b|账户恢复|账号恢复", re.I)
_LOGIN_BEFORE = re.compile(
    r"\b(?:log|sign)\s+in\b[^.!?\n]{0,160}\bbefore\b|(?:移除|删除)前[^。；]{0,50}登录|"
    r"登录[^。；]{0,50}(?:移除|删除)前",
    re.I,
)
_CLARIFY = re.compile(
    r"\b(?:please|must|need to)\s+(?:specify|clarify|confirm)|"
    r"\b(?:which|what|whether)\b[^.!。]{0,200}[?？]|"
    r"请(?:说明|确认|提供|澄清)|(?:哪个|哪种|什么|是否)[^。！]{0,100}[？?]",
    re.I,
)


def complete_rule_blocks(text, *, max_chars=MAX_RULE_CHARS):
    """Keep a contiguous conditional paragraph/list, including its explanations.

    Headings and blank paragraph boundaries stop the block. A colon without a
    following branch is incomplete, and an oversized block is never truncated.
    """
    lines = text.splitlines(keepends=True)
    blocks, offset = [], 0
    for index, line in enumerate(lines):
        start = offset
        offset += len(line)
        if not _START.search(line):
            continue
        end = offset
        if line.rstrip().endswith((":", "：")):
            for following in lines[index + 1 :]:
                if not following.strip() or re.match(r"^\s*#{1,6}\s", following):
                    break
                end += len(following)
        quote = text[start:end].strip()
        if (
            quote.endswith((":", "："))
            or max_chars is not None
            and len(quote) > max_chars
            or not re.search(
                r"\b(?:can|cannot|eliminates?|access|will|works?|unless|except)\b", quote, re.I
            )
        ):
            continue
        blocks.append(quote)
    return list(dict.fromkeys(blocks))


def _texts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _texts(child)
    elif isinstance(value, Mapping):
        for key in ("evidence_terms", "conditions"):
            yield from _texts(value.get(key))


def _events(text):
    result = set()
    if re.search(r"\bunshar\w*\b|取消共享", text, re.I) and re.search(
        r"\bfolders?\b|文件夹", text, re.I
    ):
        result.add(("unshare", "folder"))
    if re.search(r"\b(?:remov\w*|removed)\b|移除", text, re.I):
        role = re.search(
            r"\bremov\w*\s+(?:a\s+|the\s+)?(members?|editors?|guests?|owners?|auditors?)\b",
            text,
            re.I,
        )
        subject = (
            role[1].casefold().rstrip("s")
            if role
            else "member"
            if re.search(r"\bmember\b|\bmembers\b|成员|\bthem\b", text, re.I)
            else None
        )
        obj = (
            "organization"
            if re.search(r"\borganization\b|组织", text, re.I)
            else "folder"
            if re.search(r"\bfolder\b|文件夹", text, re.I)
            else None
        )
        if subject and obj:
            result.add(("remove_" + subject, obj))
    if re.search(r"\b(?:leav\w*|left)\b|离开", text, re.I) and re.search(
        r"\bfolder\b|文件夹", text, re.I
    ):
        result.add(("leave", "folder"))
    if re.search(r"\bdelet\w*\s+(?:a\s+|the\s+)?link\b|删除.{0,5}链接", text, re.I):
        result.add(("delete", "link"))
    return result


def source_exception_constraints(fact, *, available_facts=()):
    """Read complete admitted originals and explicit receipts, never model reasons."""
    if fact.dimension != "feature" or fact.field != "evidence_terms":
        return ()
    result = []
    texts = list(dict.fromkeys([fact.quote, *_texts(fact.value)]))
    for text in texts:
        for block in complete_rule_blocks(text):
            events = _events(block)
            if (
                _AUTH.search(block)
                and _ACCESS.search(block)
                and re.search(r"\bunless\b", block, re.I)
            ):
                kind = "authentication_access"
            elif _COPY.search(block):
                kind = "retained_copy"
            elif re.search(r"\blinks?\b[^.!?\n]{0,100}\bstill\s+be\s+enabled\b", block, re.I):
                kind = "surviving_link"
            elif ("delete", "link") in events and re.search(r"no longer works", block, re.I):
                kind = "deleted_link"
            elif re.search(r"\bexcept(?:\s+if)?\s*:", block, re.I):
                kind = "exception_list"
            else:
                continue
            branches = (
                re.findall(r"^\s*[-*]\s+(.+)", block, re.M) if kind == "exception_list" else []
            )
            row = {"kind": kind, "quote": block, "events": sorted(events), "branches": branches}
            if row not in result:
                result.append(row)
    for constraint in _verified_receipt_constraints(fact, available_facts):
        if constraint not in result:
            result.append(constraint)
    return tuple(result)


def _receipt_scope_matches(fact, receipt):
    scope = fact.qualifiers.get("source_scope")
    events = receipt.get("events", [])
    if not isinstance(events, list) or any(
        not isinstance(event, (list, tuple))
        or len(event) != 2
        or not all(isinstance(value, str) for value in event)
        for event in events
    ):
        return False
    return bool(
        isinstance(scope, dict)
        and scope.get("captured_page_id")
        and scope.get("source_url")
        and all(receipt.get(key) == value for key, value in scope.items())
        and (not scope.get("raw_source_id") or scope["raw_source_id"] == fact.source_id)
        and _events(fact.quote) & {tuple(event) for event in receipt.get("events", [])}
    )


def _verified_receipt_constraints(fact, available_facts):
    """Replay the receipt against the admitted originating item in this view."""
    rows = fact.qualifiers.get("source_exception_links", [])
    if not isinstance(rows, list):
        return
    for receipt in rows:
        if not isinstance(receipt, dict) or not _receipt_scope_matches(fact, receipt):
            continue
        origin = next(
            (
                other
                for other in (fact, *available_facts)
                if receipt.get("evidence_item_id") in other.evidence_item_ids
                and other.source_id == fact.source_id
                and other.competitor == fact.competitor
                and other.dimension == fact.dimension
                and other.qualifiers.get("source_scope") == fact.qualifiers.get("source_scope")
            ),
            None,
        )
        if origin is None:
            continue
        proxy = origin.model_copy(update={"qualifiers_json": "{}"})
        for derived in source_exception_constraints(proxy):
            from packages.research.evidence.snapshot_models import canonical_json

            if all(
                canonical_json(receipt.get(key)) == canonical_json(value)
                for key, value in derived.items()
            ):
                yield derived


def source_scope(item):
    return {
        "captured_page_id": item.captured_page_id,
        "source_url": item.source_url,
        "raw_source_id": item.raw_source_id,
        "context": {
            key: item.metadata.get(key, item.value.get(key))
            for key in ("document_section", "section_path", "plan", "role")
        },
        "operations": item.value.get("operations", []),
    }


def source_exception_links(item, accepted_items):
    if (
        item.status != "accepted"
        or item.dimension != "feature"
        or not isinstance(item.value, Mapping)
    ):
        return []
    events = _events(item.quote)
    result = []
    for source in accepted_items:
        if (
            source.status != "accepted"
            or source.competitor != item.competitor
            or source.dimension != item.dimension
            or not isinstance(source.value, Mapping)
            or source_scope(source) != source_scope(item)
            or not source.captured_page_id
            or not source.source_url
        ):
            continue
        from packages.research.evidence.snapshot_models import EvidenceFact, canonical_json

        proxy = EvidenceFact(
            id=source.id,
            semantic_id=source.id,
            source_id=source.raw_source_id or "",
            competitor=source.competitor,
            dimension="feature",
            field="evidence_terms",
            value_json=canonical_json(source.value.get("evidence_terms", [])),
            quote=source.quote,
            status="supported",
            confidence=source.confidence,
        )
        for row in source_exception_constraints(proxy):
            if events & {tuple(event) for event in row["events"]}:
                result.append({**row, "evidence_item_id": source.id, **source_scope(source)})
    return sorted(result, key=lambda row: (row["evidence_item_id"], row["quote"]))


def _asserted(text, pattern):
    """Recognize an affirmative assertion of a finite source predicate.

    Negation of that predicate, failed prerequisites and explicit denial scopes
    cannot be rescued by the same words occurring later in the sentence.
    """
    matches = list(re.finditer(pattern, text, re.I))
    if not matches:
        return False
    for match in matches:
        prefix = text[: match.start()]
        sentence = re.split(r"[.!?。！？;；]", prefix)[-1]
        local = re.split(r"[,，:]", sentence)[-1][-80:]
        if re.search(
            r"\b(?:it is not true that|it is false that|false that|denies? that)\b|"
            r"并非|不是真的|不是事实",
            sentence,
            re.I,
        ):
            return False
        if re.search(
            r"\b(?:does?|did|is|are|was|were|will|would|can|could|has|have)\s+not\b|"
            r"\b(?:cannot|can't|never|failed|unsuccessful)\b|不允许|不能|并不|未能|失败",
            local,
            re.I,
        ):
            return False
    return True


def _subjects(text):
    aliases = {
        "members": "member",
        "editors": "editor",
        "guests": "guest",
        "auditors": "auditor",
        "owners": "owner",
        "成员": "member",
        "编辑者": "editor",
    }
    matches = re.findall(
        r"\b(member|editor|guest|auditor|owner)s?\s+accounts?\b|"
        r"\bremov\w*\s+(members?|editors?|guests?|auditors?|owners?)\b|"
        r"(成员|编辑者)(?:账户|账号)",
        text,
        re.I,
    )
    return {
        aliases.get(value.casefold(), value.casefold())
        for group in matches
        for value in group
        if value
    }


def _object_key(text):
    text = re.sub(r"^(?:(?:that|this|the|an?|your|their|shared)\s+)+", "", text, flags=re.I)
    return {"文件夹": "folder", "共享文件夹": "folder", "组织": "organization"}.get(
        text.strip().casefold(), text.strip().casefold()
    )


def _copy_objects(text):
    objects = set()
    for clause in re.split(r"[.!?。！？;；\n]", text):
        if _CLARIFY.search(clause):
            continue
        for match in re.finditer(
            r"\bkeep (?:a )?copy of ([^,;.!?]{1,80})|"
            r"保留([^，。；]{0,20})副本",
            clause,
            re.I,
        ):
            objects.add(_object_key(match[1] if match[1] is not None else match[2]))
    return objects


def _removal_objects(text):
    objects = set()
    for clause in re.split(r"[.!?。！？;；\n]", text):
        if _CLARIFY.search(clause):
            continue
        for match in re.finditer(
            r"\bremov(?:e|es|ed|ing)\b(?:\s+[^,.;:!?]{1,60}?)?\s+from\s+"
            r"(?:(?:your|their|our|the|an?|this)\s+)?((?:(?:public|private|shared)\s+)?[a-z-]+)|"
            r"移除([^，。；]{1,12}?)(?:的)?(?:成员|用户)|从([^，。；]{1,12}?)(?:中|内)?移除",
            clause,
            re.I,
        ):
            objects.add(_object_key(next(value for value in match.groups() if value is not None)))
    return objects


def _recovered_password_login(text):
    assignment = (
        r"\bassigned (?:a |the )?master password (?:using|via|through) account recovery\b|"
        r"\baccount recovery assigned (?:a |the )?master password\b|"
        r"(?:账户|账号)恢复(?:为其)?(?:分配|设置)(?:了)?(?:一个|新的?)?主密码"
    )
    login = (
        r"\b(?:log|sign) in (?:with|using) (?:that|this|the same) master password "
        r"(?:at least )?once before\b|"
        r"(?:移除|删除)前(?:使用|用)(?:该|此|同一)主密码(?:至少)?登录(?:过)?一次|"
        r"(?:使用|用)(?:该|此|同一)主密码(?:在)?(?:移除|删除)前(?:至少)?登录(?:过)?一次"
    )
    assigned, logged = re.search(assignment, text, re.I), re.search(login, text, re.I)
    return bool(
        assigned
        and logged
        and assigned.end() < logged.start()
        and _asserted(text, assignment)
        and _asserted(text, login)
    )


def _sync_rules(text):
    rules = set()
    aliases = {
        "其他账户": "other accounts",
        "其他账号": "other accounts",
        "其它账户": "other accounts",
        "其它账号": "other accounts",
    }
    for clause in re.split(r"[.!?。！？;；\n]", text):
        if _CLARIFY.search(clause):
            continue
        for match in re.finditer(
            r"(?P<negative>no longer |not |stop\w* )?sync\w* with (?P<object>[^,.;!?]{1,80})|"
            r"(?P<zh_negative>不再|停止|不会|不)?同步(?:到|与)?(?P<zh_object>[^，。；]{1,20})|"
            r"(?:不再|停止)(?:与|和)(?P<zh_before>[^，。；]{1,20})同步",
            clause,
            re.I,
        ):
            obj = (
                next(
                    value
                    for value in (match["object"], match["zh_object"], match["zh_before"])
                    if value is not None
                )
                .strip()
                .casefold()
            )
            if match["zh_object"] and obj.startswith(("时", "后", "前", "之后", "之前")):
                # A sync-time clause describes when device removal occurs.
                continue
            negative = bool(match["negative"] or match["zh_negative"] or match["zh_before"])
            rules.add((negative, aliases.get(obj, obj)))
    return rules


def _covered(text, row):
    kind = row["kind"]
    if kind == "authentication_access":
        recovery, login = _RECOVERY.search(text), _LOGIN_BEFORE.search(text)
        conjunction = (
            text[recovery.end() : login.start()]
            if recovery and login and recovery.end() <= login.start()
            else ""
        )
        source = row["quote"]
        outcome = (
            r"eliminates?\s+(?:all\s+)?(?:account\s+)?access|"
            r"lose\s+(?:all\s+)?(?:account\s+)?access|"
            r"(?:cannot|can't|will not be able to)\s+(?:log|sign)\s+in|"
            r"失去[^。；]{0,12}访问|无法访问|消除[^。；]{0,12}访问"
        )
        if (
            _AUTH.search(text)
            and recovery
            and login
            and not re.search(
                outcome + r"|retain[^.;]{0,20}access|still[^.;]{0,20}access", text, re.I
            )
        ):
            return None
        return bool(
            _AUTH.search(text)
            and recovery
            and login
            and _asserted(text, _RECOVERY.pattern)
            and _asserted(text, _LOGIN_BEFORE.pattern)
            and _recovered_password_login(text)
            and not re.search(
                r"\b(?:never|not)\b|从未|未曾|从不|未能|没有|不曾", login.group(), re.I
            )
            and _subjects(source) == _subjects(text)
            and _removal_objects(source) == _removal_objects(text)
            and re.search(r"\band\b|且|并且|同时|还需", conjunction, re.I)
            and not re.search(r"\bor\b|或者|或是", conjunction, re.I)
            and re.search(r"\bunless\b|除非|只有|否则", text, re.I)
            and re.search(
                r"(?:do not have|without|no)\s+master passwords?|没有主密码|无主密码", text, re.I
            )
            and (
                not re.search(r"trusted devices?", source, re.I)
                or re.search(r"trusted devices?|受信任设备|可信设备", text, re.I)
            )
            and _asserted(text, outcome)
        )
    if kind == "retained_copy":
        return bool(
            _asserted(text, _COPY.pattern)
            and _copy_objects(row["quote"]) == _copy_objects(text)
            and _asserted(text, _NO_SYNC.pattern)
            and _sync_rules(row["quote"]) == _sync_rules(text)
            and set(map(tuple, row["events"])) <= _events(text)
            and re.search(r"\b(?:choose|option|if|when)\b|选择|允许|如果|可保留", text, re.I)
        )
    if kind == "surviving_link":
        return bool(
            re.search(r"\blink\b|链接", text, re.I)
            and _asserted(text, r"\bstill\b[^.!?]{0,50}\benabled\b|仍然?有效|仍可访问")
            and set(map(tuple, row["events"])) <= _events(text)
            and re.search(r"\bleav\w*\b|离开", text, re.I)
        )
    if kind == "deleted_link":
        return bool(
            ("delete", "link") in _events(text)
            and _asserted(text, r"no longer works|不再有效|失效|无法.{0,5}访问")
        )
    if kind == "exception_list":
        branches = row["branches"]
        return bool(branches and all(_branch_covered(text, branch) for branch in branches))
    return False


def _branch_covered(text, branch):
    if _asserted(text, r"\s+".join(map(re.escape, branch.split()))):
        return True
    if re.search(r"\binactive\b", branch, re.I):
        return _asserted(
            text,
            r"(?:包含|含有)[^。；]{0,15}(?:不活跃|非活动|停用|未激活)"
            r"[^。；]{0,8}共享文件夹",
        )
    if re.search(r"\binside another\b", branch, re.I):
        return _asserted(
            text, r"(?:位于|处于|在)[^。；]{0,8}(?:另一|其他|父)[^。；]{0,8}共享文件夹"
        )
    if re.search(r"\bcontains shared folders\b", branch, re.I):
        return _asserted(text, r"(?:包含|含有)[^。；]{0,8}共享文件夹")
    return False


def claim_source_exception_reasons(claim, facts, *, available_facts=()):
    reasons = []
    for fact in facts:
        constraints = list(source_exception_constraints(fact, available_facts=available_facts))
        admitted_ids = fact.qualifiers.get("source_exception_item_ids", [])
        admitted_ids = admitted_ids if isinstance(admitted_ids, list) else []
        receipts = fact.qualifiers.get("source_exception_links", [])
        for receipt in receipts if isinstance(receipts, list) else ():
            if (
                isinstance(receipt, dict)
                and _receipt_scope_matches(fact, receipt)
                and receipt.get("evidence_item_id") in admitted_ids
                and not any(
                    receipt.get("evidence_item_id") in other.evidence_item_ids
                    for other in (fact, *available_facts)
                )
            ):
                if receipt.get("kind") != "authentication_access" or _ACCESS.search(claim.text):
                    reasons.append("source_exception_unresolved")
        # Legacy records have no capture receipt. A relevant admitted rule in the
        # same source can reveal unresolved closure, but cannot create a link.
        for other in available_facts:
            if (
                other.id == fact.id
                or other.source_id != fact.source_id
                or other.competitor != fact.competitor
                or other.dimension != fact.dimension
            ):
                continue
            scope, other_scope = (
                fact.qualifiers.get("source_scope"),
                other.qualifiers.get("source_scope"),
            )
            if scope and other_scope and scope != other_scope:
                continue
            for row in source_exception_constraints(other):
                if (
                    _events(fact.quote) & {tuple(event) for event in row["events"]}
                    and row not in constraints
                ):
                    if not scope or not other_scope:
                        if row["kind"] == "authentication_access" and not _ACCESS.search(
                            claim.text
                        ):
                            continue
                        if not _covered(claim.text, row):
                            reasons.append("source_exception_unresolved")
                    else:
                        constraints.append(row)
        for row in constraints:
            if row["kind"] == "authentication_access" and not _ACCESS.search(claim.text):
                continue
            if row["kind"] == "retained_copy" and not re.search(
                r"delet|remov|copy|sync|access|删除|移除|副本|同步|访问|看不到", claim.text, re.I
            ):
                continue
            if row["kind"] == "exception_list" and not re.search(
                r"unshar|取消共享", claim.text, re.I
            ):
                continue
            covered = _covered(claim.text, row)
            if not covered:
                reasons.append(
                    "source_exception_unresolved"
                    if covered is None
                    else "source_exception_omitted_or_changed"
                )
        for text in [fact.quote, *_texts(fact.value)]:
            if re.search(r"\bexcept(?:\s+if)?\s*:", text, re.I) and not any(
                row["kind"] == "exception_list" for row in constraints
            ):
                reasons.append("source_exception_unresolved")
    return tuple(dict.fromkeys(reasons))


def answer_source_exception_reasons(record, claims, *, facts=()):
    if record.status not in {"answered", "partial"}:
        return ()
    selected = [claim for claim in claims if claim["id"] in record.claim_ids]
    text = "\n".join(claim["text"] for claim in selected)
    question = record.question
    reasons = []
    missing = _missing_question_inputs(question)
    ambiguous = bool(missing)
    clarified = _clarified_fields(text)
    if ambiguous and not set(missing) <= clarified:
        reasons.append("answer_source_action_clarification_missing")
    if ambiguous and record.conclusion == "yes":
        reasons.append("answer_source_exception_unresolved")
    selected_ids = {fid for claim in selected for fid in claim.get("fact_ids", ())}
    from types import SimpleNamespace

    originals = [fact for fact in facts if fact.id in selected_ids]
    if claim_source_exception_reasons(SimpleNamespace(text=text), originals, available_facts=facts):
        reasons.append("answer_source_exception_unpublished")
    for fact in facts:
        if fact.id not in selected_ids:
            continue
        for row in source_exception_constraints(fact, available_facts=facts):
            if row["kind"] == "authentication_access" and not _ACCESS.search(text):
                continue
            if not _covered(text, row):
                reasons.append("answer_source_exception_unpublished")
    if ambiguous:
        # Source branches must be published as propositions, not a stray if/when.
        branch_facts = originals or [
            SimpleNamespace(
                dimension="feature", field="evidence_terms", quote=text, value=[], qualifiers={}
            )
        ]
        branches = [
            row
            for fact in branch_facts
            for row in source_exception_constraints(fact, available_facts=facts)
        ]
        if not branches or not all(_covered(text, row) for row in branches):
            reasons.append("answer_source_branches_unpublished")
        if record.resolution != "clarification" or record.conclusion != "depends":
            reasons.append("answer_source_exception_unresolved")
    return tuple(dict.fromkeys(reasons))


def _clarified_fields(text):
    fields = set()
    aliases = {
        "actual_action": (
            r"actual action|which (?:action|operation)|具体操作|实际操作|"
            r"哪[^。；]{0,10}(?:操作|按钮)"
        ),
        "data_ownership": (
            r"data ownership|who owns|personally.owned|organization.owned|"
            r"数据归属|数据所有者|谁的"
        ),
        "retained_copy": (
            r"retained cop(?:y|ies)|keep (?:a )?copy|copy choice|"
            r"保留[^。；]{0,5}副本|副本选择"
        ),
        "access_path": r"access path|shared links?|view links?|访问路径|共享链接|查看链接",
    }
    for clause in re.findall(r"[^.!?。！？;；\n]+[?？]?", text):
        if _CLARIFY.search(clause):
            fields.update(
                field for field, pattern in aliases.items() if re.search(pattern, clause, re.I)
            )
    return fields


def _missing_question_inputs(question):
    """Finite request input aliases, used only to detect uncertainty, never facts."""
    if not re.search(r"删掉|取消共享|\bunshare\b", question, re.I):
        return []
    # A named permanent account operation already resolves the generic 'delete'.
    if re.search(r"(?:个人|自己的)[^。；]{0,12}(?:账户|账号)[^。；]{0,10}永久删掉", question):
        return []
    folder = bool(re.search(r"\bfolder\b|文件夹", question, re.I))
    owner = bool(re.search(r"\b(?:I own|owner|my own)\b|所有者|自有|我拥有", question, re.I))
    action = bool(
        folder
        and (
            re.search(r"\bunshare\b", question, re.I) or owner and re.search(r"整个|全部", question)
        )
    )
    outcome = bool(
        re.search(r"\b(?:access|copy|see|view)\b|看不到|看到|访问|副本|留下", question, re.I)
    )
    missing = [] if action else ["actual_action"]
    if outcome:
        if not owner and not re.search(r"个人|组织(?:拥有|数据)|personally.owned", question, re.I):
            missing.append("data_ownership")
        if not re.search(
            r"\b(?:did not allow|chose to allow|chose not to allow|allowed)\b[^.!?]{0,80}"
            r"\bkeep (?:a )?copy\b|(?:没有|未|已|不|选择|允许)[^。；]{0,12}保留[^。；]{0,5}副本",
            question,
            re.I,
        ):
            missing.append("retained_copy")
        if not re.search(
            r"\bno (?:shared |view )?links?\b|\bonly (?:through|via) (?:the |a )?link\b|"
            r"(?:没有|未创建|不使用|已删除)[^。；]{0,8}链接|仅通过[^。；]{0,8}链接",
            question,
            re.I,
        ):
            missing.append("access_path")
    return missing


def required_question_clarifications(questions):
    return [
        {"question_id": question["question_id"], "missing_fields": missing}
        for question in questions
        if (missing := _missing_question_inputs(question["question"]))
    ]


def question_exception_fact_ids(question, facts):
    """Rank original exception observations for recall, without binding sources."""
    events = _events(question)
    broad = bool(re.search(r"取消共享|删掉|\bunshare\b|\bremove\b", question, re.I))
    related_paths = bool(re.search(r"\b(?:copy|link|access)\b|副本|链接|看到|访问", question, re.I))
    candidates = {}
    for fact in facts:
        for row in source_exception_constraints(fact):
            if not (
                events & {tuple(event) for event in row["events"]}
                or broad
                and (
                    row["kind"] in {"authentication_access", "retained_copy", "exception_list"}
                    or related_paths
                )
            ):
                continue
            identity = (
                row["kind"],
                row["quote"],
                fact.source_id,
                str(fact.qualifiers.get("source_scope", {})),
            )
            # Prefer the original rule over a neighbour containing the same
            # admitted context. Never merge different roles/conditions/captures.
            rank = (fact.quote.strip() != row["quote"], len(fact.value_json), fact.id)
            if identity not in candidates or rank < candidates[identity][0]:
                candidates[identity] = (rank, fact.id)
    return list(dict.fromkeys(value[1] for _, value in sorted(candidates.items())))
