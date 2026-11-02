# 局部调研报告

## 执行摘要

仅展示通过逐条审核的资料观察；未完成问题仍待核实，不能据此排名。

## 竞争发现

### 功能

### Cloudflare — 功能

- Cache Domain Purge 角色包含特定域的边缘缓存清除权限。 [source:raw-source-c71a5d8161af6e06ae53]

- Cloudflare 角色只能被赋予其给定作用域（Roles can only ever be assigned to their given scope）。 [source:raw-source-c71a5d8161af6e06ae53]

- Workers Paid 套餐的 Standard 用量模式以 CPU 时间作为计费维度。 [source:raw-source-52ba7b31b51e937245c1]

- 条件推断：当前缺少足以确定该项费用的可计费 CPU 总量或可靠用量界限，不能仅凭动态请求数核实完整账单。 [source:raw-source-52ba7b31b51e937245c1]

#### 问题回答情况

- Cloudflare: 同事只被授予 example.com 的 Cache Domain Purge 角色，没有任何其他角色。他能因此清除同一 Cloudflare 账户里 other.example 的边缘缓存吗？ — 部分回答
  结论：需按条件判断
  - 他能因此清除同一 Cloudflare 账户里 other.example 的边缘缓存吗？ (other.example) — 尚不能确定
  Cloudflare 角色只能被赋予其给定作用域（Roles can only ever be assigned to their given scope）。 [source:raw-source-c71a5d8161af6e06ae53]
- Cloudflare: 我们用 Cloudflare Workers Paid 的 Standard 用量模式，这个月有 1500 万次动态请求。本月账单准确是多少美元？ — 部分回答
  结论：尚不能确定
  Workers Paid 套餐的 Standard 用量模式以 CPU 时间作为计费维度。 当前缺少足以确定该项费用的可计费 CPU 总量或可靠用量界限，不能仅凭动态请求数核实完整账单。 [source:raw-source-52ba7b31b51e937245c1]

## 置信度说明

已审核只表示绑定证据在本次模型审核中支持该观察，不代表人工验收或产品总体质量。未发布的主张保留在审核记录中。下一步：核验相同任务的操作、角色与条件。

## 证据附录

- Cloudflare：Pricing · Cloudflare Workers docs [source:raw-source-52ba7b31b51e937245c1]
- Cloudflare：Account roles · Cloudflare Fundamentals docs [source:raw-source-c71a5d8161af6e06ae53]
