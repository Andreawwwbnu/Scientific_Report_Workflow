# -*- coding: utf-8 -*-
"""参考文献：只由 manifest（权威来源）生成，不再依赖模型输出。"""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from .config import WorkflowConfig
from .corpus import raw_filename
from .textutil import split_frontmatter


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def raw_author(cfg: WorkflowConfig, entry: dict) -> str:
    """manifest 未填 author 时，用阶段 1 回填的作者（如 arXiv）。"""
    path = cfg.raw_chapter_dir(entry["chapter"]) / raw_filename(entry)
    if path.exists():
        meta, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        return str(meta.get("作者", "") or "")
    return ""


def author_of(cfg: WorkflowConfig, e: dict) -> str:
    a = (e.get("author") or "").strip() or raw_author(cfg, e).strip() or (e.get("publisher") or "").strip() or "佚名"
    if "et al" in a.lower():
        raise ValueError(f"{e['id']} 作者含 'et al.'，请在 manifest 补全真实作者或改用发布主体")
    n = int(cfg.ref_cfg.get("max_authors", 0) or 0)
    if n > 0:
        parts = [p.strip() for p in re.split(r"[,，、;；]", a) if p.strip()]
        if len(parts) > n:
            a = ", ".join(parts[:n]) + ", 等"
    return a


def format_reference(cfg: WorkflowConfig, e: dict, access_date: Optional[str] = None) -> str:
    year = str(e.get("date", ""))[:4] or "n.d"
    rtype = e.get("ref_type", "EB/OL")
    line = f"[{e['id']}] {author_of(cfg, e)}. {e['title']}.[{rtype}]. {year}."
    url = e.get("url")
    if url:
        line += f" {url}"
        if access_date:
            line += f"[引用日期 {access_date}]。"
    return line


def build_reference_lines(cfg: WorkflowConfig, order: Optional[List[str]] = None,
                          access_date: Optional[str] = None) -> List[str]:
    """order：按此编号顺序输出（只含主编号）；缺省按 manifest 编号顺序。"""
    by_id = {e["id"]: e for e in cfg.canonical_entries}
    ids = order if order is not None else sorted(by_id, key=cfg.id_num)
    return [format_reference(cfg, by_id[i], access_date) for i in ids if i in by_id]


def build_references(cfg: WorkflowConfig, order: Optional[List[str]] = None,
                     access_date: Optional[str] = None) -> str:
    return "\n".join(build_reference_lines(cfg, order, access_date))
