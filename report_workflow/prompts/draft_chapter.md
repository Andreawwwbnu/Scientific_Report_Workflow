version: 3.0
===SYSTEM===
你是{{persona}}。你必须严格遵守来源、引用、结构与篇幅约束，只使用输入材料中的信息。
===USER===
请撰写《{{report_title}}》中的一章：{{chapter_heading}}。

<citation_rules>
（最高优先级）
严禁编造作者、文献、数据、实验结果、案例、时间、市场规模、技术结论；只能使用 <analysis> 与 <evidence> 中的信息。
允许的来源编号只有：{{allowed_ids}}
正文引用统一使用上角标：<sup>[{{id_prefix}}01]</sup>；多来源：<sup>[{{id_prefix}}01][{{id_prefix}}03]</sup>。
禁止裸写 [编号]、（编号）、数字角标，禁止创造新编号。
引用必须继承素材中已标注的来源，不得凭标题或自身知识重新分配来源。
引用节制：同一来源支撑同一事实只引用一次；每个论点至多标注 2 个来源。
</citation_rules>

<structure_rules>
1. 必须按 <headings> 逐行原样输出标题（含 # 号），顺序不变，不得增删改；标题下的内容必须对应该标题的主题，禁止跨节串写。
{{subheading_rule}}
2. 有 ### 小节时，每节内部统一结构：首句给出本节核心判断（总起句）→ 随后 2—3 段展开；每段只论证一个论点，段首句即该段结论，段内按“论点→机制→证据”展开。
3. 每段不超过 {{max_paragraph_chars}} 字；每句只承载一个判断；删除一切铺垫、套话、过渡句与“综上/总之”式复述。
4. 全文去重：同一论据、数据、结论只出现一次。{{other_chapters_note}}
</structure_rules>

<style_rules>
围绕技术本身组织，不写成文献罗列，少用“某某提出/认为”；客观、严谨、精炼、技术化，避免营销与新闻稿语言；未经材料支持，禁用“革命性/颠覆性/划时代”等词。
{{style_rules}}
</style_rules>

<length>
本章正文 {{min_chars}}–{{max_chars}} 字（目标约 {{target_chars}} 字，标题与引用角标不计）。某节论据不足时写少而非注水，不得为凑字数重复观点。
</length>

<chapter_guide>
{{write_guide}}
</chapter_guide>

<headings>
{{headings}}
</headings>

<skipped_sections>
{{skipped_note}}
</skipped_sections>

<analysis>
以下是分析结论（论证骨架）：
{{analysis}}
</analysis>

<evidence>
以下是证据池（事实陈述 + 来源编号）：
{{evidence}}
</evidence>
{{other_chapters}}
{{feedback}}
直接输出本章 Markdown，不要任何前置说明或代码块。
