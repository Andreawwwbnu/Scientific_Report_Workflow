# -*- coding: utf-8 -*-
"""
阶段 3：结构化素材 → 分小节深度分析（替代旧 analyze_chapters.py）
- 分析任务来自 project.yaml 各 section.analyze_task
- 全流程共享一个 LLM 客户端；推理模型(reasoner)自动剔除不支持的 temperature
- 输出过短或来源编号非法时各重试一次；非法编号不再只告警、会阻断该小节质量
"""
from __future__ import annotations

import re

from .common import (
    WorkflowConfig, citation_set, dump_frontmatter,
    normalize_aliases_in_text, now_str, split_frontmatter,
)

def _section_block(material: str, sec_id: str) -> str:
    """从结构化素材中切出指定小节的文本块（## 1.1 起，到下一小节或文末）。"""
    m = re.search(rf"^##\s+{re.escape(sec_id)}(?:[\s　].*)?$", material, flags=re.M)
    if not m:
        return ""
    start = m.end()
    nxt = re.search(r"^##\s+\d", material[start:], flags=re.M)
    return material[start:start + nxt.start()] if nxt else material[start:]


def _section_has_evidence(material: str, sec: dict, cfg: WorkflowConfig) -> bool:
    """小节是否有可分析证据：以块内是否含来源编号为准。
    注意：不能仅凭"暂无证据"字样跳过——如 4.3 同时含证据行和标记行。"""
    block = _section_block(material, sec["id"])
    if not block.strip():
        return False
    return bool(citation_set(block, cfg.id_prefix))


def _allowed_ids(material_text: str, cfg: WorkflowConfig) -> set:
    ids = citation_set(material_text, cfg.id_prefix)
    # frontmatter 的 source_ids 是 "- SE01" 形式，补进来作为权威允许集
    meta, _ = split_frontmatter(material_text)
    for x in meta.get("source_ids", []) or []:
        ids.add(x)
    return {cfg.canonical_id(i) for i in ids}


def analyze_section(material: str, sec: dict, allowed: set, cfg: WorkflowConfig, llm,
                    retry_reason: str = "") -> str:
    llm_cfg = cfg.llm_cfg
    prompt = f"""你是严谨的技术情报分析师，严格基于给定素材完成分析任务。

## 核心规则
1. 所有结论 100% 基于提供的素材，绝不引入外部知识、数据、案例。
2. 每个核心结论句末标注素材来源编号，格式 [{cfg.id_prefix}01]，允许编号：{sorted(allowed)}；同一来源支撑同一事实只引用一次。
3. 输出 3–5 条分析要点，每条 = 一句核心判断（结论先行）+ 支撑证据；要点之间必须逻辑递进（如"机理→指标→局限"或"判断→机制→意义"），禁止平行罗列、禁止条目间内容重叠。
4. 涉及进展、动态、事件、里程碑类内容时，每条必须包含"时间—主体—成果/事件"三要素；引用数据必须标注来源编号，禁止无来源的概括性判断。
4. 同一论据在本小节只允许出现一次；不得对同一事实换措辞复述；不写总起段、不写总结段、不写开场白。
5. 表达凝练、简洁、明确：每句只承载一个判断，直接给出"判断+证据"，删除一切铺垫、套话与过渡句。
6. 长度严格控制在 {llm_cfg.get('min_section_chars', 200)}–{llm_cfg.get('max_section_chars', 800)} 字；宁可少写，不得注水凑字。
{retry_reason}
## 分析任务
小节：{sec['id']} {sec['name']}
要求：{sec['analyze_task']}

## 结构化素材
{material}
"""
    return llm.chat(
        model=llm_cfg["analyze_model"],
        system="你是专业技术情报分析师，只基于给定素材输出分析结论，不补充外部知识。",
        user=prompt,
        max_tokens=int(llm_cfg["max_tokens_analyze"]),
        # reasoner 不支持 temperature，LLMClient 会自动忽略该参数
        temperature=float(llm_cfg["temperature_fast"]),
    )


