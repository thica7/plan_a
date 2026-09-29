# 明亮田园像素工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成已确认的全站中文化、明亮田园像素主题和真实浏览器交互验收。

**Architecture:** 静态文案继续使用现有 i18n 字典；独立显示函数本地化状态、维度与已知系统诊断，业务数据与请求保持原值。统一桌面调色板与共用组件样式，保留现有 React 业务页；以真实交互回归修复桌面焦点和页面内导航。

**Tech Stack:** React 18、TypeScript、Zustand、原生 CSS/SVG、Vitest/Testing Library、Vite、Codex 浏览器验收。

工作目录：`/Users/a1/Documents/ChatGPT/竞品分析优化/plan_a_pm_modes`。下方 pnpm 命令在 `frontend` 中执行。依次实施，每批分别通过规格与质量审查；用户已授权持续执行，不再按批次请求许可。

---

### Task 1: 中文显示基础与研究主流程

**Files:** 新建 `frontend/src/i18n/display.ts`、`display.test.ts`；修改 `frontend/src/stores/i18n.ts`、`frontend/src/pages/NewRun.tsx`、`RunDetail.tsx`、`History.tsx`；覆盖 `frontend/src/features/new-run/`、`run-detail/`、`history/`、`hitl/`、`report/`、`discovery/`、`kb/`、`trace/`、`graph/`、`swimlane/`、`messages/`、`revisions/`、`cost/` 中面向用户的文案。

- [ ] 先写显示回归：中文名称不改变 API 枚举，英文切换可恢复，未知产品名和引用正文原样保留。

```ts
expect(displayLabel('feature', 'zh-CN')).toBe('功能体验');
expect(displayLabel('draft', 'zh-CN')).toBe('草稿');
expect(displayLabel('feature', 'en-US')).toBe('feature');
expect(displayLabel('iPhone Duo', 'zh-CN')).toBe('iPhone Duo');
```

- [ ] 运行 `pnpm test src/i18n/display.test.ts`，确认缺少实现失败。追加真实 DimensionsSection 的中文名称/说明与请求仍使用 `feature` 的组件回归。
- [ ] 实现只作用于显示的词表与维度说明；使用 `t()` 替换静态用户文案。已知 runtime 诊断显示中文；原始诊断可以查看，来源正文不进入翻译函数。

```tsx
const { locale, t } = useTranslation();
<strong>{displayLabel(skill.name, locale)}</strong>
```

- [ ] 翻译标题、数值单位、状态、占位符、辅助提示、空状态、审核操作与可访问名称；不更改请求数据、QA 判定或报告文本。
- [ ] 运行相关组件测试、`pnpm test`、`pnpm build`；自行检查没有 DOM 内容替换与未知证据正文翻译。提交 `feat: localize research workflow and display labels`。

### Task 2: 知识、采集与工作台中文覆盖

**Files:** `frontend/src/pages/KnowledgePage.tsx`、`SearchPage.tsx`、`CrawlPage.tsx`、`EnterpriseWorkbench.tsx`；`frontend/src/features/workbench/*.tsx`、`crawl/*.tsx`、`retrieval/`、`upload/`、`version/`；`frontend/src/components/SourceCard.tsx`、`frontend/src/components/product-shell/`；`frontend/src/features/desktop/FilesApp.tsx`、`DesktopSettings.tsx`；扩展 Task 1 的词表和字典。

- [ ] 用真实工作台组件与已有 fixture 写失败测试，断言中文模式渲染“覆盖热图”“草稿”“未满足发布条件”，业务状态仍是 `draft/blocked`；验证切回英文。
- [ ] 运行新增测试确认失败；逐页把静态文案放入 i18n，复用统一枚举标签。英文 backend QA finding 保留 code 与原文，面向用户的说明使用明确中文映射，不假造后端没有的数据。

```tsx
<StatusPill tone={reportStatusTone(version.status)}>
  {displayLabel(version.status, locale)}
</StatusPill>
```

