# -*- coding: utf-8 -*-
"""
阶段 1：文献抓取入库（替代旧 harness_obsidian_import.py）
- 文献清单来自 config/literature_manifest.yaml（唯一事实源）
- arXiv 自动抓取学科/作者/提交历史/摘要；普通网页用 trafilatura 抽正文
- 修复：成功/失败计数、请求重试与礼貌限速、Obsidian 双链嵌套方括号、
  同篇异源（arXiv id）重复识别
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional, Tuple

import requests

from .common import (
    DIR_FRAMEWORK, DIR_RAW, WorkflowConfig, dump_frontmatter,
    now_str, sanitize_filename, credibility_score,
)


def _headers(cfg: WorkflowConfig) -> dict:
    return {"User-Agent": cfg.fetch_cfg.get("user_agent", "Mozilla/5.0")}


def arxiv_pdf_url(url: str) -> Optional[str]:
    m = re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#]+)", url.lower())
    return f"https://arxiv.org/pdf/{m.group(1)}" if m else None


def arxiv_id(url: str) -> Optional[str]:
    m = re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#v]+)", url.lower())
    return m.group(1) if m else None


def fetch_arxiv(url: str, cfg: WorkflowConfig) -> Tuple[Optional[str], dict, str]:
    """返回 (正文, 额外元数据(authors...), 状态)。"""
    timeout = int(cfg.fetch_cfg.get("timeout", 30))
    last_err = None
    for attempt in range(int(cfg.llm_cfg.get("max_retries", 3))):
        try:
            resp = requests.get(url, headers=_headers(cfg), timeout=timeout)
            resp.raise_for_status()
            break
        except requests.RequestException as e:  # noqa: PERF203
            last_err = e
            time.sleep(min(2 ** attempt, 8))
    else:
        return None, {}, f"arXiv 请求失败：{last_err}"

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        subject = soup.select_one("td.tablecell.subjects")
        authors = [a.get_text(" ", strip=True)
                   for a in soup.select("div.authors a") if a.get_text(strip=True)]
        abstract = soup.select_one("blockquote.abstract")
        abstract_text = ""
        if abstract:
            abstract_text = abstract.get_text(" ", strip=True)
            abstract_text = re.sub(r"^Abstract:\s*", "", abstract_text, flags=re.I)
        history = soup.select_one("div.submission-history")
        history_text = ""
        if history:
            history_text = re.sub(r"\s+", " ", history.get_text(" ", strip=True))
            history_text = re.sub(r"^Submission history\s*:?\s*", "", history_text, flags=re.I)

        lines = []
        if subject:
            lines.append(f"**学科领域：** {subject.get_text(' ', strip=True)}\n")
        if authors:
            lines.append(f"**作者：** {', '.join(authors)}\n")
        if history_text:
            lines.append(f"**提交信息：** {history_text}\n")
        if abstract_text:
            lines.append("## Abstract\n")
            lines.append(abstract_text + "\n")
        extra = {"authors": ", ".join(authors)} if authors else {}
        body = "\n".join(lines).strip()
        status = "成功" if abstract_text else "未找到 Abstract"
        return (body if abstract_text else None), extra, status
    except Exception as e:  # noqa: BLE001
        return None, {}, f"arXiv 解析失败：{e}"


def _download_html(url: str, cfg: WorkflowConfig) -> Tuple[Optional[str], Optional[str]]:
    """用 requests 下载 HTML（可控超时/请求头/重试）。返回 (html, 错误信息)。"""
    timeout = int(cfg.fetch_cfg.get("timeout", 30))
    last_err = None
    for attempt in range(int(cfg.llm_cfg.get("max_retries", 3))):
        try:
            resp = requests.get(
                url, headers=_headers(cfg), timeout=timeout, allow_redirects=True
            )
            resp.raise_for_status()
            # requests 偶尔按 ISO-8859-1 误判编码，导致中文乱码
            if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text, None
        except requests.RequestException as e:  # noqa: PERF203
            last_err = e
            time.sleep(min(2 ** attempt, 8))
    return None, str(last_err)


def fetch_general(url: str, cfg: WorkflowConfig) -> Tuple[Optional[str], str]:
    # 注意：trafilatura.fetch_url 不支持 timeout/headers 关键字，
    # 因此统一用 requests 下载，再交给 trafilatura.extract 解析正文。
    try:
        import trafilatura
    except ImportError:
        return None, "缺少 trafilatura 依赖，无法抓取普通网页"
    html, err = _download_html(url, cfg)
    if html is None:
        return None, f"网页下载失败（可能被反爬）：{err}"
    try:
        markdown = trafilatura.extract(
            html, output_format="markdown",
            include_links=True, include_images=False, include_tables=True,
        )
        return (markdown, "成功") if markdown else (
            None, "正文提取失败（可能为JS渲染页面，需手工补充）")
    except Exception as e:  # noqa: BLE001
        return None, f"网页解析异常：{e}"


def build_frontmatter(entry: dict, cfg: WorkflowConfig, extra: dict) -> dict:
    meta = {
        "来源编号": entry["id"],
        "标题": entry["title"],
        "来源链接": entry["url"],
        "发布主体": entry.get("publisher", ""),
        "发布时间": entry.get("date", ""),
        "文献类型": entry.get("lit_type", ""),
        "可信度等级": entry.get("credibility", ""),
        "来源分类": entry["chapter"],
        "核心对应章节": entry.get("section", ""),
        "标签": entry.get("tags", []),
        "专题": cfg.name,
        "抓取时间": now_str(),
    }
    if entry.get("alias_for"):
        meta["镜像归并到"] = entry["alias_for"]
    if entry.get("related_urls"):
        meta["关联链接"] = entry["related_urls"]
    # 作者优先用 manifest，其次用抓取回填
    if entry.get("author"):
        meta["作者"] = entry["author"]
    elif extra.get("authors"):
        meta["作者"] = extra["authors"]
    pdf = arxiv_pdf_url(entry["url"])
    if pdf:
        meta["PDF链接"] = pdf
    return meta


def raw_filename(entry: dict) -> str:
    # 用 "SE01 - 标题.md"，避免 [SE01] 方括号在 Obsidian 双链中嵌套
    return f"{entry['id']} - {sanitize_filename(entry['title'])}.md"


def fetch_one(url: str, cfg: WorkflowConfig):
    """统一路由：arXiv 走摘要解析，其余走 requests+trafilatura。"""
    if "arxiv.org" in url.lower():
        return fetch_arxiv(url, cfg)
    c, s = fetch_general(url, cfg)
    return c, {}, s


def process_entry(entry: dict, cfg: WorkflowConfig) -> str:
    url = entry["url"]
    content, extra, status = fetch_one(url, cfg)
    # 同一成果的关联入口（如官方项目站 + arXiv 论文）一并抓取拼接
    related_notes = []
    for ru in entry.get("related_urls", []) or []:
        rc, _re, rs = fetch_one(ru, cfg)
        if rc:
            related_notes.append(f"## 关联来源：{ru}（{rs}）\n\n{rc}")
        else:
            related_notes.append(f"## 关联来源：{ru}\n\n> ⚠️ 关联入口抓取失败（{rs}），请手工补充。")
        time.sleep(float(cfg.fetch_cfg.get("polite_delay_sec", 1.5)))
    if related_notes:
        content = ((content or "") + "\n\n" + "\n\n".join(related_notes)).strip() or None
        if content:
            status = "成功"

    if content:
        body = f"# {entry['id']} {entry['title']}\n\n> **抓取状态：** {status}\n\n{content}\n"
    else:
        body = (f"# {entry['id']} {entry['title']}\n\n> ⚠️ **抓取状态：** {status}\n\n"
                f"程序未能自动提取正文，请人工补充。\n\n## 原始链接\n\n{url}\n")
        pdf = arxiv_pdf_url(url)
        if pdf:
            body += f"\n## PDF\n\n{pdf}\n"

    full = f"---\n{dump_frontmatter(build_frontmatter(entry, cfg, extra))}\n---\n\n{body.strip()}\n"
    save_dir = cfg.raw_chapter_dir(entry["chapter"])
    path = save_dir / raw_filename(entry)
    path.write_text(full, encoding="utf-8")
    print(f"  → {entry['id']} | {status} | {path.name}")
    return status


def check_duplicates(cfg: WorkflowConfig):
    """精确 URL 重复 + arXiv id 重复；已声明 alias_for 的镜像只提示不算冲突。"""
    url_seen, arxiv_seen, problems = {}, {}, []
    alias = cfg.alias_map
    for e in cfg.all_entries:
        if e["url"] in url_seen:
            problems.append(f"URL 重复：{e['id']} 与 {url_seen[e['url']]} -> {e['url']}")
        url_seen[e["url"]] = e["id"]
        aid = arxiv_id(e["url"])
        if aid:
            if aid in arxiv_seen:
                a, b = arxiv_seen[aid], e["id"]
                if alias.get(b) == a or alias.get(a) == b:
                    print(f"  ℹ️ 同篇异源（已声明镜像）：{a} / {b}（arXiv:{aid}）")
                else:
                    problems.append(f"疑似同一篇 arXiv 文献但未声明 alias_for：{a} / {b}（{aid}）")
            else:
                arxiv_seen[aid] = e["id"]
    if problems:
        print("\n⚠️ 重复/疑似重复：")
        for p in problems:
            print("   - " + p)
    else:
        print("✅ 未发现未声明的重复文献")


def generate_index(cfg: WorkflowConfig) -> Path:
    lines = [
        "---", f"title: {cfg.report_title}·文献索引",
        f"专题: {cfg.name}", "type: literature-index",
        f"updated: {now_str()}", "---", "",
        f"# {cfg.report_title}——文献索引", "",
        f"> 共收录 **{len(cfg.all_entries)}** 条，去镜像后唯一文献 "
        f"**{len(cfg.canonical_entries)}** 条。", "",
    ]
    for ch in cfg.chapters:
        lines.append(f"## {ch['name']}\n")
        for e in cfg.entries_of_chapter(ch["folder"], canonical=False):
            note = f"（镜像，归并到 {e['alias_for']}）" if e.get("alias_for") else ""
            rel = f"../{DIR_RAW}/{ch['folder']}/{raw_filename(e)}"
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
updated: {now_str()}
---
# {cfg.name}

## 研究框架
{nav}

## 目录说明
- `{DIR_FRAMEWORK}`：项目说明与文献索引
- `{DIR_RAW}`：按章归档的原始抓取素材（Markdown + YAML 元数据）
- `03-结构化素材`：阶段2 LLM 证据抽取产物
- `04-分析产出`：阶段3 分小节深度分析产物
- `05-报告草稿`：阶段4 生成的报告草稿
- `06-终稿与参考文献`：阶段5 终稿 Markdown 与阶段6 Word 文档
"""
    path = cfg.framework_dir / "00-项目说明.md"
    path.write_text(content, encoding="utf-8")
    return path


