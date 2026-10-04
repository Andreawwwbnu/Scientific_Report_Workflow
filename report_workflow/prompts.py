# -*- coding: utf-8 -*-
"""Prompt 外置与渲染。

Prompt 文件在 `report_workflow/prompts/*.md`，格式：
    version: 3.0
    ===SYSTEM===
    ……
    ===USER===
    ……
变量写作 `{{name}}`。专题目录下的 `prompts/` 同名文件会覆盖默认 Prompt。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PKG_PROMPTS = Path(__file__).parent / "prompts"
_VAR = re.compile(r"\{\{(\w+)\}\}")


@dataclass
class Prompt:
    name: str
    version: str
    system: str
    user: str

    @property
    def tag(self) -> str:
        return f"{self.name}@{self.version}"


def _find(name: str, override_dir: Optional[Path]) -> Path:
    if override_dir and (override_dir / f"{name}.md").exists():
        return override_dir / f"{name}.md"
    p = PKG_PROMPTS / f"{name}.md"
    if not p.exists():
        raise FileNotFoundError(f"找不到 Prompt：{name}")
    return p


def load_prompt(name: str, override_dir: Optional[Path] = None) -> Prompt:
    text = _find(name, override_dir).read_text(encoding="utf-8")
    m = re.search(r"===SYSTEM===\s*(.*?)\s*===USER===\s*(.*)\Z", text, re.S)
    if not m:
        raise ValueError(f"Prompt {name} 缺少 ===SYSTEM=== / ===USER=== 分隔")
    head = text[:text.index("===SYSTEM===")]
    vm = re.search(r"version:\s*(\S+)", head)
    return Prompt(name, vm.group(1) if vm else "0", m.group(1).strip(), m.group(2).strip())


def render(name: str, override_dir: Optional[Path] = None, **variables) -> Prompt:
    p = load_prompt(name, override_dir)

    def sub(text: str) -> str:
        def _r(m):
            k = m.group(1)
            if k not in variables:
                raise KeyError(f"Prompt {name} 缺少变量 {{{{{k}}}}}")
            return str(variables[k])
        return _VAR.sub(_r, text)

    return Prompt(p.name, p.version, sub(p.system), sub(p.user))
