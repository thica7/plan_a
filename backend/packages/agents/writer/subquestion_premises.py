"""Exact premise receipts and finite negative-decision checks.

These are conservative rejection checks, not a general entailment prover.
The independent reviewer still checks the partition, actors, objects, modal
scope and all prerequisites. A valid digest only proves unchanged inputs.
"""

import hashlib
import re

from packages.research.evidence.answer_coverage_models import AnswerSubquestionBinding
from packages.research.evidence.snapshot_models import canonical_json

CONTRACT = "subquestion-premises-v1"
CONTRACT_V2 = "subquestion-premises-v2"
_RESOURCE_NAME = r"[A-Z](?:[0-9]{1,3})?"
_RESOURCE_NOUN = r"(?:boards?|看板|白板|vaults?|保险库|folders?|文件夹|workspaces?|工作区|resources?|资源)"


def named_resource_items(question):
    """Finite explicit A/B lists only; unknown names stay with semantic review."""
    from packages.agents.writer.answer_action_scope import _INVERTED, _QUESTION
    requests = [unit.rsplit(':', 1)[-1].rsplit('：', 1)[-1]
        for unit in re.split(r'(?<=[。!?？！])|(?<=\.)\s+', question)
        if _QUESTION.search(unit) or _INVERTED.match(unit)]
    request = ' '.join(requests)
    pattern = (rf"{_RESOURCE_NOUN}\s*(?P<first>{_RESOURCE_NAME})(?![A-Za-z0-9_])"
        rf"\s*(?:、|和|及|与|,\s*(?:and\s+)?|\band\b|&)\s*"
        rf"(?:{_RESOURCE_NOUN}\s*)?(?P<second>{_RESOURCE_NAME})(?![A-Za-z0-9_])")
    pairs = [match.group('first', 'second') for match in re.finditer(pattern, request, re.I)]
    if not pairs and re.search(_RESOURCE_NOUN, question, re.I) and re.search(r"逐项|分别|\beach\b|\bseparately\b", question, re.I):
        pairs = [match.group('first', 'second') for match in re.finditer(
            rf"(?<![A-Za-z0-9_])(?P<first>{_RESOURCE_NAME})\s*(?:、|和|与|\band\b)\s*"
            rf"(?P<second>{_RESOURCE_NAME})(?![A-Za-z0-9_])", request)]
    return tuple(dict.fromkeys(item for pair in pairs for item in pair))


def named_resource_outcome_reasons(record, claims):
    """An answered resource list must visibly apply the rule to every item."""
    if record.status != 'answered' or record.resolution not in {'direct', 'conditional'}:
        return ()
    items = named_resource_items(record.question)
    if len(items) < 2:
        return ()
    from packages.agents.writer.answer_action_scope import _ACTIONS, requested_answer_actions
    actions = requested_answer_actions(record.question)
    if not actions:
        return ()
    selected = [row for row in claims if row['id'] in record.claim_ids]
    for action in actions:
        outcomes = set().union(*(_named_action_outcomes(row['text'], items, _ACTIONS[action])
            for row in selected)) if selected else set()
        if not set(items) <= outcomes:
            return ('answer_named_resource_outcome_missing',)
    return ()