def process_chapter(chapter: dict, cfg: WorkflowConfig, llm) -> tuple[int, int, int]:
    print(f"\n🔍 {chapter['name']}")
    structured_path = cfg.structured_path(chapter)
    if not structured_path.exists():
        print(f"  ❌ 结构化素材不存在：{structured_path.name}（请先运行阶段2）")
        return 0, len(chapter["sections"]), 0

    material = structured_path.read_text(encoding="utf-8")
    allowed = _allowed_ids(material, cfg)
    min_len = int(cfg.llm_cfg.get("min_section_chars", 200))
    max_len = int(cfg.llm_cfg.get("max_section_chars", 800))
    results, success, skipped = [], 0, 0

    for sec in chapter["sections"]:
        print(f"  🔹 {sec['id']} {sec['name']}")
        # 无证据的小节不调 LLM、不纳入分析，仅留跳过标记供阶段4识别
        if not _section_has_evidence(material, sec, cfg):
            skipped += 1
            print("    ⏭️ 无充分证据，按规则跳过，不纳入分析")
            results.append(
                f"## {sec['id']} {sec['name']}\n"
                f"> ⚠️ 本小节无充分证据，按规则未纳入分析，请勿在成稿中展开。\n"
            )
            continue
        result = ""
        try:
            result = analyze_section(material, sec, allowed, cfg, llm)
            result = normalize_aliases_in_text(result, cfg.alias_map)
            # 质量门：过短/过长或非法编号 → 带反馈重试一次
            used = citation_set(result, cfg.id_prefix)
            invalid = used - allowed
            retry_note = ""
            if len(result) < min_len:
                retry_note += f"\n[上次问题] 输出仅 {len(result)} 字，未达 {min_len} 字下限，请补足核心判断与证据。"
            if len(result) > max_len:
                retry_note += f"\n[上次问题] 输出 {len(result)} 字，超过 {max_len} 字上限，请压缩到上限以内，只保留核心判断与证据。"
            if invalid:
                retry_note += f"\n[上次问题] 出现非法编号 {sorted(invalid)}，只允许 {sorted(allowed)}。"
            if retry_note:
                print(f"    ⚠️ 触发质量重试：{retry_note.strip()[:80]}")
                result = analyze_section(material, sec, allowed, cfg, llm, retry_note)
                result = normalize_aliases_in_text(result, cfg.alias_map)
            still_invalid = citation_set(result, cfg.id_prefix) - allowed
            if still_invalid:
                print(f"    ⚠️ 重试后仍有非法编号：{sorted(still_invalid)}，已保留但请人工核查")
            results.append(f"## {sec['id']} {sec['name']}\n{result}\n")
            success += 1
            print(f"    ✅ 完成，{len(result)} 字")
        except Exception as e:  # noqa: BLE001
            print(f"    ❌ 失败：{str(e)[:100]}")
            results.append(f"## {sec['id']} {sec['name']}\n> ⚠️ 本小节分析失败，请人工补充\n")
    # 正则兜底：清除任何残留的非允许编号的尖括号包裹（保守，仅标记不删事实）
    header = {
        "title": f"{chapter['name']}·分析结论",
        "project": cfg.name,
        "model": cfg.llm_cfg["analyze_model"],
        "source_material": structured_path.name,
        "generated": now_str(),
    }
    out = (
        f"---\n{dump_frontmatter(header)}\n---\n\n"
        f"# {chapter['name']}·分析结论\n"
        f"> 分析依据：`{structured_path.name}`；所有结论均基于结构化素材推导，未引入外部知识。\n\n"
        + "\n".join(results)
    )
    path = cfg.analysis_path(chapter)
    path.write_text(out, encoding="utf-8")
    print(f"  💾 已保存：{path.name}（成功 {success}，跳过 {skipped}，共 {len(chapter['sections'])} 小节）")
    return success, len(chapter["sections"]), skipped


def run(cfg: WorkflowConfig, llm=None) -> dict:
    print("=" * 72)
    print("🚀 阶段3：结构化素材 → 分小节深度分析")
    print("=" * 72)
    if llm is None:
        from .common import LLMClient
        llm = LLMClient(cfg)
    total_ok = total_n = total_skip = 0
    for chapter in cfg.chapters:
        ok, n, sk = process_chapter(chapter, cfg, llm)
        total_ok += ok
        total_n += n
        total_skip += sk
    print("\n" + "=" * 72)
    print(f"🏁 完成：{total_ok}/{total_n} 个小节成功，{total_skip} 个无证据小节已跳过；输出目录：{cfg.analysis_dir}")
    print("⚠️ 请人工校验分析逻辑与来源标注，再进入阶段4")
    print("=" * 72)
    return {"success": total_ok, "total": total_n}
