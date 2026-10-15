"""Caller-declared retrieval facts and conservative output-format separation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.knowledge.ingestion import IngestionPipeline
from packages.knowledge.models import DocumentCreate, RetrievalIntent, RetrievalRequest
from packages.knowledge.query_intent import resolve_retrieval_plan
from packages.knowledge.repository import KnowledgeRepository
from packages.knowledge.retrieval import QueryRewriter, RetrievalService


def request(query: str, **changes) -> RetrievalRequest:
    return RetrievalRequest(query=query, workspace_id="ws-a", project_id="project-a", **changes)


@pytest.mark.parametrize(
    "field", ["scope", "workspace_id", "project_id", "competitor", "market", "role"]
)
def test_intent_rejects_authority_fields(field):
    with pytest.raises(ValidationError):
        RetrievalIntent(fact_queries=["battery"], **{field: "other"})


@pytest.mark.parametrize("values", [
    {"fact_queries": []}, {"fact_queries": [" "]},
    {"fact_queries": ["fact"] * 6}, {"fact_queries": ["x" * 501]},
    {"fact_queries": ["fact"], "required_terms": [" "]},
    {"fact_queries": ["fact"], "required_terms": ["x"] * 11},
    {"fact_queries": ["fact"], "required_terms": ["x" * 81]},
    {"fact_queries": ["fact"], "output_language": "x" * 41},
])
def test_intent_bounds(values):
    with pytest.raises(ValidationError):
        RetrievalIntent(**values)


def test_structured_suffix_only_after_boundary_and_preserves_original():
    original = "Vacuum X 36 的续航；输出中文并保留出处"
    plan = resolve_retrieval_plan(request(original))
    assert plan.original_query == original
    assert plan.queries == ("Vacuum X 36 的续航",)
    assert plan.output_language == "中文"
    assert plan.require_citations is True

    english = resolve_retrieval_plan(request(
        "Battery runtime; answer in Chinese and include citations"
    ))
    assert english.queries == ("Battery runtime",)
    assert english.output_language == "中文"

    comma = resolve_retrieval_plan(request(
        "Battery runtime, answer in Chinese and include citations"
    ))
    assert comma.queries == ("Battery runtime",)
    assert comma.output_language == "中文"
    assert english.require_citations is True

    after_question = resolve_retrieval_plan(request(
        "Can Aurora synchronize settings between desktop and mobile? 用中文回答并保留条件。"
    ))
    assert after_question.output_language == "中文"
    assert after_question.queries == ("Can Aurora synchronize settings between desktop and mobile",)


@pytest.mark.parametrize("query", [
    "中文支持、消息保留和引用功能", "battery answer in Chinese and include citations",
    "battery；输出中文并保留出处，也比较价格", "battery；输出火星语",
])
def test_unknown_or_body_phrases_are_not_stripped(query):
    assert resolve_retrieval_plan(request(query)).queries == (query,)


def test_raw_policy_is_exact_and_conflicts_with_explicit_intent():
    query = "battery；输出中文并保留出处"
    plan = resolve_retrieval_plan(request(query, intent_policy="raw"))
    assert plan.queries == (query,)
    with pytest.raises(ValidationError):
        request(query, intent_policy="raw", retrieval_intent={"fact_queries": ["battery"]})


def test_long_question_plans_bounded_facts_and_keeps_model_and_access_conditions():
    original = "Acme Vault 7 的离线编辑和同步有什么前提条件？Free 套餐的管理员能否在私有仓库启用分支保护？；输出中文并保留出处"
    plan = resolve_retrieval_plan(request(original))
    assert plan.origin == "auto"
    assert plan.original_query == original
    assert 2 <= len(plan.queries) <= 5
    assert all("Acme" in fact and "Vault" in fact and "7" in fact for fact in plan.queries)
    assert any("offline" in fact for fact in plan.queries)
    assert any("branch protection" in fact for fact in plan.queries)
    assert any(all(term in fact for term in ("free", "admin", "private"))
               for fact in plan.queries)
    assert all("输出中文" not in fact for fact in plan.queries)
    assert plan.output_language == "中文" and plan.require_citations


def test_auto_numeric_constraints_stay_with_their_fact_clause():
    plan = resolve_retrieval_plan(request("Acme V7 的充电器45W是什么规格？电池50Wh是否影响续航？"))
    assert plan.origin == "auto"
    charger = next(fact for fact in plan.queries if "charger" in fact)
    battery = next(fact for fact in plan.queries if "battery" in fact)
    assert "45w" in charger and "50wh" not in charger
    assert "50wh" in battery and "45w" not in battery
    assert all("V7" in fact for fact in plan.queries)


@pytest.mark.parametrize("amount", ["50.5Wh", "-50Wh", ".5Wh", "1/2Wh", "1,050Wh", "1，050Wh"])
def test_auto_plan_preserves_quantity_numeric_text_before_lexical_matching(amount):
    plan = resolve_retrieval_plan(request(
        f"Acme Vault 7 的电池{amount}是否支持在断网的时候继续编辑？"
    ))
    assert plan.origin == "auto"
    assert all(amount.casefold() in fact for fact in plan.queries)


@pytest.mark.asyncio
@pytest.mark.parametrize("amount,source_amount,wrong_amount,answerable", [
    ("50.5Wh", "50.5Whr", "5Wh", True),
    ("-50Wh", "-50Whr", "50Wh", True),
    (".5Wh", ".5Whr", "5Wh", True),
    ("1/2Wh", "1/2Whr", "2Wh", False),
    ("1,050Wh", "1,050Whr", "1Wh", False),
    ("1，050Wh", "1，050Whr", "1Wh", False),
])
async def test_auto_quantity_decimal_cannot_be_recalled_as_a_different_amount(
    tmp_path, amount, source_amount, wrong_amount, answerable
):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        pipeline = IngestionPipeline(repo, object())
        good = await pipeline.ingest(DocumentCreate(
            title="Exact specifications", text=f"Acme Vault 7 battery {source_amount} supports offline editing.",
            source_type="manual", workspace_id="ws-a", project_id="project-a",
        ))
        await pipeline.ingest(DocumentCreate(
            title="Different amount", text=f"Acme Vault 7 battery {wrong_amount} supports offline editing. Reference notes 1 and 50.",
            source_type="manual", workspace_id="ws-a", project_id="project-a",
        ))
        engine = RetrievalService(repo, object(), embed_fn=lambda texts: [], query_rewriter=ForbiddenRewriter())
        response = await engine.retrieve(request(
            f"Acme Vault 7 的电池{amount}是否支持在断网的时候继续编辑？", mode="sparse"
        ))
        assert [hit.document_id for hit in response.hits] == ([good] if answerable else [])


def test_auto_records_unknown_chinese_conditions_and_keeps_recognized_access_filters():
    query = "Acme 企业版的访客仅受邀后才能离线编辑，数据不得出境是否影响同步？"
    plan = resolve_retrieval_plan(request(query))
    if plan.origin == "auto":
        assert "不得" in plan.unknown_terms and "出境" in plan.unknown_terms
        assert "数据不得出境是否影响同步" in plan.preserved_clauses
        assert any("enterprise" in fact and "guest" in fact and "invited" in fact
                   for fact in plan.queries)
    else:
        assert plan.queries == (query,)
        assert plan.planning_reason


def test_long_unknown_clauses_are_auditable_while_entity_topic_queries_can_find_counterevidence():
    query = "Acme Vault 7 默认加密，是否表示每台设备里的本地资料也被自动加密？"
    plan = resolve_retrieval_plan(request(query))
    assert plan.origin == "auto"
    assert any("encryption" in fact and "7" in fact for fact in plan.queries)
    assert plan.unknown_terms
    assert "是否表示每台设备里的本地资料也被自动加密" in plan.preserved_clauses
    assert plan.planning_reason == "unresolved_clauses_preserved_for_verification"


def test_unknown_chinese_entity_without_declared_scope_is_not_silently_removed():
    query = "飞鱼七代在断网的时候能否继续编辑并在联网以后同步？"
    plan = resolve_retrieval_plan(request(query))
    assert plan.queries == (query,)


@pytest.mark.parametrize("query,topics", [
    ("免费套餐的私有仓库可以直接启用分支保护吗？管理员默认也必须受所有限制吗？",
     ("branch protection", "free", "admin", "private")),
    ("请问电池的容量是多少，充电器是否支持50W？", ("battery", "capacity", "charger")),
])
def test_brandless_domain_question_is_only_auditable_topic_recall(query, topics):
    plan = resolve_retrieval_plan(request(query))
    assert plan.origin == "topic_scope_lookup"
    assert plan.original_query == query
    assert plan.preserved_clauses == (query,)
    assert plan.planning_reason == "missing_product_scope_topics_only_for_verification"
    assert all(any(topic in fact for fact in plan.queries) for topic in topics)
    assert all("Acme" not in fact for fact in plan.queries)


@pytest.mark.parametrize("query", [
    "飞鱼七代的私有仓库可以直接启用分支保护吗？管理员默认受限制吗？",
    "私有仓库的分支保护是否支持飞鱼七代？管理员默认受限制吗？",
    "Acme 与 Other 的分支保护和权限有何差异？",
    "Acme vs Other 的分支保护和权限有何差异？",
    "Acme / Other 的分支保护和权限有何差异？",
    "Acme 对比 Other 的分支保护和权限有何差异？",
    "Acme 比 Other 的离线编辑和同步有哪些差异？",
    "Acme 或 Other 的离线编辑和同步有哪些差异？",
    "Acme 以及 Other 的离线编辑和同步有哪些差异？",
    "Acme + Other 的离线编辑和同步有哪些差异？",
    "Acme 胜过 Other 的离线编辑和同步有哪些差异？",
    "Acme 对于 Other 的离线编辑和同步有哪些差异？",
    "Acme 对 Other 的离线编辑和同步有哪些差异？",
    "Acme 同 Other 的离线编辑和同步有哪些差异？",
    "Acme or Other 的离线编辑和同步有哪些差异？",
    "Acme，Other 的离线编辑和同步有哪些差异？",
    "Acme 的电池容量是多少？Other 的充电器是否支持50W？",
    "Acme 的离线编辑是否可用？Other 的同步需要哪些条件？",
    "Acme Vault 7 . Other 的离线编辑和同步有哪些差异？",
    "Acme Vault 7.Other 的离线编辑和同步有哪些差异？",
    "请问免费账号的管理员是否默认也必须受所有限制？",
    "请问是否可以继续使用，默认条件有什么差异？",
])
def test_brandless_planning_does_not_remove_unknown_entity_or_infer_product(query):
    plan = resolve_retrieval_plan(request(query))
    assert plan.origin not in {"auto", "topic_scope_lookup", "dimension_scope_lookup"}
    assert plan.queries == (query,)


@pytest.mark.parametrize("query", [
    "Acme 的离线编辑有哪些前提条件？同步是否支持加密？",
    "Acme Vault 7 的离线编辑有哪些前提条件？同步是否支持加密？",
    "Acme Andromeda 的离线编辑有哪些前提条件？同步是否支持加密？",
    "Acme VersusX 的离线编辑有哪些前提条件？同步是否支持加密？",
    "Acme Orbit 的离线编辑有哪些前提条件？同步是否支持加密？",
    "Acme 的离线编辑有哪些前提条件？Acme 的同步是否支持加密？",
])
def test_single_product_clauses_and_connector_substrings_keep_automatic_planning(query):
    plan = resolve_retrieval_plan(request(query))
    assert plan.origin == "auto"
    assert all("Acme" in fact for fact in plan.queries)
    assert any("offline" in fact for fact in plan.queries)
    assert any("sync" in fact for fact in plan.queries)
    assert plan.original_query == query


@pytest.mark.parametrize("product", ["Acme 比特 Pro", "Acme 和弦 Pro"])
def test_declared_product_name_keeps_internal_chinese_connector_characters(product):
    query = f"{product} 的离线编辑有哪些前提条件？同步是否支持加密？"
    req = request(query, competitors=[product], dimensions=["feature"])
    plan = resolve_retrieval_plan(req)
    assert plan.origin == "auto"
    assert req.competitors == [product]
    assert any("offline" in fact for fact in plan.queries)
    assert any("sync" in fact for fact in plan.queries)
    assert plan.original_query == query


@pytest.mark.parametrize("join", ["与", "和", "/", "vs", "比", "或", "以及", "+", "or", "，"])
def test_declared_product_is_not_removed_from_multi_product_safety_check(join):
    query = f"Acme {join} Other 的离线编辑和同步有哪些差异？"
    req = request(query, competitors=["Acme"])
    plan = resolve_retrieval_plan(req)
    assert plan.origin == "original"
    assert plan.queries == (query,)
    assert req.competitors == ["Acme"]


@pytest.mark.parametrize("product", ["Acme Vault 7", "Acme Vault-7", "Acme V7.1"])
def test_declared_product_allows_adjacent_model_parts_without_other_product(product):
    query = f"{product} 的离线编辑和同步有哪些条件？"
    plan = resolve_retrieval_plan(request(query, competitors=["Acme"]))
    assert plan.origin == "auto"
    assert all("7" in fact for fact in plan.queries)


@pytest.mark.parametrize("query", [
    "Acme Console OLED 的充电器45W和电池50Wh是不是同一个指标？官方3–12小时能保证所有游戏12小时吗？",
    "只凭官方规格，Acme Console LCD 是否保证所有游戏都能连续运行8小时？请保留电池和续航的原始口径。",
])
def test_standalone_numeric_constraints_are_not_additional_product_anchors(query):
    plan = resolve_retrieval_plan(request(query))
    assert plan.origin == "auto"
    assert plan.original_query == query
    assert all("Acme" in fact and "Console" in fact for fact in plan.queries)
    assert plan.preserved_clauses
    assert any("小时" in clause for clause in plan.preserved_clauses)
    if "45W" in query:
        assert all("45w" in fact and "50wh" in fact for fact in plan.queries)
        assert all("12" not in fact for fact in plan.queries)


def test_unparsed_access_dependency_keeps_both_names_and_original_conditions():
    query = "用 BrowserA 在断网时编辑 WorkspaceB，需要哪些桌面浏览器准备？无痕窗口行不行？"
    plan = resolve_retrieval_plan(request(query))
    assert plan.origin == "original"
    assert plan.queries == (query,)
    assert plan.planning_reason == "unsupported_or_unbounded_question"


@pytest.mark.asyncio
@pytest.mark.parametrize("competitors", [[], ["Argo"]])
async def test_model_after_chinese_intro_stays_shared_across_fact_queries(tmp_path, competitors):
    query = "只凭官方规格，Argo 7 的电池容量是多少？续航是否能达到8小时？"
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        pipeline = IngestionPipeline(repo, object())
        good = await pipeline.ingest(DocumentCreate(
            title="Exact model specifications", text="Argo 7 battery capacity is 50Wh. Runtime is 8 hours.",
            competitor="Argo", source_type="manual", workspace_id="ws-a", project_id="project-a",
        ))
        await pipeline.ingest(DocumentCreate(
            title="Different model runtime", text="Argo 70 runtime is 8 hours.",
            competitor="Argo", source_type="manual", workspace_id="ws-a", project_id="project-a",
        ))
        engine = RetrievalService(repo, object(), embed_fn=lambda _: [], query_rewriter=ForbiddenRewriter())
        response = await engine.retrieve(request(query, competitors=competitors, mode="sparse", final_top_k=10))
        assert [hit.document_id for hit in response.hits] == [good]
        plan = response.diagnostics["query_plan"]
        assert plan["origin"] == "auto"
        assert all("7" in fact.split() for fact in plan["queries"])
        assert any("8" in fact.split() for fact in plan["queries"] if "runtime" in fact)


@pytest.mark.parametrize("competitors", [[], ["Argo"], ["Argo 7"]])
@pytest.mark.parametrize("query", [
    "Argo 7 与 Argo 70 的离线编辑和同步有哪些差异？",
    "Argo 7 vs Argo 70 的离线编辑和同步有哪些差异？",
    "Argo 7 的离线编辑是否可用？Argo 70 的同步需要哪些条件？",
])
def test_repeated_brand_with_different_numeric_models_is_not_one_product(query, competitors):
    req = request(query, competitors=competitors)
    plan = resolve_retrieval_plan(req)
    assert plan.origin == "original"
    assert plan.queries == (query,)
    assert req.competitors == competitors


@pytest.mark.parametrize("competitors", [[], ["Argo"], ["Argo 7"]])
def test_repeated_same_complete_numeric_model_keeps_single_product_planning(competitors):
    query = "Argo 7 的离线编辑有哪些条件？Argo 7 的同步是否支持加密？"
    plan = resolve_retrieval_plan(request(query, competitors=competitors))
    assert plan.origin == "auto"
    assert all("7" in fact.split() for fact in plan.queries) or competitors == ["Argo 7"]


@pytest.mark.parametrize("competitors", [[], ["Argo"]])
@pytest.mark.parametrize("query", [
    "Argo 7-1 与 Argo 7-2 的离线编辑和同步有哪些差异？",
    "Argo 7-1 vs Argo 7-2 的离线编辑和同步有哪些差异？",
    "Argo 7-1 的离线编辑是否可用？Argo 7-2 的同步需要哪些条件？",
])
def test_numeric_hyphen_model_tokens_remain_distinct(query, competitors):
    plan = resolve_retrieval_plan(request(query, competitors=competitors))
    assert plan.origin == "original"
    assert plan.queries == (query,)


@pytest.mark.parametrize("competitors", [[], ["Argo"], ["Argo 7-1"]])
def test_same_numeric_hyphen_model_token_stays_whole(competitors):
    query = "Argo 7-1 的离线编辑有哪些条件？Argo 7-1 的同步是否支持加密？"
    plan = resolve_retrieval_plan(request(query, competitors=competitors))
    assert plan.origin == "auto"
    assert all("7-1" in fact.split() for fact in plan.queries) or competitors == ["Argo 7-1"]


@pytest.mark.parametrize("suffix", [
    "请保留原始口径和条件。", "请保留套餐口径和适用条件。", "请保留出处和条件。",
])
def test_last_output_instruction_does_not_become_retention_or_plan_fact(suffix):
    query = "Acme 的电池容量是多少？" + suffix
    plan = resolve_retrieval_plan(request(query))
    assert all("retention" not in fact and "plans" not in fact for fact in plan.queries)
    assert plan.original_query == query
    assert plan.output_language is None
    assert plan.require_citations == ("出处" in suffix)


@pytest.mark.parametrize("query", [
    "Acme 的消息保留多久？", "Acme 是否保留历史？",
    "Acme 的电池容量是多少？请保留消息和历史。",
    "Acme 的电池容量是多少？请保留原始口径和条件，也比较价格。",
])
def test_retention_fact_or_nonfinal_output_instruction_is_not_stripped(query):
    plan = resolve_retrieval_plan(request(query))
    if plan.origin == "auto":
        assert any("retention" in fact for fact in plan.queries)
    else:
        assert plan.queries == (query,)


@pytest.mark.asyncio
async def test_brandless_topic_recall_keeps_scope_and_cache_canonical_checks(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        pipeline = IngestionPipeline(repo, object())
        good = await pipeline.ingest(DocumentCreate(
            title="Repository controls", text="Private repositories support branch protection. Admin rules are optional.",
            source_type="manual", workspace_id="ws-a", project_id="project-a", competitor="Acme",
        ))
        other = await pipeline.ingest(DocumentCreate(
            title="Other repository controls", text="Other private repositories support branch protection.",
            source_type="manual", workspace_id="ws-a", project_id="project-a", competitor="Other",
        ))
        for fields in ({"workspace_id": "other"}, {"project_id": "other"}, {"source_type": "report"}):
            values = dict(title="Foreign controls", text="Private repositories support branch protection.",
                          source_type="manual", workspace_id="ws-a", project_id="project-a", competitor="Other")
            values.update(fields)
            await pipeline.ingest(DocumentCreate(**values))
        engine = RetrievalService(repo, object(), embed_fn=lambda _: [], query_rewriter=ForbiddenRewriter())
        req = request("免费套餐的私有仓库可以直接启用分支保护吗？管理员默认也必须受所有限制吗？",
                      mode="sparse", source_roles=["source"], num_rewrites=2)
        response = await engine.retrieve(req)
        assert {hit.document_id for hit in response.hits} == {good, other}
        assert response.diagnostics["query_plan"]["origin"] == "topic_scope_lookup"
        assert response.diagnostics["fact_query_results"]
        assert req.competitors == []
        cached = await engine.retrieve(req)
        assert cached.hits[0].chunk_id == response.hits[0].chunk_id
        assert [(hit.chunk_id, hit.text, hit.score) for hit in cached.hits] == [
            (hit.chunk_id, hit.text, hit.score) for hit in response.hits
        ]
        assert (cached.query, cached.total) == (response.query, response.total)
        assert cached.diagnostics["cache"]["hit"] is True
        assert cached.diagnostics["query_fusion"]["executed_queries"] == []
        scoped = await engine.retrieve(req.model_copy(update={"competitors": ["Acme"]}))
        assert [hit.document_id for hit in scoped.hits] == [good]
        assert scoped.diagnostics["query_plan"]["origin"] == "auto"
        await repo.soft_delete(good)
        assert [hit.document_id for hit in (await engine.retrieve(req)).hits] == [other]


@pytest.mark.asyncio
@pytest.mark.parametrize("amount,source_amount,wrong_amount,answerable", [
    ("50.5Wh", "50.5Whr", "5Wh", True),
    ("-50Wh", "-50Whr", "50Wh", True),
    (".5Wh", ".5Whr", "5Wh", True),
    ("1/2Wh", "1/2Whr", "2Wh", False),
    ("1,050Wh", "1,050Whr", "1Wh", False),
    ("1，050Wh", "1，050Whr", "1Wh", False),
])
async def test_brandless_topic_recall_preserves_quantity_literals(
    tmp_path, amount, source_amount, wrong_amount, answerable
):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        pipeline = IngestionPipeline(repo, object())
        good = await pipeline.ingest(DocumentCreate(
            title="Battery specifications", text=f"Battery {source_amount} supports offline editing and sync.",
            source_type="manual", workspace_id="ws-a", project_id="project-a",
        ))
        await pipeline.ingest(DocumentCreate(
            title="Different capacity", text=f"Battery {wrong_amount} supports offline editing and sync. Notes 1 and 50.",
            source_type="manual", workspace_id="ws-a", project_id="project-a",
        ))
        engine = RetrievalService(repo, object(), embed_fn=lambda _: [], query_rewriter=ForbiddenRewriter())
        response = await engine.retrieve(request(
            f"请问电池的容量{amount}是否支持在断网的时候继续编辑并在联网以后同步？", mode="sparse",
        ))
        plan = response.diagnostics["query_plan"]
        assert plan["origin"] == "topic_scope_lookup"
        assert all(amount.casefold() in fact for fact in plan["queries"])
        assert [hit.document_id for hit in response.hits] == ([good] if answerable else [])


def test_dimension_scope_lookup_is_explicit_metadata_browse_with_full_question_preserved():
    query = "Acme 的产品优化方向与目标用户"
    plan = resolve_retrieval_plan(request(query, competitors=["Acme"], dimensions=["feature"], source_roles=["source"]))
    assert plan.origin == "dimension_scope_lookup"
    assert plan.queries == ("Acme",)
    assert plan.preserved_clauses == (query,)
    assert plan.planning_reason == "metadata_scoped_browse_without_fact_parse"
    for changes in ({"competitors": []}, {"competitors": ["Acme", "Other"]},
                    {"dimensions": []}, {"dimensions": ["feature", "pricing"]},
                    {"source_roles": []}, {"source_roles": ["historical_report"]}):
        values = dict(competitors=["Acme"], dimensions=["feature"], source_roles=["source"])
        values.update(changes)
        assert resolve_retrieval_plan(request(query, **values)).origin != "dimension_scope_lookup"
    numeric = resolve_retrieval_plan(request(query + " 50Wh", competitors=["Acme"], dimensions=["feature"], source_roles=["source"]))
    assert numeric.origin != "dimension_scope_lookup"


@pytest.mark.parametrize("query", ["battery", "Acme battery", "电池容量", "warranty 36 months"])
def test_short_fact_keywords_do_not_become_metadata_product_browse(query):
    plan = resolve_retrieval_plan(request(
        query, competitors=["Acme"], dimensions=["feature"], source_roles=["source"],
    ))
    assert plan.origin == "original"
    assert plan.queries == (query,)


@pytest.mark.asyncio
async def test_auto_plan_searches_english_facts_without_llm_and_rejects_wrong_model(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        pipeline = IngestionPipeline(repo, object())
        own = await pipeline.ingest(DocumentCreate(
            title="Access guide", text="Acme Vault 7 supports offline editing. Sync uses encryption.",
            source_type="manual", workspace_id="ws-a", project_id="project-a",
        ))
        await pipeline.ingest(DocumentCreate(
            title="Other model", text="Acme Vault 70 supports offline editing and sync.",
            source_type="manual", workspace_id="ws-a", project_id="project-a",
        ))
        engine = RetrievalService(repo, object(), embed_fn=lambda texts: [],
                                  query_rewriter=ForbiddenRewriter())
        original = "Acme Vault 7 在断网的时候能否继续编辑？同步是否支持加密？；输出中文并保留出处"
        response = await engine.retrieve(request(original, mode="sparse", num_rewrites=2))
        assert response.query == original
        assert [hit.document_id for hit in response.hits] == [own]
        assert response.diagnostics["query_plan"]["origin"] == "auto"
        assert response.diagnostics["fact_query_results"]


def test_explicit_facts_preserve_terms_and_standalone_numbers():
    plan = resolve_retrieval_plan(request(
        "Vacuum X 36 与 Vacuum 24 的电池；输出中文并保留出处",
        competitors=["Vacuum X 36"],
        retrieval_intent={"fact_queries": ["电池容量", "质保"], "required_terms": ["Li-ion"]},
    ))
    assert plan.origin == "explicit"
    assert len(plan.queries) == 2
    assert all("Li-ion" in query and "24" in query for query in plan.queries)
    assert all("36" not in query for query in plan.queries)
    assert all("输出中文" not in query for query in plan.queries)


def test_full_competitor_model_number_is_not_appended():
    plan = resolve_retrieval_plan(request(
        "Vacuum X 36 电池", competitors=["Vacuum X 36"],
        retrieval_intent={"fact_queries": ["电池容量"]},
    ))
    assert plan.queries == ("电池容量",)


def test_numbers_next_to_units_or_unknown_model_are_preserved():
    plan = resolve_retrieval_plan(request(
        "Vacuum X 36 与 Y2 电池 5000mAh，输出中文",
        competitors=["Vacuum X 36"],
        retrieval_intent={"fact_queries": ["电池容量"]},
    ))
    assert plan.queries == ("电池容量 2 5000",)
    assert plan.required_terms == ("2", "5000")


@pytest.mark.parametrize(
    "required, fact",
    [
        ("36", "续航 36.5 小时"),
        ("36", "续航 0.36 小时"),
        ("36.5", "续航 136.5 小时"),
        ("36.5", "续航 36.50 小时"),
    ],
)
def test_required_number_is_not_satisfied_by_a_different_numeric_token(required, fact):
    plan = resolve_retrieval_plan(request(
        "续航对比", retrieval_intent={"fact_queries": [fact], "required_terms": [required]},
    ))
    assert plan.queries == (f"{fact} {required}",)


@pytest.mark.parametrize("required, fact", [("5000", "5000mAh"), ("2", "Y2")])
def test_required_number_matches_complete_token_next_to_unit_or_model_letter(required, fact):
    plan = resolve_retrieval_plan(request(
        "电池对比", retrieval_intent={"fact_queries": [fact], "required_terms": [required]},
    ))
    assert plan.queries == (fact,)


@pytest.mark.asyncio
async def test_legacy_rewrite_diagnostics_list_actual_queries():
    class Rewriter(QueryRewriter):
        async def rewrite(self, query: str, *, num_rewrites: int) -> list[str]:
            return ["capacity"]

    class Repo:
        async def search_chunks(self, query, **kwargs):
            return []

    engine = RetrievalService(Repo(), object(), embed_fn=lambda texts: [],
                              query_rewriter=Rewriter())
    response = await engine.retrieve(request("battery", mode="sparse", num_rewrites=1))
    assert response.diagnostics["query_plan"]["queries"] == ("battery", "capacity")


def test_preserved_constraints_over_query_limit_are_rejected():
    with pytest.raises(ValueError, match="2000"):
        resolve_retrieval_plan(request(
            " ".join(str(number) for number in range(420)), retrieval_intent={
                "fact_queries": ["x" * 500],
            },
        ))


class ForbiddenRewriter(QueryRewriter):
    async def rewrite(self, query: str, *, num_rewrites: int) -> list[str]:
        raise AssertionError("explicit facts must not invoke LLM rewrite")


@pytest.mark.asyncio
async def test_explicit_facts_search_real_sqlite_and_report_only_final_chunk_ids(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        class NoVectors:
            async def upsert(self, ids, vectors, payloads):
                pass

        ids = []
        for text in ["battery capacity 36 hours", "warranty coverage 36 months"]:
            ids.append(await IngestionPipeline(repo, NoVectors()).ingest(
                DocumentCreate(title=text, text=text, source_type="manual",
                               workspace_id="ws-a", project_id="project-a"),
            ))
        engine = RetrievalService(repo, NoVectors(), embed_fn=lambda texts: [],
                                  query_rewriter=ForbiddenRewriter())
        original = "battery and warranty 36；answer in Chinese and include citations"
        response = await engine.retrieve(request(
            original, mode="sparse", top_k=5, final_top_k=5,
            retrieval_intent={"fact_queries": ["battery capacity", "warranty coverage"]},
        ))
        assert response.query == original
        assert {hit.document_id for hit in response.hits} == set(ids)
        grouped = response.diagnostics["fact_query_results"]
        assert len(grouped) == 2
        assert {cid for group in grouped for cid in group["chunk_ids"]} == {
            hit.chunk_id for hit in response.hits
        }
        assert response.diagnostics["query_plan"]["origin"] == "explicit"

        narrowed = await engine.retrieve(request(
            original, mode="sparse", top_k=5, final_top_k=1,
            retrieval_intent={"fact_queries": ["battery capacity", "warranty coverage"]},
        ))
        assert len(narrowed.hits) == 1
        retained_id = narrowed.hits[0].chunk_id
        narrowed_groups = narrowed.diagnostics["fact_query_results"]
        assert sorted(group["chunk_ids"] for group in narrowed_groups) == [[], [retained_id]]


@pytest.mark.asyncio
async def test_explicit_fact_lists_rrf_deduplicates_shared_chunk(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        await IngestionPipeline(repo, object()).ingest(DocumentCreate(
            title="shared", text="battery capacity", source_type="manual",
            workspace_id="ws-a", project_id="project-a",
        ))
        engine = RetrievalService(repo, object(), embed_fn=lambda texts: [],
                                  query_rewriter=ForbiddenRewriter())
        response = await engine.retrieve(request(
            "battery capacity", mode="sparse", final_top_k=5,
            retrieval_intent={"fact_queries": ["battery", "capacity"]},
        ))
        assert len(response.hits) == response.total == 1
        chunk_id = response.hits[0].chunk_id
        assert [item["chunk_ids"] for item in response.diagnostics["fact_query_results"]] == [
            [chunk_id], [chunk_id],
        ]


@pytest.mark.asyncio
async def test_explicit_number_and_scope_filter_before_sparse_limit(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        pipeline = IngestionPipeline(repo, object())
        foreign = [
            {"workspace_id": "ws-b"}, {"project_id": "project-b"},
            {"competitor": "Other"}, {"market": "US"},
            {"source_type": "report"},
        ]
        for override in foreign:
            fields = dict(title="foreign", text="battery capacity 36 hours " + repr(override),
                          source_type="manual", workspace_id="ws-a", project_id="project-a",
                          competitor="Vacuum", market="CN")
            fields.update(override)
            await pipeline.ingest(DocumentCreate(**fields))
        await pipeline.ingest(DocumentCreate(
            title="wrong number", text="battery capacity 24 hours", source_type="manual",
            workspace_id="ws-a", project_id="project-a", competitor="Vacuum", market="CN",
        ))
        own = await pipeline.ingest(DocumentCreate(
            title="correct", text="battery capacity 36 hours", source_type="manual",
            workspace_id="ws-a", project_id="project-a", competitor="Vacuum", market="CN",
        ))
        engine = RetrievalService(repo, object(), embed_fn=lambda texts: [],
                                  query_rewriter=ForbiddenRewriter())
        response = await engine.retrieve(request(
            "Vacuum battery 36", mode="sparse", competitors=["Vacuum"], market="CN",
            source_roles=["source"], top_k=1, final_top_k=1,
            retrieval_intent={"fact_queries": ["battery capacity"]},
        ))
        assert [hit.document_id for hit in response.hits] == [own]
        assert response.diagnostics["query_plan"]["queries"] == ("battery capacity 36",)


@pytest.mark.asyncio
async def test_plan_cache_isolated_and_canonical_rechecked(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        own = await IngestionPipeline(repo, object()).ingest(DocumentCreate(
            title="battery", text="battery capacity", source_type="manual",
            workspace_id="ws-a", project_id="project-a",
        ))
        engine = RetrievalService(repo, object(), embed_fn=lambda texts: [],
                                  query_rewriter=ForbiddenRewriter())
        calls = []
        search = repo.search_chunks

        async def observed(query, **kwargs):
            calls.append(query)
            return await search(query, **kwargs)

        repo.search_chunks = observed
        common = dict(mode="sparse", enable_query_rewrite=False)
        raw = request("battery；输出中文", intent_policy="raw", **common)
        structured = request("battery；输出中文", **common)
        await engine.retrieve(raw)
        first = await engine.retrieve(structured)
        assert first.hits and first.hits[0].document_id == own
        assert calls == ["battery；输出中文", "battery；输出中文", "battery"]
        await engine.retrieve(structured)
        assert calls == ["battery；输出中文", "battery；输出中文", "battery"]
        await repo.soft_delete(own)
        stale = await engine.retrieve(structured)
        assert stale.hits == []


@pytest.mark.asyncio
async def test_reranker_receives_complete_original_query_with_format_suffix(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        await IngestionPipeline(repo, object()).ingest(DocumentCreate(
            title="battery", text="battery capacity", source_type="manual",
            workspace_id="ws-a", project_id="project-a",
        ))
        seen = []

        def rerank(query, texts):
            seen.append(query)
            return [1.0] * len(texts)

        engine = RetrievalService(repo, object(), embed_fn=lambda texts: [],
                                  rerank_fn=rerank, query_rewriter=ForbiddenRewriter())
        await engine.retrieve(request("battery capacity；输出中文并保留出处",
                                      mode="sparse", rerank_top_k=1))
        assert seen == ["battery capacity；输出中文并保留出处"]
