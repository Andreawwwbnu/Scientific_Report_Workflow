# -*- coding: utf-8 -*-
"""阶段 4：分析结论 + 证据 → 报告草稿（分章生成）。

相对旧版“整篇一次生成、不过关就整篇重写”：
- 按章生成，质检不过只重写出问题的那一章（带具体反馈），并可并发；
- 综述性章节（synthesis=True，通常是“遴选理由”）最后写，可参考其他章成稿，避免重复；
- 摘要 / 关键词 / 结论单独生成（最后一步，只能概括正文）；
- 篇幅预算由 project.yaml 的 word_count + 各章 weight 推导，不再写死在代码里；
- 参考文献由 manifest 权威生成，模型不参与；
- 确定性处理：引用统一包成 <sup>、非法引用编号自动剔除，不靠模型“自觉”。
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Set, Tuple

from .config import ReportChapter, WorkflowConfig
from .evidence import Evidence, evidence_lines, parse_analysis, parse_structured
from .llm import BaseLLM, parallel_map
from .prompts import render
from .references import build_references
from .textutil import (citation_set, cite_re, near_duplicate_pairs, normalize_aliases_in_text,
                       split_by_heading, split_sentences, visible_length,
                       wrap_citations)


# ============================================================
# 素材装配
# ============================================================
def load_materials(cfg: WorkflowConfig) -> Tuple[Dict[str, Dict[str, List[Evidence]]], Dict[str, Dict[str, Optional[str]]], List[str]]:
    structured, analysis, missing = {}, {}, []
    for ch in cfg.chapters:
        sp, ap = cfg.structured_path(ch), cfg.analysis_path(ch)
        if not sp.exists():
            missing.append(sp.name)
        else:
            structured[ch["id"]] = parse_structured(sp.read_text(encoding="utf-8"))
        if not ap.exists():
            missing.append(ap.name)
        else:
            analysis[ch["id"]] = parse_analysis(ap.read_text(encoding="utf-8"))
    return structured, analysis, missing


def chapter_inputs(cfg: WorkflowConfig, rc: ReportChapter, structured, analysis) -> dict:
    analysis_blocks, evid, skipped = [], [], []
    for cid in rc.source_chapters:
        ch = cfg.chapter_by_id(cid)
        for sec in ch["sections"]:
            a = analysis.get(cid, {}).get(sec["id"])
            if a is None:
                skipped.append(f"{sec['id']} {sec['name']}")
            else:
                analysis_blocks.append(f"【{sec['id']} {sec['name']}】\n{a}")
            evid += structured.get(cid, {}).get(sec["id"], [])
    allowed = {cfg.canonical_id(e.source) for e in evid}
    return {"analysis": "\n\n".join(analysis_blocks), "evidence": evidence_lines(evid),
            "allowed": allowed, "skipped": skipped}


# ============================================================
# 单章生成与校验
# ============================================================
def _body_only(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _clean_model_text(text: str, cfg: WorkflowConfig) -> str:
    t = text.strip()
    t = re.sub(r"^```(?:markdown|md)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    t = normalize_aliases_in_text(t, cfg.alias_map)
    return wrap_citations(t, cfg.id_prefix)


def _strip_illegal(text: str, allowed: Set[str], prefix: str) -> Tuple[str, List[str]]:
    removed: List[str] = []

    def repl(m):
        sid = m.group(0).strip("[]")
        if sid in allowed:
            return m.group(0)
        removed.append(sid)
        return ""

    out = cite_re(prefix).sub(repl, text)
    out = re.sub(r"<sup>\s*</sup>", "", out)
    return out, removed


def check_chapter(text: str, rc: ReportChapter, cfg: WorkflowConfig, allowed: Set[str]) -> Tuple[List[str], List[str]]:
    """返回 (硬问题, 软问题)。硬问题：标题结构、非法引用；软问题：篇幅、段落过长。"""
    hard, soft = [], []
    found = [ln.strip() for ln in text.splitlines() if ln.lstrip().startswith("#")]
    if found != rc.headings:
        hard.append("标题与要求不一致。要求逐行原样输出：" + " / ".join(rc.headings)
                    + "；实际为：" + (" / ".join(found) if found else "（无标题）"))
    bad = citation_set(text, cfg.id_prefix) - allowed
    if bad:
        hard.append(f"出现不允许的来源编号 {sorted(bad)}")
    lo, hi = cfg.chapter_char_range(rc)
    n = visible_length(_body_only(text))
    if n < lo:
        soft.append(f"正文仅 {n} 字，低于下限 {lo} 字：请在已有论据基础上补足论证（不得编造）")
    elif n > hi:
        soft.append(f"正文 {n} 字，超过上限 {hi} 字：请删去次要论据与重复表述")
    maxp = int(cfg.draft_cfg["max_paragraph_chars"])
    long_paras = [p for p in _body_only(text).split("\n") if p.strip() and visible_length(p) > maxp * 1.3]
    if long_paras:
        soft.append(f"有 {len(long_paras)} 段超过 {maxp} 字，请拆分")
    return hard, soft


def generate_chapter(rc: ReportChapter, cfg: WorkflowConfig, llm: BaseLLM, inputs: dict,
                     other_text: str = "", extra_allowed: Optional[Set[str]] = None) -> dict:
    dc, lc = cfg.draft_cfg, cfg.llm_cfg
    allowed = set(inputs["allowed"]) | set(extra_allowed or set())
    lo, hi = cfg.chapter_char_range(rc)
    style_rules = "\n".join(f"- {r}" for r in dc.get("style_rules", []))
    skipped = inputs["skipped"]
    skipped_note = ("以下小节证据不足，已被分析阶段跳过，不得就其展开论述：" + "、".join(skipped)) if skipped else "无"
    sub_rule = ("本章不设 ### 小节标题，整章连续成文（只保留上面的 ## 标题），按分析结论的逻辑递进组织段落。"
                if rc.no_subheadings else "")
    other_block = ("<other_chapters>\n以下是其他章已完成的正文（仅用于归纳与避免重复，不得复述其细节）：\n"
                   f"{other_text}\n</other_chapters>") if other_text else ""
    other_note = "本章为归纳性章节：论据须与其他章已写内容不重复，只做归纳判断。" if other_text else ""

    best, best_key = None, None
    feedback = ""
    tag = ""
    for attempt in range(1 + int(dc["max_rewrites"])):
        p = render("draft_chapter", cfg.prompts_override_dir,
                   persona=dc["persona"], report_title=cfg.report_title, chapter_heading=rc.heading,
                   id_prefix=cfg.id_prefix, allowed_ids="、".join(sorted(allowed)) or "（无）",
                   subheading_rule=sub_rule, max_paragraph_chars=dc["max_paragraph_chars"],
                   other_chapters_note=other_note, style_rules=style_rules,
                   min_chars=lo, max_chars=hi, target_chars=cfg.chapter_target_chars(rc),
                   write_guide=rc.write_guide or "按分析结论的逻辑递进组织。",
                   headings="\n".join(rc.headings), skipped_note=skipped_note,
                   analysis=inputs["analysis"], evidence=inputs["evidence"],
                   other_chapters=other_block, feedback=feedback)
        tag = p.tag
        raw = llm.chat(task="draft_chapter", model=lc["draft_model"], system=p.system, user=p.user,
                       max_tokens=int(lc.get("max_tokens_draft", 8192)),
                       temperature=float(lc.get("temperature_draft", 0.3)))
        text = _clean_model_text(raw, cfg)
        hard, soft = check_chapter(text, rc, cfg, allowed)
        n = visible_length(_body_only(text))
        key = (len(hard), 0 if lo <= n <= hi else abs(n - (lo + hi) // 2))
        if best is None or key < best_key:
            best, best_key = (text, hard, soft), key
        if not hard and not soft:
            break
        feedback = ("\n<feedback>上一版存在以下问题，请在保持来源与结构的前提下修正后重新输出整章：\n- "
                    + "\n- ".join(hard + soft) + "\n</feedback>")
    text, hard, soft = best  # type: ignore[misc]
    text, removed = _strip_illegal(text, allowed, cfg.id_prefix)
    if removed:
        soft.append(f"已自动剔除非法引用编号 {sorted(set(removed))}")
        hard = [h for h in hard if "来源编号" not in h]
    return {"text": text, "hard": hard, "soft": soft, "prompt": tag,
            "chars": visible_length(_body_only(text))}


# ============================================================
# 摘要 / 关键词 / 结论
# ============================================================
def check_frame(parts: Dict[str, str], cfg: WorkflowConfig, body_ids: Set[str]) -> Tuple[List[str], List[str]]:
    wc = cfg.wc_cfg
    hard, soft = [], []
    for k in ("摘要", "关键词", "结论与展望"):
        if k not in parts or not parts[k].strip():
            hard.append(f"缺少“## {k}”")
    if hard:
        return hard, soft
    a = visible_length(parts["摘要"])
    if not wc["abstract_min"] <= a <= wc["abstract_max"]:
        soft.append(f"摘要 {a} 字，应在 {wc['abstract_min']}–{wc['abstract_max']} 字")
    c = visible_length(parts["结论与展望"])
    if not wc["conclusion_min"] <= c <= wc["conclusion_max"]:
        soft.append(f"结论与展望 {c} 字，应在 {wc['conclusion_min']}–{wc['conclusion_max']} 字")
    kws = [k for k in re.split(r"[；;，,、\s]+", parts["关键词"].strip()) if k]
    if not wc["keywords_min"] <= len(kws) <= wc["keywords_max"]:
        soft.append(f"关键词 {len(kws)} 个，应为 {wc['keywords_min']}–{wc['keywords_max']} 个")
    bad = citation_set(parts["结论与展望"] + parts["摘要"], cfg.id_prefix) - body_ids
    if bad:
        hard.append(f"摘要/结论中引用了正文没有出现的来源 {sorted(bad)}")
    return hard, soft


def generate_frame(cfg: WorkflowConfig, llm: BaseLLM, chapter_texts: List[str]) -> dict:
    dc, lc, wc = cfg.draft_cfg, cfg.llm_cfg, cfg.wc_cfg
    chapters = "\n\n".join(chapter_texts)
    body_ids = citation_set(chapters, cfg.id_prefix)
    style_rules = "；".join(dc.get("style_rules", [])) or "无额外要求"
    best, best_key, feedback, tag = None, None, "", ""
    for attempt in range(1 + int(dc["max_rewrites"])):
        p = render("draft_frame", cfg.prompts_override_dir,
                   persona=dc["persona"], report_title=cfg.report_title, id_prefix=cfg.id_prefix,
                   abstract_min=wc["abstract_min"], abstract_max=wc["abstract_max"],
                   conclusion_min=wc["conclusion_min"], conclusion_max=wc["conclusion_max"],
                   keywords_min=wc["keywords_min"], keywords_max=wc["keywords_max"],
                   style_rules=style_rules, chapters=chapters, feedback=feedback)
        tag = p.tag
        raw = llm.chat(task="draft_frame", model=lc["draft_model"], system=p.system, user=p.user,
                       max_tokens=int(lc.get("max_tokens_frame", 4096)),
                       temperature=float(lc.get("temperature_draft", 0.3)))
        text = _clean_model_text(raw, cfg)
        parts = split_by_heading(text, 2)
        hard, soft = check_frame(parts, cfg, body_ids)
        key = (len(hard), len(soft))
        if best is None or key < best_key:
            best, best_key = (parts, hard, soft), key
        if not hard and not soft:
            break
        feedback = ("\n<feedback>上一版存在以下问题，请修正后重新输出三个部分：\n- "
                    + "\n- ".join(hard + soft) + "\n</feedback>")
    parts, hard, soft = best  # type: ignore[misc]
    text = "\n\n".join(f"## {k}\n\n{parts[k].strip()}" for k in ("摘要", "关键词", "结论与展望") if k in parts)
    return {"parts": parts, "text": text, "hard": hard, "soft": soft, "prompt": tag}


# ============================================================
# 组装 / 主流程
# ============================================================
def assemble(cfg: WorkflowConfig, chapter_texts: Dict[str, str], parts: Dict[str, str]) -> str:
    out = [f"# {cfg.report_title}", "",
           "## 摘要", "", parts.get("摘要", "").strip(), "",
           "## 关键词", "", parts.get("关键词", "").strip(), ""]
    for rc in cfg.report_chapters:
        out += [chapter_texts[rc.id].strip(), ""]
    out += ["## 结论与展望", "", parts.get("结论与展望", "").strip(), ""]
    refs = build_references(cfg)
    out += ["## 参考文献", "", refs, ""]
    return "\n".join(out)


def run(cfg: WorkflowConfig, llm: BaseLLM, only_chapters: Optional[Set[str]] = None, **_) -> dict:
    print("=" * 72)
    print("🚀 阶段4：分析结论 → 报告草稿（分章生成）")
    print("=" * 72)
    structured, analysis, missing = load_materials(cfg)
    if missing:
        print("❌ 缺少上游产物：" + "；".join(missing))
        return {"ok": False, "reason": "missing_inputs"}

    rcs = cfg.report_chapters
    inputs = {rc.id: chapter_inputs(cfg, rc, structured, analysis) for rc in rcs}
    texts: Dict[str, str] = {}
    results: Dict[str, dict] = {}
    workers = int(cfg.llm_cfg.get("concurrency", 3))

    def wanted(rc: ReportChapter) -> bool:
        if not only_chapters:
            return True
        return rc.id in only_chapters or not cfg.draft_chapter_path(rc).exists()

    def load_existing(rc: ReportChapter):
        t = cfg.draft_chapter_path(rc).read_text(encoding="utf-8")
        texts[rc.id] = t

    for rc in rcs:
        if not wanted(rc):
            load_existing(rc)
            print(f"  ⏭️ {rc.heading}：沿用已有草稿")

    def gen(rc: ReportChapter, other: str = "", extra: Optional[Set[str]] = None):
        return generate_chapter(rc, cfg, llm, inputs[rc.id], other, extra)

    plain = [rc for rc in rcs if not rc.synthesis and wanted(rc)]
    synth = [rc for rc in rcs if rc.synthesis and wanted(rc)]
    for rc, (ok, res) in zip(plain, parallel_map(gen, plain, workers)):
        if not ok:
            print(f"  ❌ {rc.heading} 生成失败：{str(res)[:100]}")
            results[rc.id] = {"text": "", "hard": [f"生成异常：{res}"], "soft": [], "chars": 0, "prompt": ""}
        else:
            results[rc.id] = res
            texts[rc.id] = res["text"]
    for rc in synth:
        others = "\n\n".join(texts[o.id] for o in rcs if o.id != rc.id and o.id in texts)
        extra = citation_set(others, cfg.id_prefix)
        try:
            res = gen(rc, others, extra)
            results[rc.id] = res
            texts[rc.id] = res["text"]
        except Exception as e:  # noqa: BLE001
            print(f"  ❌ {rc.heading} 生成失败：{str(e)[:100]}")
            results[rc.id] = {"text": "", "hard": [f"生成异常：{e}"], "soft": [], "chars": 0, "prompt": ""}

    for rc in rcs:
        r = results.get(rc.id)
        if r is None:
            continue
        if r["text"]:
            cfg.draft_chapter_path(rc).write_text(r["text"], encoding="utf-8")
        lo, hi = cfg.chapter_char_range(rc)
        flag = "❌" if r["hard"] else ("⚠️" if r["soft"] else "✅")
        print(f"  {flag} {rc.heading}：{r['chars']} 字（目标 {lo}–{hi}）"
              + (f"｜{'；'.join(r['hard'] + r['soft'])[:90]}" if (r["hard"] or r["soft"]) else ""))

    missing_chapters = [rc.heading for rc in rcs if not texts.get(rc.id, "").strip()]
    if missing_chapters:
        print("❌ 以下章节缺失，无法组装：" + "；".join(missing_chapters))
        return {"ok": False, "reason": "chapter_failed", "chapters": {k: _brief(v) for k, v in results.items()}}

    frame = generate_frame(cfg, llm, [texts[rc.id] for rc in rcs])
    cfg.draft_frame_path.write_text(frame["text"], encoding="utf-8")
    fflag = "❌" if frame["hard"] else ("⚠️" if frame["soft"] else "✅")
    print(f"  {fflag} 摘要/关键词/结论" + (f"｜{'；'.join(frame['hard'] + frame['soft'])[:90]}" if (frame["hard"] or frame["soft"]) else ""))

    draft = assemble(cfg, texts, frame["parts"])
    cfg.draft_path.write_text(draft, encoding="utf-8")

    # 跨章近重复
    sents = [(rc.id, s) for rc in rcs for s in split_sentences(_body_only(texts[rc.id]), 20)]
    dups = [(a, b, j) for a, b, j in near_duplicate_pairs(sents, 0.6)]
    report = {
        "chapters": {rc.id: _brief(results[rc.id]) for rc in rcs if rc.id in results},
        "frame": {"hard": frame["hard"], "soft": frame["soft"]},
        "near_duplicates": [{"a": a[:60], "b": b[:60], "jaccard": j} for a, b, j in dups],
    }
    (cfg.draft_dir / "draft_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                                     encoding="utf-8")
    hard_all = [h for r in results.values() for h in r["hard"]] + frame["hard"]
    print("\n" + "=" * 72)
    print(f"🏁 草稿：{cfg.draft_path.name}｜近重复句对 {len(dups)}；" + llm.usage.summary_line())
    if dups:
        print(f"⚠️ 发现 {len(dups)} 组跨章近重复句，详见 draft_report.json")
    print("⚠️ 请人工审阅草稿：事实、逻辑、重复，再进入阶段5")
    print("=" * 72)
    return {"ok": not hard_all, "hard": hard_all, "near_duplicates": len(dups)}


def _brief(r: dict) -> dict:
    return {"chars": r.get("chars", 0), "hard": r.get("hard", []), "soft": r.get("soft", []),
            "prompt": r.get("prompt", "")}