def _named_action_outcomes(text, items, action):
    """Bind finite named outcomes inside decision clauses, excluding scenario prose."""
    modal = (r"\b(?:can(?:not)?|can['’]t|may|allowed|permitted)\b"
             r"|不能|无法|可以|能够|不允许|允许|不具备|不具有|具备")
    labels = re.compile(r'(?<![A-Za-z0-9_])(?:' + '|'.join(map(re.escape, items))
                        + r')(?![A-Za-z0-9_])')
    outcomes = set()
    for unit in re.split(r'[。；;.!?？\n，,]', text):
        # Conditional prefixes carry request inputs; only their resulting
        # decision clause can establish an item's visible action outcome.
        unit = re.sub(r'^\s*(?:在|当|若|如果|假设|题设).*?(?:条件下|情况下|题设下|时|下)\s*', '', unit)
        if re.match(r'^\s*(?:if|when|assuming|given|because)\b|^\s*(?:若|如果|假设)', unit, re.I):
            continue
        unit = re.split(r'\b(?:if|when|because|provided|assuming)\b|因为|由于|如果', unit, maxsplit=1, flags=re.I)[0]
        for predicate in re.finditer(modal, unit, re.I):
            verbs = list(re.finditer(action, unit, re.I))
            if not verbs:
                continue
            verb = min(verbs, key=lambda match: min(abs(match.start() - predicate.end()),
                abs(predicate.start() - match.end())))
            start, end = sorted((predicate.start(), verb.start()))
            bound = [label for label in labels.finditer(unit) if start <= label.start() <= end]
            if bound:
                outcomes.update(label.group() for label in bound)
                continue
            after = [label for label in labels.finditer(unit) if label.start() >= verb.end()]
            if verb.start() > predicate.start() and after:
                first = after[0]
                if re.fullmatch(rf'\s*(?:on|in|at|to|from|within|于|在)\s*(?:the\s+)?(?:{_RESOURCE_NOUN}\s*)?',
                                unit[verb.end():first.start()], re.I):
                    outcomes.add(first.group())
                    continue
            before = [label for label in labels.finditer(unit) if label.end() <= predicate.start()]
            if before:
                last = before[-1]
                context = unit[last.end():predicate.start()]
                if not re.search(r'\b(?:is|are|has|have|enabled|disabled|when|if|with|assuming|settings?)\b'
                    r'|开启|关闭|启用|题设|条件|设置|无关|时|下', context, re.I):
                    outcomes.add(last.group())
    return outcomes
_NEGATIVE = re.compile(
    r"\b(?:cannot|can['’]t|does\s+not|do\s+not|not\s+(?:allowed|permitted|available|have))\b"
    r"|不能|无法|没有|不允许|不具备|不可(?!以通过)|不支持",
    re.I,
)
_SCOPE = re.compile(
    r"\bspecific\s+(?:domain|resource)|\b(?:domain|resource)[ -]scoped"
    r"|仅(?:允许|适用)|只适用|特定(?:域|资源)",
    re.I,
)
_NUMBERS = {
    "single": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
}
_COUNT = r"(?:\d+|single|one|two|three|four|five|一|二|两|三|四|五)"
_UNITS = {
    "people": r"(?:people|users?|members?|persons?|(?:个|名|位)?(?:人|用户|成员))",
    "collections": r"(?:个\s*)?(?:collections?|集合)",
    "containers": r"(?:个\s*)?(?:containers?|容器)",
    "vaults": r"(?:个\s*)?(?:(?:shared\s+|private\s+)?vaults?|(?:共享|私人|私有|个人)?保险库)",
}
_EXTRA_OBJECTS = re.compile(
    r"(?P<private_vault>\bprivate\s+vaults?\b|(?:私人|私有|个人)保险库)"
    r"|(?P<shared_vault>\bshared\s+vaults?\b|共享保险库)"
    r"|(?P<vault>\bvaults?\b|保险库)"
    r"|(?P<organization>\borganizations?\b|组织)"
    r"|(?P<workspace>\bworkspaces?\b|工作区)",
    re.I,
)


def _scope_objects(text):
    """Recognize finite conflicts; unknown nouns still require semantic review."""
    from packages.agents.writer.answer_resolution import _objects

    return _objects(text) | {match.lastgroup for match in _EXTRA_OBJECTS.finditer(text)}


