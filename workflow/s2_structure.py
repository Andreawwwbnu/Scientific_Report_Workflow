# -*- coding: utf-8 -*-
"""
阶段 2：原始文献 → 结构化证据素材（替代旧 structure_literatures.py）
- 只做“证据抽取 + 归类 + 去重”，禁止自由写作
- 章节/小节/归类规则全部来自 project.yaml
- 证据截断保留文首（定义）+ 文末（结论数据）
- 模型输出先做镜像编号归并，再校验来源合法性；非法编号自动修复重试一次
"""
from __future__ import annotations

import re
from pathlib import Path

from .common import (
    WorkflowConfig, credibility_score, dump_frontmatter,
    head_tail_clip, now_str, split_frontmatter, normalize_aliases_in_text,
)
from .s1_fetch import raw_filename


def load_entry_material(entry: dict, cfg: WorkflowConfig) -> dict | None:
    path = cfg.raw_chapter_dir(entry["chapter"]) / raw_filename(entry)
    if not path.exists():
        return None
    meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
    meta["body"] = _clean_body(body)
    meta["_id"] = entry["id"]
    meta["_canonical"] = cfg.canonical_id(entry["id"])
    return meta


def _clean_body(body: str) -> str:
    skip_prefix = (
        "> **抓取状态：**", "> ⚠️ **抓取状态：**", "## 文献使用说明",
        "**对应报告章节：**", "**文献类型：**", "**可信度：**", "**原文链接：**",
    )
    kept = [ln for ln in body.splitlines() if not ln.strip().startswith(skip_prefix)]
    return "\n".join(kept).strip()


def evidence_block(meta: dict, cfg: WorkflowConfig) -> str:
    url = meta.get("来源链接", "")
    is_arxiv = "arxiv.org" in url.lower()
    keep_head = int(cfg.fetch_cfg.get("arxiv_body_keep_head" if is_arxiv else "web_body_keep_head", 300))
    keep_tail = int(cfg.fetch_cfg.get("body_keep_tail", 1100))
    body = head_tail_clip(meta.get("body", ""), keep_head, keep_tail)
    return f"""
【来源编号：{meta['_id']}】
标题：{meta.get('标题', '未知')}
发布主体：{meta.get('发布主体', '未知')}
文献类型：{meta.get('文献类型', '未知')}
可信度等级：{meta.get('可信度等级', '未知')}
来源链接：{url}
【该来源提供的原始内容】
{body}
【来源结束：{meta['_id']}】
"""


def build_prompt(chapter: dict, materials: list, cfg: WorkflowConfig) -> str:
    sec_lines = []
    for sec in chapter["sections"]:
        sec_lines.append(f"- {sec['id']} {sec['name']}：{sec['extract_rule']}")
    allowed = sorted({m["_canonical"] for m in materials})
    blocks = "\n".join(evidence_block(m, cfg) for m in materials)
    return f"""
你正在为专业技术调研报告执行“原始文献 → 结构化证据素材”任务。
研究主题：{cfg.name}
当前章节：{chapter['name']}
本章节小节与归类约束：
{chr(10).join(sec_lines)}

允许使用的文献编号（主编号）只有：{', '.join(allowed)}

================ 规则 ================
1. 任务性质是“证据抽取+分类+合并去重”，不是自由写作，不扩展知识、不做趋势预测。
2. 每条信息先判断是否直接回答该小节问题；不匹配的即使存在也不放入。禁止跨小节抢内容。
3. 只能使用下面【原始内容】中的事实；禁止使用你自身知识、训练数据或其他页面；
   禁止补造材料中没有的数据、案例、因果关系。
4. 数字、百分比、benchmark、日期、版本号逐字忠实，不得四舍五入。
5. 同一事实多来源重复时保留权威来源，互补证据可共同标注，不机械堆砌引用。
6. 每个事实要点句末标注来源，格式：- 要点。[{cfg.id_prefix}01]；多来源：[{cfg.id_prefix}01][{cfg.id_prefix}03]。
7. 只输出 Markdown，格式严格如下，不要导语、总结、表格、参考文献列表、分析结论：
## X.X 小节名
- 要点。[编号]
8. 某小节证据不足时输出：
## X.X 小节名
- 暂无充分证据。

================ 文献材料 ================
{blocks}

现在直接输出结构化 Markdown。
"""


