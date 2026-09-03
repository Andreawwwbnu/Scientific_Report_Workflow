# -*- coding: utf-8 -*-
"""
阶段 5：报告草稿 → 正式终稿 Markdown（替代旧 finalize_report.py）
关键修复：
1) 草稿文件名与阶段4共享常量，不再断链；
2) 裸引用上角标化只作用于“正文”，参考文献区保持 [SE01] 条目形态
   （旧版会把参考文献也包进 <sup>，残留空标签并流入 Word）；
3) 标题/结构规范化以 project.yaml.report_blueprint 为基准；
4) 唯一文献数由 manifest 动态计算，不再硬编码；
5) 字数口径与阶段4一致（正文剔除摘要/关键词/参考文献）。
"""
from __future__ import annotations

import re

from .common import (
    WorkflowConfig, body_length_for_qc, citation_set,
    normalize_aliases_in_text, split_reference_section,
    split_frontmatter, today_str, now_str, dump_frontmatter,
)


def clean_marks(text: str) -> str:
    kept = [ln for ln in text.splitlines()
            if not ln.strip().startswith(("⚠️", "待补充", "【待补充"))]
    text = "\n".join(kept)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def wrap_body_citations(body: str, prefix: str) -> str:
    """正文内：保护已有 <sup>...</sup>，把剩余裸 [SE01][SE02] 包成上角标。"""
    protected = []

    def protect(m):
        token = f"__CIT_{len(protected)}__"
        protected.append(m.group(0))
        return token

    body = re.sub(r"<sup>\s*(?:\[[A-Za-z]+\d+\])+\s*</sup>", protect, body)
    body = re.sub(r"((?:\[[A-Za-z]+\d+\])+)", lambda m: f"<sup>{m.group(1)}</sup>", body)
    for i, c in enumerate(protected):
        body = body.replace(f"__CIT_{i}__", c)
    return body


def standardize_references(body: str, refs: str, cfg: WorkflowConfig) -> str:
    if not refs:
        return body
    access = today_str()
    canonical_order = [e["id"] for e in sorted(
        cfg.canonical_entries, key=lambda x: int(re.search(r"\d+", x["id"]).group()))]
    lines, seen, cur = [], set(), ""
    for raw in refs.splitlines():
        s = raw.strip()
        if not s:
            continue
        m = re.search(r"\[" + cfg.id_prefix + r"(\d+)\]", s)
        if m:
            if cur:
                lines.append(cur)
            sid = f"{cfg.id_prefix}{int(m.group(1)):02d}"
            sid = cfg.canonical_id(sid)
            if sid in seen:
                cur = ""
                continue
            seen.add(sid)
            cleaned = re.sub(r"\[[A-Za-z]+\d+\]", "", s, count=1)
            cleaned = cleaned.replace("<sup>", "").replace("</sup>", "").strip()
            cur = f"[{sid}] {cleaned}"
        elif cur:
            cur += " " + s
    if cur:
        lines.append(cur)

    # 按 manifest 主编号顺序排列
    def _ord(line):
        m = re.match(r"\[([A-Za-z]+\d+)\]", line)
        return canonical_order.index(m.group(1)) if m and m.group(1) in canonical_order else 999

    lines = [re.sub(r"\s+", " ", ln).strip() for ln in lines]
    lines.sort(key=_ord)
    out = []
    for ln in lines:
        if "http://" in ln or "https://" in ln:
            ln = re.sub(r"\[(?:访问|引用)日期[^\]]*\]", "", ln).rstrip("。；; ")
            ln += f"[引用日期 {access}]。"
        out.append(ln)
    return body + "\n\n## 参考文献\n\n" + "\n".join(out)


def normalize_headings(text: str, cfg: WorkflowConfig) -> str:
    # 摘要/关键词成行标题
    text = re.sub(r"(?m)^摘要[:：]\s*$", "## 摘要", text)
    text = re.sub(r"(?m)^摘要[:：]\s*(.+)$", r"## 摘要\n\1", text)
    text = re.sub(r"(?m)^关键词[:：]\s*$", "## 关键词", text)
    text = re.sub(r"(?m)^关键词[:：]\s*(.+)$", r"## 关键词\n\1", text)
    # 一级章标题降为二级；结论标题统一
    for bp in cfg.blueprint:
        if bp.startswith("## ") and "、" in bp:
            name = bp[3:]
            text = re.sub(rf"(?m)^#{{1,2}}\s*{re.escape(name.split('（')[0])}[^\n]*$", bp, text)
    text = re.sub(r"(?m)^#{1,2}\s*结论与展望\s*$", "## 结论与展望", text)
    text = re.sub(r"(?m)^#{1,2}\s*参考文献\s*$", "## 参考文献", text)
    return text