def _counts(text, *, upper=False):
    if upper and re.search(
        r"\b(?:if|unless|provided|assuming|recommend\w*|suggest\w*)\b"
        r"|如果|若|仅当|除非|假设|假定|建议|推荐",
        text,
        re.I,
    ):
        return {}
    values = {}
    for unit, pattern in _UNITS.items():
        for match in re.finditer(f"(?P<n>{_COUNT})\\s*{pattern}", text, re.I):
            if upper:
                before, after = text[: match.start()], text[match.end() :]
                # A different predicate's negative cannot erase this cap.
                # Conditions above remain attached to the entire original atom.
                local = re.split(
                    r"\b(?:and|but)\s+(?=(?:may|can|must|cannot|does|do|has|have|is|are)\b)"
                    r"|[。；;]|(?:且|但)(?=(?:只能|仅能|可以|不能|并非|不限))",
                    before,
                    flags=re.I,
                )[-1]
                if re.search(r"\b(?:not|never)\b|并非|不是|不限", local, re.I):
                    continue
                limit = re.search(
                    r"(?:\bonly|\bup\s+to|\bat\s+most|\bmaximum\s+of|最多|至多|上限为?|仅限|不超过)\s*$"
                    r"|(?:最多|至多)(?:只能|仅能|可|可以)?(?:使用|提供|拥有|包含|支持|容纳|允许)\s*$"
                    r"|(?:只能|仅能|只可|仅可)(?:访问|加入)(?:由[^，。；;!?？\n]{1,40}选择的)?\s*$",
                    before,
                    re.I,
                )
                at_a_time = re.match(r"\s+at\s+a\s+time\b", after, re.I)
                if not limit and not at_a_time:
                    continue
                if limit and re.search(
                    r"\b(?:not|never)\s*$|(?:不|并非|不是)\s*$", before[: limit.start()], re.I
                ):
                    continue
            raw = match["n"].casefold()
            values.setdefault(unit, []).append(int(raw) if raw.isdigit() else _NUMBERS[raw])
    return values


def _destruction_denies_retention(question, texts):
    """Only complete account deletion rules; membership removal is not deletion."""
    deletion = re.compile(
        r"\bdelet(?:e|ing)\s+(?:(?:your|my|the|an?|their)\s+)?account\b"
        r"|删除(?:我的|你的|该|这个)?(?:账户|账号|帐号)",
        re.I,
    )
    retention = r"\b(?:keep|retain|preserve)\b|保留|留下"
    if not deletion.search(question) or not re.search(retention, question, re.I):
        return False
    data_objects = {
        "passwords": r"\bpasswords?\b|密码",
        "files": r"\bfiles?\b|文件(?!夹)",
        "data": r"\bdata\b|数据",
    }
    requested = {key for key, pattern in data_objects.items() if re.search(pattern, question, re.I)}
    if not requested:
        return False
    for text in texts:
        if not deletion.search(text) or not _scope_objects(question) <= _scope_objects(text):
            continue
        if re.search(
            r"\b(?:if|unless|may|can|could|might|would|not|except)\b|如果|若|仅当|除非|除外|可以|可能|并非|不会",
            text,
            re.I,
        ):
            continue
        if not re.search(
            r"\b(?:removes?|deletes?|destroys?|erases?)\s+(?:all|every)\b|(?:删除|清除|销毁)所有",
            text,
            re.I,
        ):
            continue
        if all(re.search(data_objects[key], text, re.I) for key in requested):
            return True
    return False


