# 本机与内网演示部署交付

## 本轮范围

按已批准方案实现演示部署底座、可选 Redis、任务恢复和持久性保护。用户明确由另一台电脑承担后续 Docker 部署，本机只执行离线测试、预览和构建；本轮外部付费模型调用为 0。Kafka 暂不加入。

## 实际变更

| 模块 | 已实现 | 实机边界 |
| --- | --- | --- |
| 部署入口 | `light` / `persistent`、可选 Redis、统一 API/Worker 配置、localhost 默认、LAN 鉴权、最终端口检查 | 镜像构建、平台架构和健康检查待部署机验证 |
| 资源归属 | `up` 前检查容器 checkout 与 Compose 标签、现存卷标签，显式固定 Compose 文件 | Docker 标签真实格式待实机验证；移动 checkout 后需人工核对旧项目 |
| Redis | 惰性短超时客户端、JSON/TTL 限制、哈希 key、服务器时间 Lua 原子窗口 | fake client 不执行 Lua；真实 Lua、TTL、并发及断连待验证 |
| 来源缓存 | 实际 `fetch_evidence_page` 入口接入；拒绝动态价格/凭据/摘要/损坏项；保留原采集时间 | 真实网页变化与缓存过期效果待验证；不缓存知识库/私人上传/报告 |
| 共享限流 | 鉴权后按服务端主体执行；覆盖创建、工作流、扫描、监控、续跑、重做等入口 | 429、503 规则已离线验证；真实代理、多客户端和 Redis 故障待验证 |
| 就绪检查 | livez / readyz；必需依赖失败返回 503，可选缓存失败仅 warn | 不是完整任务、Worker 队列或报告质量验收 |
| 任务恢复 | 同 run/thread checkpoint 续跑、持久实际执行归属、当前模型策略复核、重复恢复拒绝 | 单进程保护；没有跨进程 lease 或外部模型 exactly-once |
| SSE | `Last-Event-ID` 单调补读、Nginx 透传和禁缓冲 | 浏览器/代理断线实机验证待执行 |
| 数据工具 | 默认预览、一致备份清单/哈希、全新隔离目标恢复、demo 重启检查 | 真实 PG/Qdrant/SQLite 卷备份恢复、停电/强杀及 Temporal 实机恢复待验证 |

`run-data`、`artifact-data`、Postgres、Qdrant 保留持久化；Redis 可以丢弃，重启会重置短时限流。只有实际路由明确的 LangGraph 任务进入普通恢复，Temporal 与 legacy unknown 不被擅自转换。已有人工等待与限定重做使用原有处理入口。

## 验证记录

完整回归结果与命令记录见同目录 [`2026-10-16-demo-deployment-results.json`](2026-10-16-demo-deployment-results.json)。测试日志和只读审查报告留在 Git 忽略的 `data/artifacts/demo-deployment-2026-10-16/`，不上传原始运行资料。

后端完整回归 **4477 通过、1 跳过**，212 条告警主要为现有 FastAPI lifespan 弃用提示；前端 OpenAPI 同步与生产构建通过。凭据字面值/模式扫描通过，实际 `.env` 不被 Git 跟踪。首次完整回归暴露两处旧测试与执行归属规则冲突，调整为明确检查 local / Temporal owner 后重新执行全量，最终退出码为 0。

- 实际 SQLite journal / checkpoint 关闭重开，demo 图和假模型 real 图都覆盖了续跑；禁止外网的测试不能证明真实模型调用质量。
- 新增公开 fetch 入口测试，确认启用缓存时真正复用，价格请求绕过，关闭时不初始化 Redis。
- 独立部署审查复现并修复了同名外部项目误更新、`.env` 端口覆盖和示例默认绑定问题；复核无未解决 P1/P2。
- 独立运行时审查修复了 FastAPI shutdown 注册、损坏缓存结构、漏限流入口、实际路由归属及恢复模型策略；最终恢复边界独立复核通过。
- 部署、备份、恢复、故障和 Redis 五类预览均生成合法 JSON，没有调用 Docker 或创建备份目录。Redis 实机验收只有 `--execute` 才连接服务，并使用随机命名空间有 TTL 的探针。

本轮增加的测试验证工程保护与执行一致性；此前真实报告中的 Miro 条件归属/正文遗漏、Airtable robots 阻断等问题没有通过本轮部署改造获得内容验收，报告仍不能宣称达到完整交付标准。

## 另一台电脑的下一步

1. 拉取当前分支，准备 Docker Engine + Compose v2 和 Python 3.11+，创建该电脑私有 `.env`；先使用 demo 模式。
2. 先运行部署 `--dry-run`，再在部署电脑执行 `--mode light --redis --build` 和 `--check`。
3. 在独立 `plan-a-drill-*` 项目完成备份恢复、demo 重启与 Redis `--execute` 探针，以及停止 Redis 后的 503 / 恢复检查。
4. 需要 Temporal 时，在错开端口的独立 persistent 项目验证完整任务和 Worker 重启，核对已提交阶段、预算、事件与人工等待；再验收 Qdrant HTTP 与真实语义模型 provider。

完整命令、端口、数据范围和应回传的脱敏结果见 [部署说明](../docker_deployment.md)。当前不需要在这台开发电脑安装或启动 Docker。
