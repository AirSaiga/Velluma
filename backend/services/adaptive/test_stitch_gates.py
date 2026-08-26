# Velluma - NLE-ADF 3.0 stitch 字数闸与碎片拼回单测（P1 批次）
# AGPL-3.0
"""2026-08-25 写作台辅助层治理 P1 批次回归（docs/adaptive-assist-hardening.md）。

覆盖四项：
1. 保尾截断 _truncate_keep_tail（P1-1/A3）：outline 超字截断改「保尾」——
   末段（引向 after_text 的承接段）完整保留，超字从前往后按句界删节；
   单段成文/末段自身超限退化为既有尾截（防死循环）；前段超长单句整段让位；
2. 碎片拼回判定 _contains_fragment（P1-2/A4）：标点等价类/空白变体算
   「已含」不再拼回；字符内容变化（加字/换词）仍判不含、照常拼回；
3. 路由级（LLM/上下文装配/观测全桩化，不连真实 LLM/DB）：outline 字数闸
   走保尾、stitch 标点变体不重复拼回、短窗观测字段（P1-3/C1）、
   max_tokens 下限 2200（P1-4/C2）。

配方同 test_world_model_liveness.py：独立 asyncio.run、UUID 带字母。
运行：python -m pytest backend/services/adaptive/test_stitch_gates.py -v
"""

import asyncio
import json
import uuid

from backend.routes.chapter_generation.adaptive import (
    STITCH_MAX_TOKENS_FLOOR,
    StitchGhostRequest,
    _contains_fragment,
    _truncate_at_sentence,
    _truncate_keep_tail,
)
from backend.services.context.budget import (
    STITCH_ROLLING_LONG_MAX_CHARS,
    STITCH_ROLLING_SHORT_MAX_CHARS,
)
from backend.services.llm.client import REASONING_DISABLED

CH = str(uuid.UUID("aa210000-0000-4000-8000-0000000000d1"))


def _sents(prefix: str, n: int):
    """造 n 句等结构短句（prefix + 两位序号 + 固定占位 + 句号），句句可辨。"""
    return [f"{prefix}{i:02d}句正文填充占位。" for i in range(1, n + 1)]


# ============================================================
# 1. 纯函数：保尾截断
# ============================================================

def test_keep_tail_preserves_final_paragraph_and_trims_front():
    head_sents = _sents("檐水", 20)   # 前段：20 句
    tail_sents = _sents("承接", 4)    # 末段：引向 after_text 的承接段
    head = "".join(head_sents)
    tail = "".join(tail_sents)
    text = f"{head}\n\n{tail}"
    # 前段只容得下尾部约 60 字——必然从前往后删节
    limit = len(tail) + 2 + 60

    out = _truncate_keep_tail(text, limit)

    assert len(out) <= limit                          # 字数硬上限
    assert out.endswith(tail)                         # 末段完整保留（P1-1 核心）
    assert not out.startswith(head_sents[0])          # 开头被删节
    assert any(out.startswith(s) for s in head_sents)  # 前段按句界让位、非字符腰斩
    assert out in text                                # 纯删节，无字符改写


def test_keep_tail_noop_within_limit():
    text = "他推门进来。\n\n雨还没停，他望着窗外出神。"
    assert _truncate_keep_tail(text, 100) == text


def test_keep_tail_single_paragraph_degrades_to_tail_cut():
    # 单段成文：末段即全文，没有「删前保尾」的操作空间 → 既有尾截
    text = "一句话说到底。" * 60
    limit = 50
    assert _truncate_keep_tail(text, limit) == _truncate_at_sentence(text, limit)


def test_keep_tail_oversized_tail_degrades_to_tail_cut():
    head = "短句收尾。" * 10
    tail = "承接段超限占位。" * 20    # 末段自身就超 limit → 保不住，回落尾截
    text = f"{head}\n\n{tail}"
    limit = 80
    assert _truncate_keep_tail(text, limit) == _truncate_at_sentence(text, limit)


def test_keep_tail_giant_head_sentence_drops_head():
    # 前段是无句末标点的超长单句：找不到句界删节点 → 整个前段让位、只留末段
    head = "没有任何句读的一整条长句往下拖" * 10
    tail = "承接段完整保留。"
    text = f"{head}\n\n{tail}"
    assert _truncate_keep_tail(text, 40) == tail


