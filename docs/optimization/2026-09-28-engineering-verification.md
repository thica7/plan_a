# 工程与端口优化验收记录

日期：2026-09-28。分支：`codex/optimization-desktop`。

## 已完成

- Compose backend / temporal-worker 共享环境，使用 `http://qdrant:6333` 与
  `/app/runs/knowledge_docker.db`，共享数据卷，两者依赖 Qdrant 的健康检查。
- Qdrant `/readyz` readiness 使用官方 Debian 镜像中的 Bash TCP，无需 curl / wget。
  宿主 Qdrant 端口支持 `QDRANT_BIND`。
- `.env.example` 补本地端口、KB 路径、provider、collection / index version；provider 从同一份
  `.env` 传给 backend / worker，Compose 不覆盖 provider 选择。
- Windows 和 Mac/Linux 共用 Python 标准库运行入口，解释器探测项目 `.venv` / PATH，
  支持显式 `PYTHON_EXECUTABLE` / `NODE_EXECUTABLE`。
- 后台 PID 写入项目记录。停止前校验仓库、服务路径、PID 创建标记；端口占用者仅用于诊断。
- 启动明确传入 Vite port / strictPort / API target，状态读取实际启动记录。
- Docker 启动入口从 Compose 解析结果生成访问地址，Makefile 默认采用项目 `.venv`。

## 实测

| 检查 | 结果 |
| --- | --- |
| 首轮回归测试（实现前） | 11 failed，统一运行入口缺失 |
| 补充状态与路径边界（实现前） | 新增 3 failed：新 `.env` 干扰历史状态、路径前缀冒认、占用者诊断缺失 |
| `.venv/bin/python -m pytest backend/tests/unit/test_dev_runtime.py -q` | 16 passed；补测无法读取活跃任务与带负时区时间戳的拒停逻辑 |
| 目标 Python 文件 Ruff | 通过 |
| `git diff --check` | 通过 |
| 5 个 shell 入口 `bash -n` | 通过 |
| shell start / stop / status / Compose help 入口 | 通过 |
| Makefile 运行入口 `make -n` | 正确采用 `.venv` 和透传参数 |
| `tsc -p tsconfig.node.json --noEmit` | 通过 |
| 实际 Vite 服务 + 临时 API HTTP 服务 | 自定义前端端口生效，`/api/health` 到达自定义后端端口 |
| 实际 Vite 端口冲突 | strictPort 拒绝启动，保持原服务监听 |
| YAML 解析与环境/依赖检查 | backend/worker 环境一致，Qdrant service_healthy gate 正确 |
| readiness shell + 临时 HTTP 服务 | HTTP 503 返回非零；HTTP 200 返回零 |

PID 停止测试只终止该测试自行创建的 Python sleeper，未停止用户进程。
本机 Codex 文件沙盒禁止 `ps`；读取测试创建进程信息的回归项在自动批准的隔离外测试调用中运行。
进程信息读取失败时运行入口拒绝验证归属，不把读取失败视为停止成功。
后端任务状态无法读取时默认拒绝停止；只有显式 `--force` 才跳过该检查。

## 环境限制

- 本机没有 Docker，未执行 `docker compose config` / 镜像构建 / 容器健康启动；仅解析 YAML、
  验证健康检查命令的 HTTP 状态逻辑和 Compose URL 解析函数。
- 本机没有 Windows / PowerShell，未执行 Windows CIM、解释器探测与 `.cmd` 服务启动。
- 未进行需要 Postgres / Temporal / Qdrant 服务的完整本地 backend + worker + Vite readiness。
  `--no-docker` 要求依赖服务已经通过其他方式提供。
- 未调用真实收费模型或搜索 API，未提交或 push。

运行方式及 PID 记录恢复说明见 `docs/docker_deployment.md`。
