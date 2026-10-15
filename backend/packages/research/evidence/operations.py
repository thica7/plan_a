"""Source-bound document operations, without vendor-specific capability answers.

An operation label is a retrieval/projection hint, not a model of role hierarchy.
Unknown prerequisites remain unknown; statements about other roles are not merged.
"""
from __future__ import annotations

import re
from functools import lru_cache

from packages.research.evidence.snapshot_models import EvidenceFact, canonical_json
from packages.research.models import QualityGap

OPERATIONS = {
    'read': ('阅读', r'\b(?:views?|reads?|access)\s+(?:(?:the|a|all|any|workspace)\s+)*(?:pages?|documents?|docs?|items?|content)\b|(?:查看|阅读)(?:(?:该|此|这个|所有|全部|共享的|已分享的|现有的|的|在|中|内|里|文件夹|数据库|工作区)\s*){0,12}(?:页面|文档|条目|内容)'),
    'comment': ('评论', r'\bcomment(?:s|ing)?\b(?![- ]only)|评论|批注'),
    'edit': ('编辑', r'\bedit(?:s|ing)?\b|编辑|修改内容'),
    'create': ('创建', r'\bcreat(?:es?|ing)\s+(?:(?:a|new|the|any)\s+)*(?:(?:up to \d+|an unlimited number of)\s+)?(?:pages?|documents?|docs?|items?(?!\s+templates?)|content)\b|创建(?:(?:新的?|该|此|这个|所有|全部|的|在|中|内|里|文件夹|数据库|工作区)\s*){0,12}(?:页面|文档|条目|内容)(?!模板)'),
    'share': ('分享', r'\bshar(?:e|ing)\b|分享|共享链接'),
    'manage_access': ('权限管理', r'\b(?:manage|change|modify|set|assign|grant|revoke|adjust|create)\s+(?:(?:the|a|an|user(?:[’\']s)?|specific|different|general|new|view|and|edit|page|document|workspace|default|content|access)\s+)*(?:permissions?|roles?|access|restrictions?)\b|(?:管理|修改|更改|变更|设置|分配|授予|撤销)(?:[^。；\n]{0,16})(?:访问权限|访问级别|访问设置|权限)'),
}
ROLE_LABELS = r'Can comment|Can edit(?: content)?|Can view|Can create|Can manage(?: access)?|Full access|Comment-only|Read-only'
_ROLE = re.compile(r'\b(' + ROLE_LABELS + r'|Doc Makers?(?: \(Workspace admin\)s?)?|comment-only|read-only|(?:team |workspace )?(?:owners?|admins?|administrators?|members?|guests?)|editors?|viewers?|collaborators?|managers?)\b|仅评论|仅查看|编辑者|管理员|访客', re.I)
_PLAN = re.compile(r'\b(?:all plans|any plan|(?:paid|free|enterprise|business|professional|pro|standard|premium) plans?)\b|所有套餐|免费版|付费套餐|企业版', re.I)
_DENIED = re.compile(r"\bcannot\b|\bcan[’']t\b|\bcan not\b(?!\s+only\b)|\bwon[’']t be able to\b|\bwill not be able to\b|\bnot (?:start|begin|be) sharing\b|\bnot (?:allowed|available|supported|permitted|edit|share)\b|\bnot\s+(?:manage|change|modify|set|assign|grant|revoke|adjust)\s+(?:(?:the|a|an|general|user|document|page|workspace)\s+)*(?:access|permissions?|roles?|restrictions?)\b|\bunable to\b|不能|无法|不支持|不得", re.I)
_PREREQUISITE = re.compile(r'\bonly\b|\brequires?\b|\bneeds?\b|\bmust\b|\bunless\b|\bexcept\b|\bwithout\b|\b(?:after|before)\b|限制|需要|仅限|前提|除非', re.I)
_MODAL = r"cannot|can[’']t|can not|won[’']t be able to|will not be able to|will not(?=\s+be sharing)|can|may|must"
_ACCESS_CONTROL = re.compile(r'\b(?:restricts?|limits?|controls?|determines?)\s+(?:who|whether)\b[^.;\n]*|\b(?:restricts?|limits?)\s+access\b|\b(?:add|remove)\s+(?:a\s+)?restrictions?\b', re.I)
_CHOICE_INTRO = re.compile(r'\b(?:choose|select)\b[^:\n]*(?:share|access|permissions?|modes?|options?)[^:\n]*:\s*$|\b(?:access|permissions?)\b[^:\n]*\b(?:states|modes|options)\b[^:\n]*:\s*$', re.I)