def run(cfg: WorkflowConfig) -> dict:
    print("=" * 72)
    print(f"🚀 阶段1：文献抓取入库 —— {cfg.name}")
    print("=" * 72)
    # 目录骨架
    for ch in cfg.chapters:
        cfg.raw_chapter_dir(ch["folder"])
    for d in (cfg.framework_dir, cfg.structured_dir, cfg.analysis_dir,
              cfg.draft_dir, cfg.final_dir):
        pass
    print("✅ 目录结构已就绪")

    print("\n🔍 重复检查")
    check_duplicates(cfg)

    delay = float(cfg.fetch_cfg.get("polite_delay_sec", 1.5))
    success, fail, failed_ids = 0, 0, []
    print(f"\n📥 开始抓取，共 {len(cfg.all_entries)} 条（请求间隔 {delay}s）")
    print("-" * 72)
    for i, entry in enumerate(cfg.all_entries):
        try:
            status = process_entry(entry, cfg)
            if status == "成功":
                success += 1
            else:
                fail += 1
                failed_ids.append(entry["id"])
        except Exception as e:  # noqa: BLE001
            fail += 1
            failed_ids.append(entry["id"])
            print(f"  → {entry['id']} | 处理异常：{e}")
        if i < len(cfg.all_entries) - 1:
            time.sleep(delay)

    idx = generate_index(cfg)
    readme = generate_readme(cfg)
    print("\n" + "=" * 72)
    print(f"🏁 完成：成功 {success}，失败/需人工补充 {fail}")
    if failed_ids:
        print("   需人工补充：" + ", ".join(failed_ids))
    print(f"📂 根目录：{cfg.root}")
    print(f"📑 索引：{idx}")
    print(f"📄 说明：{readme}")
    print("=" * 72)
    return {"success": success, "fail": fail, "failed_ids": failed_ids}
