# 局部调研报告

## 执行摘要

仅展示通过逐条审核的资料观察；未完成问题仍待核实，不能据此排名。

## 竞争发现

### 功能

### Cloudflare — 功能

- Cache Domain Purge 角色授予清除特定域边缘缓存的权限，并允许读取区域设置。 [source:raw-source-c71a5d8161af6e06ae53]

- 角色只能被分配到其给定的作用域，且多个角色可以分配给同一策略。 [source:raw-source-c71a5d8161af6e06ae53]

- Cloudflare Workers Paid 的 Standard 用量模式下，请求计费为每月包含 1000 万次请求，超出部分每百万次加收 0.30 美元。 [source:raw-source-52ba7b31b51e937245c1]

- Cloudflare Workers Paid 计划对账户设有每月最低收费 5 美元。 [source:raw-source-52ba7b31b51e937245c1]

#### 问题回答情况

- Cloudflare: 同事只被授予 example.com 的 Cache Domain Purge 角色，没有任何其他角色。他能因此清除同一 Cloudflare 账户里 other.example 的边缘缓存吗？ — 已回答
  结论：否
  Cache Domain Purge 角色授予清除特定域边缘缓存的权限，并允许读取区域设置。 由于 Cache Domain Purge 角色仅作用于特定域，且角色只能被分配到其给定作用域，仅被授予 example.com 的 Cache Domain Purge 角色并不能确立对同一账户内 other.example 的清除边缘缓存权限。 角色只能被分配到其给定的作用域，且多个角色可以分配给同一策略。 [source:raw-source-c71a5d8161af6e06ae53]
- Cloudflare: 我们用 Cloudflare Workers Paid 的 Standard 用量模式，这个月有 1500 万次动态请求。本月账单准确是多少美元？ — 尚未核实
  本次已审核证据尚未完整覆盖此问题。

## 置信度说明

已审核只表示绑定证据在本次模型审核中支持该观察，不代表人工验收或产品总体质量。未发布的主张保留在审核记录中。下一步：核验相同任务的操作、角色与条件。

## 证据附录

- Cloudflare：Pricing · Cloudflare Workers docs [source:raw-source-52ba7b31b51e937245c1]
- Cloudflare：Account roles · Cloudflare Fundamentals docs [source:raw-source-c71a5d8161af6e06ae53]