def alternative_condition_blocks(text):
    """Only an original selector followed by a list establishes alternatives."""
    lines, blocks = text.splitlines(), []
    for index, line in enumerate(lines):
        if not _CHOICE_INTRO.search(line):
            continue
        options = []
        indent = None
        content_indent = None
        blank_lines = ''
        for option in lines[index + 1:]:
            if not option.strip():
                blank_lines += '\n'
                continue
            bullet = re.match(r'^(\s*)[-*]\s+', option)
            nested = bullet and indent is not None and len(bullet[1]) > indent
            continued = (not bullet and content_indent is not None
                         and len(option) - len(option.lstrip()) >= content_indent
                         and not re.match(r'^\s*#{1,6}(?:\s|$)', option))
            if nested or continued:
                # Blank lines belong to a branch only when a following line
                # proves that its list indentation continues.
                options[-1] += '\n' + blank_lines + option.rstrip()
                blank_lines = ''
                continue
            if not re.match(r'^\s*[-*]\s+[^:]+\s*:', option) or re.match(r'^\s*[-*]\s+(?:' + ROLE_LABELS + r')\s*:', option, re.I):
                break
            if indent is None:
                indent = len(bullet[1])
            elif len(bullet[1]) != indent:
                break
            options.append(option.strip())
            content_indent = bullet.end()
            blank_lines = ''
        if len(options) >= 2:
            blocks.append('\n'.join([line.strip(), *options]))
    return list(dict.fromkeys(blocks))


def _condition_groups(terms):
    return [dict(operator='any_of', options=re.split(r'\n(?=[-*]\s)', block.split('\n', 1)[1]))
            for block in dict.fromkeys(block for term in terms for block in alternative_condition_blocks(term))]


def _plan_from_text(text):
    names = r'Team/Business|Enterprise|Business|Professional|Standard|Premium|Team|Free|Pro'
    match = re.search(r'\b((?:' + names + r')(?:(?:,?\s+(?:and|or)\s+|,\s*)(?:' + names + r'))*)\s+(?:plans?|only)\b', text, re.I)
    if match and re.search(r'\band\b|\bor\b|,|Team/Business', match[1], re.I):
        return match[1]
    simple = _PLAN.search(text)
    return simple.group() if simple else match[1] if match else None


def _permission_table_rows(fact, terms, conditions):
    def cells(line):
        return [cell.strip() for cell in line.strip().strip('|').split('|')]
    lines = fact.quote.strip().splitlines()
    row = cells(lines[-1])
    headers = list(dict.fromkeys(tuple(cells(line)) for term in terms for line in term.splitlines()
        if line.strip().startswith('|') and len(cells(line)) == len(row)
        and all(_ROLE.fullmatch(cell) for cell in cells(line)[1:])))
    if len(headers) != 1 or len(row) < 2:
        return []
    header = headers[0]
    label = row[0]
    target = re.search(r'\b(pages?|documents?|docs?|items?|workspaces?|content|comments?)\b', label, re.I)
    if not target:
        return []
    obj = target.group()
    scope = ('document' if re.fullmatch(r'documents?|docs?|pages?', obj, re.I) else
             'item' if re.fullmatch(r'items?', obj, re.I) else
             'workspace' if re.fullmatch(r'workspaces?', obj, re.I) else
             'comment' if re.fullmatch(r'comments?', obj, re.I) else 'content')
    actions = [op for op in OPERATIONS if operation_matches_text(op, label)]
    if scope == 'comment':
        actions = ['comment'] if re.search(r'\b(?:add|leave|post)\b', label, re.I) else []
    rows = []
    for role, cell in zip(header[1:], row[1:]):
        marker = re.fullmatch(r'(✅|✖️?|❌|Yes|No)(?:\s+(\([^\n]+\)|\*))?', cell, re.I)
        if not marker:
            continue
        # A star cannot be dropped: retain all original footnote lines.
        footnotes = fact.qualifiers.get('table_context', [])[1:]
        if marker[2] == '*' and not footnotes:
            continue
        plan = _availability_plan(role, conditions)
        prerequisites = [{'kind': 'other', 'quote': value} for value in
                         [*([cell] if marker[2] and marker[2] != '*' else []), *(footnotes if marker[2] == '*' else [])]]
        for op in actions:
            rows.append(dict(operation=op, effect='allowed' if marker[1].casefold() in {'✅','yes'} else 'denied',
                role=role, plan=plan, access_scope=scope, object_type='page' if re.fullmatch(r'pages?',obj,re.I) else scope,
                object_quote=obj, prerequisites=prerequisites, condition_evidence=list(conditions),
                quote=fact.quote, operation_quote=lines[-1], missing_fields=[] if plan else ['plan'],
                fact_id=fact.id, source_id=fact.source_id, competitor=fact.competitor))
    return rows


