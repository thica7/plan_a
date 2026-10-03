# 共享证据快照实施计划

> **For agentic workers:** 按 `subagent-driven-development` 或 `executing-plans` 逐项实施；每项先失败测试、最小实现、规格与质量审查，再进入下一项。

**Goal:** 下游 Agent 消费同一证据版本，事实变化能使对应依赖失效，并保留可回查的来源与消费记录。

**Architecture:** 复用现有 RunDetail / RunJournal 保存 typed 快照，服务端集中解析可信来源引用。Agent 取得按职责和预算筛选的视图，原引用 token 保持兼容；版本与依赖检查接入现有 graph、缓存、scoped redo 和 Writer EvidencePack。

**Tech Stack:** Python、Pydantic、SQLite RunJournal、LangGraph、现有知识仓库和 pytest；仅更新生成的前端 API 类型，不新增页面。

设计依据：[共享证据设计](2026-10-03-rag-shared-evidence-design.md)。状态：用户已于 2026-10-03 确认，开始按任务实施；基线 `6b42b30`，沿用已有隔离工作区。本阶段不调用付费模型 / 搜索，不部署 HTTP Qdrant，不自动迁移旧资料归属。

## 文件与接口边界

| 文件 | 职责 |
| --- | --- |
| 新建 `backend/packages/research/evidence/snapshot_models.py` | RunEvidenceSnapshot、EvidenceSource、EvidenceFact、EvidenceConsumption、StageEvidenceView；不依赖 RunDetail，避免循环导入 |
| 必要修改 `backend/packages/research/evidence/__init__.py` | 原公开接口保持兼容，延迟加载业务依赖，避免 typed DTO 导入模型时触发循环 |
| 新建 `backend/packages/research/evidence/snapshot.py` | 规范化与构建快照、内容摘要、版本比对、按 ID 回读 |
| 新建 `backend/packages/research/evidence/views.py` | 按身份 / 职责筛选、原文与事实成对组装、上下文预算 |
| 新建 `backend/packages/orchestrator/evidence_context.py` | canonical 文档引用解析、冻结、消费记录、旧结果提交检查 |
| 修改 `backend/packages/schema/api_dto.py` | RunDetail 追加快照、当前指针、消费记录，旧 JSON 默认空 |
| 修改 `backend/packages/orchestrator/service.py`、`graph.py`、`state.py` | mixin 接线、阶段冻结时点、重做与恢复 |
| 修改 `backend/packages/agents/analysts/logic.py`、`comparator/logic.py`、`reflector/logic.py` | 使用当前快照输入，产物记录依赖，缓存保持范围 |
| 修改 `backend/packages/agents/writer/evidence_pack.py`、`writer/logic.py`、`qa/logic.py` | 既有 EvidencePack 读取快照；引用与版本查验 |
| 必要修改 `backend/packages/agents/planner/logic.py`、`collectors/logic.py` | 历史线索明确角色；采集清单与现有检索契约接线 |
| 修改 `frontend/openapi.json`、`frontend/src/api/openapi.ts` | 仅同步 typed RunDetail 字段 |

以下接口在对应任务中定义并测试，后续任务不得新增同义接口：

```python
# snapshot.py
def seal_snapshot(detail, *, phase, canonical_documents):
    """验证、构建或复用快照，并原子更新 detail 的历史与当前指针。"""

def current_snapshot(detail):
    """按当前指针回读并验证 hash；无快照返回 None。"""

def changed_evidence(previous, current):
    """返回新增 / 删除 / 变更的 source 与 fact 语义身份集合。"""

# views.py
def select_evidence_view(snapshot, *, agent, competitor=None, dimension=None,
                         source_ids=None, max_bytes=8192):
    """返回新对象，保留快照身份、选中 ID、预算与缺口。"""

# evidence_context.py，RunService 的集中适配，不允许模型覆盖 scope
async def _prepare_evidence_snapshot(self, record, *, phase):
    """回读可信文档引用并冻结；缺失 / 越界引用成为拒绝项。"""

def _begin_evidence_use(self, record, *, agent, competitor=None,
                        dimension=None, source_ids=None):
    """固定当前快照，返回视图和依赖凭据，记录实际选中证据。"""

def _validate_evidence_use(self, record, use):
    """当前版本变化时检查依赖；变更或失效则拒绝提交旧结果。"""
```

## 任务 1：快照数据与确定性版本

**Files:** 新建 snapshot_models.py、snapshot.py；修改 api_dto.py；新建 `backend/tests/unit/test_run_evidence_snapshot.py`。