def _explicit_negative_text(text, *, question=""):
    # An outer uncertainty/negation or an unresolved condition cannot prove a
    # plain no. The reviewer still decides the meaning of eligible assertions.
    if re.search(
        r"无法(?:确认|确定|证明)|未(?:确认|确定|证实)|不能(?:确认|确定|断言)|并非|不是|"
        r"如果|若|仅当|除非|假设|假定|"
        r"\b(?:if|unless|assuming|unconfirmed|not\s+(?:necessarily|true))\b",
        text, re.I,
    ):
        return False
    nonautomatic = re.fullmatch(
        r"[^。；;.!?？\n]+不会自动(?:决定|改变|影响)[^。；;.!?？\n]+[。.!]?", text.strip())
    if nonautomatic:
        # This finite new assertion form does not gain truth from advice or an
        # outer denial. An explicit conditional prefix must also be a request
        # input here; absent parent context cannot establish that premise.
        if re.search(r"建议|推荐|最好|不能(?:说|认为|断定|认定)", text):
            return False
        condition = re.match(r"\s*(在[^，,。；;.!?？\n]{1,100}?(?:条件下|情况下|前提下|时))",
                             text)
        if condition and condition[1] not in question:
            return False
    if _NEGATIVE.search(text) or nonautomatic:
        return True
    # Only the plain present-tense possession form with a simple noun subject
    # gains this shortcut. Modal, probabilistic or outer-negated wording needs
    # independent support; it cannot establish an unconditional product denial.
    return bool(re.match(r"^\s*(?:(?:a|an|the|all)\s+)?[a-z][a-z'-]*\s+(?:have|has)\s+no\b",
                         text, re.I)) and not re.search(
        r"\b(?:may|might|could|would|can|if|unless|when|sometimes|possibly)\b", text, re.I)


def _negative_supported(binding, selected):
    texts = [claim["text"] for claim in selected]
    if binding.relation == "explicit_negative":
        negatives = [text for text in texts if _explicit_negative_text(
            text, question=binding.question_quote)]
        # A positive sibling cannot supply the object of a different negative
        # atom. Claim atomicity and unrecognized predicates remain model checks.
        def named_types(text):
            return {match['label'].upper(): _scope_objects(match['noun']) for match in re.finditer(
                rf"(?P<noun>{_RESOURCE_NOUN})\s*(?P<label>{_RESOURCE_NAME})(?![A-Za-z0-9_])",
                text, re.I)}

        requested = named_types(binding.question_quote)
        requested_names = set(requested) | {
            label.upper() for label in named_resource_items(binding.question_quote)}
        # A generic product rule need not repeat the scenario's labels. When
        # both texts name resources, an extra label or changed object conflicts.
        negatives = [text for text in negatives if not requested_names or all(
            label in requested_names and (label not in requested or requested[label] == objects)
            for label, objects in named_types(text).items())]
        objects = set().union(*(_scope_objects(text) for text in negatives)) if negatives else set()
        return bool(negatives) and _scope_objects(binding.question_quote) <= objects
    if binding.relation == "upper_bound":
        requested = _counts(binding.question_quote)
        objects = _scope_objects(binding.question_quote)
        return any(
            cap < number
            for text in texts
            if objects <= _scope_objects(text)
            for unit, numbers in requested.items()
            for number in numbers
            for cap in _counts(text, upper=True).get(unit, ())
        )
    if binding.relation == "resource_scope":
        from packages.agents.writer.answer_action_scope import _ACTIONS, requested_answer_actions

        rules = [c["text"] for c in selected if c.get("kind") == "fact"]
        return any(_SCOPE.search(text) for text in rules) and all(
            any(re.search(_ACTIONS[action], text, re.I) for text in rules)
            for action in requested_answer_actions(binding.question_quote)
        )
    if binding.relation == "destructive_effect":
        return _destruction_denies_retention(binding.question_quote, texts)
    if binding.relation == "permission_entailment":
        # Reject the implication "can therefore must", not actual duties in
        # all contexts. Permission alone cannot establish universal not-must.
        return (
            bool(re.search(r"意味|推出|\b(?:mean|imply|entail)", binding.question_quote, re.I))
            and bool(
                re.search(r"必须|义务|\b(?:must|required|obligat)", binding.question_quote, re.I)
            )
            and any(
                re.search(r"可以|允许|\b(?:can|may|allowed|permitted)\b", t, re.I) for t in texts
            )
        )
    return False