def _availability_plan(role, conditions, operation=None, object_type=None):
    candidates = []
    branches = []
    for term in conditions:
        lines = term.splitlines()
        for index, line in enumerate(lines):
            if operation:
                for clause in re.split(r'[.;\n]', line):
                    if (re.match(r'^\W*On (?:the )?[^,]+,\s*you can\b', clause, re.I)
                            and not any(not match.group().lower().startswith('can ') for match in _ROLE.finditer(clause))
                            and operation_matches_text(operation, clause)
                            and not _DENIED.search(clause)):
                        if branch_plan := _plan_from_text(clause):
                            target = re.search(r'\b(pages?|documents?|docs?|items?|workspaces?|content)\b', clause, re.I)
                            obj = target.group().casefold() if target else ''
                            branch_object = ('page' if re.fullmatch(r'pages?', obj) else
                                'document' if re.fullmatch(r'documents?|docs?', obj) else
                                'item' if re.fullmatch(r'items?', obj) else
                                'workspace' if re.fullmatch(r'workspaces?', obj) else
                                'content' if obj == 'content' else None)
                            if object_type and branch_object == object_type:
                                branches.append(branch_plan)
            if re.match(r'^\W*Available (?:on|to)\s*$', line, re.I) and index + 1 < len(lines):
                line += '\n' + lines[index + 1]
            direct = re.match(r'^\W*(?:Available (?:on|to)|Availability:|适用于)', line, re.I)
            enumerated = re.search(r'\b(?:are|is) available on\b', line, re.I)
            if not (direct or enumerated):
                continue
            roles = [m.group().casefold() for m in _ROLE.finditer(line)]
            if enumerated and not roles:
                continue
            if roles and (not role or not any(r == role.casefold() for r in roles)):
                continue
            if len(set(m.group().casefold() for m in _PLAN.finditer(line))) > 1 and len(set(roles)) > 1:
                continue
            if plan := _plan_from_text(line):
                candidates.append(plan)
    candidates = list(dict.fromkeys(candidates))
    if candidates:
        return candidates[0] if len(candidates) == 1 else None
    return ' / '.join(dict.fromkeys(branches)) if branches else None


def required_operations(topic: str, use_cases=()) -> tuple[str, ...]:
    focus = ' '.join((topic, *use_cases))
    if re.search(r'权限|访问控制|\bpermissions?\b|\broles?\b|access boundaries|access control', focus, re.I):
        return tuple(OPERATIONS)
    return tuple(key for key, (_, pattern) in OPERATIONS.items() if re.search(pattern, focus, re.I))


def operation_repair_rounds(topic, use_cases, dimension, *, enabled, depth_rounds):
    if enabled and dimension == 'feature' and required_operations(topic, use_cases):
        return max(1, depth_rounds)
    return depth_rounds if enabled else 0


