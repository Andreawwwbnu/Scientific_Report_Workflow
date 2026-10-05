# -*- coding: utf-8 -*-
"""配置加载、路径约定、报告结构推导、篇幅预算与配置校验。

一个专题 = 一个目录：
    projects/<slug>/project.yaml
    projects/<slug>/literature_manifest.yaml   （文献清单：唯一事实源）
    projects/<slug>/sources/                   （可选：local_file 指向的本地正文）
    projects/<slug>/prompts/                   （可选：覆盖默认 Prompt）
    projects/<slug>/output/                    （默认输出根目录，已被 .gitignore 忽略）
"""
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

# ============================================================
# 目录名约定（全链路统一）
# ============================================================
DIR_FRAMEWORK = "01-项目框架"
DIR_RAW = "02-原始素材"
DIR_STRUCTURED = "03-结构化素材"
DIR_ANALYSIS = "04-分析产出"
DIR_DRAFT = "05-报告草稿"
DIR_FINAL = "06-终稿与参考文献"
DIR_META = ".workflow"          # 缓存、运行记录

DRAFT_FILENAME = "报告草稿_完整版.md"
SKIP_MARK = "无充分证据"
_RUN_STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")        # 阶段 3 对无证据小节写入的标记关键词


def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class ReportChapter:
    """成稿中的一章。取材自一个或多个“分析章”（阶段 2/3 的章）。"""
    index: int
    id: str
    heading: str                       # 不含 “## ”
    source_chapters: List[str]
    sections: List[str]                # 不含 “### ”，如 “2.1 概念定义”
    weight: float = 1.0
    write_guide: str = ""
    no_subheadings: bool = False
    synthesis: bool = False            # True：最后写，可参考其他章成稿

    @property
    def headings(self) -> List[str]:
        out = [f"## {self.heading}"]
        if not self.no_subheadings:
            out += [f"### {s}" for s in self.sections]
        return out


