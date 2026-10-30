# 本机持久化任务工作台 P0 交付记录

日期：2026-10-30。业务基线：`b744fa0e1db4857df99668ae333687eb2e636a55`；设计／计划提交：`f6eefbe8e52c86d300647e2fe701774c9becef35`；分支：`codex/pastoral-desktop`。用户已批准本轮 P0。完整后端重跑、前端、标准工具生成、构建、Ruff 新增 0 与实机闭环已独立验证，预发布候选扫描无发现。提交前复核实际暂存范围与扫描；本记录不提前声明提交或推送，实际发布以包含本文的 Git 历史与远端核验为准。

设计与范围见[设计说明](2026-10-30-persistent-workbench-design.md)、[实施计划](2026-10-30-persistent-workbench-plan.md)，机器可读摘要见[脱敏结果](2026-10-30-persistent-workbench-results.json)。本轮保留[上一期提交中心原交付](2026-10-29-task-center-delivery.md)与[原结果](2026-10-29-task-center-results.json)，没有重写旧证据。

## 本轮完成的行为

- 独立原生 PostgreSQL profile 保存企业项目／run／报告版本和提交中心／Outbox／任务次数账本；知识库、执行日志及检查点继续使用 profile 内 SQLite，不宣称全部迁到 PG。
- `scripts/workbench_runtime.py` 提供 init／start／status／stop，全部默认预览，只有 `--execute` 实际执行。默认 profile `runs/local-workspace`、API 8010、前端 5180；正常停止保留数据，没有 destroy。
- start 按 PG → API readyz → Relay ready → Vite 顺序启动；重复 start 复用同配置进程。PID、UTC 创建时间、实际命令、代码／工作区身份不符时拒绝发信号；端口冲突拒绝，不杀占用者。
- 明亮像素桌面新增提交中心列表和详情，覆盖工作区／状态筛选、游标分页、UTC 月度快照及 reserve／release 流水；新建研究在 runtime 严格为 true 时走原六个提交／额度 API，关闭或旧缺字段时走旧入口。未知 capability／新接口错误不回退创建第二单。
- 网络未知结果的相同载荷重试沿用原幂等键，修改载荷换键并防双击。派发状态与 `run_status` 分开，实际关联 run 后才提供原分析详情链接；取消与重试派发由服务端最终裁定，动作后重读服务器所选月份快照。
- 提交资源约 4 秒串行轮询，错误需手动恢复；文档隐藏、窗口最小化、卸载或作用域变化会停读／abort 并丢弃过期响应。恢复保留月份／筛选并重新读取，旧报告页未重写。

## 完整企业 PostgreSQL 与隔离边界

实测 macOS arm64、原生 **PostgreSQL 15.18（Homebrew）＋pgvector 0.8.7**；完整企业 public **19 表**和提交中心三份迁移可用。应用角色 `plan_a_workspace_app` 为 NOSUPERUSER／NOBYPASSRLS／NOINHERIT，无 owner 成员关系、schema DDL 或 TRUNCATE 权限。管理连接只用于显式 CLI 初始化，API／Relay 使用受限应用连接。

PG 的 `listen_addresses` 为空，仅监听私有 Unix socket；macOS socket 位于工作区外的短路径 `/private/tmp/pwpg-{uid}-{rootHash20}`。profile／PG data／socket 目录 0700，私有记录 0600，标记绑定 UID 与规范路径。Unix socket 为 local trust，同一系统用户属于信任边界。网页服务仅绑定 127.0.0.1，demo 关闭 API 鉴权，不能据此开放内网或公网。

受控子环境不加载根／frontend env 文件，不继承 provider key、管理 DSN、Redis、Temporal 或 Qdrant HTTP；固定 demo、LangGraph、任务中心开启、全局运行上限 2／工作区 1。API／Relay 共用 profile journal 和图检查点，KB、cache、traces、preference、产物、Vite cache 均隔离。全局任务中心默认仍 false，旧入口和原 `.env` 不改。早期基线曾发现 Vite 忽视关闭标志，最终使用 dev-null envDir 与显式 loadEnv guard，并以真实 Vite core 的 8 项 Node 断言验证，不据此声称整轮所有早期进程从未读 env 文件。

真实状态探针曾触发 SQLSTATE 23514，确认旧 run CHECK 拒绝 `completed_with_blockers`。本轮新增 `backend/db/postgres/002_run_delivery_status.sql`，在既有管理连接、事务与 advisory lock 中顺序应用 001＋002；原 001 未修改，保留原五状态并允许该阻断状态，非法状态继续拒绝。已验受限 app 读写、旧库升级与重复迁移保留正常／阻断数据；没有将阻断强改 completed，没有修改 QA 或发布规则。另一台部署的源码也须包含 002 并由管理员迁移；现有 Compose 的 Relay／脚本／owner 环境隔离仍未接全，不能因 native 通过宣称容器直接可用。

