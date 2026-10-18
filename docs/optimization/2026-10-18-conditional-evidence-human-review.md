# 八题与三条标签的人工确认记录

项目用户已明确回复：

> 认可这8题的边界和修正后的T1–T3标签。允许继续，先修复Miro关键证据漏选、套餐前提遗漏和GitBook中文条件句误判，再跑独立评测，暂时不训练模型。

处理记录时间：2026-10-18T02:15:30Z（不是声称原消息的精确时间）。

- 8 题的问句、官方来源和参考边界保持不变；[已审核数据](../../eval/agent-readiness-holdout-v1-reviewed.jsonl)与[审核 manifest](../../eval/agent-readiness-holdout-v1-reviewed-manifest.json)记录原 candidate 与 reviewed 文件 SHA。
- T1 只确认 Basecamp 单题条件结论正确，不把旧工作流、引用绑定或整份报告标记成功。
- T2 确认 GitBook “仅 Enterprise”排他结论错误；T3 确认缺指定口径精确报价时合理不足答复。
- [三条已审核标签](../../eval/agent-readiness-trajectory-review-v1-reviewed.json)保留 run/question/report SHA 作用域。原 candidate 文件及旧轨迹导出不改写。

这次人工确认针对参考边界和旧单题标签，**不是对后续生成报告的验收**。新运行仍须逐题核查答案、全部子问、条件和引用；机器审核单独标记，正确性奖励不自动赋值。训练与权重下载继续关闭。

原始候选问题及官方链接保留在[候选构造时的人审单](2026-10-18-agent-readiness-human-review.md)。它的 candidate 文案是历史构造状态；本记录及 reviewed 数据说明当前确认状态。实现代理不得读取新参考后调修复；runtime 只传问题和官方来源身份。