@dataclass
class WorkflowConfig:
    project_yaml: Path
    project: dict
    manifest: dict
    root: Path
    mock: bool = False
    use_cache: bool = True

    # ---------- 基本属性 ----------
    @property
    def project_dir(self) -> Path:
        return self.project_yaml.parent

    @property
    def meta(self) -> dict:
        return self.project["project"]

    @property
    def name(self) -> str:
        return self.meta["name"]

    @property
    def slug(self) -> str:
        return self.meta.get("slug") or self.project_dir.name

    @property
    def report_title(self) -> str:
        return self.meta["report_title"]

    @property
    def version(self) -> str:
        return str(self.meta.get("version", "v1.0"))

    @property
    def id_prefix(self) -> str:
        return self.meta.get("id_prefix", "SE")

    @property
    def chapters(self) -> List[dict]:
        """分析章（阶段 2/3 的单位）。"""
        return self.project["chapters"]

    @property
    def llm_cfg(self) -> dict:
        return self.project.get("llm", {})

    @property
    def fetch_cfg(self) -> dict:
        return self.project.get("fetch", {})

    @property
    def retrieval_cfg(self) -> dict:
        d = {"chunk_chars": 700, "top_k": 8, "per_source_max": 3, "always_include_head": True,
             "max_items_per_section": 8, "query_expansion": "llm"}
        d.update(self.project.get("retrieval", {}) or {})
        return d

    @property
    def draft_cfg(self) -> dict:
        d = {
            "persona": "专业技术情报分析师与报告撰稿人",
            "style_rules": [],
            "max_paragraph_chars": 150,
            "chapter_tolerance": 0.2,
            "max_rewrites": 2,
        }
        d.update(self.project.get("draft", {}) or {})
        return d

    @property
    def wc_cfg(self) -> dict:
        d = {"body_min": 2800, "body_max": 3200, "abstract_min": 250, "abstract_max": 300,
             "conclusion_min": 150, "conclusion_max": 200, "keywords_min": 5, "keywords_max": 7}
        d.update(self.project.get("word_count", {}) or {})
        return d

    @property
    def word_cfg(self) -> dict:
        return self.project.get("word", {}) or {}

    @property
    def ref_cfg(self) -> dict:
        d = {"only_cited": False, "numbering": "manifest", "max_authors": 0,
             "access_date": "today"}
        d.update(self.project.get("references", {}) or {})
        return d

    @property
    def qc_cfg(self) -> dict:
        d = {"llm_check": False, "llm_check_max_sentences": 60}
        d.update(self.project.get("qc", {}) or {})
        return d

    # ---------- 报告结构 ----------
    def chapter_by_id(self, cid: str) -> Optional[dict]:
        return next((c for c in self.chapters if c["id"] == cid), None)

    def chapter_by_folder(self, folder: str) -> Optional[dict]:
        return next((c for c in self.chapters if c["folder"] == folder), None)

    @property
    def report_chapters(self) -> List[ReportChapter]:
        """成稿章节。未配置 report.chapters 时按分析章 1:1 推导。"""
        rc_cfg = (self.project.get("report") or {}).get("chapters")
        result: List[ReportChapter] = []
        if not rc_cfg:
            for i, ch in enumerate(self.chapters):
                result.append(ReportChapter(
                    index=i, id=ch["id"], heading=ch["name"], source_chapters=[ch["id"]],
                    sections=[f"{s['id']} {s['name']}" for s in ch["sections"]]))
            return result
        for i, c in enumerate(rc_cfg):
            src = c.get("source_chapters") or [c["id"]]
            if isinstance(src, str):
                src = [src]
            sections = c.get("sections")
            if sections is None:
                base = self.chapter_by_id(c["id"]) or {"sections": []}
                sections = [f"{s['id']} {s['name']}" for s in base["sections"]]
            result.append(ReportChapter(
                index=i, id=str(c["id"]), heading=c["heading"], source_chapters=[str(x) for x in src],
                sections=list(sections), weight=float(c.get("weight", 1.0)),
                write_guide=(c.get("write_guide") or "").strip(),
                no_subheadings=bool(c.get("no_subheadings", False)),
                synthesis=bool(c.get("synthesis", False))))
        return result

    @property
    def blueprint(self) -> List[str]:
        """完整成稿标题序列（含参考文献），阶段 4/5 校验共用。"""
        out = ["## 摘要", "## 关键词"]
        for rc in self.report_chapters:
            out += rc.headings
        out += ["## 结论与展望", "## 参考文献"]
        return out

    def chapter_target_chars(self, rc: ReportChapter) -> int:
        wc = self.wc_cfg
        mid = (wc["body_min"] + wc["body_max"]) / 2
        total_w = sum(c.weight for c in self.report_chapters) or 1.0
        return int(round(mid * rc.weight / total_w))

    def chapter_char_range(self, rc: ReportChapter) -> Tuple[int, int]:
        t = self.chapter_target_chars(rc)
        tol = float(self.draft_cfg["chapter_tolerance"])
        return int(t * (1 - tol)), int(t * (1 + tol))

    # ---------- 路径 ----------
    def dir_of(self, name: str) -> Path:
        p = self.root / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def framework_dir(self) -> Path:
        return self.dir_of(DIR_FRAMEWORK)

    @property
    def raw_root(self) -> Path:
        return self.dir_of(DIR_RAW)

    @property
    def structured_dir(self) -> Path:
        return self.dir_of(DIR_STRUCTURED)

    @property
    def analysis_dir(self) -> Path:
        return self.dir_of(DIR_ANALYSIS)

    @property
    def draft_dir(self) -> Path:
        return self.dir_of(DIR_DRAFT)

    @property
    def draft_chapters_dir(self) -> Path:
        p = self.draft_dir / "chapters"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def final_dir(self) -> Path:
        return self.dir_of(DIR_FINAL)

    @property
    def meta_dir(self) -> Path:
        return self.dir_of(DIR_META)

    @property
    def cache_dir(self) -> Path:
        p = self.meta_dir / "cache"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def runs_dir(self) -> Path:
        p = self.meta_dir / "runs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def raw_chapter_dir(self, folder: str) -> Path:
        p = self.raw_root / folder
        p.mkdir(parents=True, exist_ok=True)
        return p

    def structured_path(self, chapter: dict) -> Path:
        return self.structured_dir / f"{chapter['id']}-{chapter['folder']}-结构化素材.md"

    def analysis_path(self, chapter: dict) -> Path:
        return self.analysis_dir / f"{chapter['id']}-{chapter['folder']}-分析结论.md"

    def draft_chapter_path(self, rc: ReportChapter) -> Path:
        return self.draft_chapters_dir / f"{rc.id}.md"

    @property
    def draft_frame_path(self) -> Path:
        return self.draft_chapters_dir / "frame.md"

    @property
    def draft_path(self) -> Path:
        return self.draft_dir / DRAFT_FILENAME

    @property
    def final_basename(self) -> str:
        return f"{self.report_title}_{self.version}"

    @property
    def final_md_path(self) -> Path:
        return self.final_dir / f"{self.final_basename}.md"

    @property
    def final_docx_path(self) -> Path:
        return self.final_dir / f"{self.final_basename}.docx"

    @property
    def qc_report_path(self) -> Path:
        return self.final_dir / "质检报告.md"

    @property
    def review_report_path(self) -> Path:
        return self.final_dir / "审稿意见.md"

    def write_text_safe(self, path: Path, text: str) -> None:
        """写文件；若已存在且内容不同，先把旧版备份到 .workflow/backup/<时间戳>/，避免冲掉你的手工修改。"""
        path = Path(path)
        if path.exists():
            try:
                old = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                old = None
            if old is not None and old != text:
                try:
                    rel = path.resolve().relative_to(self.root.resolve())
                except ValueError:
                    rel = Path(path.name)
                dest = self.meta_dir / "backup" / _RUN_STAMP / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)
        path.write_text(text, encoding="utf-8")

    def resolve_project_path(self, p: str) -> Path:
        path = Path(p).expanduser()
        return path if path.is_absolute() else (self.project_dir / path)

    # ---------- 文献清单视图 ----------
    @property
    def all_entries(self) -> List[dict]:
        return self.manifest["literatures"]

    def entry(self, lit_id: str) -> Optional[dict]:
        return next((e for e in self.all_entries if e["id"] == lit_id), None)

    @property
    def alias_map(self) -> Dict[str, str]:
        return {e["id"]: e["alias_for"] for e in self.all_entries if e.get("alias_for")}

    def canonical_id(self, lit_id: str) -> str:
        alias, seen = self.alias_map, set()
        while lit_id in alias and lit_id not in seen:
            seen.add(lit_id)
            lit_id = alias[lit_id]
        return lit_id

    @property
    def canonical_entries(self) -> List[dict]:
        return [e for e in self.all_entries if not e.get("alias_for")]

    def mirrors_of(self, canonical: str) -> List[dict]:
        return [e for e in self.all_entries
                if e.get("alias_for") and self.canonical_id(e["id"]) == canonical]

    def entries_of_chapter(self, folder: str, canonical: bool = True) -> List[dict]:
        items = [e for e in self.all_entries if e["chapter"] == folder]
        if canonical:
            picked: Dict[str, dict] = {}
            for e in items:
                cid = self.canonical_id(e["id"])
                if cid not in picked or e["id"] == cid:
                    picked[cid] = e
            items = list(picked.values())
        return sorted(items, key=lambda e: e["id"])

    def id_num(self, lit_id: str) -> int:
        m = re.search(r"(\d+)$", lit_id)
        return int(m.group(1)) if m else 0

    # ---------- Prompt ----------
    @property
    def prompts_override_dir(self) -> Optional[Path]:
        p = self.project_dir / "prompts"
        return p if p.is_dir() else None