def operation_matches_text(operation, text):
    action = re.sub(r"[\"'“‘](?:" + ROLE_LABELS + r")[\"'”’]", '', text, flags=re.I)
    action = re.sub(r'^\s*(?:[-*]\s*)?(?:' + ROLE_LABELS + r')\s*:', '', action, flags=re.I)
    action = re.split(r'\bwithout\b|\b(?:only\s+)?(?:after|before|unless|when|if)\b|\brequires?\b|无需|不必|仅当|前提是|除非', action, maxsplit=1, flags=re.I)[0]
    if operation == 'manage_access' and _ACCESS_CONTROL.search(action):
        return True
    if operation != 'manage_access':
        # Configuring who may act is an access-control action. The nested verb
        # does not assert that the configuring person can perform that action.
        action = _ACCESS_CONTROL.sub('', action)
    if operation == 'read':
        action = re.sub(r'\bviews?\s+and\s+comments?\s+on\s+', 'view ', action, flags=re.I)
    if operation == 'comment' and not re.search(
        rf'\bcomment(?:s|ing)?\s+on\b|\b(?:{_MODAL}|to)\s+comment\b|'
        r'\b(?:add|leave|post|write|make)\s+(?:(?:a|an|the|new|inline|your|own|any)\s+)*comments?\b|'
        r'发表评论|添加(?:行内|页面)?评论|留下评论|(?:可以|只能|不能|允许|支持)(?:(?:直接|仅|仅仅|进行)|(?:查看|阅读)(?:并|和|及))?(?:评论|批注)|'
        r'(?:对|为)[^。；，\n]{0,18}(?:评论|批注)', action, re.I):
        return False
    if operation == 'edit':
        action = re.sub(r'\b(?:view\s+and\s+)?edit\s+(?:(?:the|a|an|your|access|view|content|user)\s+)*(?:restrictions?|permissions?|access)\b', '', action, flags=re.I)
    if operation == 'create':
        action = re.sub(r'\bcreates?\s+(?:and|or)\s+(?:deletes?|edits?)\s+', 'create ', action, flags=re.I)
        action = re.sub(r'创建(?:和|或|并)(?:编辑|删除)', '创建', action)
    if operation == 'share':
        action = re.sub(r'\bshar(?:e|ing)\s+(?:dialogs?|settings?|menus?|buttons?|options?|icons?)\b', '', action, flags=re.I)
        action = re.sub(r'\b(?:start|begin|be)\s+sharing\s+(?:(?:a|an|the|your|any|shared)\s+)*(?=(?:documents?|docs?|pages?|items?|content)\b)', 'share ', action, flags=re.I)
        action = re.sub(r'\bsharing\b', '', action, flags=re.I)
        action = re.sub(r'\b(?:select(?:ing)?|click(?:ing)?)\s+(?:on\s+)?(?:(?:the|a|an)\s+)?Share(?:\s+(?:button|menu|option))?\b', '', action, flags=re.I)
        action = re.sub(r'\b(?:trying|attempting|want(?:ing)?|wish(?:ing)?)\s+to\s+share\b', '', action, flags=re.I)
    if operation in {'edit', 'share'}:
        verb = r'edit(?:ing)?' if operation == 'edit' else r'shar(?:e|ing)'
        zh_verb = '编辑' if operation == 'edit' else '分享'
        action = re.sub(rf'\b{verb}\s+(?:(?:a|an|the|your|own|any)\s+)*(?:comments?|repl(?:y|ies)|profiles?|settings?)\b|{zh_verb}(?:评论|回复|个人资料)', '', action, flags=re.I)
        explicit_document = re.search(rf'\b{verb}\s+(?:(?:a|an|the|your|own|any|shared|same)\s+)*(?:pages?|documents?|docs?|content)\b|{zh_verb}(?:页面|文档|内容)', action, re.I)
        if not explicit_document and not _DENIED.search(action):
            # Source-local references can name the comment before the verb,
            # e.g. "the comment you'd like to edit" / "comment and edit text".
            action = re.sub(rf'\b(?:comments?|repl(?:y|ies))\b[^.;\n]{{0,65}}\b{verb}\b|(?:评论|回复)[^。；\n]{{0,35}}{zh_verb}', '', action, flags=re.I)
    return bool(re.search(OPERATIONS[operation][1], action, re.I))


