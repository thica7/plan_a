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
CONTRACT_V3 = "subquestion-premises-v3"
CONTRACT_V4 = "subquestion-premises-v4"
CONTRACT_V5 = "subquestion-premises-v5"
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


def subquestion_binding_reasons(record, claims, *, required=False,
                               answer_review_contract=CONTRACT, facts=()):
    if answer_review_contract not in {CONTRACT, CONTRACT_V2, CONTRACT_V3, CONTRACT_V4, CONTRACT_V5}:
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
            _negative_supported_v2(binding, selected,
                premise_version=(5 if answer_review_contract == CONTRACT_V5 else
                                 4 if answer_review_contract == CONTRACT_V4
                                 else 3 if answer_review_contract == CONTRACT_V3 else 2),
                facts=facts)[0]
            if answer_review_contract in {CONTRACT_V2, CONTRACT_V3, CONTRACT_V4, CONTRACT_V5}
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


_RESTATEMENT = re.compile(r'[,，]\s*(?P<link>即|i\.e\.|that\s+is)\s*', re.I)
_RESTATEMENT_SCOPE = re.compile(
    r'^\s*(?P<product>[A-Za-z][A-Za-z0-9 .\'-]*?\s+)?'
    r'(?P<plan>free|paid|premium|enterprise|business|standard|免费|付费)\s*'
    r'(?P<resource>organizations?(?![A-Za-z])|组织)', re.I)
_RESTATEMENT_PERMISSION = re.compile(
    rf'\s*(?:允许\s*用户(?:\s*与\s*(?:另外\s*)?(?:其他|{_COUNT}\s*(?:个|名|位)?\s*)?用户)?'
    r'\s*(?:存储并)?(?:安全)?(?:共享|分享)(?:数据|密码)'
    r'|allows?\s+users?\s+to\s+(?:store\s+and\s+)?(?:securely\s+)?share\s+(?:data|passwords?)'
    rf'(?:\s+with\s+(?:other\s+|another\s+|{_COUNT}\s+)?users?)?)\s*', re.I)
_RESTATEMENT_PEER_V4 = re.compile(
    rf'\s*仅支持与另外\s*{_COUNT}\s*(?:个|名|位)?用户'
    r'(?:存储并)?(?:安全)?(?:共享|分享)(?:数据|密码)\s*', re.I)


def _organization_alias_v4(text, identity):
    """Consume one complete, exactly equivalent plan/organization alias only."""
    tail = text[identity.end():]
    if not re.match(r'\s*[（(]', tail):
        return identity.end(), ''
    match = re.match(r'\s*(?P<quote>\((?P<ascii>[^()（）]+)\)|（(?P<cjk>[^()（）]+)）)', tail)
    alias = _RESTATEMENT_SCOPE.fullmatch(
        (match['ascii'] or match['cjk']).strip()) if match else None
    plans = {'免费': 'free', '付费': 'paid'}
    original_plan = plans.get(identity['plan'].casefold(), identity['plan'].casefold())
    if (not alias or alias['product']
            or plans.get(alias['plan'].casefold(), alias['plan'].casefold()) != original_plan):
        return None
    return identity.end() + match.end(), match['quote']


