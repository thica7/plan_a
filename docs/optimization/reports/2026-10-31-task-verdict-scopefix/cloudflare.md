# 局部调研报告

## 执行摘要

仅展示通过逐条审核的资料观察；未完成问题仍待核实，不能据此排名。

## 竞争发现

### 功能

### Cloudflare — 功能

- Cloudflare 的 Cache Domain Purge 角色授予清除特定域边缘缓存的权限，并允许读取区域设置。 [source:raw-source-c71a5d8161af6e06ae53]

- Cloudflare 的域范围角色仅适用于账户内指定的某个域。 [source:raw-source-c71a5d8161af6e06ae53]

#### 问题回答情况

- Cloudflare: 同事只被授予 example.com 的 Cache Domain Purge 角色，没有任何其他角色。他能因此清除同一 Cloudflare 账户里 other.example 的边缘缓存吗？ — 已回答
  结论：否
  - 他能因此清除同一 Cloudflare 账户里 other.example 的边缘缓存吗？ (other.example) — 否
  Cloudflare 的 Cache Domain Purge 角色授予清除特定域边缘缓存的权限，并允许读取区域设置。 仅被授予 example.com 的 Cache Domain Purge 角色（无其他角色）并不蕴含其可清除同一 Cloudflare 账户内 other.example 的边缘缓存，因为域范围角色仅适用于账户内的指定域。 Cloudflare 的域范围角色仅适用于账户内指定的某个域。 [source:raw-source-c71a5d8161af6e06ae53]
- Cloudflare: 我们用 Cloudflare Workers Paid 的 Standard 用量模式，这个月有 1500 万次动态请求。本月账单准确是多少美元？ — 部分回答
  已给请求条件：购买范围 Workers Paid、报价币种 美元。本次请求及已准入资料不足以核实准确的完整账单。请先确认：适用市场／地区、税费口径、CPU 总用量、完整用量明细及其他计费项目；补齐适用的定价资料和输入后，再核验截至 2026-10-31 的适用金额。

## 置信度说明

已审核只表示绑定证据在本次模型审核中支持该观察，不代表人工验收或产品总体质量。未发布的主张保留在审核记录中。下一步：核验相同任务的操作、角色与条件。

## 证据附录

- Cloudflare：Account roles · Cloudflare Fundamentals docs [source:raw-source-c71a5d8161af6e06ae53]