- [x] 写失败用例：相同输入不同到达顺序不变版本；事实值改变而正文 hash 不变产生新版本；嵌套对象不能改写历史；同 hash 不同工作区不能复用。
- [x] 运行新测试并保留失败依据。
- [x] 定义来源 / 事实 / 冲突 / 缺口及消费模型，模型 `extra="forbid"`；快照记录冻结，结构化值以 canonical JSON 保存，视图解码为新对象。身份、原日期、引用和事实值都参与内容摘要；创建时间与检索排名不参与。
- [x] 快照来源采用明确的字段白名单；网页任意 metadata、full_text、HTML、凭据和工作流指令不进入阶段提示。引用身份由 canonical 资料或已准入的本次来源确定，不能由模型生成。
- [x] 接线时已复现包初始化循环；为 evidence 包保留全部原 exports 的延迟加载，先补独立进程导入顺序 RED / GREEN 回归。不重构其他包。
- [x] 追加 RunDetail 字段，原 JSON 缺字段时正常读取：

```python
evidence_snapshots: list[RunEvidenceSnapshot] = Field(default_factory=list)
evidence_snapshot_id: str | None = None
evidence_consumptions: list[EvidenceConsumption] = Field(default_factory=list)
```

- [x] 实现 seal_snapshot / current_snapshot / changed_evidence；当前指针与历史列表一起交给现有 RunJournal.save_run。相同契约且同 phase 复用，否则单调升版；来源冲突不覆盖旧值。
- [x] 新测试转绿，再跑 run_journal / active_run_journal 回归；独立规格与质量复审通过，按任务保存提交。

代表性失败测试使用本文件末尾的 make_detail：

```python
def test_fact_change_with_same_body_creates_new_snapshot():
    detail = make_detail(price="3999 CNY")
    first = seal_snapshot(detail, phase="analysis", canonical_documents={})
    detail.raw_sources = make_detail(price="4299 CNY").raw_sources
    second = seal_snapshot(detail, phase="analysis", canonical_documents={})
    assert second.version == first.version + 1
    assert first.id != second.id
    assert "3999 CNY" in first.model_dump_json()
    assert "4299 CNY" not in first.model_dump_json()
```

## 任务 2：可信引用解析与阶段视图

**Files:** 新建 views.py、evidence_context.py；修改 service.py 的 mixin 接线；新建 `backend/tests/unit/test_stage_evidence_views.py`、`test_evidence_snapshot_scope.py`。

- [x] 写失败用例：伪造 metadata 归属 / 版本、其他工作区、未知旧文档、错误完整型号、公共库显式 null、过期价格和未来日期；视图改动不污染快照；预算不能截断值或孤立引用。
- [x] 从 record.detail 构建 KnowledgeScope，在 canonical 仓库回读来源文档 / 分块；版本或 hash 不匹配成为具体缺口。重复 seal 和查询不得刷新来源时间。
- [x] 必要内部接线：公开 `seal_snapshot` 签名保持不变，共用私有封存 helper 接收服务器验证产生的逐来源拒绝项，随 gaps 进入摘要。不改 RawSource metadata、不事后改冻结快照；范围读取的 missing / out_of_scope / unknown 统一为 `canonical_document_unavailable`，不越权回读探测。
- [x] 使用 `normalized_fields_from_source` 的现有字段适配；缺少支持原文或仅有历史观点时保留信号，不生成已核验事实。保留原 JSON 类型与 evidence_item_ids。
- [x] 实现 select_evidence_view，按产品 / 维度 / 明确引用筛选。quick / standard / deep 分别限制每段 8192 / 16384 / 24576 UTF-8 字节；超预算按完整事实与原文对分段或记录缺口，不静默丢出处。
- [x] _begin_evidence_use 保存实际选中 ID、snapshot ID、依赖 hash、估计上下文；_validate_evidence_use 重新校验当前依赖，阻止旧结果提交。
- [x] 定向测试转绿，运行第一阶段 storage / retrieval / reference 回归；保存任务提交并审查。

```python
def test_view_is_scoped_and_does_not_mutate_snapshot():
    detail = make_detail()
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    before = snapshot.model_dump_json()
    view = select_evidence_view(snapshot, agent="analyst", competitor="Product A",
                                dimension="pricing", max_bytes=8192)
    assert view.snapshot_id == snapshot.id
    assert len(view.to_prompt_json().encode("utf-8")) <= 8192
    assert snapshot.model_dump_json() == before
    other = select_evidence_view(snapshot, agent="analyst", competitor="Product A Pro",
                                 dimension="pricing", max_bytes=8192)
    assert other.source_ids == []
```

## 任务 3：图的冻结时点与持久恢复

**Files:** 修改 graph.py、state.py、service.py；新建 `backend/tests/unit/test_evidence_snapshot_graph.py`；扩展 test_run_journal.py。

