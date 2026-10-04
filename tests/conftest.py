import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from report_workflow.config import load_config  # noqa: E402


@pytest.fixture()
def demo_cfg(tmp_path):
    """demo 专题（虚构素材 + MockLLM），输出到临时目录，互不干扰。"""
    return load_config(ROOT / "projects" / "demo", root_override=str(tmp_path / "out"), mock=True)


@pytest.fixture()
def demo_run(demo_cfg):
    from report_workflow import cli
    from report_workflow.llm import make_llm
    llm = make_llm(demo_cfg)
    results = {}
    for name in ["fetch", "structure", "analyze", "draft", "finalize", "word", "qc"]:
        results[name] = cli.run_stage(name, demo_cfg, llm, {})
    return demo_cfg, llm, results