# ============================================================
# 2. 纯函数：碎片拼回判定规范化
# ============================================================

def test_contains_fragment_exact_match():
    assert _contains_fragment("他握紧刀，转过身去。", "握紧刀，转过身去")


def test_contains_fragment_ascii_terminal_variant():
    # 「。」被复述成半角叹号——句末等价类，算已含、不重复拼回
    assert _contains_fragment("他握紧刀! 刀锋映出他通红的眼。", "他握紧刀。")


def test_contains_fragment_terminal_class_variant():
    # 句末异形（。→？）视为同一种「一句终了」
    assert _contains_fragment("他握紧刀？", "他握紧刀。")


def test_contains_fragment_whitespace_variant():
    assert _contains_fragment("他握紧刀 。", "他握紧刀。")
    assert _contains_fragment("他 握紧 刀。", "他握紧刀。")


def test_contains_fragment_comma_width_variant():
    assert _contains_fragment("他说,走。", "他说，走。")


def test_contains_fragment_semantic_change_not_contained():
    # 加了「了」——语义变了，该拼回
    assert not _contains_fragment("他握紧了刀，指节发白。", "他握紧刀。")


def test_contains_fragment_absent():
    assert not _contains_fragment("她收刀入鞘，退回阴影里。", "他握紧刀。")


def test_contains_fragment_empty_fragment_defensive():
    assert _contains_fragment("任何文本。", "")


# ============================================================
# 3. 路由级（全桩化）：字数闸保尾 / 拼回判定 / 观测字段 / 预算下限
# ============================================================

class _Result:
    def __init__(self, content):
        self.content = content


class _Rec:
    def record_result(self, *a, **k):
        pass


class _Bundle:
    outline_text = ""
    previous_summary = ""
    worldview_text = ""
    canon_context = ""
    spatial_brief = ""
    character_secrets = []


class _Ctx:
    bundle = _Bundle()
    proper_nouns = []
    chapter_intent = ""
    memory_echoes = []
    style_positive = ""
    author_samples = []


def _run_stitch(monkeypatch, request: StitchGhostRequest, llm_contents):
    """直调 stitch_ghost 路由（LLM/上下文装配/观测全桩化，不连真实 LLM/DB）。

    返回 (GHOST_DONE payload 或 None, LLM 调用 kwargs 列表, trace 事件 dict)。
    """
    from backend.routes.chapter_generation import adaptive as adaptive_route

    llm_calls = []
    traces = {}

    async def fake_llm(system_prompt, user_prompt, **kw):
        llm_calls.append(kw)
        return _Result(llm_contents[min(len(llm_calls) - 1, len(llm_contents) - 1)])

    async def fake_assemble(**kw):
        return _Ctx()

    async def fake_spine_rows(chapter_id, db):
        return []

    async def fake_flush(chapter_id):
        return None

    def fake_trace(event, **data):
        traces.setdefault(event, []).append(data)

    monkeypatch.setattr(adaptive_route, "call_llm_with_usage", fake_llm)
    monkeypatch.setattr(adaptive_route, "assemble_stitch_context", fake_assemble)
    monkeypatch.setattr(adaptive_route, "_spine_anchor_rows_for_prompt", fake_spine_rows)
    monkeypatch.setattr(adaptive_route, "get_adaptive_recorder", lambda cid: _Rec())
    monkeypatch.setattr(adaptive_route, "flush_adaptive_records", fake_flush)
    monkeypatch.setattr(adaptive_route, "bind_adaptive_trace", lambda cid: None)
    monkeypatch.setattr(adaptive_route, "trace_event", fake_trace)

    async def scenario():
        resp = await adaptive_route.stitch_ghost(CH, request, None)
        frames = []
        async for chunk in resp.body_iterator:
            frames.append(chunk if isinstance(chunk, str) else chunk.decode("utf-8"))
        return frames

    frames = asyncio.run(scenario())
    done = None
    for f in frames:
        if f.startswith("data: "):
            payload = json.loads(f[len("data: "):].strip())
            if payload.get("event") == "GHOST_DONE":
                done = payload
    return done, llm_calls, traces


TAIL_PARA = "他忽然收势，转身望向门外深不见底的雨幕。"