def premise_digest(question, binding, claims):
    by_id = {claim["id"]: claim for claim in claims}
    fields = (
        "id",
        "text",
        "kind",
        "fact_ids",
        "source_ids",
        "operation_binding",
        "source_span_bindings",
    )
    if not set(binding.claim_ids) <= by_id.keys():
        raise ValueError("unpublished subquestion premise")
    selected = [{key: by_id[cid].get(key) for key in fields} for cid in binding.claim_ids]
    data = dict(
        question=question,
        question_quote=binding.question_quote,
        claim_ids=binding.claim_ids,
        conclusion=binding.conclusion,
        relation=binding.relation,
        selected_claims=selected,
    )
    return hashlib.sha256(canonical_json(data).encode()).hexdigest()


def bind_subquestions(rows, question, claims):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 8:
        raise ValueError("missing subquestion decisions")
    bindings = []
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"question_quote", "claim_ids", "conclusion", "relation"}
            or not isinstance(row["claim_ids"], list)
        ):
            raise ValueError("invalid subquestion decision")
        binding = AnswerSubquestionBinding(**row, support_digest="0" * 64)
        binding = binding.model_copy(
            update={"support_digest": premise_digest(question, binding, claims)}
        )
        bindings.append(binding)
    return tuple(bindings)


def subquestion_binding_reasons(record, claims, *, required=False, answer_review_contract=CONTRACT):
    if answer_review_contract not in {CONTRACT, CONTRACT_V2}:
        return ('answer_review_contract_invalid',)
    bindings = record.subquestion_bindings
    resource_reasons = named_resource_outcome_reasons(record, claims)
    if not bindings:
        return (*resource_reasons, *(("answer_subquestion_binding_required",) if required else ()))
    reasons = set(resource_reasons)
    by_id = {claim["id"]: claim for claim in claims}
    cursor = 0
    outcomes = []
    for binding in bindings:
        # Contiguous, ordered excerpts preserve the entire original request,
        # including scenario conditions and output requirements. No hidden tail.
        start = record.question.find(binding.question_quote, cursor)
        if start < 0 or record.question[cursor:start].strip():
            reasons.add("answer_subquestion_partition_incomplete")
        else:
            cursor = start + len(binding.question_quote)
        if (
            len(binding.claim_ids) != len(set(binding.claim_ids))
            or not set(binding.claim_ids) <= set(record.claim_ids)
            or not set(binding.claim_ids) <= by_id.keys()
        ):
            reasons.add("answer_subquestion_binding_changed")
            continue
        if premise_digest(record.question, binding, claims) != binding.support_digest:
            reasons.add("answer_subquestion_binding_changed")
        selected = [by_id[cid] for cid in binding.claim_ids]
        if record.status == "answered" and (
            not selected or binding.conclusion == "unknown" or binding.relation == "unresolved"
        ):
            reasons.add("answer_subquestion_premise_missing")
        if binding.conclusion == "no" and not (
            _negative_supported_v2(binding, selected)[0] if answer_review_contract == CONTRACT_V2
            else _negative_supported(binding, selected)
        ):
            reasons.add("answer_subquestion_negative_unproven")
        outcomes.append(binding.conclusion)
    if record.question[cursor:].strip():
        reasons.add("answer_subquestion_partition_incomplete")
    if {cid for binding in bindings for cid in binding.claim_ids} != set(record.claim_ids):
        reasons.add("answer_subquestion_claims_unassigned")
    if record.conclusion in {"yes", "no"} and any(value != record.conclusion for value in outcomes):
        reasons.add("answer_subquestion_conclusion_mismatch")
    return tuple(sorted(reasons))


def _decision_question(text):
    # Remove only this complete source-reading instruction, never its target
    # predicate or a scenario condition involving an actual business page.
    return re.sub(r'仅依据所给(?:官方)?页面[，,]\s*逐项(?:回答|判断)[：:]', '', text)


_FINITE_UNSAFE = re.compile(
    r'\b(?:if|unless|when|assuming|provided|recommend\w*|suggest\w*|not|never|'
    r'unconfirmed|unverified|may|might|could|would|cannot)\b'
    r'|如果|若|仅当|除非|假设|假定|建议|推荐|并非|不是|未确认|未核实|不只|不仅|不限|例如|比如|示例'
    r'|不能(?:说|认定|确定|断言|认为)|无法(?:确认|确定|证明)|未(?:确认|证实|核实)|可能|也许|或许|不一定|未必'
    r'|[“”‘’「」『』"]', re.I)
