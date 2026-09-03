# -*- coding: utf-8 -*-
"""
research_report_workflow.common
全链路共享的配置、路径、文献清单视图、引用工具、LLM 客户端与文本工具。
六个阶段脚本只负责各自流程，不再重复定义常量。
"""
from __future__ import annotations

import os
import re
import time
import yaml
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ============================================================
# 目录名约定（全链路统一）
# ============================================================
DIR_FRAMEWORK = "01-项目框架"
DIR_RAW = "02-原始素材"
DIR_STRUCTURED = "03-结构化素材"
DIR_ANALYSIS = "04-分析产出"
DIR_DRAFT = "05-报告草稿"
DIR_FINAL = "06-终稿与参考文献"

# 阶段4/5 之间共享的草稿文件名（修复旧版两脚本文件名不一致的断链问题）
DRAFT_FILENAME = "报告草稿_完整版.md"


# ============================================================
# 配置加载
# ============================================================
def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class WorkflowConfig:
    project_yaml: Path
    project: dict
    manifest: dict
    root: Path

    # ---------- 基本属性 ----------
    @property
    def name(self) -> str:
        return self.project["project"]["name"]

    @property
    def report_title(self) -> str:
        return self.project["project"]["report_title"]

    @property
    def version(self) -> str:
        return self.project["project"].get("version", "v1.0")

    @property
    def id_prefix(self) -> str:
        return self.project["project"].get("id_prefix", "SE")

    @property
    def chapters(self) -> List[dict]:
        return self.project["chapters"]

    @property
    def llm_cfg(self) -> dict:
        return self.project["llm"]

    @property
    def fetch_cfg(self) -> dict:
        return self.project.get("fetch", {})

    @property
    def wc_cfg(self) -> dict:
        return self.project.get("word_count", {})

    @property
    def word_cfg(self) -> dict:
        return self.project.get("word", {})

    @property
    def blueprint(self) -> List[str]:
        return self.project.get("report_blueprint", [])

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
    def final_dir(self) -> Path:
        return self.dir_of(DIR_FINAL)

    def raw_chapter_dir(self, folder: str) -> Path:
        p = self.raw_root / folder
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ---------- 文献清单视图 ----------
    @property
    def all_entries(self) -> List[dict]:
        return self.manifest["literatures"]

    @property
    def alias_map(self) -> Dict[str, str]:
        """镜像编号 -> 主编号，例如 SE06 -> SE01。"""
        return {
            e["id"]: e["alias_for"]
            for e in self.all_entries
            if e.get("alias_for")
        }

    def canonical_id(self, lit_id: str) -> str:
        """沿 alias_for 链归并到主编号。"""
        alias = self.alias_map
        seen = set()
        while lit_id in alias and lit_id not in seen:
            seen.add(lit_id)
            lit_id = alias[lit_id]
        return lit_id

    @property
    def canonical_entries(self) -> List[dict]:
        """去镜像后的唯一文献（用于参考文献与计数）。"""
        result = []
        for e in self.all_entries:
            if not e.get("alias_for"):
                result.append(e)
        return result

    def entries_of_chapter(self, folder: str, canonical: bool = True) -> List[dict]:
        items = [e for e in self.all_entries if e["chapter"] == folder]
        if canonical:
            # 同一主编号在本章只保留一份（优先保留非镜像条目）
            picked: Dict[str, dict] = {}
            for e in items:
                cid = self.canonical_id(e["id"])
                if cid not in picked or e["id"] == cid:
                    picked[cid] = e
            items = list(picked.values())
        return sorted(items, key=lambda e: e["id"])

    def chapter_by_folder(self, folder: str) -> Optional[dict]:
        for ch in self.chapters:
            if ch["folder"] == folder:
                return ch
        return None

    def cite_pattern(self) -> re.Pattern:
        return re.compile(rf"\[{self.id_prefix}\d+\]")

    # ---------- 阶段产物文件名 ----------
    def structured_path(self, chapter: dict) -> Path:
        return self.structured_dir / f"{chapter['id']}-{chapter['folder']}-结构化素材.md"

    def analysis_path(self, chapter: dict) -> Path:
        return self.analysis_dir / f"{chapter['id']}-{chapter['folder']}-分析结论.md"

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


