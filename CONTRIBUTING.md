# 贡献与代码规范

> 本文档定义 **Competiscope v2 (Plan A)** 项目的代码规范。所有贡献者（包括人类与 AI 协作者）必须遵守。
> 最后更新：2026-06-06

---

## 1. 通用原则

1. **简单优先**：能用 30 行解决的不要写 300 行。拒绝过早抽象、配置化、speculative flexibility。
2. **小步提交**：每次 commit 只做一件事，diff 行数控制在可 review 范围。
3. **可读性 > 性能 > 巧妙**：除非有数据支撑的瓶颈，否则先写人能看懂的代码。
4. **测试覆盖关键路径**：业务逻辑、边界、错误处理必须有测试。框架代码、纯类型导出可豁免。
5. **中文优先**：注释、commit message、PR 描述、文档用中文。技术术语保留英文。

---

## 2. Python 后端 (FastAPI + Pydantic v2)

### 2.1 工具链
- **包管理**：`pyproject.toml`（PEP 621），pip 装开发依赖
- **Lint / Format**：`ruff check` + `ruff format`（已配 `backend/ruff.toml`）
- **类型检查**：`mypy --strict` 或 Pyright（计划中）
- **测试**：`pytest`，文件命名 `test_*.py`

### 2.2 代码风格
- 缩进 4 空格，行宽 100
- 类型注解**必须**（参数 + 返回值）
- Pydantic v2 模型，禁用 mutable 默认值（用 `Field(default_factory=...)`）
- 公共函数写 docstring（中文，一句话 + 详细可选）
- 异步优先；同步阻塞调用必须显式走 `asyncio.to_thread`

### 2.3 目录结构
```
backend/
  app/                       # FastAPI 入口、路由、依赖
    main.py
    routes/                  # REST 路由
    routers/                 # 兼容层（deprecated，新代码用 routes/）
  packages/                  # 业务包
    knowledge/               # RAG + KB
      parsers/               # 多格式解析器（base + html/md/json/csv/text）
      embeddings.py          # 嵌入 provider
      reranker.py            # 重排 provider
      eval.py                # 评估指标
      ingestion.py           # 入库 pipeline
      retrieval.py           # 检索服务
      repository.py          # SQLite 仓储
      models.py              # Pydantic 模型
      vector_store.py        # Qdrant 适配
    crawler/                 # 爬虫子系统
      sources.py             # 多源适配器（sitemap/RSS/web_search/manual）
      scheduler.py           # 调度器
      fetcher.py             # HTTP 抓取
      parser.py              # HTML 解析（trafilatura）
      policy.py              # 限流 + SSRFGuard
      repository.py          # 持久化 frontier
      models.py
    agents/                  # LangGraph 节点
    orchestrator/            # DAG + scoping
    schema/                  # 共享 schema（与 packages 解耦）
    llm/                     # LLM 客户端
    config/                  # 配置
    observability/           # trace
  tests/unit/                # pytest
  Dockerfile
  pyproject.toml
  ruff.toml
```

### 2.4 错误处理
- 自定义异常继承自领域根异常（如 `KnowledgeError`）
- 路由层用 `HTTPException` 转换，**不**在仓储层抛 HTTPException
- 关键错误必须记录到 observability（trace span）

---

## 3. TypeScript 前端 (React + Vite)

### 3.1 工具链
- **包管理**：`pnpm`（已配 `pnpm-workspace.yaml`）
- **Lint**：`pnpm lint`（ESLint + react-hooks）
- **类型**：`tsc --noEmit`（tsconfig strict mode）
- **测试**：`vitest`（unit）+ `playwright`（e2e）

### 3.2 代码风格
- 缩进 2 空格，行宽 100
- **禁止 `any`**，所有函数参数/返回值必须有类型
- React 组件：函数组件 + hooks；class 组件**禁用**
- 状态管理：**zustand**（store）+ **tanstack-query**（server state）
- 文件命名：组件 PascalCase，工具 camelCase，常量 UPPER_SNAKE_CASE
- 引入顺序：React → 第三方 → 本地（用 ESLint 规则强制）

### 3.3 目录结构
```
frontend/
  src/
    api/                     # REST/SSE 客户端（按资源分子文件）
      client.ts              # fetch 封装
      knowledge.ts
      crawl.ts
      batch.ts
      eval.ts
      types.ts               # 自动生成（不要手改）
      index.ts               # barrel
    stores/                  # zustand stores
      knowledgeStore.ts
      crawlStore.ts
      searchStore.ts
    pages/                   # 路由级页面
    features/                # 功能模块
      swimlane/
      upload/                # F1 批量上传
      version/               # F2 版本视图
      retrieval/             # F3 检索参数
      eval/                  # F4 评估
      crawl/                 # F5-F7
    components/              # 通用 UI 原子
    lib/                     # 工具函数
  scripts/                   # 维护脚本
    check-openapi-sync.sh    # F10
    check-openapi-sync.ps1
  tests/                     # vitest
  e2e/                       # playwright
  package.json
  tsconfig.json
  vite.config.ts
  tailwind.config.ts
```