_FINITE_PLAN = re.compile(r'\b(free|paid|premium|enterprise|business|standard)\b', re.I)
_COUNT_ACTIONS = {
    'share': r'\bshar(?:e[ds]?|ing)\b|共享|分享',
    'join': r'\b(?:join\w*|invit\w*)\b|加入',
    'access': r'\baccess\b|访问',
    'edit': r'\bedit\w*\b|编辑|修改',
    'delete': r'\b(?:delet\w*|remov\w*)\b|删除|移除',
    'create': r'\bcreat\w*\b|创建|新建',
}


def _count_clause(text, match):
    before = re.split(r'[,，。；;.!?？\n]', text[:match.start()])[-1]
    after = re.split(r'[,，。；;.!?？\n]', text[match.end():], maxsplit=1)[0]
    # A noun such as "shared vault" is not itself a sharing operation.
    return before + ' ' + after


def _count_actions(text):
    from packages.agents.writer.answer_action_scope import _ACTIONS
    return {key for key, pattern in (_COUNT_ACTIONS | _ACTIONS).items()
            if re.search(pattern, text, re.I)}


def _count_occurrences(text):
    for unit, pattern in _UNITS.items():
        if unit == 'vaults':
            pattern = (r'(?:个\s*)?(?:由[^，。；;!?？\n]{1,40}选择的)?'
                       r'(?:(?:shared\s+|private\s+)?vaults?|(?:共享|私人|私有|个人)?保险库)')
        for match in re.finditer(rf'(?P<n>{_COUNT})\s*{pattern}', text, re.I):
            raw = match['n'].casefold()
            yield unit, int(raw) if raw.isdigit() else _NUMBERS[raw], match


def _finite_scope_matches(question, text):
    requested, offered = _scope_objects(_decision_question(question)), _scope_objects(text)
    for key, pattern in (('private_vault', r'(?<![A-Za-z])private\s+vaults?(?![A-Za-z])'),
                         ('shared_vault', r'(?<![A-Za-z])shared\s+vaults?(?![A-Za-z])')):
        if re.search(pattern, question, re.I):
            requested.add(key)
        if re.search(pattern, text, re.I):
            offered.add(key)
    if 'vault' in offered:
        offered |= {'shared_vault', 'private_vault'}
    if not requested <= offered:
        return False
    plans = set(word.casefold() for word in _FINITE_PLAN.findall(question))
    other = set(word.casefold() for word in _FINITE_PLAN.findall(text))
    if plans and other and not other <= plans:
        return False
    def names(value):
        return {m.group().casefold() for m in re.finditer(
            rf'{_RESOURCE_NOUN}\s*{_RESOURCE_NAME}(?![A-Za-z0-9_])', value, re.I)}
    if names(text) and names(question) != names(text):
        return False
    from packages.agents.writer.answer_resolution import _subjects
    wanted, _ = _subjects(_decision_question(question))
    actual, _ = _subjects(text)
    return not (wanted and actual and wanted.isdisjoint(actual))


