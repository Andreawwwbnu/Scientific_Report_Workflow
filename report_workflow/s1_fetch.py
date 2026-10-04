# -*- coding: utf-8 -*-
"""阶段 1：文献抓取入库。

v3 相对旧版：
- 默认**不覆盖**已存在且有正文的素材（旧版每次重跑都会冲掉你手工补充的正文）；`--force` 才强制重抓；
- 支持 `local_file`：manifest 条目可直接指向本地 md/txt/pdf，不联网；
- arXiv 优先抓**全文**（arxiv.org/html → PDF），失败再退回摘要页；
- 失败条目生成占位文件，并在末尾列出“需人工补充”清单；
- 去重：精确 URL + arXiv id（同篇异源需用 alias_for 声明）。
"""
from __future__ import annotations

import io
import re
import time
from pathlib import Path
from typing import Optional, Tuple

from .config import DIR_RAW, WorkflowConfig
from .corpus import PLACEHOLDER_MARK, is_placeholder, raw_filename
from .textutil import dump_frontmatter, split_frontmatter

OK = "成功"


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _headers(cfg: WorkflowConfig) -> dict:
    return {"User-Agent": cfg.fetch_cfg.get(
        "user_agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")}


def arxiv_id(url: str) -> Optional[str]:
    m = re.search(r"arxiv\.org/(?:abs|pdf|html)/([^/?#]+)", url.lower())
    if not m:
        return None
    aid = re.sub(r"\.pdf$", "", m.group(1))
    return re.sub(r"v\d+$", "", aid)


def arxiv_pdf_url(url: str) -> Optional[str]:
    aid = arxiv_id(url)
    return f"https://arxiv.org/pdf/{aid}" if aid else None


# ============================================================
# 网络
# ============================================================
def _get(url: str, cfg: WorkflowConfig, binary: bool = False):
    import requests
    timeout = int(cfg.fetch_cfg.get("timeout", 30))
    retries = int(cfg.fetch_cfg.get("max_retries", 3))
    last: Optional[Exception] = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=_headers(cfg), timeout=timeout, allow_redirects=True)
            resp.raise_for_status()
            if binary:
                return resp.content, None
            if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text, None
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(min(2 ** attempt, 8))
    return None, str(last)


def _html_to_markdown(html: str) -> Optional[str]:
    try:
        import trafilatura
    except ImportError:
        return None
    try:
        return trafilatura.extract(html, output_format="markdown", include_links=False,
                                   include_images=False, include_tables=True)
    except Exception:  # noqa: BLE001
        return None


def _pdf_to_text(data: bytes) -> Optional[str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(p.extract_text() or "").strip() for p in reader.pages]
        return "\n\n".join(p for p in pages if p) or None
    except Exception:  # noqa: BLE001
        return None


def _cap(text: str, cfg: WorkflowConfig) -> str:
    limit = int(cfg.fetch_cfg.get("max_body_chars", 150000))
    return text if len(text) <= limit else text[:limit] + "\n\n（正文过长，已截断）"


