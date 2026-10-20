"""Finite request-only questions; no product facts or evidence inference."""

import re

from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage

_META = re.compile(
    r'拼写|字符串|翻译|修辞|讨论引文|是什么意思|(?:字|文本|文字).{0,12}(?:颜色|红色)|'
    r'\b(?:spell(?:ing)?|translat\w*|meaning|definition|quoted (?:text|phrase)|font|text colou?r)\b|'
    r'\bwhat does\b[^?？]*\bmean\b', re.I)
_ACTION = re.compile(r'删掉|删除|移除|移出|取消共享|\b(?:delet\w*|remov\w*|unshare)\b', re.I)
_DATA = re.compile(r'密码|数据|保险库|条目|文件夹?|文档|\b(?:passwords?|data|vaults?|items?|files?|folders?|documents?)\b', re.I)
_TARGET = re.compile(r'同事|成员|用户|账户|账号|\b(?:colleagues?|members?|users?|accounts?)\b', re.I)
_OUTCOME = re.compile(r'留下|保留|留存|丢失|访问|看到|看不到|(?:会|是否).{0,16}删除|'
                      r'\b(?:remain\w*|retain\w*|keep|kept|lose|lost|access|deleted|will delete)\b', re.I)
_NAMED_ACTION = re.compile(
    r'\b(?:remov(?:e|ing)\s+(?:a\s+|the\s+)?members?|delet(?:e|ing)\s+(?:an?\s+|the\s+)?accounts?|unshare)\b|'
    r'从.{0,6}组织.{0,6}移除|(?:移除|移出).{0,6}组织|移除(?:组织)?成员|取消共享|永久删除.{0,8}(?:账户|账号|数据)|'
    r'(?:删除账户|删除账号|删除数据)', re.I)
_OWNERSHIP = re.compile(
    r'(?:个人|自己(?:的)?).{0,10}(?:密码|数据|保险库|账户|账号|条目|文件夹?|文档)|'
    r'组织(?:拥有|所有|数据)|(?:密码|数据|条目|文件夹?|文档).{0,8}(?:归|属于).{0,4}(?:组织|个人)|'
    r'\b(?:personal(?:ly)?[- ](?:owned|vault|data|passwords?)|organization[- ]owned|'
    r'(?:data|items?|passwords?)\s+(?:belong(?:s)? to|owned by)\s+(?:the\s+)?(?:organization|user))\b', re.I)

_QUESTIONS = {
    'actual_action': (
        '请确认具体操作：您准备移除成员，还是永久删除账户或数据？',
        'Please confirm the actual action: remove the member, or permanently delete an account or data?'),
    'data_ownership': (
        '请确认数据归属：相关数据属于个人，还是组织？',
        'Please confirm data ownership: does the data belong to the individual or the organization?'),
    'retained_copy': (
        '请确认您的副本选择：是否允许对方保留副本？',
        'Please confirm your copy choice: did you allow the other person to keep a copy?'),
    'access_path': (
        '请确认您要检查的访问路径：通过账户、同步设备，还是共享链接访问？',
        'Please confirm the access path to check: through the account, a synced device, or a shared link?'),
}


def request_clarification_fields(question):
    """Recognize explicit data-operation outcome requests, conservatively."""
    action = _ACTION.search(question)
    if (_META.search(question) or not action or not _DATA.search(question) or not _TARGET.search(question)
            or not _OUTCOME.search(question) or not re.search(r'[?？]|吗|是否|能否', question)):
        return ()
    # Instructions about performing the action remain research requests even
    # when a preceding offboarding clause already contains an action.
    if re.search(r'如何|怎样|怎么|\bhow (?:do|can|should|would|to)\b', question, re.I):
        return ()
    # A finite local question cannot deliver a separate coordinated request.
    if re.search(r'(?:以及|并且|另外|而且|同时)[^。?？;；\n]{0,100}(?:能否|可否|是否|吗)|'
                 r'\b(?:and|also)\s+(?:can|could|does|do|is|are|will|would|has|have|what|which|how)\b', question, re.I):
        return ()
    if not (re.search(r'后|会|仍|还|\b(?:after|once|following|will|would|still)\b', question[action.end():], re.I)
            or re.search(r'\b(?:after|once|following|will|would)\b', question[:action.start()], re.I)):
        return ()
    fields = []
    if not _NAMED_ACTION.search(question):
        fields.append('actual_action')
    if not _OWNERSHIP.search(question):
        fields.append('data_ownership')
    # Ask only about an explicitly missing user choice/path. Product questions
    # such as "does it retain a copy?" must remain research requests.
    uncertain = [clause for clause in re.split(r'[。.!?？;；，,]', question)
                 if re.search(r'尚未确定|未说明|未提供|不知道|不清楚|\b(?:unknown|unspecified|not specified)\b', clause, re.I)]
    if any(re.search(r'(?:用户|我|我们).{0,10}(?:是否选择|是否允许).{0,12}保留副本|'
                     r'\b(?:whether (?:I|we|the user) (?:chose|allowed)|(?:my|our) copy choice)\b', clause, re.I)
           for clause in uncertain):
        fields.append('retained_copy')
    if any(re.search(r'(?:哪条|哪个|何种).{0,8}(?:共享链接|访问路径)|'
                     r'\b(?:which (?:shared link|access path)|(?:my|our) access path)\b', clause, re.I)
           for clause in uncertain):
        fields.append('access_path')
    return tuple(fields)


def server_clarification_answer(question):
    """Rebuild the entire v3 record solely from current question identity/text."""
    fields = request_clarification_fields(question['question'])
    if not fields:
        return None
    zh = bool(re.search(r'[\u4e00-\u9fff]', question['question']))
    return ReportAnswerCoverage(
        question_id=question['question_id'], question=question['question'], binding_version=3,
        status='partial', resolution='clarification', conclusion='depends',
        claim_ids=(), evidence_spans=(), basis_snapshot_id=None, missing_fields=fields,
        answer=' '.join(_QUESTIONS[field][0 if zh else 1] for field in fields),
        reason=('当前请求缺少具体输入；请先确认以下问题。' if zh else
                'The current request lacks specific inputs; please confirm the following questions.'))


def clarification_rule_relevant(question, text):
    """A finite relevance gate for lifecycle rules, not a semantic proof."""
    if not (_ACTION.search(question) and _DATA.search(question) and _OUTCOME.search(question)):
        return True  # Other existing source-rule paths retain their guards.
    if _META.search(question) or not _DATA.search(text):
        return False
    # Mere same-product passwords, plan limits, and organization-owner roles
    # cannot establish deletion/retention or ownership of the requested data.
    return bool((_ACTION.search(text) and _OUTCOME.search(text)) or _OWNERSHIP.search(text)
                or re.search(r'\b(?:organizations? own|owned by the (?:individual )?user|'
                             r'belong to (?:the )?(?:members?|organization))\b|组织拥有|归个人', text, re.I))


def has_lifecycle_rule(question, claims):
    """Prefer the existing source path only when a real operation rule is present."""
    return any(clarification_rule_relevant(question, row['text']) and _ACTION.search(row['text'])
               and _DATA.search(row['text']) for row in claims)