def _operation_prerequisites(clause, conditions, operation, role, groups):
    alternatives = {line.strip() for group in groups for option in group['options'] for line in option.splitlines()}
    # A legacy capture can omit the selector while retaining the contrasting
    # invited-only/public-link option definitions. A generic Eligibility line
    # supplies no evidence of that option structure.
    isolated = {}
    for item in conditions:
        for line in item.splitlines():
            match = re.match(r'^\s*[-*]\s+(Only\s+[^:]*invited|Anyone\s+[^:]*(?:link|web)|Everyone\s+[^:]*(?:workspace|organization|team)[^:]*)\s*:\s*This means\b.*\baccess\b', line, re.I)
            if match:
                isolated[line.strip()] = match[1].split()[0].casefold()
    if 'only' in isolated.values() and any(kind in {'anyone','everyone'} for kind in isolated.values()):
        alternatives.update(isolated)
    terms = dict.fromkeys(line.strip() for item in [*([clause] if _PREREQUISITE.search(clause) else []), *conditions] for line in item.splitlines())
    prerequisites = []
    for term in terms:
        if term in alternatives or _CHOICE_INTRO.search(term):
            continue
        # An existential count of member categories describes the role taxonomy.
        # "Only invited members can create" still states actual eligibility.
        if member_classification(term) or re.search(r'\?\s*$', term):
            continue
        introduction = re.match(r'\s*This (?:page|article|guide)\s+(?:answers|describes|explains|covers)\b', term, re.I)
        explicit_requirement = re.search(
            r'\bmust\b|\brequires?\b|\bneeds?\s+(?:to|access|permissions?|the|a|an)\b|'
            r'\bonly\b[^.;\n]*\b(?:can|may|allowed|permitted)\b|\bonly\s+(?:after|before|if|when|unless)\b|'
            r'parent|ancestor|父级|上级|需要|仅限|前提', term, re.I)
        if introduction and not explicit_requirement:
            continue
        if not (_PREREQUISITE.search(term) or _PLAN.search(term) or _DENIED.search(term)):
            continue
        before = re.search(r'\bbefore\s+(.+)', term, re.I)
        bound_requirement = _PREREQUISITE.search(term) and (operation_matches_text(operation, term)
            or before and operation_matches_text(operation, before[1]))
        if operation != 'manage_access' and (_ACCESS_CONTROL.search(term)
                or operation_matches_text('manage_access', term)) and not bound_requirement:
            continue
        # An adjacent operation/role rule cannot become this action's universal
        # prerequisite. Operation-free access/parent requirements still apply.
        actions = {key for key in OPERATIONS if operation_matches_text(key, term)}
        access_requirement = _PREREQUISITE.search(term) and re.search(
            r'\b(?:must|need(?:s)?|require(?:s)?)\s+(?:(?:to|have|be|given|granted|the)\s+)*access\b|'
            r'\bonly\b[^.;\n]*\b(?:can|may)\s+access\b|parent|ancestor|父级|上级', term, re.I)
        named = re.match(r'^\s*(?:[-*]\s*)?(' + ROLE_LABELS + r')\s*:', term, re.I)
        necessity = re.search(r'\bmust\b|\brequires?\b|\bneeds?\s+(?:to|access|permissions?|the|a|an)\b|限制|需要|仅限|前提|除非', term, re.I)
        eligibility = re.search(r'\bonly\b[^.;\n]*\b(?:can|may|allowed|permitted)\b', term, re.I)
        conditional = (re.match(r'^\W*(?:only\s+)?(?:if|when|unless|except|after|before|without)\b', term, re.I)
            or operation in actions and re.search(r'\b(?:if|when|unless|except|after|before|without)\b', term, re.I))
        # A description of who can configure a role is not a prerequisite for
        # the nested view/comment action. Keep the original as review context.
        if re.search(r'\bcan\s+(?:decide|choose|determine)\s+(?:which|who|whether)\b', term, re.I):
            continue
        if not (named or _PLAN.search(term) or _DENIED.search(term) or necessity
                or eligibility or conditional or access_requirement):
            continue
        actor = _ROLE.search(term)
        capability = re.search(r'\bcan\b|\bmay\b', term, re.I)
        grant_before_action = (before and operation_matches_text(operation, before[1])
            and re.search(r'\bmust\s+(?:grant|give)\b[^.;\n]*\baccess\b', term, re.I))
        access_requirement = access_requirement or grant_before_action
        if (role is not None and actor and capability and actor.start() < capability.start()
                and actor.group().casefold().rstrip('s') != (role or '').casefold().rstrip('s')
                and not (role or '').casefold().startswith(actor.group().casefold())
                and term.rstrip('.') != clause.rstrip('.')
                and not access_requirement):
            continue
        if actions and operation not in actions and not access_requirement:
            continue
        if named and (not role or named[1].casefold() != role.casefold()):
            continue
        if re.search(r'parent|ancestor|父级|上级', term, re.I):
            kind = 'parent_access'
        elif re.search(r'shared with|invited|分享给|受邀', term, re.I):
            kind = 'shared_access'
        elif re.search(r'permission|access|权限|访问', term, re.I):
            kind = 'permission'
        elif _PLAN.search(term):
            kind = 'plan'
        else:
            kind = 'other'
        prerequisites.append({'kind': kind, 'quote': term})
    return prerequisites


def member_classification(text):
    return bool(re.search(r'\b(?:we\s+(?:only\s+)?have|there\s+are)\b', text, re.I)
        and re.search(r'\b(?:types|kinds|categories)\s+of\s+(?:members?|roles?)\b|\bmember\s+types\b', text, re.I)
        and not any(operation_matches_text(key, text) for key in OPERATIONS)
        and not re.search(r'\brequires?\b|\bneeds?\b|\bmust\b|\bunless\b|\bbefore\b|\bafter\b', text, re.I))