def _restated_count_action(text, cap, question, unit, *, premise_version=3):
    """Bridge only an explicit adjacent restatement of a finite organization rule.

    Every quote is taken from this complete published fact. Unrecognized subjects,
    packages, resources and user categories cannot establish this new witness.
    """
    if unit != 'people':
        return None
    links = [link for link in _RESTATEMENT.finditer(text) if link.end() <= cap.start()]
    if not links:
        return None
    link = links[-1]
    # Consume the complete antecedent region; earlier qualifiers cannot be
    # discarded merely because a recognized permission follows a delimiter.
    antecedent = text[:link.start()].strip()
    restatement = text[link.end():]
    # A later delimiter or sentence cannot supply this cap or its operation.
    if re.search(r'[,，。；;.!?？\n]', text[link.end():cap.start()]):
        return None
    if not re.fullmatch(r'[^,，。；;.!?？\n]+[。.!]?', restatement):
        return None
    left, right = _RESTATEMENT_SCOPE.match(antecedent), _RESTATEMENT_SCOPE.match(restatement)
    if not left or not right:
        return None
    plans = {'免费': 'free', '付费': 'paid'}

    def plan(value):
        return plans.get(value.casefold(), value.casefold())

    if plan(left['plan']) != plan(right['plan']):
        return None
    requested_plans = {plan(m.group()) for m in re.finditer(
        r'\b(?:free|paid|premium|enterprise|business|standard)\b|免费|付费', question, re.I)}
    if requested_plans != {plan(left['plan'])}:
        return None
    left_product, right_product = ((match['product'] or '').strip().casefold()
                                   for match in (left, right))
    if right_product and right_product != left_product:
        return None
    if left_product and not re.search(r'(?<![A-Za-z0-9])' + re.escape(left_product)
                                     + r'(?![A-Za-z0-9])', question, re.I):
        return None
    if (_scope_objects(antecedent) != {'organization'}
            or _scope_objects(restatement) != {'organization'}):
        return None
    left_end, right_end = left.end(), right.end()
    extra = {}
    if premise_version == 4:
        left_alias = _organization_alias_v4(antecedent, left)
        right_alias = _organization_alias_v4(restatement, right)
        if left_alias is None or right_alias is None:
            return None
        left_end, alias_quote = left_alias
        right_end, _ = right_alias
        if alias_quote:
            extra['organization_alias_quote'] = alias_quote
    left_tail = antecedent[left_end:]
    # Only an explicit generic-user permission and an organization user cap are
    # supported here. Other roles/labels and unknown categories remain unresolved.
    if not (_RESTATEMENT_PERMISSION.fullmatch(left_tail)
            or premise_version == 4 and _RESTATEMENT_PEER_V4.fullmatch(left_tail)):
        return None
    if premise_version == 4:
        peers = list(_count_occurrences(left_tail))
        if peers:
            raw = cap['n'].casefold()
            maximum = int(raw) if raw.isdigit() else _NUMBERS[raw]
            if len(peers) != 1 or peers[0][0] != 'people' or peers[0][1] + 1 != maximum:
                return None
            extra['peer_count'] = peers[0][1]
    if not re.fullmatch(
            r'\s*(?:(?:最多|至多|上限为?|仅限|不超过)(?:只能|仅能|可|可以)?'
            r'(?:使用|提供|拥有|包含|支持|容纳|允许)?|(?:supports?\s+)?(?:at\s+most|up\s+to|only))\s*',
            text[link.end() + right_end:cap.start()], re.I):
        return None
    # Inclusion of an owner is the only finite count-population annotation.
    # Unknown exclusions, grouping and active-user qualifiers must stay unknown.
    if not re.fullmatch(
            r'\s*(?:（含所有者）|\(including\s+(?:the\s+)?owner\))?[。.!]?\s*',
            text[cap.end():], re.I):
        return None
    from packages.agents.writer.answer_resolution import _SUBJECT

    for value in (antecedent, text[link.end():cap.end()], question):
        if any(match.lastgroup != 'generic' for match in _SUBJECT.finditer(value)):
            return None
    actions = _count_actions(antecedent)
    if not actions or _count_actions(restatement) - actions:
        return None
    return dict(actions=actions, cap_sentence=text, action_antecedent_quote=antecedent,
                cap_clause_quote=restatement, restatement_quote=link['link'], **extra)