## 真实持久化与故障验收

独立验收器 `backend/scripts/verify_persistent_workbench.py` 默认预览；execute 只创建自身随机私有临时 profile 与 loopback 端口，拒绝外部 DSN 或任意用户目标。验证使用真实 PG、受限 app pool、HTTP API、Relay 与 demo Graph，模型内容为合成数据。

| 场景 | 实际结果与边界 |
| --- | --- |
| 完整企业闭环 | project、run、报告版本、提交／一次 reserve、journal／事件／checkpoint 绑定；API 报告与 PG 一致 |
| 两阶段重启 | API／Relay 重启保持 PG 身份；再正常停止 PG／整栈并重启，业务及执行快照相等 |
| 幂等并发 | 同 key 20 请求仅一单／一次 reserve；不代表真实模型吞吐 |
| 最后一次额度 | 10 个不同请求竞争，1 个 accepted、9 个 429；不是模型账单 |
| pending 取消 | 合法取消只释放一次，已有发送意图仍不退款 |
| Relay 暂停 | 无 Relay 时保持 pending，恢复后原单派发完成 |
| 断库及原 key 恢复 | 断库 503；沿用原故障请求同 key，两次 202 指向同一单、一次 reserve，无孤儿，最终完成并跨重启保持 |
| 清理与失败注入 | spawn 后 registry 写入前也记账；真实旧／新 Relay 退出证明独立，repeat cleanup 一致；异常退出保持失败，活跃／归属未知不发信号且保 PG |

恢复时先观测到 readyz 双依赖 200，真实 POST 仍出现旧池 503 三次、约 0.65 秒后 202；验收经有界同键重试确认恢复。该观测不能推成 readyz 后所有请求立即成功或恢复 SLA。成功临时 profile 只在所有自有进程正常退出且物理 PG 退出证明齐全后删除；失败保留私有诊断，不操作用户常驻目录。

Root 另从真实浏览器填写 quick／AI／demo 的双产品研究，创建提交、进入详情并打开报告；完成正常全栈 stop、API／Relay／前端及 PG 物理退出核验后，再用独立 CLI start 并重载原报告。前后保持 **1 个报告版本、1 次 reserve、35 个事件、19 个检查点**，project／run／提交 ID、报告 SHA 与全部执行快照一致。已实际操作桌面最大化、最小化／任务栏恢复及窄屏／桌面分支。常驻演示访问地址为 `http://127.0.0.1:5180`（提交中心 `/submissions`）、API `http://127.0.0.1:8010`；本次交付时服务已启动，机器重启后仍需手动 start。

## 工程验证状态

| 项目 | 本轮独立结果 |
| --- | --- |
| 全后端 | 二轮完整 **9175 通过／1 跳过／250 条 warning**，pytest 429.15 秒（外层 431.555 秒）、退出 0；首轮失败原件保留 |
| 全前端 | 58 文件／340 测试通过，退出 0 |
| Vite 真实 core 环境隔离 | Node 独立运行 8／8 通过，退出 0 |
| 标准 OpenAPI／TypeScript 生成稳定 | 官方 `export_openapi.py` 和 `openapi-typescript` 临时生成，两命令退出 0；JSON／TS 与受保护源逐字节一致，源文件未被重写 |
| 生产构建 | `pnpm --dir frontend build` 退出 0；Vite 5.4.21、1996 modules、7.301 秒 |
| 实际配置 Ruff 增量 | 已含最终测试隔离窄修，backend＋启动器的 4023 项存量保持 4023；按 path／code／message／精确 source-line 的 Counter 新增 0、移除 0；原命令退出 1，不是全仓 Ruff 清零 |
| 预发布候选凭据扫描 | 当前快照 1634 个 tracked／非 ignored 新源码和文档候选，沿用既有 scanner 规则，0 发现；排除私有 env／运行目录 |
| 最终暂存范围与扫描 | 文档冻结后由 root 在提交前核对实际暂存内容；本快照不声称已完成，结果由最终 Git 交付核验记录确认 |
| 全仓交互审计 | 已知存量 4 error／89 warning，源自旧 DimensionEvidencePanel；本轮 Task3 变更范围 0 error／0 warning，不称全仓通过 |

