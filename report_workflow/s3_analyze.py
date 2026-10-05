# -*- coding: utf-8 -*-
"""阶段 3：结构化证据 → 分小节分析（只推理，不补料）。

质量门（旧版只告警、仍照常保存；v3 改为确定性处理）：
- 引用编号必须 ⊆ **本小节证据**的来源（比旧版的“本章来源”更严）；
- 非法引用：先带反馈重试一次，仍有则**删除含非法引用的要点**，保证错误不会流入成稿；
- 数字：分析里出现的数字必须能在本小节证据里找到，否则重试一次，仍有则在文件头记录警告；
- 长度越界同样触发一次带反馈重试。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from .config import WorkflowConfig
from .evidence import FAIL_NOTE, SKIP_NOTE, Evidence, evidence_lines, parse_structured
from .llm import BaseLLM, parallel_map
from .prompts import render
from .textutil import (citation_set, extract_numbers, normalize_aliases_in_text,
                       number_universe, with_frontmatter)


def _length(text: str) -> int:
    return len(re.sub(r"\s+|\[[A-Za-z]+\d+\]", "", text))


def _call(sec: dict, items: List[Evidence], allowed: Set[str], cfg: WorkflowConfig, llm: BaseLLM,
          feedback: str = "") -> tuple[str, str]:
    lc = cfg.llm_cfg
    p = render("analyze", cfg.prompts_override_dir,
               topic=cfg.name, section_id=sec["id"], section_name=sec["name"],
               analyze_task=sec["analyze_task"], id_prefix=cfg.id_prefix,
               allowed_ids="、".join(sorted(allowed)),
               min_chars=int(lc.get("min_section_chars", 200)), max_chars=int(lc.get("max_section_chars", 800)),
               evidence=evidence_lines(items), feedback=feedback)
    text = llm.chat(task="analyze", model=lc["analyze_model"], system=p.system, user=p.user,
                    max_tokens=int(lc.get("max_tokens_analyze", 8192)),
                    temperature=float(lc.get("temperature_fast", 0.1)))
    return normalize_aliases_in_text(text, cfg.alias_map), p.tag


def _drop_bad_bullets(text: str, allowed: Set[str], prefix: str) -> tuple[str, int]:
    """删除含非法来源编号的要点行；返回 (新文本, 删除条数)。"""
    kept, dropped = [], 0
    for ln in text.splitlines():
        if citation_set(ln, prefix) - allowed:
            dropped += 1
            continue
        kept.append(ln)
    return "\n".join(kept).strip(), dropped


def analyze_section(sec: dict, items: List[Evidence], cfg: WorkflowConfig, llm: BaseLLM) -> dict:
    prefix = cfg.id_prefix
    lc = cfg.llm_cfg
    min_len, max_len = int(lc.get("min_section_chars", 200)), int(lc.get("max_section_chars", 800))
    allowed = {cfg.canonical_id(e.source) for e in items}
    universe = number_universe(" ".join(e.claim + " " + e.quote for e in items))

    def problems(text: str) -> List[str]:
        out = []
        n = _length(text)
        if n < min_len:
            out.append(f"输出仅 {n} 字，未达 {min_len} 字下限，请补足核心判断与证据")
        if n > max_len:
            out.append(f"输出 {n} 字，超过 {max_len} 字上限，请压缩，只保留核心判断与证据")
        bad = citation_set(text, prefix) - allowed
        if bad:
            out.append(f"出现非法来源编号 {sorted(bad)}，只允许 {sorted(allowed)}")
        nums = sorted({x for x in extract_numbers(text) if x not in universe})
        if nums:
            out.append(f"出现证据中没有的数字 {nums}，数字必须逐字取自证据")
        return out

    text, tag = _call(sec, items, allowed, cfg, llm)
    probs = problems(text)
    if probs:
        fb = "\n<feedback>上次输出的问题：\n- " + "\n- ".join(probs) + "\n请逐条修正后重新输出。</feedback>"
        text, tag = _call(sec, items, allowed, cfg, llm, fb)
        probs = problems(text)

    removed = 0
    text, removed = _drop_bad_bullets(text, allowed, prefix)
    warnings = [p for p in probs if "非法来源" not in p]  # 非法来源已确定性处理
    if removed:
        warnings.append(f"已删除 {removed} 条含非法来源编号的要点")
    return {"text": text, "warnings": warnings, "prompt": tag}


def run(cfg: WorkflowConfig, llm: BaseLLM, only_chapters: Optional[Set[str]] = None, **_) -> dict:
    print("=" * 72)
    print("🚀 阶段3：结构化证据 → 分小节分析")
    print("=" * 72)
    chapters = [c for c in cfg.chapters if not only_chapters or c["id"] in only_chapters]
    structured: Dict[str, Dict[str, List[Evidence]]] = {}
    missing = []
    for ch in chapters:
        p = cfg.structured_path(ch)
        if not p.exists():
            missing.append(p.name)
            continue
        structured[ch["id"]] = parse_structured(p.read_text(encoding="utf-8"))
    if missing:
        print("❌ 缺少阶段2产物：" + "；".join(missing))
        return {"ok": False, "reason": "missing_structured"}

    jobs = []
    for ch in chapters:
        for sec in ch["sections"]:
            items = structured[ch["id"]].get(sec["id"], [])
            jobs.append((ch, sec, items))
    workers = int(cfg.llm_cfg.get("concurrency", 3))

    def work(j):
        ch, sec, items = j
        if not items:
            return None
        return analyze_section(sec, items, cfg, llm)

    outs = parallel_map(work, jobs, workers)
    results: Dict[str, Dict[str, str]] = {}
    warn_by_sec: Dict[str, List[str]] = {}
    ok_n = skip_n = fail_n = 0
    tag = ""
    for (ch, sec, items), (ok, res) in zip(jobs, outs):
        blocks = results.setdefault(ch["id"], {})
        head = f"## {sec['id']} {sec['name']}"
        if not ok:
            print(f"  ❌ {sec['id']} 失败：{str(res)[:100]}")
            blocks[sec["id"]] = f"{head}\n{FAIL_NOTE}\n"
            fail_n += 1
        elif res is None:
            print(f"  ⏭️ {sec['id']} 无证据，跳过（成稿不得展开）")
            blocks[sec["id"]] = f"{head}\n{SKIP_NOTE}\n"
            skip_n += 1
        else:
            tag = res["prompt"] or tag
            body = res["text"]
            if not body.strip():
                blocks[sec["id"]] = f"{head}\n{FAIL_NOTE}\n"
                fail_n += 1
                print(f"  ❌ {sec['id']} 输出为空")
                continue
            blocks[sec["id"]] = f"{head}\n{body}\n"
            ok_n += 1
            if res["warnings"]:
                warn_by_sec[sec["id"]] = res["warnings"]
            flag = "⚠️" if res["warnings"] else "✅"
            print(f"  {flag} {sec['id']} {sec['name']}：{_length(body)} 字"
                  + (f"｜{'；'.join(res['warnings'])[:80]}" if res["warnings"] else ""))

    for ch in chapters:
        meta = {"title": f"{ch['name']}·分析结论", "project": cfg.name,
                "model": cfg.llm_cfg.get("analyze_model", ""), "source_material": cfg.structured_path(ch).name,
                "prompt": tag}
        warns = {s["id"]: warn_by_sec[s["id"]] for s in ch["sections"] if s["id"] in warn_by_sec}
        if warns:
            meta["warnings"] = warns
        body = (f"# {ch['name']}·分析结论\n"
                f"> 分析依据：`{cfg.structured_path(ch).name}`；结论均由证据推导，未引入外部知识。\n\n"
                + "\n".join(results[ch["id"]][s["id"]] for s in ch["sections"]))
        cfg.write_text_safe(cfg.analysis_path(ch), with_frontmatter(meta, body))

    print("\n" + "=" * 72)
    print(f"🏁 成功 {ok_n}｜跳过 {skip_n}｜失败 {fail_n}；" + llm.usage.summary_line())
    print("⚠️ 建议人工校验分析逻辑与来源标注，再进入阶段4")
    print("=" * 72)
    return {"ok": fail_n == 0 and ok_n > 0, "success": ok_n, "skipped": skip_n, "failed": fail_n,
            "warnings": warn_by_sec}