def load_config(config_path: str | Path, root_override: Optional[str] = None) -> WorkflowConfig:
    config_path = Path(config_path).expanduser().resolve()
    project = load_yaml(config_path)
    manifest_path = config_path.parent / "literature_manifest.yaml"
    manifest = load_yaml(manifest_path)

    root = root_override or os.getenv("REPORT_PROJECT_ROOT") or project["project"]["root"]
    root = Path(root).expanduser()
    if not root.is_absolute():
        # 相对路径相对于工作流根目录（config 的上两级）
        root = (config_path.parent.parent / root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return WorkflowConfig(config_path, project, manifest, root)


# ============================================================
# Markdown / Front Matter 工具
# ====================================================
def split_frontmatter(text: str) -> Tuple[dict, str]:
    """返回 (meta, body)；无 front matter 时 meta={}。"""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            try:
                meta = yaml.safe_load(parts[1].strip()) or {}
            except yaml.YAMLError:
                meta = {}
            return meta, parts[2].strip()
    return {}, text


def dump_frontmatter(meta: dict) -> str:
    return yaml.dump(meta, allow_unicode=True, sort_keys=False, default_flow_style=False).strip()


def strip_frontmatter(text: str) -> str:
    _, body = split_frontmatter(text)
    return body


def sanitize_filename(name: str, limit: int = 140) -> str:
    name = re.sub(r'[\\/:*?"<>|\[\]]', "_", name)
    name = name.replace("\n", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name[:limit].rstrip()


# ============================================================
# 引用编号工具（前缀无关）
# ============================================================
def find_citations(text: str, prefix: str) -> List[str]:
    return re.findall(rf"\[{prefix}\d+\]", text)


def citation_set(text: str, prefix: str) -> set:
    return {c.strip("[]") for c in find_citations(text, prefix)}


def normalize_aliases_in_text(text: str, alias_map: Dict[str, str]) -> str:
    """把镜像编号统一替换为主编号，同时兼容 <sup> 包裹形式。"""
    for old, new in alias_map.items():
        text = text.replace(f"<sup>[{old}]</sup>", f"<sup>[{new}]</sup>")
        text = text.replace(f"[{old}]", f"[{new}]")
    return text


def strip_sup_tags(text: str) -> str:
    """Word 转换前去除 HTML 上角标标签（上标由 python-docx 重新生成）。"""
    return text.replace("<sup>", "").replace("</sup>", "")


# ============================================================
# 参考文献区切分
# ============================================================
def split_reference_section(text: str) -> Tuple[str, str]:
    match = re.search(r"\n#{1,6}\s*参考文献\s*\n", "\n" + text)
    if match:
        # 补了一个前导换行，坐标整体偏移 1
        start = match.start() - 1
        end = match.end() - 1
        return text[:start].strip(), text[end:].strip()
    return text.strip(), ""


# ============================================================
# 字数统计（中文按字符计；可剔除指定小节，统一口径）
# ============================================================
def visible_length(text: str) -> int:
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"<sup>.*?</sup>", "", text)
    text = re.sub(r"[*_>`\-]", "", text)
    text = re.sub(r"\s+", "", text)
    return len(text)


def section_slice(text: str, heading_keyword: str) -> Tuple[str, int, int]:
    """切出以 ## 标题（含 keyword）开始、到下一个同级/更高级标题为止的片段。"""
    pattern = re.compile(rf"^##[# ]?.*{re.escape(heading_keyword)}.*$", re.MULTILINE)
    m = pattern.search(text)
    if not m:
        return "", -1, -1
    nxt = re.search(r"^##[^#].*$", text[m.end():], re.MULTILINE)
    end = m.end() + nxt.start() if nxt else len(text)
    return text[m.start():end], m.start(), end


def body_length_for_qc(final_text: str) -> Dict[str, int]:
    """
    返回三类长度：
      abstract  摘要
      body      正文（剔除摘要/关键词/参考文献/YAML）
      total     除参考文献与YAML外全部
    统一阶段4 prompt 与阶段5校验的口径。
    """
    text = strip_frontmatter(final_text)
    main, _refs = split_reference_section(text)

    abstract_txt, a0, a1 = section_slice(main, "摘要")
    keyword_txt, k0, k1 = section_slice(main, "关键词")

    body = main
    # 从后往前删，避免坐标位移
    for s, e in sorted([(a0, a1), (k0, k1)], reverse=True):
        if s >= 0:
            body = body[:s] + body[e:]
    return {
        "abstract": visible_length(abstract_txt),
        "body": visible_length(body),
        "total": visible_length(main),
    }


# ============================================================
# 证据截断：保留文首（定义）+ 文末（结论/数据）
# ============================================================
def head_tail_clip(text: str, keep_head: int, keep_tail: int) -> str:
    text = text.strip()
    if len(text) <= keep_head + keep_tail + 20:
        return text
    head = text[:keep_head]
    tail = text[-keep_tail:]
    return f"{head}\n……（中略）……\n{tail}"


# ============================================================
# LLM 客户端（惰性导入 openai；推理模型自动剔除不支持的参数）
# ============================================================
class LLMClient:
    def __init__(self, cfg: WorkflowConfig):
        self.cfg = cfg
        llm = cfg.llm_cfg
        self.api_key = os.getenv(llm.get("api_key_env", "DEEPSEEK_API_KEY"))
        base_url = os.getenv(llm.get("base_url_env", "DEEPSEEK_BASE_URL")) or llm.get("default_base_url")
        if not self.api_key:
            raise RuntimeError(
                f"未检测到环境变量 {llm.get('api_key_env')}，请复制 .env.example 为 .env 并填写。"
            )
        try:
            from openai import OpenAI  # 惰性导入：离线阶段无需安装 openai
        except ImportError as e:
            raise RuntimeError("缺少 openai 依赖，请先 pip install -r requirements.txt") from e
        self.client = OpenAI(api_key=self.api_key, base_url=base_url)
        self.max_retries = int(llm.get("max_retries", 3))

    @staticmethod
    def _is_reasoner(model: str) -> bool:
        # DeepSeek-reasoner 等推理模型不支持 temperature/top_p，强行传会 400
        return "reasoner" in model.lower() or "r1" in model.lower()

    def chat(self, model: str, system: str, user: str,
             max_tokens: int, temperature: Optional[float] = 0.1) -> str:
        kwargs = dict(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            stream=False,
        )
        if not self._is_reasoner(model) and temperature is not None:
            kwargs["temperature"] = temperature

        last_err = None
        for attempt in range(self.max_retries):
            try:
                resp = self.client.chat.completions.create(**kwargs)
                content = resp.choices[0].message.content
                if content and content.strip():
                    return content.strip()
                last_err = RuntimeError("模型返回为空")
            except Exception as e:  # noqa: BLE001
                last_err = e
                wait = min(2 ** attempt, 8)
                print(f"    ⚠️ 第{attempt + 1}次调用失败：{str(e)[:100]}；{wait}s 后重试")
                time.sleep(wait)
        raise RuntimeError(f"LLM 调用 {self.max_retries} 次均失败：{last_err}")


# ============================================================
# 小工具
# ============================================================
def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def credibility_score(level: str) -> int:
    if not level:
        return 1
    if level.startswith("高"):
        return 5
    if level.startswith("中"):
        return 2
    return 1
