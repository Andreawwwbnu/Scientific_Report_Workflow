# -*- coding: utf-8 -*-
"""阶段 5：草稿 → 终稿（确定性处理 + 结构校验，不调用 LLM）。

- 参考文献无条件由 manifest 重建（旧版仅当模型输出了“参考文献”节才覆盖，模型漏写就没有）；
- 支持 references.only_cited（只列被引文献）与 references.numbering（manifest 顺序 / 首次引用顺序）；
- 校验：标题完整、无空节、引用编号合法、篇幅口径、近重复；
- 校验有错误时仍写出终稿便于排查，但返回 ok=False，流水线默认在此停下。
"""
from __future__ import annotations

import re
from typing import List

from .config import WorkflowConfig
from .references import build_references, today
from .textutil import (find_citations, length_breakdown, near_duplicate_pairs,
                       normalize_aliases_in_text, split_by_heading, split_reference_section,
                       split_sentences, strip_frontmatter, visible_length, with_frontmatter,
                       wrap_citations)


def first_cited_order(text: str, cfg: WorkflowConfig) -> List[str]:
    seen: List[str] = []
    for c in find_citations(text, cfg.id_prefix):
        cid = cfg.canonical_id(c.strip("[]"))
        if cid not in seen:
            seen.append(cid)
    return seen


def clean_main(text: str, cfg: WorkflowConfig) -> str:
    t = strip_frontmatter(text)
    t = "\n".join(ln for ln in t.splitlines() if not ln.lstrip().startswith("> ⚠️"))
    t = normalize_aliases_in_text(t, cfg.alias_map)
    t = wrap_citations(t, cfg.id_prefix)
    t = re.sub(r"^(#{1,6}[ \t]+.+)\n(?!\n)", r"\1\n\n", t, flags=re.M)   # 标题后保证空行
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def validate_final(main: str, cfg: WorkflowConfig, cited: List[str]) -> dict:
    errors: List[str] = []
    warns: List[str] = []

    lines = [ln.strip() for ln in main.splitlines() if ln.startswith("#")]
    for h in cfg.blueprint:
        if h == "## 参考文献":
            continue
        if h not in lines:
            errors.append(f"缺少标题：{h}")

    # 空节：每个标题到下一个标题之间的正文不少于 30 字（## 后紧跟 ### 的容器标题除外）
    heads = list(re.finditer(r"^(#{2,3})[ \t]+(.+?)[ \t]*$", main, re.M))
    for i, m in enumerate(heads):
        title = m.group(2)
        if title == "关键词":
            continue
        end = heads[i + 1].start() if i + 1 < len(heads) else len(main)
        content = main[m.end():end]
        is_container = (m.group(1) == "##" and i + 1 < len(heads) and heads[i + 1].group(1) == "###")
        if is_container and visible_length(content) == 0:
            continue
        if visible_length(content) < 30:
            errors.append(f"章节内容过少或为空：{title}")

    valid = {e["id"] for e in cfg.canonical_entries}
    bad = [c for c in cited if c not in valid]
    if bad:
        errors.append(f"正文引用了 manifest 中不存在的编号：{bad}")
    uncited = sorted(valid - set(cited), key=cfg.id_num)
    if uncited:
        warns.append(f"以下文献未在正文被引用：{', '.join(uncited)}")

    lb = length_breakdown(main)
    wc = cfg.wc_cfg
    if not wc["body_min"] <= lb["body"] <= wc["body_max"]:
        warns.append(f"正文 {lb['body']} 字，目标 {wc['body_min']}–{wc['body_max']}")
    if not wc["abstract_min"] <= lb["abstract"] <= wc["abstract_max"]:
        warns.append(f"摘要 {lb['abstract']} 字，目标 {wc['abstract_min']}–{wc['abstract_max']}")
    if not wc["conclusion_min"] <= lb["conclusion"] <= wc["conclusion_max"]:
        warns.append(f"结论 {lb['conclusion']} 字，目标 {wc['conclusion_min']}–{wc['conclusion_max']}")

    sents = [(h, s) for h, b in split_by_heading(main, 2).items() if h not in ("摘要", "关键词", "结论与展望")
             for s in split_sentences(re.sub(r"^#+.*$", "", b, flags=re.M), 20)]
    dups = near_duplicate_pairs(sents, 0.6)
    if dups:
        warns.append(f"发现 {len(dups)} 组近重复句，建议人工合并（详见质检报告）")
    return {"errors": errors, "warnings": warns, "lengths": lb, "near_duplicates": dups}


def run(cfg: WorkflowConfig, **_) -> dict:
    print("=" * 72)
    print("🚀 阶段5：草稿 → 终稿")
    print("=" * 72)
    if not cfg.draft_path.exists():
        print(f"❌ 草稿不存在：{cfg.draft_path}（请先运行阶段4）")
        return {"ok": False, "reason": "missing_draft"}

    raw = cfg.draft_path.read_text(encoding="utf-8")
    main, _old_refs = split_reference_section(strip_frontmatter(raw))
    main = clean_main(main, cfg)
    cited = first_cited_order(main, cfg)

    rc = cfg.ref_cfg
    if rc["numbering"] == "first_cited":
        unused = [] if rc["only_cited"] else sorted(
            {e["id"] for e in cfg.canonical_entries} - set(cited), key=cfg.id_num)
        order = [c for c in cited if cfg.entry(c)] + unused
    else:
        all_ids = sorted((e["id"] for e in cfg.canonical_entries), key=cfg.id_num)
        order = [i for i in all_ids if i in set(cited)] if rc["only_cited"] else all_ids
    access = rc["access_date"]
    access = today() if access == "today" else (access or None)
    refs = build_references(cfg, order, access)

    result = validate_final(main, cfg, cited)
    lb = result["lengths"]
    meta = {"title": cfg.report_title, "project": cfg.name, "version": cfg.version,
            "type": "tech-survey-report", "generated": today(),
            "length": {"abstract": lb["abstract"], "body": lb["body"], "conclusion": lb["conclusion"]},
            "references": len(order)}
    final = with_frontmatter(meta, main + "\n\n## 参考文献\n\n" + refs)
    cfg.final_md_path.write_text(final, encoding="utf-8")

    print(f"📄 终稿：{cfg.final_md_path}")
    print(f"   字数：摘要 {lb['abstract']}｜正文 {lb['body']}｜结论 {lb['conclusion']}｜参考文献 {len(order)} 条")
    for e in result["errors"]:
        print(f"  ❌ {e}")
    for w in result["warnings"]:
        print(f"  ⚠️ {w}")
    if not result["errors"]:
        print("✅ 结构校验通过")
    print("=" * 72)
    return {"ok": not result["errors"], "errors": result["errors"], "warnings": result["warnings"],
            "lengths": lb, "cited": cited, "near_duplicates": len(result["near_duplicates"])}