def load_config(config_path: str | Path, root_override: Optional[str] = None,
                mock: bool = False, use_cache: bool = True) -> WorkflowConfig:
    config_path = Path(config_path).expanduser().resolve()
    if config_path.is_dir():
        config_path = config_path / "project.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"找不到配置：{config_path}")
    project = load_yaml(config_path)
    manifest_name = (project.get("project") or {}).get("manifest", "literature_manifest.yaml")
    manifest_path = config_path.parent / manifest_name
    if not manifest_path.exists():
        raise FileNotFoundError(f"找不到文献清单：{manifest_path}")
    manifest = load_yaml(manifest_path)

    # --root / 环境变量里的相对路径相对“当前目录”；project.yaml 里的 root 相对专题目录
    explicit = root_override or os.getenv("REPORT_PROJECT_ROOT")
    if explicit:
        root = Path(explicit).expanduser().resolve()
    else:
        root = Path((project.get("project") or {}).get("root") or "output").expanduser()
        if not root.is_absolute():
            root = (config_path.parent / root).resolve()
    return WorkflowConfig(config_path, project, manifest, root, mock=mock, use_cache=use_cache)


# ============================================================
# 配置校验（stage 运行前统一执行；`report-wf validate` 也调用）
# ============================================================
def validate_config(cfg: WorkflowConfig) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warns: List[str] = []
    p = cfg.project

    for k in ("name", "report_title", "id_prefix"):
        if not cfg.meta.get(k):
            errors.append(f"project.{k} 缺失")
    if not p.get("chapters"):
        errors.append("chapters 为空")
        return errors, warns
    if "report_blueprint" in p:
        warns.append("检测到旧版 report_blueprint：v3 起已改为 report.chapters，该字段被忽略")

    # manifest
    seen_ids, seen_urls = set(), {}
    prefix = cfg.id_prefix
    folders = {c["folder"] for c in cfg.chapters}
    sec_ids = {s["id"] for c in cfg.chapters for s in c["sections"]}
    for e in cfg.all_entries:
        for k in ("id", "title", "chapter", "section"):
            if not e.get(k):
                errors.append(f"文献 {e.get('id', '?')} 缺少必填字段 {k}")
        if not e.get("url") and not e.get("local_file"):
            errors.append(f"文献 {e.get('id', '?')} 必须提供 url 或 local_file")
        if e.get("id") in seen_ids:
            errors.append(f"文献编号重复：{e['id']}")
        seen_ids.add(e.get("id"))
        if e.get("id") and not re.fullmatch(rf"{re.escape(prefix)}\d+", e["id"]):
            errors.append(f"文献编号 {e['id']} 与 id_prefix={prefix} 不一致")
        if e.get("chapter") and e["chapter"] not in folders:
            errors.append(f"文献 {e['id']} 的 chapter={e['chapter']} 不在 chapters.folder 中")
        if e.get("section") and e["section"] not in sec_ids:
            errors.append(f"文献 {e['id']} 的 section={e['section']} 不在 chapters.sections 中")
        if e.get("url"):
            if e["url"] in seen_urls and not e.get("alias_for"):
                warns.append(f"URL 重复：{e['id']} 与 {seen_urls[e['url']]}")
            seen_urls.setdefault(e["url"], e["id"])
        if e.get("local_file") and not cfg.resolve_project_path(e["local_file"]).exists():
            errors.append(f"文献 {e['id']} 的 local_file 不存在：{e['local_file']}")
        au = (e.get("author") or "")
        if "et al" in au.lower():
            errors.append(f"文献 {e['id']} 作者含 et al.，请补全或改用 publisher")
    for e in cfg.all_entries:
        a = e.get("alias_for")
        if a and a not in seen_ids:
            errors.append(f"文献 {e['id']} alias_for 指向不存在的 {a}")
    # alias 环
    for e in cfg.all_entries:
        if e.get("alias_for"):
            cur, hops = e["id"], 0
            while cur in cfg.alias_map and hops < 20:
                cur = cfg.alias_map[cur]
                hops += 1
            if hops >= 20:
                errors.append(f"alias_for 存在环：{e['id']}")

    # chapters / sections
    ids_in_rules = set()
    chap_ids = [c["id"] for c in cfg.chapters]
    if len(chap_ids) != len(set(chap_ids)):
        errors.append("chapters.id 重复")
    for c in cfg.chapters:
        for k in ("id", "name", "folder", "sections"):
            if k not in c:
                errors.append(f"chapter {c.get('id', '?')} 缺少 {k}")
        for s in c.get("sections", []):
            for k in ("id", "name", "extract_rule", "analyze_task"):
                if not s.get(k):
                    errors.append(f"section {s.get('id', '?')} 缺少 {k}")
            if "keywords" in s and not isinstance(s["keywords"], list):
                errors.append(f"section {s['id']} 的 keywords 必须是列表")
            ids_in_rules |= set(re.findall(rf"{re.escape(prefix)}\d+", s.get("extract_rule", "")))
            if not any(e["section"] == s["id"] for e in cfg.all_entries):
                warns.append(f"小节 {s['id']} 没有任何文献，将被判定为“无充分证据”")
    for rid in sorted(ids_in_rules - seen_ids):
        errors.append(f"extract_rule 中引用了 manifest 里不存在的编号 {rid}")

    # report chapters
    rcs = cfg.report_chapters
    for rc in rcs:
        for sc in rc.source_chapters:
            if not cfg.chapter_by_id(sc):
                errors.append(f"report 章 {rc.id} 的 source_chapters={sc} 不存在")
        if rc.weight <= 0:
            errors.append(f"report 章 {rc.id} 的 weight 必须 > 0")
    if not any(rc.synthesis for rc in rcs) and len(rcs) > 1:
        pass  # 允许
    wc = cfg.wc_cfg
    if wc["body_min"] > wc["body_max"]:
        errors.append("word_count.body_min > body_max")
    if wc["abstract_min"] > wc["abstract_max"]:
        errors.append("word_count.abstract_min > abstract_max")

    # LLM
    llm = cfg.llm_cfg
    if not cfg.mock and llm.get("provider", "openai_compatible") != "mock":
        for k in ("structure_model", "analyze_model", "draft_model"):
            if not llm.get(k):
                errors.append(f"llm.{k} 缺失")
    if cfg.ref_cfg["numbering"] not in ("manifest", "first_cited"):
        errors.append("references.numbering 只能是 manifest 或 first_cited")
    return errors, warns