- [x] 写失败回放：survey 补充进入 collect 快照；HITL 补采接受后所有 Analyst 取得同一 analysis 版本；重复 QA / 恢复不升版；并行旧分支不能提交到新版本。
- [x] 在真实与 scoped redo 图的 collect_qa 调用前准备 collect 快照；analyst_dispatch 前准备 analysis 快照。demo 图走相同冻结契约，模型和搜索保持合成回放。
- [x] GraphState 只携带快照 ID，完整清单存 RunDetail；并行分支取得固定凭据，不在共享 detail 上替换输入或全文。
- [x] 必要提交边界接线：Graph 经既有 Analyst runner 显式传固定 ID，真实 / demo 分支本地持有消费凭据，在缓存应用、ReAct 与 one-shot 合并前检查；证据拒绝异常不能被 ReAct fallback 吞掉。保留旧 direct-call 可选参数兼容，实际提示输入投影仍由任务 4 完成；不以 Graph 返回后的检查代替合并前保护。
- [x] snapshot.current 的查验、消费记录与恢复沿用 RunJournal；当前指针失配 / hash 失配必须明确失败或回到安全重建入口，不能悄悄重建旧 ID。
- [x] 旧已完成报告只读；无快照的旧未完成运行在安全入口新建首份快照。运行 test_graph_send.py 和 journal / HITL 相关回归。
- [x] 保存任务提交并完成两级审查。

恢复测试的核心断言：

```python
def test_snapshot_survives_journal_reopen(tmp_path):
    path = tmp_path / "run_journal.db"
    detail = make_detail()
    first = seal_snapshot(detail, phase="analysis", canonical_documents={})
    RunJournal(path).save_run(detail)
    loaded = RunJournal(path).load_run(detail.id)
    assert loaded is not None
    assert current_snapshot(loaded).model_dump() == first.model_dump()
    assert seal_snapshot(loaded, phase="analysis", canonical_documents={}).id == first.id
```

## 任务 4：Agent 输入与产物依赖

**Files:** 修改 Analyst / Comparator / Reflector / Writer / QA 文件；必要接线 Planner / Collector；新建 `backend/tests/integration/test_agent_evidence_alignment.py`。

- [x] 用两产品 × 两维度固定回放拦截实际 LLM / 工具输入，断言 Analyst、Comparator、Reflector、Writer、QA 的 snapshot ID 一致，选中来源受职责约束。
- [x] Analyst 替换直接 raw_sources 提示输入为当前视图；ReAct、one-shot、fallback 与缓存命中均记录依赖。模型返回后先验证凭据，再合并结构化知识 / 卡片。
- [x] Comparator 检查分析产物依赖再比较，保存同口径和不可比较原因；Reflector 读取当前覆盖和冲突。
- [x] Writer 的 EvidencePack 投影使用固定快照，继续现有 SectionBrief、分段和引用 token；事实值和出处来自相同版本，不把模型补充的信息写回事实表。
- [x] QA 按报告引用 ID 回读固定快照；canonical 文档删除 / 版本变化 / 权限失效时创建具体 QCIssue 与已有 scoped redo 目标。无效来源不得因一次新的宽泛召回而被替换。
- [x] Planner 的历史线索仍标记 advisory；Collector 检索结果汇入候选清单，不能越过冻结入口直接修改下游快照。
- [x] 运行 writer_evidence_pack / analyst_claim_cards / comparator_decision_cards / report_reuse / source_currentness 回归，保存任务提交并审查。

每个异步 Agent 的输入 / 提交边界统一为：

```python
view, use = self._begin_evidence_use(record, agent="analyst",
                                     competitor=competitor, dimension=dimension)
# 现有 ReAct / one-shot 分支使用 view.to_prompt_json() 作为证据输入。
# 得到 payload 后，必须先通过凭据检查，再执行原 merge / emit 卡片逻辑。
self._validate_evidence_use(record, use)
```

集成回放必须记录并断言实际 prompt 中的版本和值，不能只断言新增日志字段存在。

## 任务 5：事实更正、缓存与依赖失效

**Files:** 修改 evidence_context.py、service.py `_prepare_redo_scope_inputs`、Analyst `_kb_cache_content_hash` 及已有 structured repair 接线；新建 `backend/tests/integration/test_evidence_snapshot_repair.py`。

