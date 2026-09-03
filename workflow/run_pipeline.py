# -*- coding: utf-8 -*-
"""
一键编排器。

用法：
  # 全流程（阶段1需要联网，阶段2-4需要 LLM API Key）
  python -m workflow.run_pipeline --config config/project.yaml --stage all

  # 只跑某一步（fetch/structure/analyze/draft/finalize/word）
  python -m workflow.run_pipeline --config config/project.yaml --stage finalize

  # 连续跑若干步
  python -m workflow.run_pipeline --config config/project.yaml --stage draft,finalize,word

  # 临时覆盖输出根目录
  python -m workflow.run_pipeline --config config/project.yaml --root /path/to/project --stage word

复用新专题：
  1) 复制 config/ 目录；修改 project.yaml（主题、章节、分析任务、蓝图）
  2) 修改 literature_manifest.yaml（文献清单）
  3) 按顺序执行六个阶段即可，代码零改动。
"""
from __future__ import annotations

import argparse
import sys

from .common import load_config

STAGES = ["fetch", "structure", "analyze", "draft", "finalize", "word"]


def main():
    ap = argparse.ArgumentParser(description="专业调研报告六阶段工作流")
    ap.add_argument("--config", required=True, help="project.yaml 路径")
    ap.add_argument("--stage", required=True,
                    help="all 或逗号分隔的：fetch,structure,analyze,draft,finalize,word")
    ap.add_argument("--root", help="覆盖 project.root 输出目录")
    args = ap.parse_args()

    stages = STAGES if args.stage == "all" else [s.strip() for s in args.stage.split(",")]
    for s in stages:
        if s not in STAGES:
            print(f"未知阶段：{s}；可选 {STAGES}")
            sys.exit(2)

    cfg = load_config(args.config, args.root)
    print(f"📌 专题：{cfg.name}\n📌 输出根目录：{cfg.root}\n📌 执行阶段：{stages}\n")

    # LLM 客户端按需只创建一次，供 2/3/4 阶段复用
    llm = None

    def need_llm():
        nonlocal llm
        if llm is None:
            from .common import LLMClient
            # 自动加载 .env（若安装了 python-dotenv）
            try:
                from dotenv import load_dotenv
                load_dotenv()
            except ImportError:
                pass
            llm = LLMClient(cfg)
        return llm

    for stage in stages:
        if stage == "fetch":
            from . import s1_fetch
            s1_fetch.run(cfg)
        elif stage == "structure":
            from . import s2_structure
            s2_structure.run(cfg, need_llm())
        elif stage == "analyze":
            from . import s3_analyze
            s3_analyze.run(cfg, need_llm())
        elif stage == "draft":
            from . import s4_draft
            s4_draft.run(cfg, need_llm())
        elif stage == "finalize":
            from . import s5_finalize
            s5_finalize.run(cfg)
        elif stage == "word":
            from . import s6_to_word
            s6_to_word.run(cfg)

    print("\n🎉 所选阶段执行完毕。")


if __name__ == "__main__":
    main()
