# -*- coding: utf-8 -*-
"""
阶段 4：结构化素材 + 分析结论 → 报告草稿（替代旧 generate_final_report.py）
- 参考文献由 literature_manifest 自动生成（作者缺失时用发布主体，禁止 et al.）
- 报告结构蓝图来自 project.yaml.report_blueprint
- 草稿文件名与阶段5共享 common.DRAFT_FILENAME，修复旧版断链
- 质检：结构完整性、引用合法性、镜像归并、分口径字数
"""
from __future__ import annotations

import re

from .common import (
    DRAFT_FILENAME, WorkflowConfig, body_length_for_qc,
    normalize_aliases_in_text, split_frontmatter,
)


def build_references(cfg: WorkflowConfig) -> str:
    lines = []
    for e in sorted(cfg.canonical_entries, key=lambda x: int(re.search(r"\d+", x["id"]).group())):
        author = (e.get("author") or e.get("publisher") or "佚名").strip()
        if "et al." in author.lower():
            raise ValueError(f"{e['id']} 作者含 'et al.'，请在 manifest 补全真实作者或改用发布主体")
        year = str(e.get("date", ""))[:4] or "n.d"
        lines.append(f"[{e['id']}] {author}. {e['title']}.[EB/OL]. {year}. {e['url']}")
    return "\n".join(lines)


def _read(path):
    return path.read_text(encoding="utf-8") if path.exists() else ""


def build_prompt(cfg: WorkflowConfig, refs: str) -> str:
    mat, ana = [], []
    for ch in cfg.chapters:
        m = _read(cfg.structured_path(ch))
        a = _read(cfg.analysis_path(ch))
        mat.append(f"【{ch['name']}·结构化素材】\n{split_frontmatter(m)[1]}")
        ana.append(f"【{ch['name']}·分析结论】\n{split_frontmatter(a)[1]}")
    canonical_ids = sorted(e["id"] for e in cfg.canonical_entries)
    alias_lines = [f"[{old}] 是 [{new}] 的镜像，统一按 [{new}] 处理，不得作为独立文献。"
                   for old, new in cfg.alias_map.items()]
    blueprint = "\n".join(cfg.blueprint)
    wc = cfg.wc_cfg
    return f"""
你是一名专业 AI 技术情报分析师与报告撰稿人。基于提供的结构化素材与分析结论，
撰写《{cfg.report_title}》。

================ 一、引用纪律（最高优先级）===============
严禁编造作者、文献、数据、实验结果、案例、时间、市场规模、技术结论；只能使用输入材料中的信息。
允许的来源编号只有：{', '.join(canonical_ids)}
{chr(10).join(alias_lines) if alias_lines else ''}
正文引用统一使用上角标：<sup>[{cfg.id_prefix}01]</sup>；多来源：<sup>[{cfg.id_prefix}01][{cfg.id_prefix}03]</sup>。
禁止裸写 [编号]、（编号）、数字角标[1]，禁止创造新编号。
引用必须继承素材中已标注的来源，不得凭标题或自身知识重新分配来源。
引用节制：同一来源支撑同一事实只引用一次；每个论点至多标注 2 个来源，禁止 3 个及以上编号连续堆砌。

================ 二、结构与逻辑（决定报告可读性，仅次于引用纪律）===============
1. 严格按下方"四、报告结构"输出，每个标题原样保留；标题下的内容必须直接对应该标题主题，禁止跨节串写。
2. 每个 ### 小节内部统一结构：首句给出本节核心判断（总起句）→ 随后 2—3 段展开，每段只论证一个论点、段首句即该段结论，段内按"论点→机制→证据"展开。
3. 每段不超过 150 字；每句只承载一个判断；删除一切铺垫、套话、过渡句与"综上/总之"式节末复述。
4. 全文去重：同一论据、数据、结论在全文只允许出现一次，放在逻辑最贴合的小节；禁止在不同章节换措辞重复（例如同一机构的职责只能描述一次）。
5. 结论与展望只写收束判断与未来方向，不得回顾复述正文已说过的内容。

================ 三、写作风格与篇幅（口径务必遵守）===============
分析结论是论证骨架，结构化素材是证据池；你负责压缩、组织、提炼、改写为连贯论证。
围绕技术本身组织，不要写成论文罗列，少用"某某提出/认为"。客观、严谨、精炼、技术化，
避免营销与新闻稿语言；未经材料支持，禁用"革命性/颠覆性/划时代"等词。
正文（不含摘要、关键词、参考文献）{wc.get('body_min',2800)}—{wc.get('body_max',3200)} 字；
摘要 {wc.get('abstract_min',250)}—{wc.get('abstract_max',300)} 字；
关键词 5—7 个；结论与展望 150—200 字。
篇幅预算：第一章约 500 字，第二章约 900 字（全文最重要），第三章约 800 字，第四章约 700 字；
某一节论据不足时写少而非注水，不得为凑字数重复观点。

—— 分章写作要点（各章必须遵循）——
- 一、遴选理由：本章不设二级标题，整章连续成文；由后三章素材归纳而成，按"技术特征优势→重要价值→近三年突破性进展→前景判断"顺序简明陈述；结合特征优势说明价值、结合近期进展说明前景良好；客观有据，不展开技术细节。
- 二、技术内涵：全文最重要章节；清晰、准确、简洁地覆盖技术定义与概念范畴、核心机理、技术特征与性能指标、技术边界与适用约束；表述精准专业，只采用权威来源表述。
- 三、最新进展：聚焦近三年全球重大突破性进展与里程碑成果，按时间或技术路线组织；每条进展必须有"时间—主体—成果"三要素与明确来源；酌情补充政策、产业、产品、资本动态；避免空泛表述，不做过度主观判断。
- 四、应用前景与重要价值：描述典型应用场景与科技、经济、社会、国防等多维价值，多从国家战略层面研判；研判必须有理有据，优先使用带权威来源的数据。

================ 四、报告结构（严格照此输出）===============
# {cfg.report_title}
{blueprint}

================ 五、输入材料 ===============
{chr(10).join(mat)}

{chr(10).join(ana)}

================ 六、参考文献（唯一允许输出的列表，原样使用，不得增删改）===============
{refs}

直接输出完整 Markdown 报告，不要任何前置说明或代码块。
"""