- [x] 写失败用例：价格值变化而正文 hash 不变；其他产品功能不变；决策变化使引用该决策的章节失效；新版本之后完成的旧分支拒绝提交。
- [x] Analyst 缓存加入可信范围和选中证据依赖摘要；不把整个全局快照 ID 当成唯一缓存身份。
- [x] 比对 changed_evidence，检查 EvidenceConsumption 与 ClaimCardBundle / SectionBrief 的来源依赖。变化使相关分支、决策、章节失效；未变产物可复用并记录原生成快照和当前验证结果。
- [x] 依赖缺失时保守重做对应阶段；无法证明章节范围时保留整份 Writer 重写，不伪造定向修复完成。
- [x] 补采生成新快照后再调度受影响分析；只改文案的 writer_only 使用同一证据快照。已有报告引用的旧来源保留审计身份，不进入当前可发布事实。
- [x] 回放用调用计数证明未变 Analyst 未重新调用，变更分支确实使用新事实；运行 test_redo_routing_contract.py、test_redo_seed_cases.py 与 run_service 回归。
- [x] 保存任务提交并完成两级审查。

回放的验收断言为：

```python
assert new_snapshot.version > old_snapshot.version
assert analyst_calls[("Product A", "pricing")] == 2
assert analyst_calls[("Product B", "feature")] == 1
assert "4299 CNY" in latest_pricing_prompt
assert "3999 CNY" not in latest_pricing_prompt
assert old_pricing_result_committed is False
assert unaffected_source_fields_after == unaffected_source_fields_before
```

这些值必须由测试中的实际拦截与数据库读取得到，不能用实现函数计算同一个预期值。

## 任务 6：完整验收与交付

**Files:** 生成 OpenAPI JSON / types，更新第一阶段交付说明的后续链接，新建第二阶段验收记录；原有 CI shard 添加必要新测试。

- [ ] 逐项对照设计的 8 个验收用例，记录未完成项，不用数量替代行为验证。
- [ ] 新增测试与受影响回归先通过，再独立规格 / 质量 / 最终集成审查。
- [ ] 使用临时 DB、禁用 .env 和付费凭据运行完整后端；前端类型更新后运行全测试与构建；导出 API 并逐字检查生成类型。
- [ ] Ruff 只要求新增诊断为零，保留已记录旧基线；差异检查与凭据模式扫描通过。
- [ ] 完整联网报告、HTTP Qdrant、语义模型质量仍单独标明未验收；未经真实成对运行，不宣称 token 或外部请求已经节省某百分比。
- [ ] 备份现有运行数据后只读核对升级；保存交付文档和本地提交，GitHub 登录可用时推送本分支。

## 测试夹具与执行方式

用于以上单测的 make_detail 放在新增测试的 fixture 模块；完整型号、事实值与正文 hash 分开，价格更正不改变正文 hash，以复现原缓存缺口：

```python
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, RawSource


def make_detail(price="3999 CNY"):
    source = RawSource(
        id="source-product-a-pricing", competitor="Product A", dimension="pricing",
        source_type="webpage_verified", title="Product A pricing",
        url="https://product-a.example/pricing", snippet="Original price evidence",
        content_hash="fixed-original-page-hash", confidence=0.8,
        extracted_at="2026-10-03T00:00:00",
        metadata={
            "last_verified_at": "2026-10-03T00:00:00",
            "normalized_fields": [{
                "kind": "pricing", "dimension": "pricing", "competitor": "Product A",
                "tier_name": "Base", "price": price, "billing_cycle": "one_time",
                "source_quote": f"Base price: {price}", "confidence": 0.8,
                "source_url": "https://product-a.example/pricing",
                "evidence_item_ids": ["item-product-a-price"],
            }],
        },
    )
    return RunDetail(
        id="run-shared-evidence", workspace_id="workspace-a", project_id="project-a",
        topic="Product research", status="running", execution_mode="real",
        created_at="2026-10-03T00:00:00", updated_at="2026-10-03T00:00:00",
        plan=AnalysisPlan(topic="Product research", competitors=["Product A", "Product B"],
                          dimensions=["pricing", "feature"], research_depth="quick"),
        raw_sources=[source],
    )
```

可信 canonical 文档、非可信 metadata、未知旧归属应使用独立 fixture，不能把此 RawSource fixture 的 metadata 当成可信文档时间的依据。需要当前日期的用例冻结时钟，避免固定日期随时间产生偶然失败。

```bash
# 仓库根目录；临时 KB 路径由测试 runner 创建，不连接真实资料库
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONPATH=backend \
.venv/bin/python -m pytest backend/tests/unit/test_run_evidence_snapshot.py -q --tb=short

COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONPATH=backend \
.venv/bin/python -m pytest backend/tests/integration/test_agent_evidence_alignment.py \
backend/tests/integration/test_evidence_snapshot_repair.py -q --tb=short
```

本机实施工作区使用共享虚拟环境 `../plan_a/.venv/bin/python` 替代上面的 `.venv/bin/python`。完整测试沿用第一阶段的临时环境 runner，清除 host API key 和 RLS 环境变量；前端使用 `envDir:false` 临时 Vitest 配置。已有进程保持只读，完成验收前不启动新真实报告。
