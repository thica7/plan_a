# 优化实施任务清单

> 使用 subagent-driven-development 与 dispatching-parallel-agents 执行互不共享文件的模块任务，逐项进行规格与代码审查。

**Goal:** 完成已授权的工程、RAG、Agent 与像素桌面四阶段优化。

**Architecture:** 保留现有业务图、API 与报告契约，修复运行和检索边界；以桌面外壳承载现有业务应用。各模块按文件所有权隔离，集成后统一验证。

**Tech Stack:** FastAPI、LangGraph、Temporal、SQLite、Qdrant、React、TypeScript、Zustand。

## 执行与验收

- [x] 工程：统一 Docker worker 的 KB/Qdrant 配置；修复端口传递与 PID 归属；补 Mac/Linux 本地入口；测试冲突不会误杀。
- [x] RAG：先写长文尾部、中文与向量失败重试测试；实现 chunk FTS、索引状态及重试；有效 provider 信息与索引版本；扩展实际评测。
- [x] Agent：先写语言往返、并发预算和门禁 smoke 回归；补 Temporal 语言字段；有界并发与总调用预算；清理已确认旧入口、迁移测试。
- [x] 前端：修 RawSource fixture；公共 API 身份处理；runId 隔离状态与订阅；像素桌面、应用注册、窗口/任务栏和深链接；测试双任务互不覆盖与布局恢复。
- [x] 规格审查：对照 2026-09-28-optimization-design.md 检查已落地改动与环境限制，记录在实施报告。
- [x] 代码审查：检查深链接恢复、错误预览、模型版本过滤、旧 shell 与交互契约；已修复发现的问题。
- [x] 本机验证：后端单测、契约/集成测试、前端测试/build、OpenAPI 同步、demo/Temporal thin-shell smoke。
- [ ] 外部环境验收：Docker 容器、Windows 启停、真实模型检索和当前回合浏览器移动端预览；当前环境或浏览器安全策略不支持，详见实施报告。

每项先复现失败，再实现、验证；任务完成后填写实测结果。Docker/Windows 服务验收在环境不可用时明确保留限制，不标记通过。
