# 产品采集修复与 RAG 核查验收

日期：2026-10-02。基线：`ccaa49c`；工作分支：`codex/pastoral-desktop`。

## 修复与检查范围

- 产品维度查询以当前竞品为主体，不混入其他产品的调研标题；社区与知识检索使用产品意图。已指定产品但类别为空时也不落回编码 Agent 模板。定向修复查询与旧未指定产品的行为保留。
- HTML 正文使用既有 trafilatura，并保留短规格表标签与数值。明确的导航、页脚不能被空提取回退带回；正文哈希随实际清理文本生成。
- 产品功能覆盖以匹配主体和维度、成功抓取页面中的准入事实及独立来源数判断，使用预算内补采，充分时停止。
- 跨 repair 轮累计已有来源，只补剩余缺口；同 URL / 同正文的旧事实不能充当新增独立来源。
- 图执行期间保护本进程的活动运行对象，避免 GET / 列表 / 事件轮询替换计划与证据；退出后恢复 journal 刷新。
- RAG 核查和升级设计覆盖 Qdrant、资料入库、时效和范围、模型状态、各 Agent 的共享证据契约。

## 当前验证记录

查询用例首次为 18 failed / 4 passed；修复后 22 passed。独立审查发现空类别仍使用 AI 社区意图，补四维度失败用例再修复。任务 1 独立质量复审相关测试 95 passed。

正文用例首次为 3 failed / 1 passed，直接使用抽取库后仍有短表压平失败；独立配置避免短正文 baseline 压平。规格审查进一步复现长导航被当成正文，新增长导航、页脚、回退和 XHTML 声明用例并修复。质量审查发现大页解析阻塞事件循环及深 DOM 截断，新增两项测试 2 failed → 2 passed。正文解析移入线程，清理后的深层 DOM 直接交给提取器，避免二次解析丢失规格。16 个正文用例与相关回归 58 passed；独立规格及质量复审通过。

质量复审重跑原 1.22 MB 表格并发四页场景，10 ms 定时器从阻塞约 1.924 秒恢复为约 11 ms 响应，四页抓取均成功；这是本地响应性验证，不是生产延迟指标。原 260 层 DOM 规格及强制空提取的中文安全回退仍保留正文。

主代理在上述修复与复审完成后独立执行查询、正文、webfetch、evidence_fetch、advanced_fetch、crawler 六个测试文件：84 passed in 1.23s。

产品事实覆盖首次新测试为 20 failed / 3 passed；实现后补旧价格契约和预算边界用例共 26 passed。规格审查发现链式重复来源随顺序变化，12 种排列 / 独立来源组合首次 8 failed / 4 passed，合并来源身份集合后全部通过。新文件 38 passed；相关五文件 138 passed；独立规格复审 90 passed。

最终审查发现跨 repair 轮未累计已取得来源，新增三项用例首先 2 failed / 1 passed；按全局目标累计后新文件 41 passed、相关五文件 141 passed。独立规格复审覆盖契约与 pipeline 93 passed，历史复用 9 passed。达到来源目标立即停止；新页与旧事实重复时继续补采，预算耗尽保留缺口；旧页不重复计入本轮抓取指标。

质量审查进一步复现缓存 URL 别名误占抓取预算：实际仅四次网络抓取却记录五次，漏掉下一独立来源。新增缓存回归首先 1 failed；区分缓存命中与实际抓取、保留产品候选 overflow 并由实际抓取次数限制后，覆盖契约与 pipeline 94 passed。缓存增加 cache_hits，不增加 fetch / adaptive_backfill_fetch_count；候选仍受 max_candidates 限制，网络抓取仍受 max_fetches 限制。

缓存修复独立规格及质量复审无未决 P1 / P2：覆盖与 pipeline 94 passed；history、research、pricing、capture、预算及取消相关 225 passed。反例取得三个独立来源，实际五次抓取、一次缓存命中，coverage 通过。在内存中分别恢复旧候选截断、旧缓存计数，两种情况都只实际抓取四次且 coverage 失败，确认两处修复都必要。主代理选定修改与四个新测试的 Ruff 检查、git diff --check 通过；本轮 19 个改动文件凭据模式扫描无命中，不读取 .env。

