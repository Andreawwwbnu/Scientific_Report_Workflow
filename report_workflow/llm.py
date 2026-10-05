# -*- coding: utf-8 -*-
"""LLM 层：OpenAI 兼容客户端（磁盘缓存 / 用量统计 / 重试）、离线 MockLLM、JSON 解析、并发映射。

缓存键 = hash(model, system, user, max_tokens, temperature)。输入没变就不会重复花钱，
这也是“增量重跑”的实现方式：改了某个小节的素材，只有受影响的 Prompt 会重新调用模型。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .config import WorkflowConfig


# ============================================================
# 用量统计
# ============================================================
class Usage:
    def __init__(self):
        self._lock = threading.Lock()
        self.by_task: Dict[str, Dict[str, int]] = {}

    def record(self, task: str, prompt_tokens: int = 0, completion_tokens: int = 0, cached: bool = False):
        with self._lock:
            d = self.by_task.setdefault(task, {"calls": 0, "cache_hits": 0,
                                               "prompt_tokens": 0, "completion_tokens": 0})
            d["calls"] += 1
            if cached:
                d["cache_hits"] += 1
            d["prompt_tokens"] += int(prompt_tokens or 0)
            d["completion_tokens"] += int(completion_tokens or 0)

    def total(self) -> Dict[str, int]:
        t = {"calls": 0, "cache_hits": 0, "prompt_tokens": 0, "completion_tokens": 0}
        for d in self.by_task.values():
            for k in t:
                t[k] += d[k]
        return t

    def summary_line(self) -> str:
        t = self.total()
        return (f"LLM 调用 {t['calls']} 次（缓存命中 {t['cache_hits']}），"
                f"tokens：输入 {t['prompt_tokens']:,} / 输出 {t['completion_tokens']:,}")


class BaseLLM:
    name = "base"

    def __init__(self):
        self.usage = Usage()

    def chat(self, *, task: str, model: str, system: str, user: str,
             max_tokens: int, temperature: Optional[float] = 0.1) -> str:
        raise NotImplementedError


# ============================================================
# 真实客户端（OpenAI 兼容：DeepSeek / OpenAI / 通义 / 各类网关）
# ============================================================
class OpenAICompatLLM(BaseLLM):
    name = "openai_compatible"

    def __init__(self, cfg: WorkflowConfig):
        super().__init__()
        self.cfg = cfg
        llm = cfg.llm_cfg
        self.api_key = os.getenv(llm.get("api_key_env", "DEEPSEEK_API_KEY"))
        base_url = os.getenv(llm.get("base_url_env", "DEEPSEEK_BASE_URL")) or llm.get("default_base_url")
        if not self.api_key:
            raise RuntimeError(
                f"未检测到环境变量 {llm.get('api_key_env', 'DEEPSEEK_API_KEY')}。"
                "请复制 .env.example 为 .env 并填写；或加 --mock 先离线跑通流程。")
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError("缺少 openai 依赖：pip install -r requirements.txt") from e
        self.client = OpenAI(api_key=self.api_key, base_url=base_url)
        self.max_retries = int(llm.get("max_retries", 3))
        self.use_cache = bool(llm.get("cache", True)) and cfg.use_cache
        self.cache_dir = cfg.cache_dir

    @staticmethod
    def _is_reasoner(model: str) -> bool:
        m = model.lower()
        return "reasoner" in m or re.search(r"(^|[-_/])r1($|[-_/])", m) is not None

    def _key(self, model, system, user, max_tokens, temperature) -> str:
        raw = json.dumps([model, system, user, max_tokens, temperature], ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def chat(self, *, task, model, system, user, max_tokens, temperature=0.1) -> str:
        temp = None if (self._is_reasoner(model) or temperature is None) else float(temperature)
        key = self._key(model, system, user, max_tokens, temp)
        cache_file = self.cache_dir / f"{key}.json"
        if self.use_cache and cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                self.usage.record(task, cached=True)
                return data["text"]
            except (json.JSONDecodeError, KeyError):
                pass

        kwargs: Dict[str, Any] = dict(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens, stream=False)
        if temp is not None:
            kwargs["temperature"] = temp

        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                resp = self.client.chat.completions.create(**kwargs)
                content = (resp.choices[0].message.content or "").strip()
                if content:
                    u = getattr(resp, "usage", None)
                    self.usage.record(task, getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0))
                    if self.use_cache:
                        cache_file.write_text(json.dumps(
                            {"model": model, "task": task, "text": content}, ensure_ascii=False),
                            encoding="utf-8")
                    return content
                last_err = RuntimeError("模型返回为空")
            except Exception as e:  # noqa: BLE001
                last_err = e
            wait = min(2 ** attempt, 8)
            print(f"    ⚠️ [{task}] 第 {attempt + 1} 次调用失败：{str(last_err)[:100]}；{wait}s 后重试")
            time.sleep(wait)
        raise RuntimeError(f"LLM 调用 {self.max_retries} 次均失败：{last_err}")


# ============================================================
# 离线 Mock：用于验证流程与测试，输出不是真实报告
# ============================================================
class MockLLM(BaseLLM):
    """按 Prompt 里的结构化标记生成确定性输出（只复述输入材料，不含任何外部知识）。"""
    name = "mock"

    _CHUNK = re.compile(r'<chunk id="([^"]+)" source="([^"]+)"[^>]*>\n?(.*?)\n?</chunk>', re.S)

    def chat(self, *, task, model, system, user, max_tokens, temperature=0.1) -> str:
        self.usage.record(task, len(user) // 2, 200)
        fn = getattr(self, f"_{task}", None)
        if fn is None:
            return "（mock）"
        return fn(user)

    # ----- 阶段 2 -----
    def _expand_query(self, user: str) -> str:
        return json.dumps({"keywords": []})

    def _extract(self, user: str) -> str:
        chunks = self._CHUNK.findall(user)
        m = re.search(r"最多输出要点数：(\d+)", user)
        limit = int(m.group(1)) if m else 4
        items, used_sources = [], set()
        ordered = sorted(chunks, key=lambda c: c[1] in used_sources)
        for cid, src, text in ordered:
            if len(items) >= min(limit, 4):
                break
            if src in used_sources:
                continue
            piece = next((p.strip() for p in re.split(r"(?<=[。！？])\s*|(?<=[.!?])\s+|\n+", text)
                          if len(p.strip()) >= 12 and not p.strip().startswith("#")), "")
            if not piece:
                continue
            if len(piece) > 100:                       # 在逗号边界截断，避免把数字切断
                cut = max(piece.rfind("，", 0, 100), piece.rfind(",", 0, 100))
                piece = piece[:cut] if cut >= 12 else piece
            used_sources.add(src)
            items.append({"claim": f"材料指出：{piece}", "quote": piece, "source": src, "chunk": cid})
        return json.dumps({"items": items}, ensure_ascii=False)

    # ----- 阶段 3 -----
    @staticmethod
    def _evidence_lines(user: str) -> List[Tuple[str, str]]:
        blocks = re.findall(r"<evidence>\n(.*?)\n</evidence>", user, re.S)
        text = blocks[-1] if blocks else user
        return [(m.group(1).strip(), m.group(2))
                for m in re.finditer(r"^-\s*(.*?)\s*\[([A-Za-z]+\d+)\]\s*$", text, re.M)]

    def _analyze(self, user: str) -> str:
        lines = self._evidence_lines(user)[:4]
        return "\n".join(f"- {t}[{i}]" for t, i in lines)

    # ----- 阶段 4 -----
    def _draft_chapter(self, user: str) -> str:
        hb = re.findall(r"<headings>\n(.*?)\n</headings>", user, re.S)
        headings = [h.strip() for h in hb[-1].splitlines() if h.strip()] if hb else []
        ab = re.findall(r"<analysis>\n(.*?)\n</analysis>", user, re.S)
        lines = [(m.group(1).strip(), m.group(2)) for m in
                 re.finditer(r"^-\s*(.*?)\s*\[([A-Za-z]+\d+)\]\s*$", ab[-1] if ab else "", re.M)]
        subs = [h for h in headings if h.startswith("### ")]
        blocks = re.findall(r"【[^】]*】\n(.*?)(?=\n\n【|\Z)", ab[-1] if ab else "", re.S)
        n = max(len(subs), 1)
        groups: List[List[Tuple[str, str]]] = [[] for _ in range(n)]
        if subs and len(blocks) == len(subs):      # 按小节一一对应
            for k, b in enumerate(blocks):
                groups[k] = [(m.group(1).strip(), m.group(2)) for m in
                             re.finditer(r"^-\s*(.*?)\s*\[([A-Za-z]+\d+)\]\s*$", b, re.M)]
        else:
            for k, item in enumerate(lines):
                groups[k % n].append(item)

        def para(items):
            return "".join(f"{t.rstrip('。')}<sup>[{i}]</sup>。" for t, i in items)

        out, gi = [], 0
        for h in headings:
            out.append(h)
            if h.startswith("## "):
                if not subs:
                    out.append(para(groups[0]))
            else:
                out.append(para(groups[gi]))
                gi += 1
            out.append("")
        return "\n".join(out).strip()

    def _draft_frame(self, user: str) -> str:
        def rng(label: str, dmin: int, dmax: int):
            m = re.search(rf"{label}：(\d+)[–-](\d+) 字", user)
            return (int(m.group(1)), int(m.group(2))) if m else (dmin, dmax)

        a_min, a_max = rng("摘要", 250, 300)
        c_min, c_max = rng("结论与展望", 150, 200)
        km = re.search(r"关键词：(\d+)[–-](\d+) 个", user)
        k_min = int(km.group(1)) if km else 5
        cb = re.findall(r"<chapters>\n(.*?)\n</chapters>", user, re.S)
        text = re.sub(r"<sup>.*?</sup>", "", cb[-1] if cb else "")
        sents = [s.strip() for s in re.split(r"(?<=[。！？])", text)
                 if len(s.strip()) > 8 and not s.strip().startswith("#")]

        def build(lo: int, hi: int, offset: int) -> str:
            pool = sents[offset:] + sents[:offset]
            out, n = "", 0
            while len(out) < lo:
                if n < len(pool):
                    out += pool[n]
                else:
                    out += f"（离线演示补充句{n - len(pool) + 1}。）"
                n += 1
                if n > len(pool) + 50:
                    break
            return out[:hi]

        kws = ["流程验证", "证据抽取", "引用校验", "离线演示", "工作流", "质量门禁", "可追溯性"]
        return (f"## 摘要\n\n{build(a_min, a_max, 0)}\n\n"
                f"## 关键词\n\n{'；'.join(kws[:max(k_min, 5)])}\n\n"
                f"## 结论与展望\n\n{build(c_min, c_max, 1)}")

    # ----- 阶段 7 -----
    def _review(self, user: str) -> str:
        return "未发现需要处理的问题。"

    def _entail(self, user: str) -> str:
        ids = [int(x) for x in re.findall(r'<item id="(\d+)">', user)]
        return json.dumps({"verdicts": [{"id": i, "verdict": "supported", "reason": "mock"} for i in ids]})


def make_llm(cfg: WorkflowConfig) -> BaseLLM:
    provider = os.getenv("REPORT_LLM_PROVIDER") or cfg.llm_cfg.get("provider", "openai_compatible")
    if cfg.mock or provider == "mock":
        return MockLLM()
    return OpenAICompatLLM(cfg)


# ============================================================
# 辅助
# ============================================================
def extract_json(text: str) -> Any:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    dec = json.JSONDecoder()
    for i, ch in enumerate(t):
        if ch in "{[":
            try:
                obj, _ = dec.raw_decode(t[i:])
                return obj
            except json.JSONDecodeError:
                continue
    raise ValueError("模型输出中未找到合法 JSON")


def parallel_map(fn: Callable[[Any], Any], items: Iterable[Any], workers: int = 1
                 ) -> List[Tuple[bool, Any]]:
    """并发执行 fn，按输入顺序返回 [(ok, 结果或异常)]；单项失败不影响其他项。"""
    items = list(items)

    def safe(x):
        try:
            return True, fn(x)
        except Exception as e:  # noqa: BLE001
            return False, e

    if workers <= 1 or len(items) <= 1:
        return [safe(x) for x in items]
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as ex:
        return list(ex.map(safe, items))