def finite_decision_witnesses(binding, selected):
    """Finite eligibility witnesses, reconstructed from whole published atoms.

    They do not replace source/schema or independent semantic review. No model
    witness, reason, unseen fact, or conditional fragment supplies a premise.
    """
    question = binding.question_quote
    witnesses = {}
    if re.search(
        r"并非|不是|不能|无法|不意味|不推出|\b(?:not|never|false|incorrect)\b", question, re.I
    ):
        return witnesses
    for claim in selected:
        text = claim['text']
        if _FINITE_UNSAFE.search(text) or not _finite_scope_matches(question, text):
            continue
        if claim.get('kind') == 'fact' and not re.search(r'或|\bor\b', question, re.I):
            for unit, maximum, cap in _count_occurrences(text):
                before, after = text[:cap.start()], text[cap.end():]
                limit = re.search(
                    r'(?:\bonly|\bup\s+to|\bat\s+most|\bmaximum\s+of|最多|至多|上限为?|仅限|不超过)'
                    r'\s*(?:(?:只能|仅能|可|可以)?(?:使用|提供|拥有|包含|支持|容纳|允许)(?:在)?\s*)?$'
                    r'|(?:只能|仅能|只可|仅可)(?:被邀请)?(?:访问|加入)\s*$', before, re.I)
                at_time = bool(re.search(r'一次|\bat\s+a\s+time\b', before + after, re.I))
                if (
                    not limit
                    or at_time
                    and not re.search(r"同时|\bsimultaneous\w*\b|\bconcurrent\w*\b", question, re.I)
                ):
                    continue
                for wanted_unit, required, request in _count_occurrences(question):
                    cap_clause, request_clause = (
                        _count_clause(text, cap),
                        _count_clause(question, request),
                    )
                    if (wanted_unit == unit and maximum < required
                            and _count_actions(cap_clause) == _count_actions(request_clause)):
                        witnesses.setdefault(
                            "upper_bound",
                            dict(
                                kind="upper_bound",
                                claim_id=claim["id"],
                                cap_quote=cap.group(),
                                request_quote=request.group(),
                                unit=unit,
                                maximum=maximum,
                                required=required,
                            ),
                        )
        if (re.search(r'意味|推出|\b(?:mean|imply|entail)', question, re.I)
                and re.search(r'必须|义务|\b(?:must|required|obligat)', question, re.I)
                and re.search(r'可以|允许|\b(?:can|may|allowed|permitted)\b', text, re.I)):
            from packages.agents.writer.answer_action_scope import (
                _ACTIONS,
                requested_answer_actions,
            )

            implication = re.search(r'意味|推出|\b(?:mean|imply|entail)', question, re.I)
            actions = requested_answer_actions(question)
            permitted = {action for action, pattern in _ACTIONS.items()
                         if re.search(pattern, question[:implication.start()], re.I)}
            required = {action for action, pattern in _ACTIONS.items()
                        if re.search(pattern, question[implication.end():], re.I)}
            # A stated duty (outside the limited denial of entailment) cannot
            # gain this shortcut from its neighbouring permission clause.
            remainder = re.sub(r'并?不(?:构成|意味|推出)[^。；;.!?？]*', '', text)
            if actions and permitted == required == actions and not re.search(
                    r'必须|义务|\b(?:must|required|obligat)', remainder, re.I):
                if all(re.search(_ACTIONS[action], text, re.I) for action in actions):
                    witnesses.setdefault(
                        "permission_entailment",
                        dict(
                            kind="permission_entailment",
                            claim_id=claim["id"],
                            permission_quote=text,
                            requested_actions=sorted(actions),
                        ),
                    )
    return witnesses


def _negative_supported_v2(binding, selected):
    if binding.relation in {'upper_bound', 'permission_entailment'}:
        witness = finite_decision_witnesses(binding, selected).get(binding.relation)
        return bool(witness), witness
    question = _decision_question(binding.question_quote)
    if binding.relation == 'explicit_negative':
        selected = [claim for claim in selected if not re.search(
            r'不能(?:说|认定|确定|断言|认为)|无法(?:确认|确定|证明)|未(?:确认|证实|核实)|可能|也许|或许|不一定|未必'
            r'|\b(?:unconfirmed|unverified|may|might|could|would)\b'
            r'|\bcannot\s+(?:say|confirm|determine|assert)\b', claim['text'], re.I)]
    return _negative_supported(
        binding.model_copy(update={"question_quote": question}), selected
    ), None


