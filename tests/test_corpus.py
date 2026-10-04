from report_workflow import s1_fetch
from report_workflow.corpus import Corpus, chunk_text, is_placeholder, tokenize


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