def validate_structure(report: str, cfg: WorkflowConfig) -> list:
    missing = []
    for line in cfg.blueprint:
        heading = line.strip()
        if heading not in report:
            missing.append(heading)
    return missing


def _length_issues(lengths: dict, wc: dict) -> list:
    """分口径检查摘要/正文字数是否落在 project.yaml word_count 区间内。"""
    issues = []
    a_min, a_max = wc.get("abstract_min", 250), wc.get("abstract_max", 300)
    b_min, b_max = wc.get("body_min", 2800), wc.get("body_max", 3200)
    if not (a_min <= lengths["abstract"] <= a_max):
        issues.append(f"摘要 {lengths['abstract']} 字，超出 {a_min}-{a_max} 字口径，请压缩/补足")
    if not (b_min <= lengths["body"] <= b_max):
        issues.append(f"正文 {lengths['body']} 字，超出 {b_min}-{b_max} 字口径，请压缩/补足且不得重复观点")
    return issues


def validate_citations(report: str, cfg: WorkflowConfig):
    # 参考文献区的 [FRxx] 是 s4 兜底写入的权威列表，不算正文引用；
    # 统计与裸引用检测都必须只看正文部分，否则全部误报
    body = report.split("## 参考文献", 1)[0]
    used = set(re.findall(rf"\[{cfg.id_prefix}\d+\]", body))
    used = {x.strip("[]") for x in used}
    canonical = {e["id"] for e in cfg.canonical_entries}
    invalid = used - canonical
    # 裸引用：先剔除所有合法 <sup>...</sup> 组（含多连引），剩余即未加上角标的
    without_sup = re.sub(r"<sup>\s*(?:\[\w+\d+\])+\s*</sup>", "", body)
    bare = sorted(set(re.findall(rf"\[{cfg.id_prefix}\d+\]", without_sup)))
    return used, invalid, bare