def _collect_materials(chapter: dict, cfg: WorkflowConfig):
    materials = []
    for entry in cfg.entries_of_chapter(chapter["folder"], canonical=False):
        m = load_entry_material(entry, cfg)
        if m:
            materials.append(m)
    # 去重到主编号，按可信度降序
    unique = {m["_canonical"]: m for m in materials}
    return sorted(unique.values(),
                  key=lambda m: (credibility_score(m.get("可信度等级", "")), m["_canonical"]),
                  reverse=True)


def validate_ids(content: str, allowed: set, prefix: str) -> set:
    found = set(re.findall(rf"\[{prefix}\d+\]", content))
    found = {x.strip("[]") for x in found}
    return found - allowed


def generate_for_chapter(chapter: dict, cfg: WorkflowConfig, llm) -> bool:
    print(f"\n📖 {chapter['name']}")
    materials = _collect_materials(chapter, cfg)
    if not materials:
        print("  ⚠️ 缺少原始素材，跳过（请先运行阶段1）")
        return False
    allowed = {m["_canonical"] for m in materials}
    print("  使用文献：" + ", ".join(sorted(allowed)))

    prompt = build_prompt(chapter, materials, cfg)
    llm_cfg = cfg.llm_cfg
    content = llm.chat(
        model=llm_cfg["structure_model"],
        system="你是专业技术情报分析师，只做证据抽取与分类，严格忠实于材料，不虚构来源、不改动数字。",
        user=prompt,
        max_tokens=int(llm_cfg["max_tokens_structure"]),
        temperature=float(llm_cfg["temperature_fast"]),
    )
    # 镜像编号归并到主编号
    content = normalize_aliases_in_text(content, cfg.alias_map)

    invalid = validate_ids(content, allowed, cfg.id_prefix)
    if invalid:
        print("  ⚠️ 首次输出含非法编号 " + ", ".join(sorted(invalid)) + "，修复重试一次")
        repair = prompt + f"\n\n注意：你上一次输出出现了非法编号 {sorted(invalid)}，允许编号只有 {sorted(allowed)}，请重写。"
        content = llm.chat(
            model=llm_cfg["structure_model"],
            system="你是专业技术情报分析师，只做证据抽取与分类。",
            user=repair,
            max_tokens=int(llm_cfg["max_tokens_structure"]),
            temperature=float(llm_cfg["temperature_fast"]),
        )
        content = normalize_aliases_in_text(content, cfg.alias_map)
        invalid2 = validate_ids(content, allowed, cfg.id_prefix)
        if invalid2:
            print("  ❌ 修复后仍含非法编号 " + ", ".join(sorted(invalid2)) + "，本章不保存")
            return False

    source_list = "\n".join(
        f"- [{m['_canonical']}] {m.get('标题', '未知')}（{m.get('发布主体', '未知')}）"
        for m in materials
    )
    header = {
        "title": f"{chapter['name']} - 结构化素材",
        "type": "structured-material",
        "project": cfg.name,
        "chapter_id": chapter["id"],
        "source_ids": sorted(allowed),
        "updated": now_str(),
    }
    out = (
        f"---\n{dump_frontmatter(header)}\n---\n\n"
        f"# {chapter['name']}\n"
        f"> 本文件由 LLM 基于 `02-原始素材` 自动抽取，定位为结构化证据素材，每条事实保留来源编号。\n\n"
        f"## 本章节来源\n{source_list}\n\n---\n\n{content.strip()}\n"
    )
    path = cfg.structured_path(chapter)
    path.write_text(out, encoding="utf-8")
    print(f"  💾 已保存：{path.name}")
    return True


def run(cfg: WorkflowConfig, llm=None) -> dict:
    print("=" * 72)
    print("🚀 阶段2：文献 → 结构化证据素材")
    print("=" * 72)
    if llm is None:
        from .common import LLMClient
        llm = LLMClient(cfg)
    ok = fail = 0
    for chapter in cfg.chapters:
        if generate_for_chapter(chapter, cfg, llm):
            ok += 1
        else:
            fail += 1
    print("\n" + "=" * 72)
    print(f"🏁 完成：成功 {ok}/{len(cfg.chapters)} 章，失败 {fail}")
    print("⚠️ 结构化素材仍需人工校验：定义、数字、章节归属、来源编号")
    print("=" * 72)
    return {"success": ok, "fail": fail}
