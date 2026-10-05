from report_workflow import s1_fetch
from report_workflow.corpus import Corpus, chunk_text, is_placeholder, raw_filename, tokenize


def test_chunk_text_keeps_content_and_size():
    text = "\n\n".join(f"第{i}段。" + "内容" * 80 for i in range(10))
    chunks = chunk_text(text, 300)
    assert len(chunks) > 3
    assert all(len(c) <= 700 for c in chunks)
    assert "".join(chunks).replace("\n", "").count("第") == 10


def test_tokenize_mixed():
    toks = tokenize("HNSW 图索引 efSearch=64")
    assert "hnsw" in toks and "图索" in toks and "索引" in toks


def test_placeholder_detection():
    assert is_placeholder("# X\n\n> ⚠️ **抓取状态：** 失败\n\n程序未能自动提取正文，请人工补充。\n")
    assert not is_placeholder("正文" * 200)


def test_search_prefers_relevant_chunk_and_keeps_head(demo_cfg):
    s1_fetch.run(demo_cfg)
    c = Corpus(demo_cfg)
    assert not c.missing
    hits = c.search("乘积量化 码本 压缩", ["DM03", "DM04"], k=3, per_source_max=2, include_head=True)
    ids = {h.id for h in hits}
    assert "DM03#c1" in ids and "DM04#c1" in ids          # 每源保底文首块
    assert any("乘积量化" in h.text for h in hits if h.source == "DM04")


def test_fetch_does_not_overwrite_manual_body(demo_cfg):
    s1_fetch.run(demo_cfg)
    e = demo_cfg.entry("DM01")
    from report_workflow.corpus import raw_filename
    path = demo_cfg.raw_chapter_dir(e["chapter"]) / raw_filename(e)
    path.write_text(path.read_text(encoding="utf-8") + "\n\n人工补充的段落MARK", encoding="utf-8")
    res = s1_fetch.run(demo_cfg)                           # 默认不覆盖
    assert "DM01" in res["skipped"] and "人工补充的段落MARK" in path.read_text(encoding="utf-8")
    s1_fetch.run(demo_cfg, force=True)                     # --force 才重抓
    assert "人工补充的段落MARK" not in path.read_text(encoding="utf-8")


def _english_doc(cfg, key_idx=9):
    """12 段无关背景 + 1 段关键结果的英文来源。"""
    e = cfg.entry("DM03")
    paras = [f"Section {i}. " + "This paragraph discusses unrelated engineering background and history. " * 6
             for i in range(12)]
    paras[key_idx] = ("Key result. Weight-only INT4 quantization with group size 128 reduces perplexity "
                      "degradation to 0.3 points on LLaMA-7B, while outlier handling needs per-channel scaling. ") * 3
    from report_workflow.textutil import with_frontmatter
    path = cfg.raw_chapter_dir(e["chapter"]) / raw_filename(e)
    path.write_text(with_frontmatter({"x": 1}, "# T\n\n" + "\n\n".join(paras)), encoding="utf-8")


def test_chinese_query_on_english_source_is_flagged_and_spreads(demo_cfg):
    """回归：中文查询词命中不了英文原文，旧实现只会取到文首几块。现在应标记 weak 并等距覆盖全文。"""
    s1_fetch.run(demo_cfg)
    _english_doc(demo_cfg)
    c = Corpus(demo_cfg)
    n = len(c.docs["DM03"].chunks)
    hits, info = c.search_with_info("低精度量化 权重量化精度损失 困惑度", ["DM03"], k=4, per_source_max=3)
    assert info["weak"] is True
    assert max(h.idx for h in hits) > 3                 # 不再只集中在文首
    assert n > 6


def test_keywords_make_english_source_retrievable(demo_cfg):
    s1_fetch.run(demo_cfg)
    _english_doc(demo_cfg)
    c = Corpus(demo_cfg)
    hits, info = c.search_with_info("低精度量化 weight-only INT4 quantization perplexity outlier", ["DM03"],
                                    k=4, per_source_max=3)
    assert info["weak"] is False
    assert any("Key result" in h.text for h in hits)


def test_expand_query_feeds_retrieval_and_failure_is_harmless(demo_cfg):
    from report_workflow import s2_structure
    from report_workflow.llm import MockLLM
    s1_fetch.run(demo_cfg)
    _english_doc(demo_cfg)
    demo_cfg.project["retrieval"]["query_expansion"] = "llm"      # demo 默认关闭，这里显式打开
    corpus = Corpus(demo_cfg)
    ch = demo_cfg.chapter_by_id("02")
    sec = ch["sections"][0]
    seen = {}

    class Expanding(MockLLM):
        def _expand_query(self, user):
            return '{"keywords": ["weight-only INT4 quantization", "perplexity", "outlier"]}'

        def _extract(self, user):
            seen["prompt"] = user
            return super()._extract(user)

    res = s2_structure.extract_section(ch, sec, demo_cfg, corpus, Expanding())
    assert res["retrieval"]["weak"] is False
    assert "INT4" in seen["prompt"]                       # 关键段落（英文）已被检索进 Prompt

    class Broken(MockLLM):
        def _expand_query(self, user):
            raise RuntimeError("boom")

    res = s2_structure.extract_section(ch, sec, demo_cfg, corpus, Broken())
    assert res["retrieval"]["weak"] is True               # 扩展失败：退回基础查询，不抛异常


def test_pdf_hyphenation_and_ligatures_do_not_break_quote_match():
    from report_workflow.corpus import clean_body
    from report_workflow.textutil import norm_for_match
    body = "# T\n\nWe study quanti-\nzation of the ﬁnal layer.\n" + "x" * 300
    cleaned = clean_body(body)
    assert "quantization" in cleaned
    assert norm_for_match("study quantization of the final layer") in norm_for_match(cleaned)
