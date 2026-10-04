# -*- coding: utf-8 -*-
"""质检与审稿（终稿之后）。

qc      确定性核验 +（可选）LLM 句级蕴含：
        1. 带引用的句子里的数字，必须出现在所引来源的原文中（零成本，拦截“数字漂移”）；
        2. 含数字却没有任何引用的句子单独列出；
        3. 引用分布：每个来源被引次数、未被引用的来源；
        4. 可选 `--llm-check`：对带引用的句子，用其所引来源最相关的原文片段做 supported/partial/unsupported 判断。
review  让 LLM 以“审稿人”身份只提问题、不改文（成本一次调用），输出 审稿意见.md。

两者都不修改终稿；结果是给你人工复核的线索，不是定论。
"""
from __future__ import annotations

import re
from typing import Dict, List

from .config import WorkflowConfig
from .corpus import Corpus
from .evidence import parse_structured
from .llm import BaseLLM, extract_json
from .prompts import render
from .textutil import (extract_numbers, find_citations, number_universe, short, split_by_heading,
                       split_reference_section, split_sentences, strip_frontmatter, strip_sup_tags)


def _body_sentences(final_text: str, cfg: WorkflowConfig) -> List[dict]:
    main, _ = split_reference_section(strip_frontmatter(final_text))
    out: List[dict] = []
    for head, body in split_by_heading(main, 2).items():
        if head in ("关键词",):
            continue
        body = re.sub(r"^#{3}[ \t]+.*$", "", body, flags=re.M)
        for s in split_sentences(body):
            cites = [c.strip("[]") for c in find_citations(s, cfg.id_prefix)]
            clean = strip_sup_tags(re.sub(r"\[[A-Za-z]+\d+\]", "", s)).strip()
            if len(clean) < 6:
                continue
            out.append({"section": head, "text": clean, "raw": s,
                        "cites": list(dict.fromkeys(cfg.canonical_id(c) for c in cites))})
    return out


def numeric_check(sentences: List[dict], corpus: Corpus) -> Dict[str, list]:
    unsupported, no_source_text, uncited_numbers = [], [], []
    for s in sentences:
        nums = extract_numbers(s["text"])
        if not nums:
            continue
        if not s["cites"]:
            if s["section"] not in ("摘要", "结论与展望"):
                uncited_numbers.append((s, nums))
            continue
        universe: set = set()
        has_text = False
        for c in s["cites"]:
            t = corpus.text_of(c)
            if t:
                has_text = True
                universe |= number_universe(t)
        if not has_text:
            no_source_text.append(s)
            continue
        bad = [n for n in nums if n not in universe]
        if bad:
            unsupported.append((s, bad))
    return {"unsupported": unsupported, "no_source_text": no_source_text, "uncited_numbers": uncited_numbers}


def llm_entail_check(sentences: List[dict], corpus: Corpus, cfg: WorkflowConfig, llm: BaseLLM) -> List[dict]:
    cands = [s for s in sentences if s["cites"] and any(corpus.has(c) for c in s["cites"])]
    cands.sort(key=lambda s: -len(extract_numbers(s["text"])))   # 含数字的优先
    cands = cands[: int(cfg.qc_cfg["llm_check_max_sentences"])]
    lc = cfg.llm_cfg
    verdicts: List[dict] = []
    for i in range(0, len(cands), 8):
        batch = cands[i:i + 8]
        blocks = []
        for k, s in enumerate(batch, start=1):
            chunks = corpus.search(s["text"], s["cites"], k=2, per_source_max=2, include_head=False)
            ev = "\n".join(f'<source id="{c.source}">{c.text}</source>' for c in chunks)
            blocks.append(f'<item id="{k}">\n<sentence>{s["text"]}</sentence>\n{ev}\n</item>')
        p = render("entail", cfg.prompts_override_dir, items="\n".join(blocks))
        try:
            text = llm.chat(task="entail", model=lc.get("review_model") or lc["draft_model"], system=p.system,
                            user=p.user, max_tokens=2000, temperature=0.0)
            data = extract_json(text)
            for v in data.get("verdicts", []):
                idx = int(v.get("id", 0)) - 1
                if 0 <= idx < len(batch):
                    verdicts.append({"sentence": batch[idx], "verdict": v.get("verdict", ""),
                                     "reason": v.get("reason", "")})
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠️ LLM 核验批次失败：{str(e)[:80]}")
    return verdicts


