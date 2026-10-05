import re

from docx import Document

from report_workflow import cli, s4_draft, s5_finalize
from report_workflow.llm import MockLLM
from report_workflow.textutil import citation_set, strip_frontmatter


def test_full_pipeline_offline(demo_run):
    cfg, llm, results = demo_run
    assert all(r.get("ok", True) for r in results.values()), results
    assert cfg.final_md_path.exists() and cfg.final_docx_path.exists() and cfg.qc_report_path.exists()
    assert llm.usage.total()["calls"] > 0


def test_final_references_come_from_manifest_and_citations_valid(demo_run):
    cfg, _, _ = demo_run
    text = cfg.final_md_path.read_text(encoding="utf-8")
    refs = text.split("## 参考文献")[1]
    assert len(re.findall(r"^\[DM\d+\]", refs, re.M)) == len(cfg.canonical_entries)
    body = strip_frontmatter(text).split("## 参考文献")[0]
    assert citation_set(body, "DM") <= {e["id"] for e in cfg.canonical_entries}
    assert "[引用日期" in refs


def test_docx_has_real_heading_styles_and_numbered_citations(demo_run):
    cfg, _, _ = demo_run
    doc = Document(str(cfg.final_docx_path))
    styles = [p.style.name for p in doc.paragraphs]
    assert "Title" in styles and "Heading 1" in styles and "Heading 2" in styles
    full = "\n".join(p.text for p in doc.paragraphs)
    assert "[DM01]" not in full.split("参考文献")[0]            # 正文已映射为 [n]
    assert re.search(r"\[1\]", full)
    footer_xml = doc.sections[0].footer._element.xml
    assert "PAGE" in footer_xml


def test_incremental_rerun_uses_cache(demo_cfg):
    """真实客户端的缓存键稳定：同样输入第二次命中缓存（这里直接测键与读写）。"""
    from report_workflow.llm import OpenAICompatLLM
    k1 = OpenAICompatLLM._key(object.__new__(OpenAICompatLLM), "m", "s", "u", 100, 0.1)
    k2 = OpenAICompatLLM._key(object.__new__(OpenAICompatLLM), "m", "s", "u", 100, 0.1)
    k3 = OpenAICompatLLM._key(object.__new__(OpenAICompatLLM), "m", "s", "u2", 100, 0.1)
    assert k1 == k2 != k3


class IllegalCiteDraftLLM(MockLLM):
    def _draft_chapter(self, user: str) -> str:
        return super()._draft_chapter(user).replace("<sup>[DM01]</sup>", "<sup>[DM01][DM77]</sup>")


def test_draft_strips_illegal_citations(demo_cfg):
    from report_workflow import s1_fetch, s2_structure, s3_analyze
    s1_fetch.run(demo_cfg)
    s2_structure.run(demo_cfg, MockLLM())
    s3_analyze.run(demo_cfg, MockLLM())
    res = s4_draft.run(demo_cfg, IllegalCiteDraftLLM())
    assert "DM77" not in demo_cfg.draft_path.read_text(encoding="utf-8")
    assert res["ok"] is True


class RenamedHeadingLLM(MockLLM):
    """模型把标题改成了近义说法：数量/层级没变 → 应被确定性还原，而不是让整条流水线失败。"""

    def _draft_chapter(self, user: str) -> str:
        return super()._draft_chapter(user).replace("## 二、技术内涵", "## 二、被改过的标题")


class MissingHeadingLLM(MockLLM):
    """模型漏写了一个小节标题：无法安全还原 → 必须被门禁拦下。"""

    def _draft_chapter(self, user: str) -> str:
        return super()._draft_chapter(user).replace("### 2.2 性能指标与边界\n", "")


def _prep(cfg):
    from report_workflow import s1_fetch, s2_structure, s3_analyze
    s1_fetch.run(cfg)
    s2_structure.run(cfg, MockLLM())
    s3_analyze.run(cfg, MockLLM())


def test_draft_autofixes_renamed_headings(demo_cfg):
    _prep(demo_cfg)
    res = s4_draft.run(demo_cfg, RenamedHeadingLLM())
    assert res["ok"] is True
    assert "## 二、技术内涵" in demo_cfg.draft_path.read_text(encoding="utf-8")


def test_draft_gate_fails_when_heading_missing(demo_cfg):
    _prep(demo_cfg)
    res = s4_draft.run(demo_cfg, MissingHeadingLLM())
    assert res["ok"] is False and any("标题" in h for h in res["hard"])


