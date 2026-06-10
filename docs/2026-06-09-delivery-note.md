# 2026-06-09 交付说明

## 本次交付范围

本次更新围绕三件事收尾：

1. 生成任务入口增加重复创建防护，降低恶意或误操作重复请求造成的服务器压力。
2. Docker Compose 部署链路补齐，并为服务器构建增加可配置镜像源。
3. 将当前 `main` 部署到服务器 `115.190.142.169`，最终公网入口为 `http://115.190.142.169:8990`。

## 当前项目用途

当前项目是一个竞品情报/竞争分析系统。用户通过前端或 API 输入分析目标、竞品、种子线索等任务参数，系统会创建一次 run，调度后端采集、分析、对比和写作流程，最终输出结构化分析结果、证据链、运行状态和报告内容。

核心入口和输出关系：

```text
用户输入任务参数
  -> frontend 新建任务页面
  -> backend /api/runs
  -> Temporal worker 执行采集与分析
  -> Postgres/Qdrant/本地 artifact 保存状态、证据和产物
  -> 前端展示 run 状态、结果和报告
```

## 项目结构检查

本次改动保持在现有结构内，没有引入新的业务层级：

- `frontend/`：React/Vite 前端，负责任务创建、结果查看和用户交互。
- `backend/`：FastAPI 后端、run orchestration、schema、workflow worker 和测试。
- `docker/`：nginx 反向代理配置。
- `docker-compose.yml`：Postgres、Qdrant、Temporal、backend、worker、frontend、nginx 的部署编排。
- `docs/`：架构、部署、交付和调试说明。
- `third_party/webfetch_v2/`：后端 Docker 镜像内使用的抓取能力依赖。

## Docker 部署优化

新增或确认的构建参数如下，默认仍使用官方源；服务器部署时可在 `.env` 中覆盖：

```text
PIP_INDEX_URL
PIP_TRUSTED_HOST
NPM_CONFIG_REGISTRY
PLAYWRIGHT_DOWNLOAD_HOST
APT_MIRROR
APT_SECURITY_MIRROR
```

服务器实际使用了：

```text
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
APT_MIRROR=http://mirrors.aliyun.com/debian
APT_SECURITY_MIRROR=http://mirrors.aliyun.com/debian-security
PLAYWRIGHT_DOWNLOAD_HOST=
APP_BIND=8990
```

说明：`PLAYWRIGHT_DOWNLOAD_HOST` 曾尝试使用 npmmirror，但当前 Playwright Chromium CFT 版本在该镜像缺文件并返回 404，因此最终保留为空，使用官方 CDN 完成下载。

## 服务器部署状态

服务器路径：

```text
/opt/competiscope/plan_a
```

公网入口：

```text
http://115.190.142.169:8990
```

健康检查：

```text
http://115.190.142.169:8990/api/health
```

最终 Compose 状态：

```text
backend: healthy
frontend: running
nginx: 0.0.0.0:8990->80
postgres: healthy, host bind 127.0.0.1:55432
qdrant: running
temporal: running, host bind 127.0.0.1:7233
temporal-ui: running, host bind 127.0.0.1:8233
temporal-worker: running
```

`/api/health` 当前返回 `warn` 是预期状态，原因是服务器 `.env` 未配置真实 LLM 和搜索服务 key；数据库、Temporal、合规、内部策略等核心检查均为 `ok`。

## 自测记录

本次更新后已执行：

```text
docker compose config --quiet
.venv\Scripts\python.exe -m pytest backend\tests\unit\test_temporal_compose.py -q
.venv\Scripts\ruff.exe check backend\tests\unit\test_temporal_compose.py
git diff --check
curl http://115.190.142.169:8990/api/health
curl http://115.190.142.169:8990/
```

结果：均通过。`docker compose config` 在本机输出过 Docker config 权限 warning，但配置校验退出码为 0。

## GitHub 状态

当前已推送到 `origin/main`：

```text
fc66d62 chore: allow apt mirror for docker builds
3baf7ec chore: make docker build sources configurable
d5e904f merge: guard duplicate run creation
```

本地工作区仅剩未跟踪测试产物：

```text
backend/.test-artifacts/
```

该目录未纳入提交。

## PR 建议

这次不需要你再提交 PR。原因是本轮更新已经直接合并并推送到 `main`，服务器也按 `main` 的内容完成部署。

后续如果要走更标准的团队流程，建议从下一次需求开始使用：

```text
feature branch -> pull request -> review -> merge main -> deploy
```

这样 GitHub 上会保留完整评审记录。