def add_yaml(text: str, cfg: WorkflowConfig) -> str:
    if text.lstrip().startswith("---"):
        return text
    meta = {
        "报告名称": cfg.report_title,
        "版本": cfg.version,
        "发布日期": today_str(),
        "文献库唯一文献数量": f"{len(cfg.canonical_entries)}篇",
        "主题分类": cfg.project["project"].get("theme", ""),
        "适用对象": cfg.project["project"].get("audience", ""),
        "生成时间": now_str(),
    }
    return f"---\n{dump_frontmatter(meta)}\n---\n\n{text}"


def _reference_ids(refs: str, cfg: WorkflowConfig) -> list:
    ids = []
    for m in re.findall(rf"\[{cfg.id_prefix}(\d+)\]", refs):
        sid = cfg.canonical_id(f"{cfg.id_prefix}{int(m):02d}")
        if sid not in ids:
            ids.append(sid)
    return sorted(ids, key=lambda x: int(re.search(r"\d+", x).group()))


def validate(text: str, cfg: WorkflowConfig):
    errors, infos = [], []
    for bp in cfg.blueprint:
        if bp not in text:
            errors.append(f"缺少章节：{bp}")
    body, refs = split_reference_section(text)
    ref_ids = _reference_ids(refs, cfg)
    if not ref_ids:
        errors.append("未识别到参考文献条目")
    if "et al." in refs:
        errors.append("参考文献存在 'et al.'")
    expected = len(cfg.canonical_entries)
    if ref_ids and len(ref_ids) != expected:
        errors.append(f"参考文献唯一数 {len(ref_ids)}，manifest 主文献为 {expected}")
    body_ids = citation_set(body, cfg.id_prefix)
    missing_ref = body_ids - set(ref_ids)
    if missing_ref:
        errors.append("正文引用但参考文献缺失：" + ", ".join(sorted(missing_ref)))
    unused = set(ref_ids) - body_ids
    if unused:
        infos.append("参考文献列出但正文未引用：" + ", ".join(sorted(unused)))
    for lvl in re.findall(r"^#{4,}\s+", text, flags=re.M):
        errors.append("存在超过三级的标题")
        break
    return errors, infos, ref_ids


def detect_duplicate_sentences(text: str, min_len: int = 15) -> list:
    """检测正文中的整句重复（只能抓逐字重复，换措辞复述需人工判断）。"""
    body, _ = split_reference_section(text)
    sents = [s.strip() for s in re.split(r"(?<=[。！？；])", body)]
    seen, dups = {}, []
    for s in sents:
        if len(s) < min_len:
            continue
        seen[s] = seen.get(s, 0) + 1
        if seen[s] == 2:
            dups.append(s)
    return dups


def run(cfg: WorkflowConfig) -> dict:
    print("=" * 72)
    print("🚀 阶段5：生成正式终稿")
    print("=" * 72)
    if not cfg.draft_path.exists():
        print(f"❌ 找不到草稿：{cfg.draft_path}（请先运行阶段4）")
        return {"ok": False}
    text = cfg.draft_path.read_text(encoding="utf-8")
    text = split_frontmatter(text)[1] if text.startswith("---") else text
    text = clean_marks(text)
    text = normalize_aliases_in_text(text, cfg.alias_map)
    text = normalize_headings(text, cfg)

    # 关键：先切分参考文献，只对正文做上角标包裹
    body, refs = split_reference_section(text)
    body = wrap_body_citations(body, cfg.id_prefix)
    text = standardize_references(body, refs, cfg)
    text = add_yaml(text, cfg)

    cfg.final_dir.mkdir(parents=True, exist_ok=True)
    cfg.final_md_path.write_text(text, encoding="utf-8")

    errors, infos, ref_ids = validate(text, cfg)
    dup = detect_duplicate_sentences(text)
    if dup:
        preview = " ｜ ".join(d[:40] + "…" if len(d) > 40 else d for d in dup[:3])
        infos.append(f"检测到 {len(dup)} 处整句重复，建议人工精简：{preview}")
    lengths = body_length_for_qc(text)
    wc = cfg.wc_cfg
    print(f"💾 终稿：{cfg.final_md_path}")
    print(f"📚 唯一参考文献：{len(ref_ids)} 篇：{', '.join(ref_ids)}")
    print(f"📄 摘要 {lengths['abstract']} 字｜正文 {lengths['body']} 字（目标 "
          f"{wc.get('body_min')}-{wc.get('body_max')}）")
    for i in infos:
        print("ℹ️ " + i)
    if errors:
        print("❌ 质检问题：")
        for e in errors:
            print("   - " + e)
    else:
        print("✅ 终稿质检全部通过")
    print("=" * 72)
    return {"ok": not errors, "errors": errors, "infos": infos,
            "lengths": lengths, "path": str(cfg.final_md_path)}
