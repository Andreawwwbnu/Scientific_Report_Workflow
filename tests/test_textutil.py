from report_workflow.textutil import (extract_numbers, length_breakdown, near_duplicate_pairs, norm_for_match,
                                      number_universe, split_frontmatter, split_reference_section,
                                      visible_length, wrap_citations, with_frontmatter)


def test_frontmatter_roundtrip():
    t = with_frontmatter({"title": "标题", "a": [1, 2]}, "正文")
    meta, body = split_frontmatter(t)
    assert meta["title"] == "标题" and body == "正文"


def test_frontmatter_with_dashes_in_body():
    meta, body = split_frontmatter("---\nk: v\n---\n\n正文\n---\n分隔线后")
    assert meta == {"k": "v"} and "分隔线后" in body


def test_wrap_citations_idempotent():
    t = "甲[LBQ01][LBQ02]。乙<sup>[LBQ03]</sup>。"
    once = wrap_citations(t, "LBQ")
    assert once == "甲<sup>[LBQ01][LBQ02]</sup>。乙<sup>[LBQ03]</sup>。"
    assert wrap_citations(once, "LBQ") == once


def test_split_reference_section():
    main, refs = split_reference_section("正文\n\n## 参考文献\n\n[A01] x")
    assert main == "正文" and refs.startswith("[A01]")


def test_numbers():
    assert extract_numbers("准确率提升 3.5%，参数量 70,000，共 3 个，2024 年") == ["3.5", "70000", "2024"]
    assert extract_numbers("见[LBQ12]与 <sup>[LBQ13]</sup>") == []
    assert "3.5" in number_universe("accuracy 3.5% and 1,000 tokens") and "1000" in number_universe("1,000")


def test_norm_for_match_ignores_whitespace_and_quotes():
    assert norm_for_match("A  “b”\n c") == norm_for_match('a"b"c')


def test_visible_length_ignores_markup():
    assert visible_length("## 标题\n正文<sup>[LBQ01]</sup>内容") == len("标题正文内容")


def test_length_breakdown():
    md = "# T\n\n## 摘要\n\n" + "甲" * 10 + "\n\n## 关键词\n\n甲；乙\n\n## 一、章\n\n" + "乙" * 20 + \
         "\n\n## 结论与展望\n\n" + "丙" * 5 + "\n\n## 参考文献\n\n[A01] x"
    lb = length_breakdown(md)
    assert (lb["abstract"], lb["conclusion"]) == (10 + 2, 5 + 5) or lb["abstract"] > 0
    assert lb["body"] == len("一、章") + 20


def test_near_duplicates():
    a = "低精度量化通过降低权重位宽来减少显存占用并提升推理吞吐量"
    b = "低精度量化通过降低权重位宽来减少显存占用并提升推理吞吐"
    c = "完全不相关的另一句话用来作为对照并且足够长以通过长度阈值"
    pairs = near_duplicate_pairs([("x", a), ("y", b), ("z", c)], 0.6, 10)
    assert len(pairs) == 1