- [ ] 覆盖工作台概览、证据、竞品、报告、治理、活动，知识文档状态、检索参数、采集失败/空状态、文件预览与设置说明。保留检索结果、报告正文、产品名称与 URL 原文。
- [ ] 运行 `pnpm test`、`pnpm build`、`pnpm audit:interactions`；审查遗漏的 JSX 英文文字和英文占位符并分类。提交 `feat: complete Chinese workbench and data tools`。

### Task 3: 田园像素主题、桌面行为与报告阅读

**Files:** `frontend/src/styles/desktop.css`、`design-tokens.css`、`app.css`（仅需要时）；`frontend/src/features/desktop/Desktop.tsx`、`DesktopWindow.tsx`、`PixelIcon.tsx`、`apps.tsx`、`windowStore.ts` 及测试；新建 `PastoralWallpaper.tsx`；`frontend/src/features/run-detail/ReportOutline.tsx`、`RunReportReviewStudio.tsx`、`ReportReaderWorkspace.tsx`、`frontend/src/features/report/ReportView.tsx` 及相关测试。

- [ ] 先复现同一运行的 view/hash 导致重复窗口、非活跃窗口第一次点击丢失和目录跳到其他窗口。添加窗口资源身份回归：

```ts
const id = useDesktopStore.getState().open('/runs/a?view=report');
expect(useDesktopStore.getState().open('/runs/a?view=quality#issue')).toBe(id);
useDesktopStore.getState().open('/runs/b');
expect(useDesktopStore.getState().windows).toHaveLength(2);
```

- [ ] 添加实际组件内锚点回归：跳转保留当前运行查询参数、不创建窗口、不选中其他窗口同名 ID。测试先失败，再根据数据流修复，不用强制刷新掩盖问题。
- [ ] 实现原创 CSS/SVG 像素天空、云、远山、草地与小屋；统一白天/夜间桌面 token。基础配色：天空 `#9edffa`、嫩草 `#9bcc6b`、纸张 `#fff1cb`、暖木 `#c58b58`、正文 `#473a2d`。实际按钮和状态颜色需保持可辨认对比。
- [ ] 共用卡片、表格、输入、按钮和审核弹窗统一像素阶梯边框/硬阴影；图标有限多色，正文使用现有中文系统字体。界面无远程字体或游戏素材依赖。
- [ ] 调整报告布局：正文紧接简明状态摘要；指标、来源、诊断可展开。无功能的“比较”按钮明确禁用并有中文说明。窄窗口单栏并隐藏失效的拖动/缩放装饰，保留滚动与键盘访问。
- [ ] 运行桌面、报告、详情组件测试及 `pnpm test`、`pnpm build`、交互审计；检查深色和减少动态偏好。提交 `feat: brighten the pastoral pixel desktop and repair navigation`。

### Task 4: 浏览器验收与交付

**Files:** `docs/optimization/2026-09-29-pastoral-desktop-results.md`；必要时补充前三项中的针对性回归。

- [ ] 通过现有本地服务在实际浏览器检查：桌面启动入口、非活跃窗口第一次点击、最小化恢复、最大化还原、表单手动竞品、极简/协作选择、一次 demo 运行、报告目录、知识库/搜索/采集、设置语言切换。
- [ ] 大桌面和窄屏分别截图；确认没有页面级横向滚动、浮层遮挡操作、状态文字溢出。检查浅色、深色和错误/加载状态。
- [ ] 对发现的问题按根因修复并加必要测试；纯文字和视觉调整采用浏览器验证，不增加实现镜像测试。
- [ ] 最终执行 `pnpm test`、`pnpm build`、`pnpm audit:interactions`、`git diff --check`；记录测试数量、86 条历史 allowlist 警告是否变化、未验证的真实服务能力。
- [ ] 规格审查通过后进行代码质量审查，修复重要问题。保留本地分支和可运行演示，不发布或合并。提交验收记录并向用户展示明亮像素页面。
