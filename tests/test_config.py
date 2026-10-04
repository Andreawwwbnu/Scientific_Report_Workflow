import copy
from pathlib import Path

import pytest

from report_workflow.config import load_config, validate_config

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ["demo", "low_precision", "frontier_risk", "_template"]


@pytest.mark.parametrize("name", PROJECTS)
def test_shipped_projects_validate(name, tmp_path):
    cfg = load_config(ROOT / "projects" / name, root_override=str(tmp_path), mock=True)
    errors, _ = validate_config(cfg)
    assert errors == []


def test_no_personal_paths_in_repo():
    for p in list((ROOT / "projects").rglob("*.yaml")) + [ROOT / "README.md"]:
        txt = p.read_text(encoding="utf-8")
        assert "/Users/" not in txt, p


def test_budget_sums_to_midpoint(demo_cfg):
    total = sum(demo_cfg.chapter_target_chars(rc) for rc in demo_cfg.report_chapters)
    mid = (demo_cfg.wc_cfg["body_min"] + demo_cfg.wc_cfg["body_max"]) // 2
    assert abs(total - mid) <= len(demo_cfg.report_chapters)


def test_blueprint_derived_from_report_chapters(demo_cfg):
    bp = demo_cfg.blueprint
    assert bp[0] == "## 摘要" and bp[-1] == "## 参考文献"
    assert "## 一、遴选理由" in bp and "### 1.1 技术特征与核心价值" not in bp   # no_subheadings
    assert "### 2.1 概念与检索机理" in bp


def test_validation_catches_errors(demo_cfg):
    bad = copy.deepcopy(demo_cfg.manifest)
    bad["literatures"][0]["section"] = "9.9"
    bad["literatures"][1]["id"] = "DM01"           # 重复编号
    bad["literatures"][2]["author"] = "Zhang et al."
    bad["literatures"][3]["alias_for"] = "DM99"
    demo_cfg.manifest = bad
    errors, _ = validate_config(demo_cfg)
    text = "\n".join(errors)
    assert "9.9" in text and "重复" in text and "et al" in text and "DM99" in text
