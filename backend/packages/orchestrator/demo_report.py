from __future__ import annotations

from packages.i18n.language import normalize_output_language, report_label
from packages.schema.api_dto import RunDetail
from packages.schema.decision_brief import decision_brief_fields, safe_decision_brief_text


def build_demo_report(detail: RunDetail, *, source_refs: str, memory_section: str) -> str:
    """Deterministic analysis fixture with the same release contract as real reports."""
    language = detail.output_language
    zh = normalize_output_language(language) == "zh-CN"
    competitors = ", ".join(detail.plan.competitors)
    dimensions = ", ".join(detail.plan.dimensions)
    parts = [f"# {detail.plan.topic}"]

    def section(key: str, rows: list[str], *, cite: bool = True) -> None:
        parts.append(f"## {report_label(language, key)}")
        parts.extend(f"- {row}{source_refs if cite else ''}" for row in rows)

    section(
        "executive_summary",
        [
            (
                (
                    f"本次 Demo 运行覆盖了 {competitors}，涉及维度有 {dimensions}"
                    f"；所有证据都是确定性演示素材，用于验证引用和发布流程。"
                )
                if zh
                else (
                    f"This demo run covers {competitors} across {dimensions}; "
                    f"deterministic fixture evidence verifies citation and pub"
                    f"lication flow."
                )
            ),
            (
                (
                    "比较应先限定相同采购场景，再核对套餐包含内容、实际工作流"
                    "和使用限制；演示素材不支持判断真实市场胜者。"
                )
                if zh
                else (
                    "Compare the same buying scenario, then verify included p"
                    "lans, workflow boundaries and usage limits; fixture evid"
                    "ence cannot establish a market winner."
                )
            ),
            (
                (
                    "下一步应收集当前官方资料，使用同一证据准入规则重新分析；"
                    "执行完成、报告结构合格与真实采购建议需要分别评审。"
                )
                if zh
                else (
                    "Collect current official material and rerun the same evi"
                    "dence admission rules; execution, structural quality and"
                    " a procurement decision each need review."
                )
            ),
        ],
    )
    section(
        "decision_summary",
        [
            (
                (
                    f"将 {competitors} 放入同一评估清单，并固定 {dimensions} 的"
                    f"测试边界；现阶段只确认系统可以产出可追溯的比较。"
                )
                if zh
                else (
                    f"Place {competitors} in one evaluation checklist with fix"
                    f"ed {dimensions} boundaries; this run establishes a trace"
                    f"able comparison contract."
                )
            ),
            (
                (
                    "采购成本需要同时核验席位数、使用额度和超额费用，不能只比"
                    "较页面上的单一价格；尚未核验的项目继续保留为缺口。"
                )
                if zh
                else (
                    "Buying cost needs seat count, usage allowance and overag"
                    "e verification together; comparing a headline price alon"
                    "e leaves an unresolved gap."
                )
            ),
            (
                (
                    "功能选择需要用同一任务衡量完成率、操作步骤和人工复核负担"
                    "；当前演示没有执行这些真实业务测试。"
                )
                if zh
                else (
                    "Feature choice needs the same task, completion criteria,"
                    " operating steps and review workload; this fixture has n"
                    "ot run those business trials."
                )
            ),
            (
                (
                    "最终建议应附带条件、证据日期和负责人；本次演示将无证据的"
                    "优劣判断留空，便于后续审阅和局部重做。"
                )
                if zh
                else (
                    "Attach conditions, evidence dates and an owner to the fi"
                    "nal decision; unsupported rankings stay unset for later "
                    "review and scoped redo."
                )
            ),
        ],
    )
    user_brief = decision_brief_fields(detail.plan.decision_brief)
    if user_brief:
        labels = (
            {"decision_question": "决策问题", "primary_job": "主要任务", "success_metric": "成功指标"}
            if zh else
            {"decision_question": "decision question", "primary_job": "primary job", "success_metric": "success metric"}
        )
        user_input = "; ".join(
            f"{labels[key]}: {safe_decision_brief_text(value)}"
            for key, value in user_brief.items()
        )
        job = user_brief.get("primary_job") or user_brief.get("decision_question") or detail.topic
        safe_job = safe_decision_brief_text(job)
        metric = user_brief.get("success_metric")
        safe_metric = (
            safe_decision_brief_text(metric)
            if metric else
            ("试点前约定可衡量的任务完成标准" if zh else "a measurable task completion threshold agreed before the pilot")
        )
        section(
            "product_opportunities",
            [
                (f"用户输入（非竞品证据）：{user_input}。" if zh else f"User-provided context (not competitor evidence): {user_input}."),
                (
                    f"待验证机会假设 1：围绕“{safe_job}”探索产品改进；竞品差异与真实需求仍待验证。"
                    if zh else
                    f"Opportunity hypothesis 1 to validate: explore a product improvement around “{safe_job}”; competitor differences and real demand remain unverified."
                ),
                (
                    f"对应任务：{safe_job}；验证动作：让目标用户用相同任务试用候选方案并记录完成情况与阻碍；成功信号：{safe_metric}。"
                    if zh else
                    f"User task: {safe_job}; validation action: have target users try candidate approaches on the same task and record completion and blockers; success signal — {safe_metric}."
                ),
            ],
            cite=False,
        )
    section(
        "competitive_findings",
        [
            (
                (
                    f"{competitors} 的演示来源均被保留在原始证据集合中；引用使"
                    f"用已有来源 ID，方便从报告返回对应证据。"
                )
                if zh
                else (
                    f"Fixture sources for {competitors} remain in raw evidence"
                    f"; existing source IDs link each report reference back to"
                    f" its material."
                )
            ),
            (
                (f"本次覆盖 {dimensions}，不将该范围外的功能、合规或服务承诺推断为已经证实的结论。")
                if zh
                else (
                    f"Coverage is limited to {dimensions}; features, complianc"
                    f"e and service commitments outside that scope remain unve"
                    f"rified."
                )
            ),
            (
                (
                    "来源完整性与产品竞争力属于不同判断；来源更多可以提高可核"
                    "验性，但不能直接证明业务效果更好。"
                )
                if zh
                else (
                    "Source coverage improves auditability, while product com"
                    "petitiveness needs outcome evidence; more sources alone "
                    "do not prove better results."
                )
            ),
            (
                (
                    "同一声明若存在矛盾，应记录来源版本与采集时间，优先补齐当"
                    "前官方资料，再决定是否需要人工复核。"
                )
                if zh
                else (
                    "For conflicting claims, record source versions and colle"
                    "ction dates, retrieve current official material and deci"
                    "de whether human review is required."
                )
            ),
            (
                (
                    "对缺失数据保留明确空白，并列出验证方法；示例报告验证了证"
                    "据不足可以被解释，而不会被自动转成确定性推荐。"
                )
                if zh
                else (
                    "Keep missing data explicit and name a validation method;"
                    " the example explains evidence gaps without converting t"
                    "hem into firm recommendations."
                )
            ),
        ],
    )
    section(
        "review_theme_summary",
        [
            (
                (
                    "演示证据不能代表真实用户口碑，需要另外采集用户评测、访谈"
                    "或经过许可的调查结果，并区分研究来源与官方事实。"
                )
                if zh
                else (
                    "Fixture evidence does not represent user sentiment; coll"
                    "ect reviews, interviews or authorized surveys and separa"
                    "te research sources from official facts."
                )
            ),
            (
                (
                    "工作流适配应按新手、专业开发者和组织管理员分别观察，避免"
                    "用单个体验片段推断所有用户的需求。"
                )
                if zh
                else (
                    "Observe novice users, professional developers and admini"
                    "strators separately rather than generalizing one experie"
                    "nce to every user group."
                )
            ),
            (
                (
                    "采用障碍需记录学习成本、已有工具迁移和评审要求；没有用户"
                    "证据时，这些是待验证假设而不是产品缺陷。"
                )
                if zh
                else (
                    "Record learning effort, existing tool migration and revi"
                    "ew requirements; without user evidence these are validat"
                    "ion hypotheses rather than product defects."
                )
            ),
            (
                (
                    "后续访谈应追踪具体任务和失败场景，并将每条主题关联到原始"
                    "记录，以便核验结论和采样偏差。"
                )
                if zh
                else (
                    "Follow concrete tasks and failure scenarios in interview"
                    "s, linking every theme to its original record for conclu"
                    "sion and sampling checks."
                )
            ),
        ],
    )
    deep_rows = []
    for competitor in detail.plan.competitors:
        deep_rows.extend(
            [
                (
                    (
                        f"{competitor}：本次演示仅检查 {dimensions} 证据在采集、分"
                        f"析和报告之间的传递，未测量真实产品性能。"
                    )
                    if zh
                    else (
                        f"{competitor}: this fixture checks {dimensions} evidence "
                        f"across collection, analysis and reporting, without measu"
                        f"ring product performance."
                    )
                ),
                (
                    (
                        f"{competitor}：评估时应核对官方版本、适用套餐和采购条件，"
                        f"任何无法从已有来源确认的字段都应保持未核验。"
                    )
                    if zh
                    else (
                        f"{competitor}: verify official versions, eligible plans a"
                        f"nd buying terms; fields unsupported by current sources s"
                        f"hould remain unverified."
                    )
                ),
                (
                    (
                        f"{competitor}：试点需要明确成功指标、测试任务、复核人和退"
                        f"出条件，再将实际结果补入对比表。"
                    )
                    if zh
                    else (
                        f"{competitor}: define pilot success metrics, tasks, a rev"
                        f"iewer and exit criteria before adding observed results t"
                        f"o the comparison."
                    )
                ),
            ]
        )
    section("competitor_deep_dives", deep_rows)
    section(
        "swot_analysis",
        [
            (
                (
                    f"优势：{competitors} 的演示材料具有稳定的证据标识，便于检"
                    f"查信息传递和追溯；这项优势仅描述演示流程。"
                )
                if zh
                else (
                    f"Strengths: fixture material for {competitors} has stable"
                    f" evidence IDs, making flow and provenance testable; this"
                    f" strength describes the demo process."
                )
            ),
            (
                (
                    "劣势：当前演示未包含真实任务成功率、完整商业条款和独立用"
                    "户研究，因此不足以验证采购收益。"
                )
                if zh
                else (
                    "Weaknesses: actual task completion, complete commercial "
                    "terms and independent user research are absent, so buyin"
                    "g value remains unverified."
                )
            ),
            (
                (
                    "机会：用当前官方资料和相同任务补充试点，能够把演示清单转"
                    "成可以复核的评估结果，并改善不完整维度。"
                )
                if zh
                else (
                    "Opportunities: current official sources and a common tas"
                    "k pilot can turn the fixture checklist into reviewable f"
                    "indings and fill incomplete dimensions."
                )
            ),
            (
                (
                    "威胁：过期套餐信息、选择性样本和未经验证的宣传都可能扭曲"
                    "结论；应通过来源日期、复核和重新采集降低影响。"
                )
                if zh
                else (
                    "Threats: outdated plan information, selective samples an"
                    "d unverified marketing can distort conclusions; source d"
                    "ates, review and recollection reduce that risk."
                )
            ),
        ],
    )
    section(
        "side_by_side_matrix",
        [
            (
                (
                    f"比较范围：{competitors} 使用相同的 {dimensions} 维度，后"
                    f"续新增维度需独立采集，不从已有示例外推。"
                )
                if zh
                else (
                    f"Comparison scope: {competitors} share the same {dimensions}"
                    f" dimensions; added dimensions need independent collectio"
                    f"n rather than extrapolation."
                )
            ),
            (
                (
                    "证据状态：表格只填入已有来源支持的事实；没有来源的值注明"
                    "待核验，证据数量不自动产生维度胜者。"
                )
                if zh
                else (
                    "Evidence status: enter facts supported by sources; unsup"
                    "ported values remain pending, and evidence count does no"
                    "t assign a dimension winner."
                )
            ),
            (
                (
                    "成本口径：同时保留周期、席位、额度和超额规则；所有比较必"
                    "须对应同一个使用场景，避免遗漏隐含条件。"
                )
                if zh
                else (
                    "Cost basis: retain billing period, seats, allowance and "
                    "overage rules for the same usage scenario to expose cond"
                    "itions hidden by a headline value."
                )
            ),
            (
                (
                    "验证安排：每个空白项指定资料类型和复核人，更新后重跑对应"
                    "分支与质量门禁，保留报告版本方便对比。"
                )
                if zh
                else (
                    "Validation plan: assign source type and reviewer to each"
                    " gap, rerun its branch and quality gate, and retain repo"
                    "rt versions for comparison."
                )
            ),
        ],
    )
    layer_key = {
        "L1": "battlecard",
        "L2": "workflow_enterprise_risk",
        "L3": "market_landscape",
    }.get(detail.plan.competitor_layer, "battlecard")
    section(
        layer_key,
        [
            (
                (
                    f"将 {competitors} 纳入同一试点评估，固定任务、范围与复核标"
                    f"准；演示中的信息传递不构成真实产品优劣判断。"
                )
                if zh
                else (
                    f"Use this demo report as a direct battlecard scaffold for"
                    f" {competitors}: fix pilot tasks, scope and review criter"
                    f"ia before judging product tradeoffs."
                )
            ),
            (
                (
                    "采用前核对现有系统的接入路径、人工审批和可回滚方案；这些"
                    "实施条件需要真实环境验证，不能由演示材料代替。"
                )
                if zh
                else (
                    "Before adoption, verify integration paths, human approva"
                    "l and rollback arrangements in the actual environment; f"
                    "ixture material cannot establish these conditions."
                )
            ),
            (
                (
                    "风险评估应把数据处理、权限和输出审核放入明确责任清单；缺"
                    "少官方证明的安全与合规声明继续保留为不足。"
                )
                if zh
                else (
                    "Assign owners to data handling, permissions and output r"
                    "eview; safety and compliance claims without official pro"
                    "of remain evidence gaps."
                )
            ),
            (
                (
                    "扩展或采购的条件是试点完成、关键证据核验和负责人签署；若"
                    "测试不达预期，应保留原有工作流并重新检查缺口。"
                )
                if zh
                else (
                    "Expansion or buying depends on pilot completion, key evi"
                    "dence verification and owner signoff; unmet criteria req"
                    "uire reviewing gaps and keeping a reversible workflow."
                )
            ),
        ],
    )
    section(
        "source_quality",
        [
            (
                (
                    "Demo 证据被投射到企业 EvidenceRecord 模型中，保留来源 ID"
                    " 以供发布门禁和报告视图追溯。"
                )
                if zh
                else (
                    "Demo evidence is projected into the enterprise EvidenceR"
                    "ecord model with source IDs preserved for release-gate a"
                    "nd report-view traceability."
                )
            ),
        ],
    )
    if memory_section:
        parts.append(memory_section.strip())
    section(
        "rag_gap_fill",
        [
            (
                (
                    f"当前状态：证据来自演示 fixture；建议检索 {competitors} 的"
                    f"当前官方 {dimensions} 文档，补齐真实任务和用户研究证据。"
                )
                if zh
                else (
                    f"Current status: evidence comes from demo fixtures. Sugge"
                    f"sted retrieval query: current official {dimensions} docu"
                    f"mentation for {competitors}, task trials and user resear"
                    f"ch."
                )
            ),
        ],
    )
    section(
        "scenario_checklist",
        [
            (
                f"{'场景' if zh else 'Scenario'}: {detail.plan.scenario_id or 'auto'}"
                f"; {detail.plan.competitor_layer}; {dimensions}."
            ),
            f"QA: {', '.join(detail.plan.qa_rule_ids) or 'default schema checks'}.",
        ],
        cite=False,
    )
    section(
        "claim_risk",
        [
            (
                (
                    "Demo 结论属于契约检查，并非最终的市场建议；合成证据需要当"
                    "前官方资料和声明验证才能用于采购判断。"
                )
                if zh
                else (
                    "Demo conclusions are contract checks, not final market r"
                    "ecommendations; synthetic evidence needs current officia"
                    "l material and claim validation before buying decisions."
                )
            ),
        ],
    )
    section(
        "next_collection",
        [
            (
                ("将 Demo 证据替换为当前的官方网页，然后在发布前重新运行声明验证和发布门禁评审。")
                if zh
                else (
                    "Replace demo evidence with current official webpages, th"
                    "en rerun claim validation and release gate review before"
                    " publication."
                )
            ),
        ],
    )
    section(
        "evidence_appendix",
        [
            f"{source.id}: {source.title} / {source.source_type} [source:{source.id}]"
            for source in detail.raw_sources[:8]
        ],
        cite=False,
    )
    return "\n\n".join(parts) + "\n"