def test_overwrite_backs_up_manual_edits(demo_run):
    cfg, llm, _ = demo_run
    ch = cfg.chapter_by_id("01")
    p = cfg.structured_path(ch)
    p.write_text(p.read_text(encoding="utf-8") + "\n手工新增的证据MARK", encoding="utf-8")
    from report_workflow import s2_structure
    s2_structure.run(cfg, llm)                                   # 重跑阶段2会覆盖该文件
    assert "手工新增的证据MARK" not in p.read_text(encoding="utf-8")
    backups = list((cfg.meta_dir / "backup").rglob(p.name))
    assert backups and "手工新增的证据MARK" in backups[0].read_text(encoding="utf-8")


def test_only_chapter_regenerates_selected(demo_run):
    cfg, llm, _ = demo_run
    p3 = cfg.draft_chapters_dir / "03.md"
    p3.write_text(p3.read_text(encoding="utf-8") + "\n手工修改MARK", encoding="utf-8")
    s4_draft.run(cfg, llm, only_chapters={"02"})
    assert "手工修改MARK" in p3.read_text(encoding="utf-8")       # 03 未被重写
    assert "手工修改MARK" in cfg.draft_path.read_text(encoding="utf-8")


def test_finalize_rebuilds_refs_even_if_model_omitted_them(demo_run):
    cfg, _, _ = demo_run
    raw = cfg.draft_path.read_text(encoding="utf-8")
    cfg.draft_path.write_text(raw.split("## 参考文献")[0], encoding="utf-8")   # 模拟模型漏写
    res = s5_finalize.run(cfg)
    assert "## 参考文献" in cfg.final_md_path.read_text(encoding="utf-8") and res["ok"]


def test_finalize_detects_missing_heading_and_gate(demo_run):
    cfg, _, _ = demo_run
    raw = cfg.draft_path.read_text(encoding="utf-8").replace("## 三、应用与趋势", "")
    cfg.draft_path.write_text(raw, encoding="utf-8")
    res = s5_finalize.run(cfg)
    assert res["ok"] is False and any("缺少标题" in e for e in res["errors"])


def test_first_cited_numbering_and_only_cited(demo_run):
    cfg, _, _ = demo_run
    cfg.project["references"] = {"only_cited": True, "numbering": "first_cited"}
    s5_finalize.run(cfg)
    text = cfg.final_md_path.read_text(encoding="utf-8")
    refs = re.findall(r"^\[(DM\d+)\]", text.split("## 参考文献")[1], re.M)
    body = text.split("## 参考文献")[0]
    first = []
    for c in re.findall(r"\[(DM\d+)\]", body):
        if c not in first:
            first.append(c)
    assert refs == first


def test_qc_flags_numbers_missing_from_source(demo_run):
    cfg, llm, _ = demo_run
    from report_workflow import s7_qc
    t = cfg.final_md_path.read_text(encoding="utf-8").replace(
        "材料指出：评估近似检索", "召回率提升了 88.8%<sup>[DM05]</sup>。材料指出：评估近似检索", 1)
    cfg.final_md_path.write_text(t, encoding="utf-8")
    res = s7_qc.run_qc(cfg, llm)
    assert res["unsupported_numbers"] >= 1
    assert "88.8" in cfg.qc_report_path.read_text(encoding="utf-8")


def test_cli_validate_and_status(capsys, tmp_path):
    assert cli.main(["validate", "demo"]) == 0
    assert cli.main(["validate", "no_such_project"]) == 2


def test_cli_run_gate_stops_and_returns_nonzero(tmp_path):
    # 不先抓取直接跑阶段 2：没有素材 → 所有章节无证据 → 门禁失败
    code = cli.main(["run", "demo", "--stages", "2,3", "--mock", "--root", str(tmp_path / "o")])
    assert code == 1


def test_cli_parse_stages():
    assert cli.parse_stages("2-4") == ["structure", "analyze", "draft"]
    assert cli.parse_stages("all")[-1] == "qc"
    assert cli.parse_stages("fetch,3") == ["fetch", "analyze"]


def test_word_toc_option(demo_run):
    from report_workflow import s6_to_word
    cfg, _, _ = demo_run
    cfg.project["word"]["toc"] = True
    out = cfg.final_dir / "toc.docx"
    s6_to_word.run(cfg, output_path=out)
    doc = Document(str(out))
    assert "TOC" in doc.element.xml and "updateFields" in doc.settings.element.xml
