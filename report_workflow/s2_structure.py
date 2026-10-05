# -*- coding: utf-8 -*-
"""阶段 2：原始素材 → 结构化证据（只抽取，不写作）。

v3 的关键变化（影响可信度最大的一环）：
1. **检索代替截断**：全文分块，按小节任务做 BM25，取最相关的块（每源保底带文首块）；
2. **证据可核验**：模型必须输出 {claim, quote, source, chunk}，代码校验
   - 来源编号在白名单内；
   - quote 必须是所给 chunk 的**逐字子串**；
   - claim 里的数字必须出现在原文里；
   不通过的证据直接丢弃，而不是“告警后照样放行”；
3. 以小节为单位并发调用，失败的小节单独重试，互不影响。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .config import WorkflowConfig
from .corpus import Chunk, Corpus
from .evidence import Evidence, format_section
from .llm import BaseLLM, extract_json, parallel_map
from .prompts import render
from .textutil import (extract_numbers, norm_for_match, normalize_aliases_in_text,
                       number_universe, with_frontmatter)


def sources_for_section(cfg: WorkflowConfig, sec: dict, corpus: Corpus) -> List[str]:
    """小节的候选来源 = manifest 中归属该小节的文献 ∪ extract_rule 中点名的编号。"""
    prefix = cfg.id_prefix
    ids = [cfg.canonical_id(e["id"]) for e in cfg.all_entries if e.get("section") == sec["id"]]
    ids += [cfg.canonical_id(x) for x in re.findall(rf"{re.escape(prefix)}\d+", sec.get("extract_rule", ""))]
    return [i for i in dict.fromkeys(ids) if corpus.has(i)]


def expand_query(sec: dict, sids: List[str], cfg: WorkflowConfig, corpus: Corpus, llm: BaseLLM) -> List[str]:
    """检索关键词 = 小节配置里手写的 keywords + （可选）LLM 生成的双语关键词。

    为什么需要：抽取规则通常是中文，而原文常是英文，纯中文查询词在 BM25 里根本命中不了英文块。
    扩展失败不影响主流程，退回基础查询。"""
    kws = [str(x) for x in (sec.get("keywords") or [])]
    if cfg.retrieval_cfg.get("query_expansion", "llm") == "llm":
        titles = "；".join(corpus.docs[s].title for s in sids)[:400]
        p = render("expand_query", cfg.prompts_override_dir, topic=cfg.name, section_id=sec["id"],
                   section_name=sec["name"], extract_rule=sec.get("extract_rule", ""),
                   analyze_task=sec.get("analyze_task", ""), source_titles=titles)
        try:
            text = llm.chat(task="expand_query", model=cfg.llm_cfg["structure_model"], system=p.system,
                            user=p.user, max_tokens=600, temperature=0.0)
            data = extract_json(text)
            extra = data.get("keywords", []) if isinstance(data, dict) else data
            kws += [str(x) for x in extra if isinstance(x, (str, int, float))][:20]
        except Exception:  # noqa: BLE001
            pass
    return kws


def verify_items(raw_items: Sequence[dict], chunks: Sequence[Chunk], allowed: Set[str],
                 cfg: WorkflowConfig, max_items: int) -> Tuple[List[Evidence], List[str]]:
    """逐条校验，返回 (合格证据, 丢弃原因列表)。"""
    by_id = {c.id: c for c in chunks}
    by_src: Dict[str, List[Chunk]] = {}
    for c in chunks:
        by_src.setdefault(c.source, []).append(c)
    good: List[Evidence] = []
    dropped: List[str] = []
    seen_claims: Set[str] = set()
    for it in raw_items:
        if not isinstance(it, dict):
            dropped.append("条目不是对象")
            continue
        claim = str(it.get("claim", "")).strip()
        quote = str(it.get("quote", "")).strip()
        src = cfg.canonical_id(str(it.get("source", "")).strip().strip("[]"))
        label = (claim[:24] or "（空）")
        if not claim or not quote:
            dropped.append(f"{label}：claim/quote 为空")
            continue
        if src not in allowed:
            dropped.append(f"{label}：来源 {src} 不在允许名单")
            continue
        nq = norm_for_match(quote)
        if len(nq) < 6:
            dropped.append(f"{label}：quote 过短")
            continue
        # 定位 quote 所在 chunk：优先模型给出的，其次同源其他块
        cand = []
        cid = str(it.get("chunk", "")).strip()
        if cid in by_id and by_id[cid].source == src:
            cand.append(by_id[cid])
        cand += [c for c in by_src.get(src, []) if c.id != cid]
        hit = next((c for c in cand if nq in norm_for_match(c.text)), None)
        if hit is None:
            dropped.append(f"{label}：quote 不是所给片段的逐字原文")
            continue
        universe = number_universe(hit.text)
        bad = [n for n in extract_numbers(claim) if n not in universe]
        if bad:
            dropped.append(f"{label}：数字 {','.join(bad)} 未出现在原文")
            continue
        key = norm_for_match(claim)
        if key in seen_claims:
            continue
        seen_claims.add(key)
        good.append(Evidence(claim=claim, source=src, quote=quote, chunk=hit.id))
        if len(good) >= max_items:
            break
    return good, dropped


def extract_section(chapter: dict, sec: dict, cfg: WorkflowConfig, corpus: Corpus, llm: BaseLLM) -> dict:
    rcfg = cfg.retrieval_cfg
    sids = sources_for_section(cfg, sec, corpus)
    if not sids:
        return {"items": [], "dropped": [], "note": "无可用来源正文", "prompt": "",
                "retrieval": {"matched": 0, "selected": 0, "weak": False}}
    kws = expand_query(sec, sids, cfg, corpus, llm)
    query = f"{sec['name']} {sec.get('extract_rule', '')} {sec.get('analyze_task', '')} {' '.join(kws)}"
    chunks, info = corpus.search_with_info(query, sids, k=int(rcfg["top_k"]),
                                           per_source_max=int(rcfg["per_source_max"]),
                                           include_head=bool(rcfg["always_include_head"]))
    allowed = set(sids)
    max_items = int(rcfg["max_items_per_section"])
    llm_cfg = cfg.llm_cfg
    feedback = ""
    items: List[Evidence] = []
    dropped: List[str] = []
    tag = ""
    for attempt in range(2):
        p = render("extract", cfg.prompts_override_dir,
                   report_title=cfg.report_title, topic=cfg.name, chapter_name=chapter["name"],
                   section_id=sec["id"], section_name=sec["name"], extract_rule=sec.get("extract_rule", ""),
                   allowed_ids="、".join(sorted(allowed)), max_items=max_items, id_prefix=cfg.id_prefix,
                   chunks=corpus.render_chunks(chunks), feedback=feedback)
        tag = p.tag
        text = llm.chat(task="extract", model=llm_cfg["structure_model"], system=p.system, user=p.user,
                        max_tokens=int(llm_cfg.get("max_tokens_structure", 4000)),
                        temperature=float(llm_cfg.get("temperature_fast", 0.1)))
        text = normalize_aliases_in_text(text, cfg.alias_map)
        try:
            data = extract_json(text)
            raw_items = data.get("items", []) if isinstance(data, dict) else data
        except ValueError as e:
            feedback = f"\n<feedback>上次输出无法解析为 JSON（{e}）。请只输出 JSON 对象。</feedback>"
            dropped = [f"JSON 解析失败：{e}"]
            continue
        items, dropped = verify_items(raw_items, chunks, allowed, cfg, max_items)
        bad_ratio = len(dropped) / max(len(raw_items), 1)
        if attempt == 0 and dropped and (bad_ratio >= 0.3 or not items):
            feedback = ("\n<feedback>上次输出有如下条目未通过核验，已被丢弃：\n- "
                        + "\n- ".join(dropped[:6])
                        + "\n请重新输出：quote 必须逐字复制自 chunk，claim 的数字必须与 quote 一致。</feedback>")
            continue
        break
    return {"items": items, "dropped": dropped, "sources": sids, "chunks": len(chunks), "prompt": tag,
            "retrieval": info, "keywords": kws}


def _chapter_markdown(chapter: dict, results: Dict[str, dict], cfg: WorkflowConfig, corpus: Corpus,
                      prompt_tag: str) -> str:
    used: List[str] = sorted({e.source for r in results.values() for e in r["items"]}, key=cfg.id_num)
    src_list = "\n".join(f"- [{s}] {corpus.docs[s].title}" for s in used if s in corpus.docs) or "- （无）"
    blocks = []
    for sec in chapter["sections"]:
        blocks.append(format_section(sec["id"], sec["name"], results[sec["id"]]["items"]))
    meta = {
        "title": f"{chapter['name']} - 结构化素材", "type": "structured-material", "project": cfg.name,
        "chapter_id": chapter["id"], "source_ids": used,
        "evidence_count": {sid: len(r["items"]) for sid, r in results.items()},
        "dropped_count": {sid: len(r["dropped"]) for sid, r in results.items()},
        "prompt": prompt_tag, "model": cfg.llm_cfg.get("structure_model", ""),
    }
    body = (f"# {chapter['name']}\n"
            "> 由 LLM 基于 `02-原始素材` 抽取并经代码核验（来源白名单、原文逐字、数字一致）。"
            "可直接增删要点；阶段 3/4/质检读取的就是本文件。\n\n"
            f"## 本章节来源\n{src_list}\n\n---\n\n" + "\n".join(blocks))
    return with_frontmatter(meta, body)


def run(cfg: WorkflowConfig, llm: BaseLLM, only_chapters: Optional[Set[str]] = None, **_) -> dict:
    print("=" * 72)
    print("🚀 阶段2：原始素材 → 结构化证据（检索 + 原文核验）")
    print("=" * 72)
    corpus = Corpus(cfg)
    if corpus.missing:
        print(f"⚠️ 以下文献没有可用正文（未抓取或仍是占位）：{', '.join(corpus.missing)}")
    chapters = [c for c in cfg.chapters if not only_chapters or c["id"] in only_chapters]
    jobs = [(ch, sec) for ch in chapters for sec in ch["sections"]]
    workers = int(cfg.llm_cfg.get("concurrency", 3))
    outs = parallel_map(lambda j: extract_section(j[0], j[1], cfg, corpus, llm), jobs, workers)

    per_chapter: Dict[str, Dict[str, dict]] = {}
    dropped_total = kept_total = 0
    failed_sections: List[str] = []
    for (ch, sec), (ok, res) in zip(jobs, outs):
        if not ok:
            print(f"  ❌ {sec['id']} 抽取失败：{str(res)[:100]}")
            res = {"items": [], "dropped": [f"异常：{res}"], "prompt": ""}
            failed_sections.append(sec["id"])
        per_chapter.setdefault(ch["id"], {})[sec["id"]] = res
        kept_total += len(res["items"])
        dropped_total += len(res["dropped"])
        mark = "✅" if res["items"] else "⚪"
        print(f"  {mark} {sec['id']} {sec['name']}：保留 {len(res['items'])} 条，丢弃 {len(res['dropped'])} 条")

    weak = [sec["id"] for (ch, sec), (ok, res) in zip(jobs, outs)
            if ok and res.get("retrieval", {}).get("weak")]
    if weak:
        print(f"⚠️ 检索信号弱的小节：{', '.join(weak)}——原文与检索词语言/用词可能不一致，"
              "建议在这些小节配置 keywords，或确认 retrieval.query_expansion: llm")
    empty_chapters = []
    for ch in chapters:
        results = per_chapter[ch["id"]]
        tag = next((r.get("prompt") for r in results.values() if r.get("prompt")), "")
        cfg.write_text_safe(cfg.structured_path(ch), _chapter_markdown(ch, results, cfg, corpus, tag))
        if not any(r["items"] for r in results.values()):
            empty_chapters.append(ch["id"])
    print("\n" + "=" * 72)
    print(f"🏁 证据保留 {kept_total} 条，核验丢弃 {dropped_total} 条；" + llm.usage.summary_line())
    if empty_chapters:
        print(f"❌ 以下章节没有任何有效证据：{', '.join(empty_chapters)}（请补充正文后重跑）")
    print("⚠️ 建议人工抽查：定义、数字、章节归属（证据文件里每条都带原文摘录，核对很快）")
    print("=" * 72)
    return {"ok": not empty_chapters, "kept": kept_total, "dropped": dropped_total,
            "empty_chapters": empty_chapters, "failed_sections": failed_sections, "weak_retrieval": weak}