def fetch_arxiv(url: str, cfg: WorkflowConfig) -> Tuple[Optional[str], dict, str]:
    aid = arxiv_id(url)
    abs_url = f"https://arxiv.org/abs/{aid}" if aid else url
    html, err = _get(abs_url, cfg)
    if html is None:
        return None, {}, f"arXiv 请求失败：{err}"
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        subject = soup.select_one("td.tablecell.subjects")
        authors = [a.get_text(" ", strip=True) for a in soup.select("div.authors a") if a.get_text(strip=True)]
        abstract = soup.select_one("blockquote.abstract")
        abstract_text = re.sub(r"^Abstract:\s*", "", abstract.get_text(" ", strip=True), flags=re.I) if abstract else ""
        history = soup.select_one("div.submission-history")
        history_text = ""
        if history:
            history_text = re.sub(r"\s+", " ", history.get_text(" ", strip=True))
            history_text = re.sub(r"^Submission history\s*:?\s*", "", history_text, flags=re.I)
    except Exception as e:  # noqa: BLE001
        return None, {}, f"arXiv 解析失败：{e}"

    lines = []
    if subject:
        lines.append(f"**学科领域：** {subject.get_text(' ', strip=True)}\n")
    if authors:
        lines.append(f"**作者：** {', '.join(authors)}\n")
    if history_text:
        lines.append(f"**提交信息：** {history_text}\n")
    if abstract_text:
        lines += ["## Abstract\n", abstract_text + "\n"]
    extra = {"authors": ", ".join(authors)} if authors else {}
    status = OK if abstract_text else "未找到 Abstract"

    # 全文：HTML 版 → PDF → 仅摘要
    if aid and cfg.fetch_cfg.get("arxiv_full_text", True):
        full, how = None, ""
        h, _ = _get(f"https://arxiv.org/html/{aid}", cfg)
        if h:
            md = _html_to_markdown(h)
            if md and len(md) >= 3000:
                full, how = md, "arXiv HTML 全文"
        if not full:
            pdf, _ = _get(f"https://arxiv.org/pdf/{aid}", cfg, binary=True)
            txt = _pdf_to_text(pdf) if pdf else None
            if txt and len(txt) >= 3000:
                full, how = txt, "PDF 全文"
        if full:
            lines += [f"## 全文（{how}）\n", _cap(full, cfg)]
            status = f"{OK}（{how}）"
        elif abstract_text:
            status = f"{OK}（仅摘要：未取得全文，建议手工补充或安装 pypdf）"
    body = "\n".join(lines).strip()
    return (body or None), extra, status


def fetch_general(url: str, cfg: WorkflowConfig) -> Tuple[Optional[str], str]:
    try:
        import trafilatura  # noqa: F401
    except ImportError:
        return None, "缺少 trafilatura 依赖，无法抓取普通网页"
    if url.lower().split("?")[0].endswith(".pdf"):
        data, err = _get(url, cfg, binary=True)
        txt = _pdf_to_text(data) if data else None
        return (_cap(txt, cfg), OK) if txt else (None, f"PDF 下载/解析失败：{err or '需安装 pypdf'}")
    html, err = _get(url, cfg)
    if html is None:
        return None, f"网页下载失败（可能被反爬）：{err}"
    md = _html_to_markdown(html)
    return (_cap(md, cfg), OK) if md else (None, "正文提取失败（可能为 JS 渲染页面，需手工补充）")


def fetch_local(path: Path) -> Tuple[Optional[str], str]:
    try:
        if path.suffix.lower() == ".pdf":
            txt = _pdf_to_text(path.read_bytes())
            return (txt, "成功（本地 PDF）") if txt else (None, "本地 PDF 解析失败（需 pypdf）")
        txt = path.read_text(encoding="utf-8")
        txt = split_frontmatter(txt)[1]
        return (txt, "成功（本地文件）") if txt.strip() else (None, "本地文件为空")
    except Exception as e:  # noqa: BLE001
        return None, f"本地文件读取失败：{e}"


def fetch_one(url: str, cfg: WorkflowConfig):
    if "arxiv.org" in url.lower():
        return fetch_arxiv(url, cfg)
    c, s = fetch_general(url, cfg)
    return c, {}, s