运行对象保护新增九项回归首先 5 failed / 4 passed，修复后 9 passed；journal、HITL、Temporal 同步和 run_service 相关的 44 个不同用例通过。实际 Planner 离线回放在发现及范围确认两处等待时并发读取 GET / 列表 / SSE，结果为 Planner 三个主体、Collector 相同三个主体，LLM 计数仍为二。异常、取消、中断、嵌套及另一服务观察 journal 更新均有回归。此保护只表达本进程活动图的所有权，不提供跨进程执行互斥。

活动运行修复独立规格与质量审查通过；独立运行新回归、run_journal、HITL runtime 和 run_service 共 336 passed in 10.91s，无未决 P1 / P2。

本轮真实任天堂规格页抓取返回 HTTP 200；正文有 96 行，保留 screen / storage 内容，无 Nintendo Account 导航。该网页结果不代表所有页面结构已经覆盖。

缓存预算修复后的主代理关键回归为 160 passed in 1.71s；最终完整后端回归为 2082 passed / 1 skipped / 106 warnings in 42.43s。跳过的是 PostgreSQL 实库 RLS 测试，缺少 ENTERPRISE_RLS_SMOKE_DATABASE_URL；警告是已有 FastAPI on_event 弃用提示。

本轮未修改前端；上轮相同前端版本的 237 个测试与 TypeScript / Vite 构建通过，不作为本轮新执行记录。

## 本轮真实任务：未通过

任务：`run-896b011110295b6f21d2b911f5fc9200`；Switch 2 极简 / 全 AI / real / feature，自动发现竞品。预算上限 160000 token / 估算 USD 0.25。

终态 failed，report_md 为空，RawSource 0。官方规格抓取成功，三次 DeepSeek 原生搜索成功，Planner 消息包含目标产品与两个竞品，但最终计划与 Collector 调度范围为空；未进入实际产品采集。检查发现 API 读取 journal 快照会替换 graph 正在使用的 RunDetail 对象，旧引用中的发现结果不能传给后续 Agent。根因已离线复现并修复，真实 Planner 回放保持相同三主体传递；本次失败任务没有重新运行。

运行预算 checkpoint：6 calls、1 repair、42728 tokens_charged、USD 0.013789164 cost_charged。费用为配置价格和 usage 的运行估算，不是供应商账单。本轮不追加付费任务；修复后的完整联网到报告闭环仍需真实复验。

后端已在原 8000 端口重启加载修复；运行配置接口与前端 5173 均 HTTP 200。运行配置确认为 real / LangGraph / deepseek-flash，搜索为 DeepSeek。该检查证明本地服务可访问，不替代完整联网报告验收。

## RAG 运行现状与固定基准

- 代码已有 Qdrant 适配器；本地配置 localhost:6333 无监听，未验收真实向量服务。
- 本地实际 provider：hash-embedding-v1，1024 维；hash-reranker-v1。采集 Agent 使用 sparse，入库 index_vectors=False。
- 主采集链通常仅入库标题与摘要；上一轮真实页面 12926 字符正文没有作为完整正文交给采集入库。
- 两个检索入口的范围、服务缓存生命周期和模型使用尚未统一。

固定 14 条构造查询：关键词 Recall@3=0.8571 / MRR=0.7143；混合为 0.9286 / 0.8929；混合加 hash 规则重排为 0.9286 / 0.8571。本基准为 64 维 hash，model_calls=0，不代表真实语义模型、生产权限隔离或 Qdrant 服务已经验收。完整指标见 [基准摘要](2026-10-02-rag-benchmark-summary.json)。

## 后续范围

RAG 下一阶段方案见 [证据与 Workflow 对齐设计](2026-10-02-rag-evidence-design.md)。先恢复现有 Qdrant 运行验证，再补完整资料、可信范围和型号 / 时效检查，接入统一证据版本，最后通过评测决定语义模型与重排。新增模型部署、索引迁移和草稿交互尚未实施。