def _permission_remainder_v4(text, actions):
    """Remove only a finite denied duty, preserving every independent obligation."""
    verbs = {'vote': '投票', 'download': '下载', 'export': '导出', 'import': '导入'}
    if len(actions) != 1 or not actions <= verbs.keys():
        return text, []
    verb = verbs[next(iter(actions))]
    actor = re.match(r'\s*([A-Za-z][A-Za-z0-9_-]*)\s+', text)
    subject = rf'(?:{re.escape(actor[1])}\s+)?' if actor else ''
    object_phrase = r'(?:每张|每个|所有|全部)?(?:卡片|附件|看板)'
    # One known subject, one must, one operation/object and a closed duty noun.
    # Arbitrary predicates on either side of must are never consumed.
    duty_pattern = (
        rf'\s*{subject}必须\s*(?:(?:对|给)\s*{object_phrase}\s*{verb}'
        rf'|{verb}(?:\s*{object_phrase})?)\s*的(?:强制)?义务'
    )
    quotes = []

    def denied(match):
        if not re.fullmatch(duty_pattern, match['duty']):
            return match.group()
        quotes.append(match.group())
        return ''

    remainder = re.sub(
        r'并?不(?:构成|意味|推出|蕴含)(?P<duty>[^,，。；;.!?？\n]{1,160}?义务)'
        r'(?=\s*(?:$|[,，。；;.!?？\n]))', denied, text)
    return remainder, quotes


_SOURCE_ORGANIZATION_V5 = (
    r'(?:[A-Za-z][A-Za-z0-9_-]*\s+)?'
    r'(?:Free|Paid|Premium|Enterprise|Business|Standard)\s+organizations?'
)
_SOURCE_CAP_V5 = re.compile(
    rf'\s*{_SOURCE_ORGANIZATION_V5}\s+'
    r'(?:offer(?:s)?\s+(?:both\s+users\s+all\s+the\s+core\s+features\s+of\s+'
    r'Password\s+Manager\s+and\s+)?|supports?\s+)'
    rf'(?:secure\s+)?data\s+sharing\s+in\s+up\s+to\s+{_COUNT}\s+collections?\s*\.?\s*', re.I)
_SOURCE_CONTEXT_V5 = re.compile(
    rf'\s*(?:Free\s+organizations?\s*\n\s*)?'
    rf'(?:Start\s+a\s+{_SOURCE_ORGANIZATION_V5}\s+to\s+store\s+and\s+securely\s+'
    r'share\s+data\s+with\s+one\s+other\s+user\.\s*)?'
    + _SOURCE_CAP_V5.pattern +
    r'(?:Any\s+user\s+of\s+any\s+plan\s+can\s+be\s+the\s+owner\s+of\s+one\s+'
    r'Free\s+organization\.\s*)?', re.I)


def _source_context_v5(fact):
    """A closed sharing-cap paragraph, including every parent qualifier.

    These transparent envelope fields supply no positive premise. Unknown
    dates, populations, exceptions, grouping or text remain unconsumed/rejected.
    """
    members = [fact.quote, *(fact.value if isinstance(fact.value, list) else [fact.value])]
    if any(not isinstance(text, str) or not (_SOURCE_CONTEXT_V5.fullmatch(text)
           or re.fullmatch(r'\s*(?:Password\s+Manager\s+Plans|Personal\s+plans)\s*', text, re.I))
           for text in members if text):
        return False
    qualifiers = fact.qualifiers
    if set(qualifiers) - {'operations', 'slot', 'source_scope'}:
        return False
    if not isinstance(qualifiers.get('operations', []), list):
        return False
    operations = list(qualifiers.get('operations', ()))
    scope = qualifiers.get('source_scope', {})
    if not isinstance(scope, dict) or set(scope) - {
            'captured_page_id', 'context', 'operations', 'raw_source_id', 'source_url'}:
        return False
    context = scope.get('context', {})
    if (not isinstance(context, dict)
            or set(context) - {'document_section', 'plan', 'role', 'section_path'}
            or any(context.get(key) is not None for key in ('plan', 'role', 'section_path'))):
        return False
    if not isinstance(scope.get('operations', []), list):
        return False
    operations.extend(scope.get('operations', ()))
    for operation in operations:
        if (not isinstance(operation, dict) or set(operation) - {
                'operation', 'effect', 'plan', 'role', 'access_scope', 'object_type',
                'object_quote', 'operation_quote', 'prerequisites', 'missing_fields'}
                or operation.get('operation') != 'share' or operation.get('effect') != 'allowed'
                or operation.get('plan') not in {None, 'Personal plans'}
                or any(operation.get(key) is not None
                       for key in ('role', 'access_scope', 'object_type', 'object_quote'))
                or set(operation.get('missing_fields', ())) - {'role', 'access_scope'}):
            return False
        quote = operation.get('operation_quote', '')
        if not isinstance(quote, str) or not (
                _SOURCE_CONTEXT_V5.fullmatch(quote) or re.fullmatch(
                    r'Start\s+a\s+Free\s+organization\s+to\s+store\s+and\s+securely\s+'
                    r'share\s+data\s+with\s+one\s+other\s+user\.?', quote, re.I)):
            return False
        for prerequisite in operation.get('prerequisites', ()):
            if (not isinstance(prerequisite, dict) or set(prerequisite) != {'kind', 'quote'}
                    or prerequisite['kind'] != 'plan'
                    or not _SOURCE_CONTEXT_V5.fullmatch(prerequisite['quote'])):
                return False
    return True