def run_qc(cfg: WorkflowConfig, llm: BaseLLM = None, llm_check: bool = False, **_) -> dict:
    print("=" * 72)
    print("🚀 质检：数字核验 / 引用分布" + (" / LLM 句级核验" if llm_check else ""))
    print("=" * 72)
    if not cfg.final_md_path.exists():
        print(f"❌ 终稿不存在：{cfg.final_md_path}")
        return {"ok": False, "reason": "missing_final"}
    text = cfg.final_md_path.read_text(encoding="utf-8")
    corpus = Corpus(cfg)
    sentences = _body_sentences(text, cfg)
    res = numeric_check(sentences, corpus)

    usage: Dict[str, int] = {}
    for s in sentences:
        for c in s["cites"]:
            usage[c] = usage.get(c, 0) + 1
    unused = sorted({e["id"] for e in cfg.canonical_entries} - set(usage), key=cfg.id_num)
    verdicts: List[dict] = []
    if llm_check or cfg.qc_cfg.get("llm_check"):
        if llm is None:
            raise RuntimeError("LLM 核验需要可用的 LLM")
        verdicts = llm_entail_check(sentences, corpus, cfg, llm)
    weak = [v for v in verdicts if v["verdict"] in ("partial", "unsupported")]

    L = [f"# 质检报告：{cfg.report_title}", "",
         "> 自动生成的**复核线索**，不是定论。数字核验是“数字是否出现在所引来源原文”的字面比对，"
         "翻译换算（如“7 万”↔ 70,000）可能产生误报，请结合原文判断。", "",
         "## 概览", "",
         f"- 正文句子 {len(sentences)} 条；带引用 {sum(1 for s in sentences if s['cites'])} 条",
         f"- 数字未见于所引来源：**{len(res['unsupported'])}** 条",
         f"- 含数字但无引用：**{len(res['uncited_numbers'])}** 条",
         f"- 所引来源缺少可用正文，无法核验：{len(res['no_source_text'])} 条",
         f"- 未被引用的文献：{', '.join(unused) if unused else '无'}"]
    if verdicts:
        L.append(f"- LLM 句级核验 {len(verdicts)} 条：部分/不支持 **{len(weak)}** 条")
    if corpus.missing:
        L.append(f"- 没有可用正文的文献：{', '.join(corpus.missing)}")
    L += ["", "## 一、数字未见于所引来源", ""]
    if res["unsupported"]:
        for s, bad in res["unsupported"]:
            L.append(f"- **{s['section']}**｜数字 {', '.join(bad)}｜引用 {', '.join(s['cites'])}\n  - {short(s['text'], 120)}")
    else:
        L.append("无。")
    L += ["", "## 二、含数字但无引用", ""]
    if res["uncited_numbers"]:
        for s, nums in res["uncited_numbers"]:
            L.append(f"- **{s['section']}**｜数字 {', '.join(nums)}\n  - {short(s['text'], 120)}")
    else:
        L.append("无。")
    if res["no_source_text"]:
        L += ["", "## 三、来源无正文，无法核验", ""]
        for s in res["no_source_text"]:
            L.append(f"- {', '.join(s['cites'])}｜{short(s['text'], 100)}")
    if verdicts:
        L += ["", "## 四、LLM 句级核验（部分/不支持）", ""]
        if weak:
            for v in weak:
                s = v["sentence"]
                L.append(f"- [{v['verdict']}] {s['section']}｜{', '.join(s['cites'])}\n  - {short(s['text'], 120)}\n  - 理由：{v['reason']}")
        else:
            L.append("无。")
    L += ["", "## 引用分布", "", "| 来源 | 被引句数 |", "|---|---|"]
    for sid in sorted(usage, key=cfg.id_num):
        L.append(f"| {sid} | {usage[sid]} |")
    cfg.qc_report_path.write_text("\n".join(L) + "\n", encoding="utf-8")

    flags = len(res["unsupported"]) + len(weak)
    print(f"📄 {cfg.qc_report_path}")
    print(f"   数字未见于来源 {len(res['unsupported'])}｜含数字无引用 {len(res['uncited_numbers'])}"
          f"｜LLM 核验不通过 {len(weak)}")
    print("=" * 72)
    return {"ok": True, "flags": flags, "unsupported_numbers": len(res["unsupported"]),
            "uncited_numbers": len(res["uncited_numbers"]), "llm_weak": len(weak)}


def run_review(cfg: WorkflowConfig, llm: BaseLLM, **_) -> dict:
    print("=" * 72)
    print("🚀 审稿：LLM 审稿人只提问题、不改文")
    print("=" * 72)
    src = cfg.final_md_path if cfg.final_md_path.exists() else cfg.draft_path
    if not src.exists():
        print("❌ 没有可审阅的稿件")
        return {"ok": False, "reason": "missing_draft"}
    draft = split_reference_section(strip_frontmatter(src.read_text(encoding="utf-8")))[0]
    ev_lines: List[str] = []
    for ch in cfg.chapters:
        p = cfg.structured_path(ch)
        if p.exists():
            for sid, items in parse_structured(p.read_text(encoding="utf-8")).items():
                ev_lines += [f"[{sid}] {e.claim} [{e.source}]" for e in items]
    lc = cfg.llm_cfg
    p = render("review", cfg.prompts_override_dir, report_title=cfg.report_title,
               evidence="\n".join(ev_lines[:400]), draft=draft)
    out = llm.chat(task="review", model=lc.get("review_model") or lc["draft_model"], system=p.system, user=p.user,
                   max_tokens=int(lc.get("max_tokens_review", 3000)), temperature=0.1)
    cfg.review_report_path.write_text(
        f"# 审稿意见：{cfg.report_title}\n\n> LLM 审稿人输出，仅供参考；请自行判断是否采纳。\n\n{out.strip()}\n",
        encoding="utf-8")
    print(f"📄 {cfg.review_report_path}")
    print("=" * 72)
    return {"ok": True}