# ============================================================
# 入库
# ============================================================
def build_frontmatter(entry: dict, cfg: WorkflowConfig, extra: dict) -> dict:
    meta = {
        "来源编号": entry["id"],
        "标题": entry["title"],
        "来源链接": entry.get("url", ""),
        "发布主体": entry.get("publisher", ""),
        "发布时间": entry.get("date", ""),
        "文献类型": entry.get("lit_type", ""),
        "可信度等级": entry.get("credibility", ""),
        "来源分类": entry["chapter"],
        "核心对应章节": entry.get("section", ""),
        "标签": entry.get("tags", []),
        "专题": cfg.name,
        "抓取时间": _now(),
    }
    if entry.get("alias_for"):
        meta["镜像归并到"] = entry["alias_for"]
    if entry.get("related_urls"):
        meta["关联链接"] = entry["related_urls"]
    if entry.get("author"):
        meta["作者"] = entry["author"]
    elif extra.get("authors"):
        meta["作者"] = extra["authors"]
    pdf = arxiv_pdf_url(entry.get("url", ""))
    if pdf:
        meta["PDF链接"] = pdf
    return meta


def _raw_path(entry: dict, cfg: WorkflowConfig) -> Path:
    return cfg.raw_chapter_dir(entry["chapter"]) / raw_filename(entry)


def process_entry(entry: dict, cfg: WorkflowConfig) -> str:
    url = entry.get("url", "")
    extra: dict = {}
    if entry.get("local_file"):
        content, status = fetch_local(cfg.resolve_project_path(entry["local_file"]))
    else:
        content, extra, status = fetch_one(url, cfg)
        notes = []
        for ru in entry.get("related_urls", []) or []:
            rc, _e, rs = fetch_one(ru, cfg)
            notes.append(f"## 关联来源：{ru}（{rs}）\n\n{rc}" if rc else
                         f"## 关联来源：{ru}\n\n> ⚠️ 关联入口抓取失败（{rs}），请手工补充。")
            time.sleep(float(cfg.fetch_cfg.get("polite_delay_sec", 1.5)))
        if notes:
            content = ((content or "") + "\n\n" + "\n\n".join(notes)).strip() or None
            if content:
                status = OK

    if content:
        body = f"# {entry['id']} {entry['title']}\n\n> **抓取状态：** {status}\n\n{content}\n"
    else:
        body = (f"# {entry['id']} {entry['title']}\n\n> ⚠️ **抓取状态：** {status}\n\n"
                f"{PLACEHOLDER_MARK}，请人工补充（把正文粘贴在下方“原始链接”之后，保留顶部 YAML 不动）。\n\n"
                f"## 原始链接\n\n{url}\n")
        pdf = arxiv_pdf_url(url)
        if pdf:
            body += f"\n## PDF\n\n{pdf}\n"
    full = f"---\n{dump_frontmatter(build_frontmatter(entry, cfg, extra))}\n---\n\n{body.strip()}\n"
    path = _raw_path(entry, cfg)
    path.write_text(full, encoding="utf-8")
    print(f"  → {entry['id']} | {status} | {path.name}")
    return status


def check_duplicates(cfg: WorkflowConfig) -> list:
    url_seen, arxiv_seen, problems = {}, {}, []
    alias = cfg.alias_map
    for e in cfg.all_entries:
        u = e.get("url")
        if not u:
            continue
        if u in url_seen and not e.get("alias_for"):
            problems.append(f"URL 重复：{e['id']} 与 {url_seen[u]} -> {u}")
        url_seen.setdefault(u, e["id"])
        aid = arxiv_id(u)
        if aid:
            if aid in arxiv_seen:
                a, b = arxiv_seen[aid], e["id"]
                if alias.get(b) == a or alias.get(a) == b:
                    print(f"  ℹ️ 同篇异源（已声明镜像）：{a} / {b}（arXiv:{aid}）")
                else:
                    problems.append(f"疑似同一篇 arXiv 文献但未声明 alias_for：{a} / {b}（{aid}）")
            else:
                arxiv_seen[aid] = e["id"]
    return problems


