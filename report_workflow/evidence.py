# -*- coding: utf-8 -*-
"""结构化证据（阶段 2 产物）与分析结论（阶段 3 产物）的读写格式。

证据文件是“人可读、可手改”的 Markdown：

    ## 1.1 小节名
    - 一句话事实陈述。[LBQ01]
      > 原文：从来源逐字摘录的片段 ｜ LBQ01#c3

你可以直接删改要点；阶段 3/4/质检读取的就是这份文件。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from .config import SKIP_MARK
from .textutil import split_by_heading

NO_EVIDENCE_LINE = "- 暂无充分证据。"
_CLAIM = re.compile(r"^-\s+(.*?)\s*\[([A-Za-z]+\d+)\]\s*$")
_QUOTE = re.compile(r"^\s+>\s*原文：(.*)$")
_SEC_HEAD = re.compile(r"^(\d+(?:\.\d+)*)\b")


@dataclass
class Evidence:
    claim: str
    source: str
    quote: str = ""
    chunk: str = ""


def format_section(sec_id: str, sec_name: str, items: List[Evidence]) -> str:
    out = [f"## {sec_id} {sec_name}"]
    if not items:
        out.append(NO_EVIDENCE_LINE)
    for it in items:
        out.append(f"- {it.claim.strip()} [{it.source}]")
        if it.quote:
            q = re.sub(r"\s+", " ", it.quote).strip()
            out.append(f"  > 原文：{q} ｜ {it.chunk}")
    return "\n".join(out) + "\n"


def parse_structured(text: str) -> Dict[str, List[Evidence]]:
    """{小节号: [Evidence]}；无证据的小节为空列表。"""
    result: Dict[str, List[Evidence]] = {}
    for head, body in split_by_heading(text, 2).items():
        m = _SEC_HEAD.match(head)
        if not m:
            continue
        items: List[Evidence] = []
        for ln in body.splitlines():
            cm = _CLAIM.match(ln)
            if cm:
                items.append(Evidence(claim=cm.group(1).strip(), source=cm.group(2)))
                continue
            qm = _QUOTE.match(ln)
            if qm and items:
                quote, _, chunk = qm.group(1).rpartition("｜")
                items[-1].quote = quote.strip()
                items[-1].chunk = chunk.strip()
        result[m.group(1)] = items
    return result


def evidence_lines(items: List[Evidence]) -> str:
    return "\n".join(f"- {e.claim} [{e.source}]" for e in items)


# ---------------- 分析结论 ----------------
SKIP_NOTE = f"> ⚠️ 本小节{SKIP_MARK}，按规则未纳入分析，请勿在成稿中展开。"
FAIL_NOTE = "> ⚠️ 本小节分析失败，请人工补充或重跑阶段 3。"


def parse_analysis(text: str) -> Dict[str, Optional[str]]:
    """{小节号: 分析正文}；被跳过或失败的小节值为 None。"""
    result: Dict[str, Optional[str]] = {}
    for head, body in split_by_heading(text, 2).items():
        m = _SEC_HEAD.match(head)
        if not m:
            continue
        b = body.strip()
        skipped = b.startswith("> ⚠️") or not b
        result[m.group(1)] = None if skipped else b
    return result