### 3.4 性能与正确性
- useEffect 必须有 cleanup（polling 定时器、订阅、AbortController）
- 长列表必须用虚拟化（react-virtuoso / react-window）
- SSE/轮询任务用 `AbortSignal` 取消
- 模块级变量**禁止**（zustand state 替代）

---

## 4. Git 工作流

### 4.1 Conventional Commits（中文 scope 允许）

```
<type>(<scope>): <description>

[body]

[footer]
```

- **type**: `feat` `fix` `refactor` `perf` `docs` `test` `chore` `ci`
- **scope**: 模块名（中文允许），如 `feat(knowledge): 添加批量入库` `fix(crawler): 修复 SSRF bypass`
- **description**: 中文，简洁（≤50 字符）
- **body**: 详细说明（可选）

示例：
```
feat(knowledge): 添加批量入库 API 与文档版本管理

- POST /api/knowledge/batch 支持 url/text/base64 三种来源
- SQLite 加 WAL、迁移表、chunks_fts
- 文档版本链 / diff / merge 三件套

Refs: B1, B5
```

### 4.2 分支策略
- `main`：稳定分支，发布
- `feat/<scope>`：功能分支
- `fix/<scope>`：修复分支
- 长寿命分支需要 issue/MR 引用

### 4.3 提交前检查
- `ruff check` + `ruff format`
- `pytest -q` 全过
- `pnpm lint` + `tsc --noEmit` + `npm run build`
- 不提交 `__pycache__` `node_modules` `.venv` `runs/*.db` `*.pyc`

### 4.4 Commit 范围
- **不** 混多个 type（如 feat + fix 拆两个 commit）
- **不** 顺带 refactor（除非明确说明）
- **不** 提交跟任务无关的格式调整

---

## 5. 文档规范

### 5.1 仓库根
- `README.md`（中文）：项目介绍、quick start、当前状态
- `CONTRIBUTING.md`（本文档）：贡献与代码规范
- `LICENSE`：声明许可证

### 5.2 模块文档
每个 `packages/<module>/` 或 `features/<module>/` 应有：
- 模块级 README（可选但推荐）
- 关键类/函数 docstring
- 复杂逻辑注释（**为什么**而非**是什么**）

### 5.3 API 文档
- 后端：FastAPI 自动生成 `/docs`（Swagger UI）
- 前端：`api/types.ts` 由 `openapi.json` 自动生成
- OpenAPI 同步检查：`frontend/scripts/check-openapi-sync.sh`

### 5.4 决策记录（ADR）
重大技术决策写 `docs/decisions/NNNN-title.md`：
- 状态（proposed/accepted/deprecated）
- 上下文
- 决策
- 后果

---

## 6. 错误与日志

### 6.1 后端
- 用 `logging`（不用 `print`）
- 关键操作（ingest/crawl/eval）写 `observability/trace`
- 用户错误（4xx）记录 `warning`；系统错误（5xx）记录 `error` + traceback

### 6.2 前端
- 用户错误：toast/notification
- 系统错误：`Sentry` 或自建错误上报
- 不在 console 输出敏感信息

---

## 7. 安全规范

1. **绝不**提交 `.env` 文件（`ARK_API_KEY`, `PPLX_API_KEY` 等）
2. **绝不**在前端代码中放 API 密钥
3. SSRF / 命令注入 / SQL 注入：见 `verify-security` 关卡
4. 用户上传文件必须 MIME 嗅探 + 大小限制 + 病毒扫描（生产环境）

---

## 8. 评审清单（提交前自查）

- [ ] `ruff check` + `ruff format` 通过
- [ ] `pytest` 通过
- [ ] `pnpm lint` + `tsc --noEmit` + `npm run build` 通过
- [ ] 没有遗留 `print` / `console.log` / 注释代码
- [ ] 没有未使用的 import / 变量
- [ ] docstring 完整（公共 API）
- [ ] 重大决策有 ADR 或 commit body 解释
- [ ] Commit message 符合 Conventional Commits

---

## 9. AI 协作者规范

本项目大量使用 Codex / Claude 作为开发协作者。AI 协作者必须：

1. **不写产品决策**：决策写进 `docs/decisions/` 或 commit body，**不**写在代码注释
2. **遵循现有风格**：通过读相邻文件 + ruff/tsconfig 配置确认
3. **完成度优先**：宁可任务范围更窄但完整，**不**留 TODO/未实现方法
4. **测试同行**：每个新功能带测试，**不**留"未来补"
5. **冲突时先报告**：AI 协作者之间有冲突时由 Claude (orchestrator) 仲裁

---

## 附录：常用命令

```bash
# 开发
make dev-backend        # uvicorn --reload
make dev-frontend       # pnpm dev

# 测试
make test-backend       # pytest
make test-frontend      # pnpm test
make m0-check           # 离线健康检查
make smoke-llm          # 真实 LLM smoke

# 契约同步
make sync-openapi       # 导出 openapi.json + 重生 types.ts

# 演示
make demo               # docker compose up
```

---

如有疑问，在 issue 里引用本文档具体节号讨论。
