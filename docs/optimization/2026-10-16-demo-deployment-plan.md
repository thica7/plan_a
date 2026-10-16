# 本机与内网演示部署实施计划

> 按用户“允许执行”及后续“本机不执行 Docker、另一台电脑负责部署”实施。使用 writing-plans / test-driven-development / systematic-debugging；独立部署脚本与 Redis 组件分工实现，最后代码审查和 verification-before-completion。所有路径相对当前已隔离 worktree。

**目标**：可复现的单机演示部署、持久化/备份、任务恢复与事件续传、可选 Redis 缓存及限流；当前机器只做离线测试，真实容器故障验证由交付脚本在另一台机器显式执行。

**边界**：Kafka 不接入。不重置现有数据、不读取/打印/提交实际凭据，不调用付费模型，不执行本机 Docker、不安装系统服务。保持单 API / 单运行 Worker，当前 SQLite 与共享 volume 不宣称支持多主多实例。

## 设计

- 轻量演示使用现有 LangGraph 与持久化检查点；持久任务演示使用现有 Temporal 外层与 Worker。Docker profile/启动参数选择可选组件，API 与 Worker 的实际编排配置必须一致。
- Redis 只做可丢弃的网页抓取缓存及原子限流：disabled 默认不建立连接；cache 故障作为 miss，限流启用时 Redis 不可用须明确拒绝新受限请求，不能静默失去限流。来源缓存保留原采集时间与 TTL，不把重用时间当成事实核验时间，不缓存失败/摘要/凭据 URL/价格动态选项，不替代证据准入。
- 缓存键包含安全的 URL 摘要、抓取策略版本/选项；缓存值为原始 typed 采集产物，命中仍走身份与正文校验。限流按可信服务器取得的主体/工作区，先覆盖付费 run 创建入口，不从客户端任意身份 header 绕过。现有 run token 预算仍单独执行。
- SSE 接受持久化事件游标，进程重启后可补读且不重复历史事件；任务从已持久化图 checkpoint 恢复，人工等待保持等待。对 real 模式中断请求只做显式恢复，避免启动时自动重跑外部调用；Temporal Activity 重试使用相同 run/checkpoint，费用预算从持久化状态恢复。
- 备份需停止写入方后导出 Postgres、SQLite/产物 volume 和 Qdrant 的一致快照，生成清单/校验；恢复默认到独立项目/目录，不覆盖当前卷。故障脚本要求显式 --execute 与隔离项目，不能误停现有开发服务。

## 任务

### 1. 部署配置与交付工具

文件：`docker-compose.yml`、`scripts/docker_deploy.py`、新建备份/故障验收脚本、`docker/nginx.conf`、部署测试。

- [x] 先写 RED：轻量/持久模式依赖、可选 Redis、localhost 默认/LAN 鉴权、image 非 latest、readiness HTTP 状态、无效参数不执行变更。
- [x] 实现版本固定与 profile、统一启动/检查命令、内网模式鉴权检查、只显示非秘密状态；保留既有开发入口兼容。
- [x] 备份恢复及容器故障步骤生成受控计划；只读预检默认不改变容器、卷或数据。相关单测与命令构造测试通过。

### 2. 可选 Redis 组件

文件：新建 `backend/packages/infrastructure/redis_runtime.py`、组件单测；主代理随后接入实际 fetch / API。

- [x] 先写 RED：默认关闭不连接、TTL/策略隔离、原采集时间、失败/不完整值拒绝、原子限流及重试时间、Redis 故障与短超时。
- [x] 用 redis-py 异步客户端实现惰性连接、有界 JSON 缓存与 Lua 原子窗口限流；固定 key prefix，URL/token 不进入明文 key/日志。使用伪 transport 完成无网络测试；真实 Redis Lua/TTL 留跨机验收。
- [x] 主代理接入 `fetch_evidence_page` 和经鉴权的 run 写入口，验证模块确实被调用及失败策略。

### 3. 恢复与持久化

文件：`backend/packages/orchestrator/service.py`、`backend/app/routers/stream.py`、运行恢复接口/相关测试，必要时配置与 API schema。

- [x] 重现 SSE 无客户端游标/重启重复历史、图恢复重复起步与预算持久化风险；先写失败回归。
- [x] 最小修复持久化游标/显式恢复；不自动重放未知外部副作用，已有 HITL/幂等/token 预算继续有效。
- [x] 离线测试真实 SQLite 重开、checkpoint 恢复、事件游标、重复提交、Redis 断连及源缓存日期，使用假模型/禁外网。

### 4. 验证与交付

- [x] 当前源码相关测试、后端完整回归、必要前端/接口生成检查、独立代码审查与凭据扫描。
- [x] 更新 README、部署文档、Agent 功能和本轮交付记录，区分离线已验证与 Docker/Redis/Postgres/Qdrant/Temporal 实机待验收。
- [x] 不运行本机 Docker。交付另一台机器的预检、启动、备份恢复、隔离故障验收命令与需回传的脱敏结果。

## 实施补充

- 独立审查后修复项目/卷归属、最终端口验证与显式 Compose 文件；示例默认改为 loopback。
- 执行归属由内部真实路由写入，旧 unknown 不迁移；恢复重新检查当前模型策略。
- 新增仅部署机显式执行的 Redis 实机探针，默认 preview，真实 Lua/TTL 验收仍未执行。
- Compose 依赖镜像使用明确标签；基镜像部分 tag 与 Python 依赖未完全锁定，未锁 digest。
- Docker、HTTP Qdrant、Postgres/Temporal 容器故障与真实 Redis 验证移交另一台电脑，不能算作本机已通过项。