def _verified_cap_span_v5(row, facts):
    """Require a fact's own literal identity; no unbound-helper fallback."""
    from packages.research.evidence.report_claims import ReportClaim
    from packages.research.evidence.source_spans import projected_source_facts

    if row.get('kind') != 'fact':
        return None
    try:
        claim = ReportClaim.model_validate(row)
    except ValueError:
        return None
    if (len(claim.source_span_bindings) != 1
            or set(claim.source_ids) != {claim.source_span_bindings[0].source_id}):
        return None
    projected, reasons = projected_source_facts(claim, facts)
    if (reasons or not projected or any(
            (fact.competitor, fact.dimension) != (claim.competitor, claim.dimension)
            for fact in projected)):
        return None
    return claim, projected


def _source_cap_witness_v5(binding, selected, facts):
    """Intersect one published cap property with its own verified literal span."""
    from packages.agents.writer.answer_action_scope import _INVERTED

    parents = {fact.id: fact for fact in facts}
    for row in selected:
        verified = _verified_cap_span_v5(row, facts)
        if not verified:
            continue
        claim, projected = verified
        if any(not _source_context_v5(parents[fact.id]) for fact in projected):
            continue
        text = claim.text
        identity = _RESTATEMENT_SCOPE.match(text)
        counts = list(_count_occurrences(text))
        # The publication must itself state a maximum, for this single shared
        # collections property. Source text cannot turn a capability into a cap.
        if (not identity or len(counts) != 1 or counts[0][0] != 'collections'
                or _FINITE_UNSAFE.search(text) or _count_actions(text) != {'share'}
                or not _finite_scope_matches(binding.question_quote, text)):
            continue
        unit, maximum, count = counts[0]
        prefix = text[identity.end():count.start()]
        if not re.fullmatch(
                r'\s*(?:的)?(?:安全)?(?:数据)?共享(?:数据|密码)?\s*'
                r'(?:最多|至多|上限为?|不超过)\s*(?:(?:可|可以)(?:放入|容纳|支持)?)?\s*', prefix):
            continue
        if not re.fullmatch(r'\s*[。.]?\s*', text[count.end():]):
            continue
        subject = binding.question_quote
        inverted = _INVERTED.match(subject)
        if inverted:
            subject = subject[inverted.end():]
        question_scope = re.match(r'\s*([^:：?？\n]+)[:：]', subject)
        if question_scope:
            subject = subject[question_scope.end():]
        inverted = _INVERTED.match(subject)
        if inverted:
            subject = subject[inverted.end():]
        if re.match(r'\s*[^:：?？\n]+[:：]', subject):
            continue
        question_identity = _RESTATEMENT_SCOPE.match(subject)
        question_products = (question_scope[1] if question_scope else None,
                             question_identity['product'] if question_identity else None)
        for fact in projected:
            original = fact.quote
            source_identity = _RESTATEMENT_SCOPE.match(original)
            if (not _SOURCE_CAP_V5.fullmatch(original) or not source_identity
                    or identity['plan'].casefold() != source_identity['plan'].casefold()
                    or any(product and product.strip().casefold() != claim.competitor.casefold()
                           for product in (identity['product'], source_identity['product'],
                                           *question_products))):
                continue
            source_witness = finite_decision_witnesses(binding,
                [dict(id=claim.id, kind='fact', text=original)],
                premise_version=4).get('upper_bound')
            if (source_witness
                    and (source_witness['unit'], source_witness['maximum']) == (unit, maximum)):
                return dict(source_witness, published_cap_quote=text, source_cap_quote=original,
                    source_span_binding=claim.source_span_bindings[0].model_dump(mode='json'))
    return None