def canonical_subquestions_v2(rows, question, claims, parent_claim_ids):
    """Keep individually qualified peers; receipt diagnostics bind every change."""
    if not isinstance(rows, list) or not 1 <= len(rows) <= 8:
        raise ValueError('missing subquestion decisions')
    bindings = []
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"question_quote", "claim_ids", "conclusion", "relation"}
            or not isinstance(row["claim_ids"], list)
        ):
            raise ValueError('invalid subquestion decision')
        bindings.append(AnswerSubquestionBinding(**row, support_digest='0' * 64))
    canonical, adjustments, witnesses = [], [], []
    cursor = 0
    for index, binding in enumerate(bindings):
        start = question.find(binding.question_quote, cursor)
        if start < 0 or question.find(binding.question_quote, start + 1) >= 0:
            raise ValueError('ambiguous or incomplete subquestion partition')
        gap = question[cursor:start]
        if gap.strip():
            if not index or not re.fullmatch(r'\s*[,，;；、]\s*', gap):
                raise ValueError('incomplete subquestion partition')
            canonical[-1]['question_quote'] += gap
            adjustments.append(dict(kind='separator_restored', branch_index=index - 1,
                                    offset=cursor, separator=gap))
        canonical.append(
            dict(
                question_quote=binding.question_quote,
                claim_ids=list(binding.claim_ids),
                conclusion=binding.conclusion,
                relation=binding.relation,
            )
        )
        cursor = start + len(binding.question_quote)
    if question[cursor:].strip():
        raise ValueError('incomplete subquestion partition')
    by_id = {claim['id']: claim for claim in claims}
    for index, row in enumerate(canonical):
        ids = row['claim_ids']
        if row['conclusion'] == 'unknown' or row['relation'] == 'unresolved':
            if ids or row['conclusion'] != 'unknown' or row['relation'] != 'unresolved':
                adjustments.append(dict(kind='branch_demoted', branch_index=index,
                    original_conclusion=row['conclusion'], original_relation=row['relation'],
                    original_claim_ids=list(ids)))
            row.update(claim_ids=[], conclusion='unknown', relation='unresolved')
            continue
        valid = (len(ids) == len(set(ids)) and set(ids) <= set(parent_claim_ids)
                 and set(ids) <= by_id.keys())
        selected = [by_id[cid] for cid in ids] if valid else []
        binding = AnswerSubquestionBinding(**row, support_digest='0' * 64)
        witness = None
        if valid and row['conclusion'] == 'no':
            valid, witness = _negative_supported_v2(binding, selected)
            if not valid and row['relation'] == 'explicit_negative':
                candidates = finite_decision_witnesses(binding, selected)
                if len(candidates) == 1:
                    relation, witness = next(iter(candidates.items()))
                    adjustments.append(dict(kind='relation_restored', branch_index=index,
                        original_relation=row['relation'], applied_relation=relation))
                    row['relation'], valid = relation, True
        if row['conclusion'] not in {'unknown', 'not_applicable'} and not selected:
            valid = False
        if valid and row['conclusion'] != 'unknown':
            from packages.agents.writer.answer_action_scope import (
                _ACTIONS,
                requested_answer_actions,
            )
            from packages.agents.writer.answer_resolution import resolution_reasons

            body = '\n'.join(claim['text'] for claim in selected)
            local = dict(
                status="answered",
                answer=body,
                resolution="direct",
                conclusion=row["conclusion"],
                claim_ids=ids,
                evidence_spans=[dict(claim_id=c["id"], quote=c["text"]) for c in selected],
            )
            valid = not resolution_reasons(
                local, _decision_question(row["question_quote"]), selected
            )
            valid &= all(re.search(_ACTIONS[action], body, re.I)
                         for action in requested_answer_actions(row['question_quote']))
        if not valid:
            adjustments.append(dict(kind='branch_demoted', branch_index=index,
                original_conclusion=row['conclusion'], original_relation=row['relation']))
            row.update(claim_ids=[], conclusion='unknown', relation='unresolved')
        elif witness:
            witnesses.append(dict(branch_index=index, **witness))
    return canonical, dict(adjustments=adjustments, finite_witnesses=witnesses)