def test_route_outline_truncation_keeps_tail(monkeypatch):
    """outline 超字：压缩重试仍超 → 保尾截断；末段承接段完整存活（A3 现场）。"""
    text = "".join(_sents("檐水", 16)) + "\n\n" + TAIL_PARA   # 230 字 > target×1.6=160
    head_first = _sents("檐水", 16)[0]
    req = StitchGhostRequest(
        fragment="主角在檐下躲雨的速记。",
        rolling_prefix="雨夜占位" * 400,   # 原始上送 1600 字（超 1200 长窗）
        mode="outline",
        target_chars=100,
        after_text="再往后他已经走到街角。",
    )
    done, llm_calls, traces = _run_stitch(monkeypatch, req, [text, ""])  # 压缩重试吐空

    # 主调用 + 压缩重试各一，预算下限 2200（P1-4/C2）
    assert len(llm_calls) == 2
    for kw in llm_calls:
        assert kw["max_tokens"] == max(STITCH_MAX_TOKENS_FLOOR, 100 * 2 + 1000) == 2200
        assert kw["reasoning_config"] == REASONING_DISABLED

    body = done["text"]
    assert len(body) <= 150                    # target×1.5 硬上限
    assert body.endswith(TAIL_PARA)            # 末段承接段完整保留（P1-1）
    assert not body.startswith(head_first)     # 开头被删节
    assert body in text

    # P1-3 观测字段：outline 长窗（1600 原始 → 1200 截窗；2026-08-25 实测调窗后）
    complete = traces["adaptive_stitch_complete"][-1]
    assert complete["rolling_prefix_raw_len"] == 1600
    assert complete["rolling_prefix_used_len"] == STITCH_ROLLING_LONG_MAX_CHARS


def test_route_stitch_punct_variant_reemission_stripped(monkeypatch):
    """追加式契约（2026-08-26）：模型复读原句（标点变体）→ 剥掉前缀只留续写。

    幽灵纯追加在原句之后，原句已在画布里——复读=屏幕重复，拼回已废除。
    """
    req = StitchGhostRequest(fragment="他握紧刀。", mode="stitch", rolling_prefix="前文占位。")
    model_text = "他握紧刀! 刀锋映出他通红的眼。"
    done, _, _ = _run_stitch(monkeypatch, req, [model_text])
    assert done["text"] == "刀锋映出他通红的眼。"


def test_route_stitch_exact_reemission_stripped(monkeypatch):
    req = StitchGhostRequest(fragment="他握紧刀。", mode="stitch", rolling_prefix="前文占位。")
    done, _, _ = _run_stitch(monkeypatch, req, ["他握紧刀。刀锋映出他通红的眼。"])
    assert done["text"] == "刀锋映出他通红的眼。"


def test_route_stitch_semantic_variant_not_stripped(monkeypatch):
    """语义变体（换词/加字）不是复读——不剥、也绝不拼回（拼回已废除）。"""
    req = StitchGhostRequest(fragment="他握紧刀。", mode="stitch", rolling_prefix="前文占位。")
    model_text = "他握紧了刀，指节泛白。"
    done, _, _ = _run_stitch(monkeypatch, req, [model_text])
    assert done["text"] == model_text


def test_route_trace_rolling_window_fields_and_token_floor(monkeypatch):
    """P1-3 短窗观测 + P1-4 预算下限：continue 短窗截窗可见、下限 2200 生效。

    2026-08-25 实测调窗（200→800）：真实 trace 回收的「驴头不对马嘴」案例坐实
    短窗是主因之一——数据门控达成，常量上调；本测试改为锁定新窗口值。
    """
    req = StitchGhostRequest(
        fragment="承接占位。",
        mode="continue",
        rolling_prefix="前" * 900,
        target_chars=120,
    )
    done, llm_calls, traces = _run_stitch(monkeypatch, req, ["短续写一句。"])
    assert done is not None

    complete = traces["adaptive_stitch_complete"][-1]
    # 短窗截断观测：原始 900 → 截窗 800（新窗口值锚点；无句界文本净截原样保留整窗）
    assert complete["rolling_prefix_raw_len"] == 900
    assert complete["rolling_prefix_used_len"] == STITCH_ROLLING_SHORT_MAX_CHARS
    assert STITCH_ROLLING_SHORT_MAX_CHARS == 800

    # max_tokens 下限：target 120 → 120×2+1000=1240 < 2200 → 取下限
    assert llm_calls[0]["max_tokens"] == STITCH_MAX_TOKENS_FLOOR == 2200