@lru_cache(maxsize=4096)
def _observations_json(fact, products):
    from packages.business_intel.entity_resolver import resolve_competitor_identity
    if fact.dimension != 'feature' or fact.field != 'evidence_terms' or fact.status != 'supported':
        return '[]'
    terms = [fact.quote, *(term for term in fact.value if isinstance(term, str))] if isinstance(fact.value, list) else [fact.quote]
    target = resolve_competitor_identity(fact.competitor)
    for term in terms:
        for product in products:
            if product.casefold() != fact.competitor.casefold() and re.search(r'(?<!\w)' + re.escape(product) + r'(?!\w)' if product.isascii() else re.escape(product), term, re.I):
                return '[]'
        for word in re.findall(r'\b[A-Za-z][A-Za-z0-9]*\b', term):
            identity = resolve_competitor_identity(word)
            if identity and identity.canonical_name.casefold() != (target.canonical_name if target else fact.competitor).casefold():
                return '[]'
    conditions = tuple(dict.fromkeys(term for term in terms if term != fact.quote))
    groups = _condition_groups(terms)
    cells = [cell.strip() for cell in fact.quote.strip().strip('|').split('|')]
    role_definition = fact.quote.strip().startswith('|') and len(cells) == 2 and _ROLE.fullmatch(cells[0])
    if fact.quote.strip().startswith('|') and not role_definition:
        rows = _permission_table_rows(fact, terms, conditions)
        stored = fact.qualifiers.get('operations')
        return canonical_json(rows) if stored is None or stored == _structured_rows(rows) else '[]'
    rows = []
    heading_role = None
    for term in terms:
        if fact.quote in term and term != fact.quote:
            prefix = term[:term.index(fact.quote)].rstrip().splitlines()
            if prefix and _ROLE.fullmatch(prefix[-1].strip().rstrip(':')):
                heading_role = prefix[-1].strip().rstrip(':')
                break
    # Negation is local to an action clause. A restriction on editing must not
    # turn an earlier affirmative comment permission into a denial.
    clauses = re.split(rf"[.;\n。；]|\bbut\b|\bhowever\b|\bwhile\b|\bwhereas\b|但是|但|然而|\band\s+(?=(?:{_MODAL}|guests|members|editors|viewers|admins|owners)\b)", fact.quote, flags=re.I)
    previous_role, previous_plan, previous_scope = heading_role, None, None
    for clause in clauses:
        label = re.match(r'^\s*\|\s*(' + _ROLE.pattern + r')\s*\|', clause, re.I) if role_definition else re.match(r'^\s*(?:[-*]\s*)?(' + ROLE_LABELS + r')\s*:', clause, re.I)
        action_clause = clause[label.end():] if label else clause
        explicit_role = next((match for match in _ROLE.finditer(clause)
            if not match.group().lower().startswith('can ')
            or re.match(r'\s*[:|]', clause[match.end():])
            or re.match(r'\s+(?:role|access)\b', clause[match.end():], re.I)), None)
        modal = re.search(rf"\b(?:{_MODAL})\b", action_clause, re.I)
        control = _ACCESS_CONTROL.search(action_clause)
        if control and modal and control.start() < modal.start():
            modal = None  # "restrict who can edit" has a nested modal.
        if label:
            modal = None
        if explicit_role and modal and explicit_role.start() > modal.start():
            # A recipient named after the action is not its acting role.
            explicit_role = None
        continuation = bool(re.match(rf"\s*(?:they|it|people with this level(?: of access)?|{_MODAL})\b", clause, re.I))
        role = label[1] if label else explicit_role.group() if explicit_role else previous_role if continuation else None
        if explicit_role and modal and explicit_role.start() < modal.start():
            role = _PLAN.sub('', clause[explicit_role.start():modal.start()]).strip()
            role = re.sub(r'\s+on\s*$', '', role, flags=re.I).strip()
        same_role = bool(role and role.casefold() == (previous_role or '').casefold())
        plan = _plan_from_text(clause) or (previous_plan if same_role else None)
        if not plan and label and not _ROLE.search(fact.quote[label.end():]):
            plan = _plan_from_text(fact.quote)
        action_text = action_clause[modal.end():] if modal else action_clause
        scope = ('document' if re.search(r'\b(?:pages?|documents?|docs?)\b|页面|文档', action_text, re.I)
                 else 'item' if re.search(r'\bitems?\b', action_text, re.I)
                 else 'workspace' if re.search(r'\bworkspaces?\b|工作区', action_text, re.I)
                 else previous_scope if same_role and re.search(r'\bcontent\b|内容', action_text, re.I)
                 else 'content' if re.search(r'\bcontent\b|内容', action_text, re.I)
                 else previous_scope if same_role else None)
        target_match = re.search(r'\b(database propert(?:y|ies)|(?:person|created by) propert(?:y|ies)|pages?|documents?|docs?|items?|collections?|rows?|cells?|workspaces?|content)\b|页面|文档|数据库属性|工作区|内容', action_text, re.I)
        if target_match is None:
            target_match = re.search(r'\b(comments?|threads?)\b|评论', action_text, re.I)
        object_quote = target_match.group() if target_match else None
        object_type = ('page' if object_quote and re.fullmatch(r'pages?|页面', object_quote, re.I)
                       else 'document' if object_quote and re.fullmatch(r'documents?|docs?|文档', object_quote, re.I)
                       else 'database_property' if object_quote and re.search(r'propert|属性', object_quote, re.I)
                       else 'table_row' if object_quote and re.fullmatch(r'rows?', object_quote, re.I)
                       else 'table_cell' if object_quote and re.fullmatch(r'cells?', object_quote, re.I)
                       else 'comment' if object_quote and re.fullmatch(r'comments?|评论', object_quote, re.I)
                       else 'comment_thread' if object_quote and re.fullmatch(r'threads?', object_quote, re.I)
                       else 'collection' if object_quote and re.fullmatch(r'collections?', object_quote, re.I)
                       else scope)
        if object_type in {'database_property', 'table_row', 'table_cell', 'comment', 'comment_thread', 'collection'}:
            scope = object_type
        # Only source-local availability rules can supply a missing plan; an
        # unrelated role-specific restriction cannot establish this role's plan.
        if not plan:
            plan = _availability_plan(role, conditions)
        condition_evidence = list(dict.fromkeys([*([clause.strip()] if _PREREQUISITE.search(clause) else []), *conditions]))
        for operation in OPERATIONS:
            if not operation_matches_text(operation, action_text):
                continue
            if operation != 'comment' and object_type in {'comment', 'comment_thread'}:
                continue
            operation_plan = plan or _availability_plan(role, conditions, operation, object_type)
            prerequisites = _operation_prerequisites(clause.strip(), conditions, operation, role, groups)
            control_object = re.search(r'\b(?:permissions?|access|restrictions?)\b', action_text, re.I) or _ACCESS_CONTROL.search(action_text) if operation == 'manage_access' else None
            rows.append({'operation': operation, 'effect': 'denied' if _DENIED.search(clause) else 'allowed',
                'role': role, 'plan': operation_plan, 'access_scope': scope,
                'object_type': 'access_control' if control_object else object_type,
                'object_quote': control_object.group() if control_object else object_quote,
                'prerequisites': prerequisites, 'condition_evidence': condition_evidence,
                **({'condition_groups': groups} if groups else {}),
                'quote': fact.quote, 'operation_quote': clause.strip(),
                'missing_fields': [key for key, value in (('role', role), ('plan', operation_plan), ('access_scope', scope)) if not value],
                'fact_id': fact.id, 'source_id': fact.source_id, 'competitor': fact.competitor})
        previous_role, previous_plan, previous_scope = role, plan, scope
    stored = fact.qualifiers.get('operations')
    if stored is not None:
        computed = _structured_rows(rows)
        if stored != computed:
            return '[]'
    return canonical_json(rows)


