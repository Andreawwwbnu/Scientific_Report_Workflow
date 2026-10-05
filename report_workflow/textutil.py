# -*- coding: utf-8 -*-
"""文本工具：Front Matter、引用编号、字数口径、句子切分、数字抽取。

只依赖标准库与 PyYAML，不含任何业务流程，方便单测。
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Tuple

import yaml

# ============================================================
# Front Matter
# ============================================================
_FM_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)(.*)\Z", re.S)


def split_frontmatter(text: str) -> Tuple[dict, str]:
    """返回 (meta, body)；无 front matter 时 meta={}。"""
    m = _FM_RE.match(text.lstrip("\ufeff"))
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
        if not isinstance(meta, dict):
            meta = {}
    except yaml.YAMLError:
        meta = {}
    return meta, m.group(2).strip()


def dump_frontmatter(meta: dict) -> str:
    return yaml.dump(meta, allow_unicode=True, sort_keys=False,
                     default_flow_style=False, width=1000).strip()


def with_frontmatter(meta: dict, body: str) -> str:
    return f"---\n{dump_frontmatter(meta)}\n---\n\n{body.strip()}\n"


def strip_frontmatter(text: str) -> str:
    return split_frontmatter(text)[1]


def sanitize_filename(name: str, limit: int = 120) -> str:
    name = re.sub(r'[\\/:*?"<>|\[\]#^]', "_", name)
    name = re.sub(r"\s+", " ", name.replace("\n", " ")).strip()
    return name[:limit].rstrip()


# ============================================================
# 引用编号
# ============================================================
def cite_re(prefix: str) -> re.Pattern:
    return re.compile(rf"\[{re.escape(prefix)}\d+\]")


def find_citations(text: str, prefix: str) -> List[str]:
    return cite_re(prefix).findall(text)


def citation_set(text: str, prefix: str) -> set:
    return {c.strip("[]") for c in find_citations(text, prefix)}


def normalize_aliases_in_text(text: str, alias_map: Dict[str, str]) -> str:
    """把镜像编号统一替换为主编号（兼容 <sup> 包裹）。"""
    for old, new in alias_map.items():
        text = text.replace(f"[{old}]", f"[{new}]")
    return text


def strip_sup_tags(text: str) -> str:
    return text.replace("<sup>", "").replace("</sup>", "")


def wrap_citations(text: str, prefix: str) -> str:
    """把裸 [ID][ID] 包成 <sup>[ID][ID]</sup>；已有 <sup> 的保持原样。"""
    protected: List[str] = []

    def protect(m):
        protected.append(m.group(0))
        return f"\x00{len(protected) - 1}\x00"

    pre = re.escape(prefix)
    text = re.sub(rf"<sup>\s*(?:\[{pre}\d+\])+\s*</sup>", protect, text)
    text = re.sub(rf"((?:\[{pre}\d+\])+)", r"<sup>\1</sup>", text)
    for i, c in enumerate(protected):
        text = text.replace(f"\x00{i}\x00", c)
    return text


# ============================================================
# 参考文献区 / 小节切分
# ============================================================
def split_reference_section(text: str) -> Tuple[str, str]:
    match = re.search(r"\n#{1,6}[ \t]*参考文献[ \t]*\n", "\n" + text)
    if not match:
        return text.strip(), ""
    start, end = match.start() - 1, match.end() - 1
    return text[:max(start, 0)].strip(), text[end:].strip()


def split_by_heading(text: str, level: int = 2) -> Dict[str, str]:
    """按 `## 标题` 切成 {标题文本: 内容}，保持出现顺序。"""
    pat = re.compile(rf"^{'#' * level}[ \t]+(.+?)[ \t]*$", re.M)
    ms = list(pat.finditer(text))
    out: Dict[str, str] = {}
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        out[m.group(1).strip()] = text[m.end():end].strip()
    return out


# ============================================================
# 字数口径
# ============================================================
def visible_length(text: str) -> int:
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"<sup>.*?</sup>", "", text)
    text = re.sub(r"\[[A-Za-z]+\d+\]", "", text)
    text = re.sub(r"[*_>`\-]", "", text)
    text = re.sub(r"\s+", "", text)
    return len(text)


def section_slice(text: str, heading_keyword: str) -> Tuple[str, int, int]:
    """切出以 ## 标题（含 keyword）开始、到下一个二级标题为止的片段。"""
    m = re.search(rf"^##[ \t]+.*{re.escape(heading_keyword)}.*$", text, re.M)
    if not m:
        return "", -1, -1
    nxt = re.search(r"^##[ \t]+\S", text[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(text)
    return text[m.start():end], m.start(), end


def length_breakdown(final_text: str) -> Dict[str, int]:
    """摘要 / 正文（剔除摘要、关键词、结论、参考文献、YAML）/ 结论 / 合计 四个口径。"""
    text = strip_frontmatter(final_text)
    main, _refs = split_reference_section(text)
    parts = {}
    spans = []
    for key, kw in (("abstract", "摘要"), ("keywords", "关键词"), ("conclusion", "结论与展望")):
        seg, s, e = section_slice(main, kw)
        parts[key] = visible_length(seg)
        if s >= 0:
            spans.append((s, e))
    body = main
    for s, e in sorted(spans, reverse=True):
        body = body[:s] + body[e:]
    # 去掉主标题行
    body = re.sub(r"^#[ \t]+.*$", "", body, flags=re.M)
    return {
        "abstract": parts["abstract"],
        "conclusion": parts["conclusion"],
        "body": visible_length(body),
        "total": visible_length(main),
    }


# ============================================================
# 句子 / 数字
# ============================================================
def split_sentences(text: str, min_len: int = 0) -> List[str]:
    parts = re.split(r"(?<=[。！？；!?;])\s*|\n+", text)
    return [p.strip() for p in parts if p and len(p.strip()) >= max(min_len, 1)]


_NUM_STRICT = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(%?)")
_NUM_LOOSE = re.compile(r"\d+(?:\.\d+)?")


def _clean_for_numbers(text: str) -> str:
    text = re.sub(r"\[[A-Za-z]+\d+\]", " ", text)
    text = text.replace("<sup>", " ").replace("</sup>", " ")
    return text


def extract_numbers(text: str) -> List[str]:
    """抽取需要核验的数字（小数 / 百分数 / 两位及以上整数 / 年份）。

    单个个位整数（如“3 个”）语言表达多变，不纳入核验，减少误报。
    返回规范化字符串（去千分位逗号、去 %）。
    """
    out: List[str] = []
    for m in _NUM_STRICT.finditer(_clean_for_numbers(text)):
        ip = m.group(1).replace(",", "")
        frac = m.group(2) or ""
        pct = m.group(3)
        if frac or pct or len(ip) >= 2:
            out.append(ip + frac)
    return out


def number_universe(text: str) -> set:
    """来源原文里的全部数字（宽松抽取，含去逗号版本），用于核验是否出现过。"""
    t = _clean_for_numbers(text).replace(",", "")
    return set(_NUM_LOOSE.findall(t))


def norm_for_match(text: str) -> str:
    """用于“原文子串”比对：去掉全部空白与常见排版符号，统一全半角引号/标点。"""
    text = unicodedata.normalize("NFKC", text)       # 全半角、连字（ﬁ→fi）统一
    text = re.sub(r"\s+", "", text)
    trans = {"“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-", "－": "-"}
    return "".join(trans.get(ch, ch) for ch in text).lower()


def char_ngrams(text: str, n: int = 6) -> set:
    text = re.sub(r"[\s，。；：、！？,.;:!?\"'“”‘’（）()\[\]<>/\\-]+", "", text)
    if len(text) < n:
        return {text} if text else set()
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def near_duplicate_pairs(sentences: List[Tuple[str, str]], threshold: float = 0.6,
                         min_len: int = 20) -> List[Tuple[str, str, float]]:
    """sentences: [(位置标签, 句子)]；返回相似度≥阈值的句对（字符 6-gram Jaccard）。"""
    items = [(loc, s, char_ngrams(strip_sup_tags(s))) for loc, s in sentences if len(s) >= min_len]
    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i][2], items[j][2]
            if not a or not b:
                continue
            inter = len(a & b)
            if not inter:
                continue
            jac = inter / len(a | b)
            if jac >= threshold:
                pairs.append((items[i][1], items[j][1], round(jac, 2)))
    return pairs


def short(text: str, n: int = 40) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[:n] + "…"


def parse_int(s: Optional[str], default: int = 0) -> int:
    try:
        return int(s)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