首轮全前端曾因 Vitest 误收 Node:test suite 而退出 1，当时 340 个业务测试已通过；仅把 Node 文件 `.test.mjs` 原字节改名为 `.check.mjs`，8 项断言 SHA256 `9bed469f208ce59a665f2f4acf6887cd14fd0952c4ae89fe90e17952ae308390` 不变，没有删除断言或改 Vitest exclude。首红、失败及后续结果全部保留。Task1–4 已分别完成规格与质量审查；冻结文档的独立规格审查、整体质量审查及最终暂存扫描在后续交付核验中记录，不以作者自查代替，也不在被提交文件中伪造自引用的最终 commit SHA。

首轮全后端为 9174 通过／1 失败／1 跳过、250 条 warning、430.26 秒、退出 1；唯一失败来自**测试模块缓存隔离**：目标测试替换 `sys.modules` 后，父 `scripts` 包仍可能缓存真实 relay 模块，单跑与全库顺序结果不同。窄修只新增父包导入与对应 monkeypatch，生产代码未改，77 条原断言全部保留；完整相关 50 项、最小反序 2 项及撤销恢复探针通过，并完成 fresh 规格／质量审查。它不是实际 Relay 生产故障；随后同环境完整后端重跑 9175 通过、无失败。唯一跳过为旧 `test_postgres_rls_smoke.py:12` 未配置外部 `ENTERPRISE_RLS_SMOKE_DATABASE_URL`；本轮私有 PG 原生 RLS A→B→A 隔离已验证，不能据此说本轮未验任何 RLS。

Root 本轮实际使用标准工具输出到临时文件，再逐字节对比 JSON／TS，避免和会读取生成源的测试竞争；没有在该轮执行 `make sync-openapi` 覆盖源。下面的 make 命令是后续复跑入口。

可在仓库根目录使用已装依赖的解释器复跑，通用 clone 为 `.venv/bin/python`；本次隔离 worktree 实际为 `../plan_a/.venv/bin/python`：

```bash
WORKBENCH_PYTHON=.venv/bin/python
# 本次隔离 worktree 复用已有依赖时改为 ../plan_a/.venv/bin/python
COMPETISCOPE_LOAD_ENV_FILES=0 PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=backend:backend/tests:backend/tests/unit:backend/tests/integration \
  "$WORKBENCH_PYTHON" -m pytest backend/tests -q -ra -p no:cacheprovider
COMPETISCOPE_LOAD_ENV_FILES=0 pnpm --dir frontend test
COMPETISCOPE_LOAD_ENV_FILES=0 node --test frontend/scripts/vite-env-isolation.check.mjs
COMPETISCOPE_LOAD_ENV_FILES=0 make sync-openapi PYTHON="$WORKBENCH_PYTHON"
COMPETISCOPE_LOAD_ENV_FILES=0 pnpm --dir frontend build
```

标准生成会写生成文件，复跑时须等会读取这些文件的后端测试结束。真实 PG／socket／进程测试使用自有目录且需要系统允许本机进程与共享内存，不把环境权限错误误判为业务通过。

## 操作、数据与未验项

启停命令、profile 各数据库路径、停机备份和恢复限制见[部署说明第 8 节](../docker_deployment.md#8-原生-postgresql-本机持久化工作台p0)。先装 PG15 与其匹配 pgvector，启动器不安装依赖；所有 action 加 `--execute` 才实际操作。停止保留 PG、SQLite、产物及私有归属记录，完整 profile 只在所有 writer／PG 停止后备份。归属标记绑定 UID／绝对路径，备份恢复演练、跨路径与跨机逻辑迁移均未验，不能直接移动 PG data 到另一台 Docker。旧数据不自动迁移，未安装机器重启自启。

本轮没有新增 Kafka、训练模型或重验真实报告内容。真实模型完整 Graph（含 blocked 状态）、真实抓取、生产语义 RAG、Docker／Windows、Temporal、Redis、PG17 完整企业组合、跨主机、停电／强杀恢复、高并发容量与稳态 SLA 均未验。历史报告结论继续为 **文字完整 1/4、文本与证据完整 0/4，整体未达标**（[2026-10-28 原交付](2026-10-28-reviewed-task-decisions-delivery.md)）；不能用本轮 demo 报告或工程测试升级该结论。

原始日志、失败、进程证明与截图保存在 Git 忽略的本机目录 `data/artifacts/persistent-workbench-2026-10-30/`，仅用于本地审计，不上传 Git，也不作为公开 README 可点击资产。[results JSON](2026-10-30-persistent-workbench-results.json)仅保存脱敏摘要及本机证据 SHA／可用性说明，不含连接秘密、原始业务正文、数据库或私有环境文件。
