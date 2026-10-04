import json

from report_workflow import s1_fetch, s2_structure, s3_analyze
from report_workflow.corpus import Corpus
from report_workflow.evidence import parse_analysis, parse_structured
from report_workflow.llm import MockLLM


class FakeExtractLLM(MockLLM):
    """返回一批含“伪造引文 / 错数字 / 非法来源”的证据，验证代码核验。"""

    def _extract(self, user: str) -> str:
        real = json.loads(super()._extract(user))["items"][0]
        items = [
            real,
            {"claim": "伪造的事实", "quote": "这句话在原文里根本不存在，完全是模型编的", "source": real["source"], "chunk": real["chunk"]},
            {"claim": "召回率达到 77.7%", "quote": real["quote"], "source": real["source"], "chunk": real["chunk"]},
            {"claim": "来源越权", "quote": real["quote"], "source": "DM06", "chunk": "DM06#c1"},
        ]
        return json.dumps({"items": items}, ensure_ascii=False)


def test_extract_rejects_fabricated_wrong_number_and_foreign_source(demo_cfg):
    s1_fetch.run(demo_cfg)
    corpus = Corpus(demo_cfg)
    ch = demo_cfg.chapter_by_id("01")
    sec = ch["sections"][0]
    res = s2_structure.extract_section(ch, sec, demo_cfg, corpus, FakeExtractLLM())
    assert len(res["items"]) == 1                          # 只剩真实的一条
    reasons = "；".join(res["dropped"])
    assert "逐字原文" in reasons and "数字" in reasons and "不在允许名单" in reasons


def test_structured_file_roundtrip_and_quotes_are_substrings(demo_cfg):
    s1_fetch.run(demo_cfg)
    s2_structure.run(demo_cfg, MockLLM())
    corpus = Corpus(demo_cfg)
    from report_workflow.textutil import norm_for_match
    for ch in demo_cfg.chapters:
        parsed = parse_structured(demo_cfg.structured_path(ch).read_text(encoding="utf-8"))
        for items in parsed.values():
            for e in items:
                assert e.quote and norm_for_match(e.quote) in norm_for_match(corpus.text_of(e.source))


class BadCiteLLM(MockLLM):
    def _analyze(self, user: str) -> str:
        return super()._analyze(user) + "\n- 这是一条引用了非法来源的结论，需要被确定性删除[DM99]。"


def test_analyze_drops_bullets_with_illegal_citations(demo_cfg):
    s1_fetch.run(demo_cfg)
    s2_structure.run(demo_cfg, MockLLM())
    res = s3_analyze.run(demo_cfg, BadCiteLLM())
    text = "".join(demo_cfg.analysis_path(c).read_text(encoding="utf-8") for c in demo_cfg.chapters)
    assert "DM99" not in text
    assert res["success"] == 4 and res["warnings"]


def test_empty_section_is_skipped(demo_cfg):
    s1_fetch.run(demo_cfg)
    s2_structure.run(demo_cfg, MockLLM())
    ch = demo_cfg.chapter_by_id("03")
    p = demo_cfg.structured_path(ch)
    txt = p.read_text(encoding="utf-8")
    start = txt.index("## 3.1")
    p.write_text(txt[:start] + "## 3.1 典型应用场景\n- 暂无充分证据。\n", encoding="utf-8")
    res = s3_analyze.run(demo_cfg, MockLLM())
    assert res["skipped"] == 1
    assert parse_analysis(demo_cfg.analysis_path(ch).read_text(encoding="utf-8"))["3.1"] is None
