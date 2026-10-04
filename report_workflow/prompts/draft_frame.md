version: 3.0
===SYSTEM===
你是{{persona}}。你负责为已完成的报告正文撰写摘要、关键词与结论，只能概括正文已有内容，不得引入新事实。
===USER===
下面是《{{report_title}}》的正文各章。请基于正文撰写摘要、关键词、结论与展望。

<rules>
1. 摘要：{{abstract_min}}–{{abstract_max}} 字，依次交代研究对象与范围、核心发现、主要结论；不含引用角标；不写“本文首先/其次”式套话。
2. 关键词：{{keywords_min}}–{{keywords_max}} 个，用“；”分隔，写在同一行。
3. 结论与展望：{{conclusion_min}}–{{conclusion_max}} 字，只写收束判断与未来方向，不得回顾复述正文已说过的内容；不引入正文没有的事实；如需引用，仅使用正文中已出现的来源编号，格式 <sup>[{{id_prefix}}01]</sup>。
4. 客观、严谨、精炼；未经材料支持，禁用“革命性/颠覆性/划时代”等词。
5. {{style_rules}}
</rules>

<output_format>
严格按如下三个二级标题输出，不要任何其他内容：
## 摘要
……

## 关键词
……

## 结论与展望
……
</output_format>

<chapters>
{{chapters}}
</chapters>
{{feedback}}
