# -*- coding: utf-8 -*-
"""原始素材语料库：加载 02-原始素材、分块、BM25 检索。

阶段 2 不再把每篇文献硬截成“文首 + 文末”，而是：
  1) 全文分块（chunk，带稳定编号 LBQ01#c3）；
  2) 以“小节名 + 归类约束 + 分析任务”为查询，BM25 取最相关的若干块；
  3) 每个来源保证至少带上文首块（概念定义通常在这里）。
纯标准库实现，无向量库依赖；中文用字二元组，英文用单词。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .config import WorkflowConfig
from .textutil import sanitize_filename, split_frontmatter

PLACEHOLDER_MARK = "程序未能自动提取正文"

_META_PREFIXES = (
    "> **抓取状态：**", "> ⚠️ **抓取状态：**", "## 文献使用说明",
    "**对应报告章节：**", "**文献类型：**", "**可信度：**", "**原文链接：**",
)


def raw_filename(entry: dict) -> str:
    """`LBQ01 - 标题.md`：不含方括号，避免 Obsidian 双链嵌套。"""
    return f"{entry['id']} - {sanitize_filename(entry['title'])}.md"


def clean_body(body: str) -> str:
    """去掉抓取元信息行与占位说明，留下可作为证据的正文。"""
    lines = body.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    kept = []
    for ln in lines:
        s = ln.strip()
        if s.startswith(_META_PREFIXES) or PLACEHOLDER_MARK in s:
            continue
        if s in ("## 原始链接", "## PDF") or re.fullmatch(r"https?://\S+", s):
            continue
        kept.append(ln)
    return "\n".join(kept).strip()


def is_placeholder(body: str, min_chars: int = 200) -> bool:
    return len(clean_body(body)) < min_chars


# ============================================================
# 分块
# ============================================================
def chunk_text(text: str, size: int = 700) -> List[str]:
    text = text.strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    units: List[str] = []
    for p in paras:
        if len(p) <= size * 1.5:
            units.append(p)
            continue
        buf = ""
        for s in re.split(r"(?<=[。！？])|(?<=[.!?])\s+", p):
            if not s:
                continue
            if buf and len(buf) + len(s) > size:
                units.append(buf.strip())
                buf = ""
            buf += s if re.search(r"[\u4e00-\u9fff]$", s) else s + " "
        if buf.strip():
            units.append(buf.strip())
    hard: List[str] = []
    for u in units:  # 无标点的超长文本（表格、代码）硬切
        while len(u) > size * 2:
            hard.append(u[:size * 2])
            u = u[size * 2:]
        hard.append(u)
    chunks: List[str] = []
    buf = ""
    for u in hard:
        if buf and len(buf) + len(u) + 2 > size:
            chunks.append(buf)
            buf = u
        else:
            buf = f"{buf}\n\n{u}" if buf else u
    if buf:
        chunks.append(buf)
    return chunks


_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*|[\u4e00-\u9fff]+")


def tokenize(text: str) -> List[str]:
    out: List[str] = []
    for m in _TOKEN.finditer(text.lower()):
        s = m.group(0)
        if "\u4e00" <= s[0] <= "\u9fff":
            out += [s] if len(s) == 1 else [s[i:i + 2] for i in range(len(s) - 1)]
        elif len(s) >= 2:
            out.append(s)
    return out


@dataclass
class Chunk:
    id: str
    source: str
    idx: int
    text: str
    tokens: List[str] = field(default_factory=list, repr=False)


@dataclass
class Doc:
    id: str
    title: str
    meta: dict
    text: str
    chunks: List[Chunk]


class Corpus:
    def __init__(self, cfg: WorkflowConfig):
        self.cfg = cfg
        self.docs: Dict[str, Doc] = {}
        self.missing: List[str] = []       # 没有可用正文的主文献编号
        self._df: Dict[str, int] = {}
        self._n_chunks = 0
        self._avg_len = 1.0
        self._load()

    # ---------- 加载 ----------
    def _read_entry(self, entry: dict):
        path = self.cfg.raw_chapter_dir(entry["chapter"]) / raw_filename(entry)
        if not path.exists():
            return None
        meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
        if is_placeholder(body):
            return None
        return meta, clean_body(body)

    def _load(self):
        size = int(self.cfg.retrieval_cfg["chunk_chars"])
        for e in self.cfg.canonical_entries:
            texts, meta = [], {}
            for ent in [e] + self.cfg.mirrors_of(e["id"]):
                got = self._read_entry(ent)
                if got:
                    m, body = got
                    meta = meta or m
                    texts.append(body)
            if not texts:
                self.missing.append(e["id"])
                continue
            full = "\n\n".join(texts)
            chunks = [Chunk(f"{e['id']}#c{i + 1}", e["id"], i, t, tokenize(t))
                      for i, t in enumerate(chunk_text(full, size))]
            self.docs[e["id"]] = Doc(e["id"], e["title"], meta, full, chunks)
        all_chunks = [c for d in self.docs.values() for c in d.chunks]
        self._n_chunks = len(all_chunks)
        total = 0
        for c in all_chunks:
            total += len(c.tokens)
            for t in set(c.tokens):
                self._df[t] = self._df.get(t, 0) + 1
        self._avg_len = total / max(self._n_chunks, 1)

    # ---------- 访问 ----------
    def has(self, sid: str) -> bool:
        return sid in self.docs

    def text_of(self, sid: str) -> str:
        d = self.docs.get(self.cfg.canonical_id(sid))
        return d.text if d else ""

    def chunk(self, chunk_id: str) -> Optional[Chunk]:
        sid = chunk_id.split("#", 1)[0]
        d = self.docs.get(self.cfg.canonical_id(sid))
        if not d:
            return None
        return next((c for c in d.chunks if c.id == chunk_id), None)

    # ---------- 检索 ----------
    def _score(self, q_tokens: Sequence[str], c: Chunk, k1: float = 1.5, b: float = 0.75) -> float:
        if not c.tokens:
            return 0.0
        tf: Dict[str, int] = {}
        for t in c.tokens:
            tf[t] = tf.get(t, 0) + 1
        s = 0.0
        for t in set(q_tokens):
            f = tf.get(t)
            if not f:
                continue
            df = self._df.get(t, 0)
            idf = math.log(1 + (self._n_chunks - df + 0.5) / (df + 0.5))
            s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(c.tokens) / self._avg_len))
        return s

    def search(self, query: str, source_ids: Sequence[str], k: int = 8,
               per_source_max: int = 3, include_head: bool = True) -> List[Chunk]:
        sids = [s for s in dict.fromkeys(self.cfg.canonical_id(x) for x in source_ids) if s in self.docs]
        cands = [c for s in sids for c in self.docs[s].chunks]
        if not cands:
            return []
        q = tokenize(query)
        score = {c.id: self._score(q, c) for c in cands}
        selected: List[Chunk] = []
        per: Dict[str, int] = {}
        if include_head:
            for s in sids[:max(1, k // 2)]:
                h = self.docs[s].chunks[0]
                selected.append(h)
                per[s] = 1
        chosen = {c.id for c in selected}
        for c in sorted(cands, key=lambda c: (-score[c.id], c.source, c.idx)):
            if len(selected) >= k:
                break
            if c.id in chosen or per.get(c.source, 0) >= per_source_max:
                continue
            selected.append(c)
            chosen.add(c.id)
            per[c.source] = per.get(c.source, 0) + 1
        order = {s: i for i, s in enumerate(sids)}
        return sorted(selected, key=lambda c: (order.get(c.source, 99), c.idx))

    def render_chunks(self, chunks: Sequence[Chunk]) -> str:
        parts = []
        for c in chunks:
            title = self.docs[c.source].title.replace('"', "'")
            parts.append(f'<chunk id="{c.id}" source="{c.source}" title="{title}">\n{c.text}\n</chunk>')
        return "\n".join(parts)
