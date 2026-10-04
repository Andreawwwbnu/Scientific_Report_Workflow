# -*- coding: utf-8 -*-
"""命令行入口：report-wf  (等价于 python -m report_workflow)

    report-wf validate  <项目>             校验配置与文献清单（不联网、不花钱）
    report-wf run       <项目> [--stages …] 运行流水线
    report-wf status    <项目>             各阶段产物一览
    report-wf init      <新项目名>          从模板创建新专题

<项目> 可以是 projects/ 下的目录名（如 low_precision），也可以是目录或 project.yaml 的路径。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from . import __version__
from .config import WorkflowConfig, load_config, validate_config

STAGES = ["fetch", "structure", "analyze", "draft", "finalize", "word", "qc", "review"]
DEFAULT_ALL = ["fetch", "structure", "analyze", "draft", "finalize", "word", "qc"]
ALIASES = {"1": "fetch", "2": "structure", "3": "analyze", "4": "draft", "5": "finalize", "6": "word",
           "7": "qc", "all": "all"}
NEEDS_LLM = {"structure", "analyze", "draft", "review"}
PROJECTS_DIR = Path(__file__).resolve().parent.parent / "projects"


def _load_dotenv():
    for p in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if p.exists():
            try:
                from dotenv import load_dotenv
                load_dotenv(p, override=False)
            except ImportError:
                for ln in p.read_text(encoding="utf-8").splitlines():
                    ln = ln.strip()
                    if ln and not ln.startswith("#") and "=" in ln:
                        k, v = ln.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            break


def resolve_project(arg: str) -> Path:
    p = Path(arg).expanduser()
    if p.exists():
        return p
    cand = PROJECTS_DIR / arg
    if cand.exists():
        return cand
    cand = Path.cwd() / "projects" / arg
    if cand.exists():
        return cand
    raise FileNotFoundError(f"找不到项目：{arg}（已尝试路径、{PROJECTS_DIR}）")


def parse_stages(spec: str) -> List[str]:
    spec = spec.strip().lower()
    if spec in ("all", ""):
        return list(DEFAULT_ALL)
    out: List[str] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part and part.replace("-", "").isdigit():
            a, b = part.split("-")
            out += [ALIASES[str(i)] for i in range(int(a), int(b) + 1)]
        else:
            name = ALIASES.get(part, part)
            if name not in STAGES:
                raise SystemExit(f"未知阶段：{part}。可选：{', '.join(STAGES)}、1-7、all")
            out.append(name)
    return [s for i, s in enumerate(out) if s not in out[:i]]


def _sanitize(obj):
    try:
        json.dumps(obj, ensure_ascii=False)
        return obj
    except TypeError:
        return json.loads(json.dumps(obj, ensure_ascii=False, default=str))


def run_stage(name: str, cfg: WorkflowConfig, llm, opts: dict) -> dict:
    from . import s1_fetch, s2_structure, s3_analyze, s4_draft, s5_finalize, s6_to_word, s7_qc
    kw = dict(only_chapters=opts.get("only_chapters"), force=opts.get("force", False))
    if name == "fetch":
        return s1_fetch.run(cfg, **kw)
    if name == "structure":
        return s2_structure.run(cfg, llm, **kw)
    if name == "analyze":
        return s3_analyze.run(cfg, llm, **kw)
    if name == "draft":
        return s4_draft.run(cfg, llm, **kw)
    if name == "finalize":
        return s5_finalize.run(cfg)
    if name == "word":
        return s6_to_word.run(cfg)
    if name == "qc":
        return s7_qc.run_qc(cfg, llm, llm_check=opts.get("llm_check", False))
    if name == "review":
        return s7_qc.run_review(cfg, llm)
    raise ValueError(name)


def cmd_validate(args) -> int:
    cfg = load_config(resolve_project(args.project), mock=args.mock)
    errors, warns = validate_config(cfg)
    n_ent, n_can = len(cfg.all_entries), len(cfg.canonical_entries)
    print(f"项目：{cfg.name}（{cfg.slug}）｜章节 {len(cfg.chapters)}｜文献 {n_ent}（去镜像 {n_can}）")
    rcs = cfg.report_chapters
    print("成稿结构：" + " → ".join(rc.heading for rc in rcs))
    wc = cfg.wc_cfg
    print(f"篇幅预算：正文 {wc['body_min']}–{wc['body_max']} 字；各章目标："
          + "，".join(f"{rc.id}≈{cfg.chapter_target_chars(rc)}" for rc in rcs))
    for w in warns:
        print(f"⚠️ {w}")
    for e in errors:
        print(f"❌ {e}")
    if errors:
        print(f"\n配置校验失败：{len(errors)} 个错误")
        return 2
    print("\n✅ 配置校验通过")
    return 0


def cmd_run(args) -> int:
    _load_dotenv()
    cfg = load_config(resolve_project(args.project), root_override=args.root, mock=args.mock,
                      use_cache=not args.no_cache)
    errors, warns = validate_config(cfg)
    for w in warns:
        print(f"⚠️ {w}")
    if errors:
        for e in errors:
            print(f"❌ {e}")
        print("配置校验失败，已停止。可运行 `report-wf validate` 查看详情。")
        return 2

    stages = parse_stages(args.stages)
    only = set(args.only_chapter.split(",")) if args.only_chapter else None
    opts = {"only_chapters": only, "force": args.force, "llm_check": args.llm_check}
    print(f"📁 输出目录：{cfg.root}")
    print(f"▶️  阶段：{' → '.join(stages)}" + ("（mock 离线模式：输出仅用于验证流程）" if cfg.mock else ""))

    llm = None
    if any(s in NEEDS_LLM for s in stages) or (("qc" in stages) and (args.llm_check or cfg.qc_cfg.get("llm_check"))):
        from .llm import make_llm
        llm = make_llm(cfg)

    record = {"project": cfg.slug, "version": __version__, "started": datetime.now().isoformat(timespec="seconds"),
              "mock": cfg.mock, "stages": {}, "models": {k: v for k, v in cfg.llm_cfg.items() if k.endswith("_model")}}
    code = 0
    for name in stages:
        t0 = time.time()
        try:
            res = run_stage(name, cfg, llm, opts) or {}
        except KeyboardInterrupt:
            print("\n⛔ 已中断")
            code = 130
            break
        except Exception as e:  # noqa: BLE001
            print(f"\n❌ 阶段 {name} 异常：{e}")
            res = {"ok": False, "exception": str(e)}
        record["stages"][name] = {"seconds": round(time.time() - t0, 1), "result": _sanitize(res)}
        if res.get("ok") is False and not args.no_gate:
            print(f"\n⛔ 阶段 {name} 未通过质量门禁，已停止后续阶段（修复后重跑，或加 --no-gate 强制继续）")
            code = 1
            break
    record["finished"] = datetime.now().isoformat(timespec="seconds")
    if llm is not None:
        record["usage"] = llm.usage.by_task
    path = cfg.runs_dir / f"run-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n🧾 运行记录：{path}")
    if llm is not None:
        print("💰 " + llm.usage.summary_line())
    return code


def cmd_status(args) -> int:
    cfg = load_config(resolve_project(args.project))
    print(f"项目：{cfg.name}\n输出目录：{cfg.root}\n")
    raw = sum(1 for _ in cfg.raw_root.rglob("*.md"))
    print(f"阶段1 原始素材：{raw} 个文件 / manifest {len(cfg.all_entries)} 条")
    print(f"阶段2 结构化证据：{sum(cfg.structured_path(c).exists() for c in cfg.chapters)}/{len(cfg.chapters)} 章")
    print(f"阶段3 分析结论：{sum(cfg.analysis_path(c).exists() for c in cfg.chapters)}/{len(cfg.chapters)} 章")
    rcs = cfg.report_chapters
    print(f"阶段4 分章草稿：{sum(cfg.draft_chapter_path(r).exists() for r in rcs)}/{len(rcs)} 章；"
          f"合并稿 {'✅' if cfg.draft_path.exists() else '—'}")
    print(f"阶段5 终稿 md：{'✅' if cfg.final_md_path.exists() else '—'}")
    print(f"阶段6 Word：{'✅' if cfg.final_docx_path.exists() else '—'}")
    print(f"质检报告：{'✅' if cfg.qc_report_path.exists() else '—'}｜审稿意见：{'✅' if cfg.review_report_path.exists() else '—'}")
    runs = sorted(cfg.runs_dir.glob("run-*.json"))
    if runs:
        print(f"最近运行：{runs[-1].name}")
    return 0


def cmd_init(args) -> int:
    src = PROJECTS_DIR / "_template"
    dest_root = Path(args.dir) if args.dir else PROJECTS_DIR
    dest = dest_root / args.name
    if dest.exists():
        print(f"❌ 已存在：{dest}")
        return 1
    if not src.exists():
        print(f"❌ 找不到模板：{src}")
        return 1
    shutil.copytree(src, dest)
    for f in dest.rglob("*.yaml"):
        f.write_text(f.read_text(encoding="utf-8").replace("__SLUG__", args.name), encoding="utf-8")
    print(f"✅ 已创建 {dest}\n下一步：编辑 project.yaml 与 literature_manifest.yaml，然后运行\n"
          f"   report-wf validate {args.name}\n   report-wf run {args.name} --stages 1")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="report-wf", description="技术调研报告自动化工作流")
    ap.add_argument("--version", action="version", version=f"report-wf {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="校验配置与文献清单")
    v.add_argument("project")
    v.add_argument("--mock", action="store_true")
    v.set_defaults(fn=cmd_validate)

    r = sub.add_parser("run", help="运行流水线")
    r.add_argument("project")
    r.add_argument("--stages", default="all",
                   help="阶段：all | 1-7 | fetch,structure,analyze,draft,finalize,word,qc,review（可逗号/区间，如 2-4）")
    r.add_argument("--only-chapter", help="仅处理指定章 id（逗号分隔，如 02,03），用于阶段 2/3/4")
    r.add_argument("--root", help="覆盖输出根目录")
    r.add_argument("--mock", action="store_true", help="用离线 MockLLM 跑通流程（输出不是真实报告）")
    r.add_argument("--force", action="store_true", help="阶段1：强制重抓已有素材")
    r.add_argument("--no-cache", action="store_true", help="禁用 LLM 缓存（默认相同输入不重复调用）")
    r.add_argument("--no-gate", action="store_true", help="阶段未通过也继续后续阶段")
    r.add_argument("--llm-check", action="store_true", help="质检阶段启用 LLM 句级核验（额外耗费）")
    r.set_defaults(fn=cmd_run)

    s = sub.add_parser("status", help="查看各阶段产物")
    s.add_argument("project")
    s.set_defaults(fn=cmd_status)

    i = sub.add_parser("init", help="从模板创建新专题")
    i.add_argument("name")
    i.add_argument("--dir", help="创建位置（默认 projects/）")
    i.set_defaults(fn=cmd_init)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
