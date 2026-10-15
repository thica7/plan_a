"""Read-only projections of the complete observations in a consumption view."""

def observation_facts(view, product, dimension):
    field = {'pricing': 'price', 'feature': 'evidence_terms'}.get(dimension)
    return [fact for fact in view.facts
            if fact.competitor == product and fact.dimension == dimension
            and fact.field == field and fact.status == 'supported'
            and fact.id in view.fact_ids and fact.source_id in view.source_ids]


def matrix_fact_value(view, product, dimension):
    if dimension not in {'feature', 'pricing'}:
        return None
    facts = observation_facts(view, product, dimension)
    if not facts:
        return '当前消费视图没有可支持此维度的正式观察。'
    rows = []
    for fact in facts:
        if dimension == 'pricing':
            # Preserve plan, amount, seat, currency and billing interval together.
            labels = {'currency': '币种', 'amount_basis': '计费单位', 'amount_period': '显示周期',
                      'billing_interval': '付款周期', 'seat_type': '席位类型', 'tax_scope': '税费',
                      'market': '地区', 'verified_at': '采集时间', 'quoted_user_count': '页面报价人数'}
            conditions = '；'.join(f'{label}：{fact.qualifiers.get(key, "unknown")}'
                                  for key, label in labels.items())
            rows.append(f'{fact.qualifiers.get("plan", "unknown")}：{fact.value}；{conditions}；原文：{fact.quote}')
        else:
            terms = fact.value if isinstance(fact.value, list) else []
            rows.append('原文：' + fact.quote + '；完整条件：' + '；'.join(
                term for term in terms if isinstance(term, str) and term != fact.quote))
    return '\n'.join(dict.fromkeys(rows))


def analysis_fact_refs(view):
    """Derived prose is not another evidence authority; refer to bound originals."""
    branches = {}
    for fact in view.facts:
        branches.setdefault((fact.competitor, fact.dimension), []).append(fact.id)
    return {'verified_analysis_branches': [
        {'competitor': product, 'dimension': dimension, 'evidence_fact_refs': sorted(ids)}
        for (product, dimension), ids in sorted(branches.items())]}