def operation_observations(fact, products=()) -> list[dict]:
    import json
    return json.loads(_observations_json(fact, tuple(sorted(products))))


def operation_binding(observation):
    """Stable derived identity; never insert synthetic IDs into source quotations."""
    import hashlib
    keys = ('fact_id', 'source_id', 'competitor', 'operation', 'object_type', 'object_quote',
            'role', 'plan', 'access_scope', 'effect', 'prerequisites', 'condition_evidence', 'operation_quote')
    bound = {key: observation[key] for key in keys}
    if observation.get('condition_groups'):
        bound['condition_groups'] = observation['condition_groups']
    bound['dimension'] = 'feature'
    return {'observation_id': 'operation-' + hashlib.sha256(canonical_json(bound).encode()).hexdigest()[:24], **bound}


def bound_operation_observation(claim, facts, products=()):
    """An explicit binding must equal one entire original, source-local row."""
    binding = claim.operation_binding
    if binding is None or claim.dimension != 'feature':
        return None
    values = binding.model_dump(mode='json')
    if (claim.fact_ids != (binding.fact_id,) or claim.source_ids != (binding.source_id,)
            or claim.competitor != binding.competitor or claim.dimension != binding.dimension):
        return None
    fact = facts.get(binding.fact_id)
    if fact is None or fact.source_id != binding.source_id or fact.competitor != claim.competitor:
        return None
    return next((row for row in operation_observations(fact, products)
                 if operation_binding(row) == values), None)