def finite_decision_witnesses(binding, selected, *, premise_version=2, facts=()):
    """Finite eligibility witnesses, reconstructed from whole published atoms.

    They do not replace source/schema or independent semantic review. No model
    witness, reason, unseen fact, or conditional fragment supplies a premise.
    """
    if premise_version == 5:
        witnesses = finite_decision_witnesses(binding, selected, premise_version=4)
        # V5 numeric decisions must be recheckable from real parent facts, even
        # when their published wording already qualifies through the v4 path.
        upper = witnesses.get('upper_bound')
        if not facts or upper and not any(
                row['id'] == upper['claim_id'] and _verified_cap_span_v5(row, facts)
                for row in selected):
            witnesses.pop('upper_bound', None)
        elif 'upper_bound' not in witnesses:
            witness = _source_cap_witness_v5(binding, selected, facts)
            if witness:
                witnesses['upper_bound'] = witness
        return witnesses
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
                    actions = _count_actions(cap_clause)
                    bridge = None
                    if premise_version in {3, 4} and not actions:
                        bridge = _restated_count_action(
                            text, cap, question, unit, premise_version=premise_version)
                        if bridge:
                            actions = bridge['actions']
                    if (wanted_unit == unit and maximum < required
                            and actions == _count_actions(request_clause)):
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
                                **({key: value for key, value in bridge.items() if key != 'actions'}
                                   if bridge else {}),
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
            denied_quotes = []
            if premise_version == 4:
                remainder, denied_quotes = _permission_remainder_v4(text, actions)
            else:
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
                            **({'denied_entailment_quotes': denied_quotes}
                               if premise_version == 4 else {}),
                        ),
                    )
    return witnesses


def _negative_supported_v2(binding, selected, *, premise_version=2, facts=()):
    if binding.relation in {'upper_bound', 'permission_entailment'}:
        witness = finite_decision_witnesses(binding, selected,
            premise_version=premise_version, facts=facts).get(binding.relation)
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


def canonical_subquestions_v2(rows, question, claims, parent_claim_ids, *,
                             premise_version=2, facts=()):
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
            valid, witness = _negative_supported_v2(
                binding, selected, premise_version=premise_version, facts=facts)
            if not valid and row['relation'] == 'explicit_negative':
                candidates = finite_decision_witnesses(
                    binding, selected, premise_version=premise_version, facts=facts)
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
            checks = resolution_reasons(local, _decision_question(row["question_quote"]), selected)
            valid = not [reason for reason in checks if not (
                premise_version == 5 and witness and witness['kind'] == 'upper_bound'
                and reason == 'answer_body_unresolved')]
            valid &= all(re.search(_ACTIONS[action], body, re.I)
                         for action in requested_answer_actions(row['question_quote']))
        if not valid:
            adjustments.append(dict(kind='branch_demoted', branch_index=index,
                original_conclusion=row['conclusion'], original_relation=row['relation']))
            row.update(claim_ids=[], conclusion='unknown', relation='unresolved')
        elif witness:
            witnesses.append(dict(branch_index=index, **witness))
    return canonical, dict(adjustments=adjustments, finite_witnesses=witnesses)