def run(cfg: WorkflowConfig, llm=None) -> dict:
    print("=" * 72)
    print("🚀 阶段4：生成报告草稿")
    print("=" * 72)
    # 输入齐备性
    missing_inputs = []
    for ch in cfg.chapters:
        if not cfg.structured_path(ch).exists():
            missing_inputs.append(str(cfg.structured_path(ch)))
        if not cfg.analysis_path(ch).exists():
            missing_inputs.append(str(cfg.analysis_path(ch)))
    if missing_inputs:
        print("❌ 缺少阶段2/3产物：")
        for m in missing_inputs:
            print("   - " + m)
        return {"ok": False, "reason": "missing_inputs"}

    refs = build_references(cfg)
    if llm is None:
        from .common import LLMClient
        llm = LLMClient(cfg)
    prompt = build_prompt(cfg, refs)
    print(f"✅ Prompt 构建完成：{len(prompt):,} 字符；参考文献 {len(cfg.canonical_entries)} 条")

    wc = cfg.wc_cfg
    feedback = ""
    for attempt in range(2):
        report = llm.chat(
            model=cfg.llm_cfg["draft_model"],
            system="你是专业 AI 技术情报分析师，必须严格遵守来源、引用、结构与篇幅约束。",
            user=prompt + feedback,
            max_tokens=int(cfg.llm_cfg["max_tokens_draft"]),
            temperature=float(cfg.llm_cfg["temperature_draft"]),
        )
        report = normalize_aliases_in_text(report, cfg.alias_map)
        # 若模型未把参考文献写全，用权威列表兜底替换，保证终稿引用可解析
        if "## 参考文献" in report:
            body_part = report.split("## 参考文献", 1)[0].rstrip()
            report = body_part + "\n\n## 参考文献\n\n" + refs + "\n"

        # 质检：结构、引用、分口径字数
        missing = validate_structure(report, cfg)
        used, invalid, bare = validate_citations(report, cfg)
        lengths = body_length_for_qc(report)
        length_issues = _length_issues(lengths, wc)

        problems = []
        if missing:
            problems.append("缺少章节：" + "；".join(missing))
        if invalid:
            problems.append("非法来源编号：" + ", ".join(sorted(invalid)))
        if bare:
            problems.append("存在未加上角标的裸引用（须改为 <sup>[编号]</sup>）：" + ", ".join(bare))
        problems += length_issues
        if not problems or attempt == 1:
            break
        print(f"⚠️ 第 {attempt + 1} 次草稿质检未过，带反馈重写：{'；'.join(problems)[:150]}")
        feedback = ("\n\n[上次草稿质检未通过，请逐条修正后重新输出完整报告]\n"
                    + "\n".join("- " + p for p in problems))

    cfg.draft_dir.mkdir(parents=True, exist_ok=True)
    cfg.draft_path.write_text(report, encoding="utf-8")

    print(f"💾 草稿已保存：{cfg.draft_path}")
    print(f"📄 摘要 {lengths['abstract']} 字｜正文 {lengths['body']} 字（目标 "
          f"{wc.get('body_min')}-{wc.get('body_max')}）｜含摘要总计 {lengths['total']} 字")
    print(f"📚 实际引用：{sorted(used)}")
    if missing:
        print("⚠️ 缺少章节：" + "；".join(missing))
    if invalid:
        print("⚠️ 非法来源编号：" + ", ".join(sorted(invalid)))
    if bare:
        print("⚠️ 存在未加上角标的裸引用：" + ", ".join(bare))
    if length_issues:
        print("⚠️ 字数口径未达标：" + "；".join(length_issues))
    if not (missing or invalid or bare or length_issues):
        print("✅ 自动质检通过，可进入阶段5")
    print("=" * 72)
    return {"ok": True, "lengths": lengths, "used": sorted(used),
            "missing": missing, "invalid": sorted(invalid), "bare": bare,
            "length_issues": length_issues,
            "path": str(cfg.draft_path)}