def _structured_rows(rows):
    # The original quote/context already belongs to the containing fact. Keep
    # operation clauses and prerequisite spans without duplicating whole pages.
    return [{key: value for key, value in row.items()
             if key not in {'fact_id', 'source_id', 'competitor', 'quote', 'condition_evidence'}} for row in rows]


def structured_operations(quote, terms, competitor, *, table_context=()):
    """Deterministic structure reparsed by admission, never model assertions."""
    fact = EvidenceFact(id='structure', semantic_id='structure', source_id='structure',
        competitor=competitor, dimension='feature', field='evidence_terms', value_json=canonical_json(terms),
        quote=quote, status='supported', confidence=1,
        qualifiers_json=canonical_json({'table_context': list(table_context)}) if table_context else '{}')
    return _structured_rows(operation_observations(fact))


def operation_alignment(view, products, required=()) -> list[dict]:
    groups = {}
    for fact in view.facts:
        if fact.source_id not in view.source_ids or fact.competitor not in products:
            continue
        for observation in operation_observations(fact, products):
            groups.setdefault(observation['operation'], {}).setdefault(fact.competitor, []).append(observation)
    rows = []
    for key in required or tuple(OPERATIONS):
        evidence = groups.get(key, {})
        statuses = {product: 'documented' if product in evidence else 'unknown' for product in products}
        missing = [product for product, status in statuses.items() if status == 'unknown']
        signatures = {(row['role'], row['plan'], row['access_scope'], row['object_type'], row['effect'], tuple(row['condition_evidence']))
                      for observations in evidence.values() for row in observations}
        incomplete = any(row['missing_fields'] or row['effect'] == 'mixed' for observations in evidence.values() for row in observations)
        state = ('insufficient_evidence' if missing else 'needs_condition_review' if incomplete or len(signatures) != 1 else 'comparable')
        rows.append({'operation': key, 'comparison_status': state, 'product_statuses': statuses,
            'observations_by_product': evidence, 'missing_products': missing})
    return rows


def operation_gaps(brief, evidence_items) -> list[QualityGap]:
    required = required_operations(brief.topic, brief.product_use_cases) if brief.dimension == 'feature' else ()
    if not required:
        return []
    facts = []
    for item in evidence_items:
        if item.status != 'accepted' or item.competitor != brief.competitor or item.dimension != brief.dimension or not isinstance(item.value, dict):
            continue
        if item.value.get('status') not in {'supported', 'documented'}:
            continue
        facts.append(EvidenceFact(id=item.id, semantic_id=item.id, source_id=item.captured_page_id,
            competitor=item.competitor, dimension=item.dimension, field='evidence_terms',
            value_json=canonical_json(item.value.get('evidence_terms', [])),
            qualifiers_json=canonical_json({'operations': item.value['operations'],
                **({'table_context': item.value['table_context']} if item.value.get('table_context') else {})} if 'operations' in item.value else {}),
            quote=item.quote, status='supported', confidence=item.confidence))
    observations = [row for fact in facts for row in operation_observations(fact, [brief.competitor])]
    gaps = []
    for operation in required:
        matched = [row for row in observations if row['operation'] == operation]
        # One complete, internally consistent observation is sufficient to close
        # this retrieval gap; cross-product role equivalence is a later check.
        if any(not row['missing_fields'] and row['effect'] != 'mixed' for row in matched):
            continue
        missing = ['operation_evidence'] if not matched else sorted(set.intersection(*(set(row['missing_fields']) for row in matched)))
        if not missing:
            missing = ['consistent_operation_conditions']
        gaps.append(QualityGap(severity='warn', dimension='feature', competitor=brief.competitor,
            field=f'operation.{operation}', reason=f'{operation}: missing source-bound {", ".join(missing)}.',
            suggested_action='targeted_discovery', acceptance_rule='Capture the same operation with its role, plan, access scope and restrictions; unknown is not unsupported.',
            source_ids=sorted({row['source_id'] for row in matched}), metadata={'source': 'operation_comparison', 'operation': operation,
                'missing_fields': missing, 'product_category': brief.product_category}))
    return gaps