def generate_index(cfg: WorkflowConfig) -> Path:
    lines = ["---", f"title: {cfg.report_title}·文献索引", f"专题: {cfg.name}",
             "type: literature-index", f"updated: {_now()}", "---", "",
             f"# {cfg.report_title}——文献索引", "",
             f"> 共收录 **{len(cfg.all_entries)}** 条，去镜像后唯一文献 **{len(cfg.canonical_entries)}** 条。", ""]
    for ch in cfg.chapters:
        lines.append(f"## {ch['name']}\n")
        for e in cfg.entries_of_chapter(ch["folder"], canonical=False):
            note = f"（镜像，归并到 {e['alias_for']}）" if e.get("alias_for") else ""
            rel = f"../{DIR_RAW}/{ch['folder']}/{raw_filename(e)}".replace(" ", "%20")
            lines.append(f"- [{e['id']} {e['title']}]({rel}){note}")
            lines.append(f"  - 类型：{e.get('lit_type', '')}｜对应：{e.get('section', '')}｜来源：{e.get('publisher', '')}")
        lines.append("")
    path = cfg.framework_dir / "00-文献索引.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def generate_readme(cfg: WorkflowConfig) -> Path:
    nav = "\n".join(f"- {ch['name']}" for ch in cfg.chapters)
    content = f"""---
title: {cfg.name}
type: project
updated: {_now()}
---
# {cfg.name}

## 研究框架
{nav}

## 目录说明
- `01-项目框架`：项目说明与文献索引
- `02-原始素材`：按章归档的原始素材（Markdown + YAML 元数据；可手工补充正文）
- `03-结构化素材`：阶段 2 证据抽取（每条证据带原文摘录，可人工增删）
- `04-分析产出`：阶段 3 分小节分析
- `05-报告草稿`：阶段 4 分章草稿（chapters/）与合并稿
- `06-终稿与参考文献`：终稿 Markdown、Word、质检报告
- `.workflow`：LLM 缓存与运行记录
"""
    path = cfg.framework_dir / "00-项目说明.md"
    path.write_text(content, encoding="utf-8")
    return path


def run(cfg: WorkflowConfig, force: bool = False, **_) -> dict:
    print("=" * 72)
    print(f"🚀 阶段1：文献抓取入库 —— {cfg.name}")
    print("=" * 72)
    for ch in cfg.chapters:
        cfg.raw_chapter_dir(ch["folder"])
    problems = check_duplicates(cfg)
    for p in problems:
        print("  ⚠️ " + p)

    delay = float(cfg.fetch_cfg.get("polite_delay_sec", 1.5))
    ok_ids, skip_ids, fail_ids = [], [], []
    print(f"\n📥 共 {len(cfg.all_entries)} 条（请求间隔 {delay}s；已有正文的素材默认跳过，--force 强制重抓）")
    print("-" * 72)
    for i, entry in enumerate(cfg.all_entries):
        path = _raw_path(entry, cfg)
        if path.exists() and not force:
            _meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
            if not is_placeholder(body):
                skip_ids.append(entry["id"])
                print(f"  ⏭️ {entry['id']} 已有正文，跳过")
                continue
        try:
            status = process_entry(entry, cfg)
        except Exception as e:  # noqa: BLE001
            print(f"  ❌ {entry['id']} 异常：{str(e)[:100]}")
            status = "异常"
        (ok_ids if status.startswith(OK) else fail_ids).append(entry["id"])
        if i < len(cfg.all_entries) - 1 and not entry.get("local_file"):
            time.sleep(delay)

    generate_index(cfg)
    generate_readme(cfg)

    print("\n" + "=" * 72)
    print(f"🏁 成功 {len(ok_ids)}｜跳过 {len(skip_ids)}｜需人工补充 {len(fail_ids)}")
    if fail_ids:
        print("✍️ 需人工补充正文（打开对应 md，在“## 原始链接”下方粘贴正文，保留顶部 YAML）：")
        for fid in fail_ids:
            e = cfg.entry(fid)
            print(f"   - {fid} {e['title'][:50]}  {e.get('url', '')}")
    print("=" * 72)
    return {"ok": True, "fetched": ok_ids, "skipped": skip_ids,
            "needs_manual": fail_ids, "duplicate_problems": problems}
