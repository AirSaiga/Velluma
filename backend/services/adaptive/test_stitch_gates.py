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
    book_id = "bk-wash"
    outline_text = ""
    previous_summary = ""
    worldview_text = ""
    canon_context = ""
    spatial_brief = ""
    character_secrets = []
    style_card = None


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
        llm_calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt, **kw})
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


# ============================================================
# 4. stitch/continue 字数闸扩面（2026-08-28 落地，2026-08-29 改两级：
#    kimi 120 字目标实测产出 600-700 字 8-10 段 → 保头截断 + 压缩改写）
# ============================================================

def test_route_stitch_overlong_compressed(monkeypatch):
    """stitch 超字：保头截断 → 压缩改写达标 → 落屏压缩稿（≤ target×1.5）。

    2026-08-29 断点衔接首句豁免后：落屏=首句+压缩稿（首句物理隔离不进压缩）。
    """
    text = "".join(_sents("檐水", 30))   # 390 字 > 120×1.6=192
    compressed = "檐水改后两句的压缩稿。"   # 压缩产物达标
    req = StitchGhostRequest(
        fragment="他握紧刀。", mode="stitch",
        rolling_prefix="前文占位。", target_chars=120,
    )
    done, llm_calls, _ = _run_stitch(monkeypatch, req, [text, compressed])

    first_sent = _sents("檐水", 30)[0]
    assert done["text"] == first_sent + compressed   # 首句豁免 + 压缩稿
    assert len(done["text"]) <= 192                   # ×1.6 硬上限
    assert len(llm_calls) == 2                 # 主生成 + 压缩改写
    assert "压缩改写" in llm_calls[1]["user_prompt"]  # 压缩指令在第二次调用
    assert "作者正文停在" in llm_calls[1]["user_prompt"]  # 压缩带断点坐标
    # 首句不进压缩草稿区（锚句声明行有意引用它，只断言草稿区干净）
    assert first_sent not in llm_calls[1]["user_prompt"].split("--- 草稿 ---")[-1]
    assert llm_calls[1]["reasoning_config"] == REASONING_DISABLED


def test_route_stitch_compress_empty_falls_back_to_head(monkeypatch):
    """压缩空产出 → 回落截取稿（句界收尾，永不劣于纯截断）。"""
    text = "".join(_sents("檐水", 30))
    req = StitchGhostRequest(
        fragment="他握紧刀。", mode="stitch",
        rolling_prefix="前文占位。", target_chars=120,
    )
    done, llm_calls, _ = _run_stitch(monkeypatch, req, [text, ""])

    body = done["text"]
    assert len(body) <= 180                          # target×1.5
    assert body.startswith(_sents("檐水", 30)[0])     # 保头
    assert body.endswith("。")                        # 句界收尾
    assert len(llm_calls) == 2                        # 压缩尝试确实发了


# ============================================================
# 4b. 线 E（2026-09-03）：burst/open 同进两级字数闸——700 字承诺下的
#     超产=快进剧情（冲章同族风险）；闸只抓 ×1.6 严重超产，正常浮动不碰
# ============================================================

def test_route_burst_overlong_compressed(monkeypatch):
    """burst 超产：700 目标产出超 ×1.6 → 同走保头截断 + 压缩改写。"""
    text = "".join(_sents("火光", 120))   # ~1560 字 > 700×1.6=1120
    compressed = "火光改后的压缩稿，收在目标内。"
    req = StitchGhostRequest(
        fragment="他抬头。", mode="burst",
        rolling_prefix="前文占位。", target_chars=700,
        beat_guidance="走向卡：仓库失火",
    )
    done, llm_calls, _ = _run_stitch(monkeypatch, req, [text, compressed])

    first_sent = _sents("火光", 120)[0]
    assert done["text"] == first_sent + compressed   # 首句豁免 + 压缩稿
    assert len(llm_calls) == 2
    assert "压缩改写" in llm_calls[1]["user_prompt"]
    assert "作者正文停在" in llm_calls[1]["user_prompt"]  # burst 有断点坐标


def test_route_burst_within_limit_untouched(monkeypatch):
    """正常浮动不碰：700 目标下 <×1.6 的产出零干预（不触发第二次调用）。"""
    text = "".join(_sents("火光", 60))   # ~780 字 < 1120
    req = StitchGhostRequest(
        fragment="他抬头。", mode="burst",
        rolling_prefix="前文占位。", target_chars=700,
        beat_guidance="走向卡：仓库失火",
    )
    done, llm_calls, _ = _run_stitch(monkeypatch, req, [text])
    assert done["text"] == text
    assert len(llm_calls) == 1


def test_route_open_overlong_uses_opening_wording(monkeypatch):
    """open 超产进闸；无作者断点 → 压缩措辞是「开篇草稿」，不讲「断点」。"""
    text = "".join(_sents("开场", 120))
    compressed = "开场压缩稿，收束完毕。"
    req = StitchGhostRequest(
        fragment="", mode="open", rolling_prefix="", target_chars=700,
    )
    done, llm_calls, _ = _run_stitch(monkeypatch, req, [text, compressed])
    assert len(llm_calls) == 2
    prompt2 = llm_calls[1]["user_prompt"]
    assert "开篇草稿" in prompt2
    assert "作者正文停在" not in prompt2
    assert done["text"].endswith(compressed)          # 首句豁免 + 压缩稿
    assert len(done["text"]) <= int(700 * 1.6)


def test_route_stitch_compress_still_over_truncated_again(monkeypatch):
    """压缩产物仍超硬限 → 对压缩稿再句界截一次（吃压缩收益，不整段丢弃）。

    首句豁免下再截只动压缩稿部分，衔接首句永不被截。
    """
    text = "".join(_sents("檐水", 30))
    overlong_compress = "".join(_sents("压缩", 30))   # 压缩稿也 ~390 字
    req = StitchGhostRequest(
        fragment="他握紧刀。", mode="stitch",
        rolling_prefix="前文占位。", target_chars=120,
    )
    done, _, _ = _run_stitch(monkeypatch, req, [text, overlong_compress])

    body = done["text"]
    assert len(body) <= 180
    assert body.startswith(_sents("檐水", 30)[0])     # 衔接首句豁免（永不被截）
    assert _sents("压缩", 30)[0] in body               # 落屏含压缩稿的截取


def test_route_continue_overlong_compressed(monkeypatch):
    text = "".join(_sents("巷口", 40))
    compressed = "巷口压缩改写后的两句。"
    req = StitchGhostRequest(
        fragment="承接占位。", mode="continue",
        rolling_prefix="前" * 100, target_chars=200,
    )
    done, llm_calls, _ = _run_stitch(monkeypatch, req, [text, compressed])
    assert done["text"] == _sents("巷口", 40)[0] + compressed   # 首句豁免+压缩稿
    assert len(done["text"]) <= 320
    assert len(llm_calls) == 2


def test_route_stitch_mild_overrun_not_touched(monkeypatch):
    """轻微超字（≤×1.6）不动——130 字对 120 目标是句界自然收尾，别腰斩，
    也不白烧压缩调用。"""
    text = "他握紧刀。" + "檐下占位一句。" * 10   # 剥离后续写 70 字 < 192
    req = StitchGhostRequest(
        fragment="他握紧刀。", mode="stitch",
        rolling_prefix="前文占位。", target_chars=120,
    )
    done, llm_calls, _ = _run_stitch(monkeypatch, req, [text])
    assert done["text"] == "檐下占位一句。" * 10
    assert len(llm_calls) == 1                 # 未触发压缩


# ============================================================
# 5. 呈现平面洗层（三平面分权 P1/P2，2026-08-29）
# ============================================================

class _FakeBook:
    id = "bk-wash"


class _FakeDb:
    async def get(self, model, pk):
        return _FakeBook()


def _patch_prohibitions(monkeypatch, ps):
    import backend.services.style.prohibitions as prohib_mod
    from backend.services.style import ghost_wash  # noqa: F401

    async def _load(db=None, *, book=None, style_card=None, **kw):
        return ps
    monkeypatch.setattr(prohib_mod, "load_prohibition_set", _load)


def _run_stitch_wash(monkeypatch, req, llm_contents, ps):
    """洗层版 harness：真 db 替身（book 命中）+ 禁忌面注入 + 事件/语义打桩。"""
    from backend.routes.chapter_generation import adaptive as adaptive_route
    import backend.services.style.events as events_mod
    import backend.services.style.semantic_match as sem_mod

    events = []
    monkeypatch.setattr(events_mod, "append_style_event",
                        lambda *a, **k: events.append(a))
    async def _no_sem(text, ps_):
        return []
    monkeypatch.setattr(sem_mod, "semantic_scan_text", _no_sem)
    _patch_prohibitions(monkeypatch, ps)

    done, llm_calls, _traces = _run_stitch(monkeypatch, req, llm_contents)
    return done, llm_calls, events


def test_route_stitch_wash_replaces_blocker(monkeypatch):
    """P1：blocker+alternative 命中 → GHOST_DONE 文本已替换 + wash 增量字段。"""
    from backend.services.style.prohibitions import ProhibitionEntry, ProhibitionSet
    ps = ProhibitionSet((
        ProhibitionEntry(pattern="深邃", is_regex=False, alternative="沉静",
                         severity="blocker", source="test"),
    ))
    req = StitchGhostRequest(fragment="他握紧刀。", mode="stitch",
                             rolling_prefix="前文占位。", target_chars=400)
    # monkeypatch _run_stitch 内部桩 + 本测 db 替身：直调路由太重，改走 harness
    # 的 db 参数不可注入——用 route 层重跑（见下），此处先验证核心函数已单测。
    # 路由级：借 _run_stitch（db=None → 洗层 try 内 db.get 失败静默跳过），
    # 因此路由级断言用可注入 db 的直调。
    async def scenario():
        from backend.routes.chapter_generation import adaptive as adaptive_route
        import backend.services.style.events as events_mod
        import backend.services.style.semantic_match as sem_mod

        events = []
        monkeypatch.setattr(events_mod, "append_style_event",
                            lambda *a, **k: events.append(a))
        async def _no_sem(text, ps_):
            return []
        monkeypatch.setattr(sem_mod, "semantic_scan_text", _no_sem)
        _patch_prohibitions(monkeypatch, ps)

        async def fake_llm(system_prompt, user_prompt, **kw):
            return _Result("他的目光深邃如海，握紧了刀柄。")
        async def fake_assemble(**kw):
            ctx = _Ctx()
            ctx.sample_ids = ["s1", "s2"]
            return ctx
        async def fake_spine(cid, db):
            return []
        monkeypatch.setattr(adaptive_route, "call_llm_with_usage", fake_llm)
        monkeypatch.setattr(adaptive_route, "assemble_stitch_context", fake_assemble)
        monkeypatch.setattr(adaptive_route, "_spine_anchor_rows_for_prompt", fake_spine)
        monkeypatch.setattr(adaptive_route, "get_adaptive_recorder", lambda cid: _Rec())
        async def _flush(cid):
            return None
        monkeypatch.setattr(adaptive_route, "flush_adaptive_records", _flush)
        monkeypatch.setattr(adaptive_route, "bind_adaptive_trace", lambda cid: None)
        monkeypatch.setattr(adaptive_route, "trace_event", lambda *a, **k: None)
        monkeypatch.setattr(adaptive_route, "_style_drift_hint_for_heartbeat",
                            lambda ch, db: None)

        resp = await adaptive_route.stitch_ghost(CH, req, _FakeDb())
        frames = []
        async for chunk in resp.body_iterator:
            frames.append(chunk if isinstance(chunk, str) else chunk.decode("utf-8"))
        return frames, events

    import asyncio, json as _json
    frames, events = asyncio.run(scenario())
    done = None
    for f in frames:
        if f.startswith("data: "):
            payload = _json.loads(f[len("data: "):].strip())
            if payload.get("event") == "GHOST_DONE":
                done = payload

    assert done is not None
    assert "深邃" not in done["text"] and "沉静" in done["text"]
    wash = done["wash"]
    assert len(wash["hits"]) == 1 and wash["hits"][0]["replaced"]
    assert wash["original_text"].startswith("他的目光深邃")   # 原稿快照（用原稿用）
    assert done["sample_ids"] == ["s1", "s2"]                 # P5 埋点贯通
    assert any(e[1] == "ghost_wash" for e in events)          # style_events 落账


def test_route_stitch_wash_repair_residual(monkeypatch):
    """P2：残留 blocker（无替代词）→ 单次修补重试，严格验收（零残留才采纳）。"""
    from backend.services.style.prohibitions import ProhibitionEntry, ProhibitionSet
    ps = ProhibitionSet((
        ProhibitionEntry(pattern="指腹", is_regex=False, alternative=None,
                         severity="blocker", source="test"),
    ))
    req = StitchGhostRequest(fragment="他握紧刀。", mode="stitch",
                             rolling_prefix="前文占位。", target_chars=400)

    async def scenario():
        from backend.routes.chapter_generation import adaptive as adaptive_route
        import backend.services.style.events as events_mod
        import backend.services.style.semantic_match as sem_mod

        monkeypatch.setattr(events_mod, "append_style_event", lambda *a, **k: None)
        async def _no_sem(text, ps_):
            return []
        monkeypatch.setattr(sem_mod, "semantic_scan_text", _no_sem)
        _patch_prohibitions(monkeypatch, ps)

        calls = []

        async def fake_llm(system_prompt, user_prompt, **kw):
            calls.append(user_prompt)
            if len(calls) == 1:
                return _Result("他的指腹磨出茧，握紧了刀柄。")
            return _Result("他的指尖磨出茧，握紧了刀柄。")   # 修补稿：零残留
        async def fake_assemble(**kw):
            return _Ctx()
        monkeypatch.setattr(adaptive_route, "call_llm_with_usage", fake_llm)
        monkeypatch.setattr(adaptive_route, "assemble_stitch_context", fake_assemble)
        monkeypatch.setattr(adaptive_route, "_spine_anchor_rows_for_prompt",
                            lambda cid, db: None)
        monkeypatch.setattr(adaptive_route, "get_adaptive_recorder", lambda cid: _Rec())
        async def _flush(cid):
            return None
        monkeypatch.setattr(adaptive_route, "flush_adaptive_records", _flush)
        monkeypatch.setattr(adaptive_route, "bind_adaptive_trace", lambda cid: None)
        monkeypatch.setattr(adaptive_route, "trace_event", lambda *a, **k: None)
        monkeypatch.setattr(adaptive_route, "_style_drift_hint_for_heartbeat",
                            lambda ch, db: None)
        monkeypatch.setattr(adaptive_route, "_GHOST_REPAIR_TS", {})

        resp = await adaptive_route.stitch_ghost(CH, req, _FakeDb())
        frames = []
        async for chunk in resp.body_iterator:
            frames.append(chunk if isinstance(chunk, str) else chunk.decode("utf-8"))
        return frames, calls

    import asyncio, json as _json
    frames, calls = asyncio.run(scenario())
    done = None
    for f in frames:
        if f.startswith("data: "):
            payload = _json.loads(f[len("data: "):].strip())
            if payload.get("event") == "GHOST_DONE":
                done = payload

    assert done is not None
    assert len(calls) == 2                                  # 主生成 + 一次修补
    assert "指腹" in calls[1]                               # 修补指令点名禁词
    assert "指腹" not in done["text"] and "指尖" in done["text"]
    wash = done["wash"]
    assert wash["hits"] == [] and wash["original_text"] == ""  # 修补稿零命中


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


# ============================================================
# 6. 断点衔接首句豁免 + 半句尾缀复读剥离（2026-08-29 接缝断裂事故）
#    现场：logs/trace_adaptive_07136b7a（08-29 03:11 / 03:40 两次 stitch，
#    作者停在半句『…在这个世道，这句』，压缩改写把补完断点的首句当修饰删除，
#    上屏读作「在这个世道，这句扳手悬在传动轴旁…」）
# ============================================================

FRAG_MID = "这是林尘昨晚睡前翻书时撇到的话，在这个世道，这句"


def test_strip_tail_repeat_mid_sentence_break():
    """半句断点：模型从悬空处重启（复读原句尾缀）→ 剥尾缀，拼合恰成完整句。

    03:11 现场：画布『…在这个世道，这句』+ 产出『在这个世道，这句话连垫桌脚
    都嫌薄。…』——不剥则上屏重复「在这个世道，这句」两遍。
    """
    from backend.routes.chapter_generation.adaptive import _strip_fragment_prefix

    out = _strip_fragment_prefix(
        "在这个世道，这句话连垫桌脚都嫌薄。他把书按进口袋。", FRAG_MID
    )
    assert out == "话连垫桌脚都嫌薄。他把书按进口袋。"


def test_strip_tail_repeat_short_suffix():
    """短尾缀（『他握紧』）同样剥：拼合『他握紧刀，…』成完整句。"""
    from backend.routes.chapter_generation.adaptive import _strip_fragment_prefix

    out = _strip_fragment_prefix("他握紧刀，刀锋映出他通红的眼。", "他握紧")
    assert out == "刀，刀锋映出他通红的眼。"


def test_strip_no_tail_repeat_when_fragment_at_sentence_end():
    """断点在句末：产出同词开头是新句复用词汇，不是复读——不剥。"""
    from backend.routes.chapter_generation.adaptive import _strip_fragment_prefix

    out = _strip_fragment_prefix("他握紧刀把门闩上了。", "他握紧刀。")
    assert out == "他握紧刀把门闩上了。"


def test_strip_tail_repeat_keeps_following_punct():
    """切割点后的标点保留：『他握紧』+『。他退后半步。』拼合成自然句。

    剥掉反而腰斩（画布『…指节发白』+『，转身走了。』若剥逗号成连run-on）。
    """
    from backend.routes.chapter_generation.adaptive import _strip_fragment_prefix

    out = _strip_fragment_prefix("他握紧。他退后半步。", "他握紧")
    assert out == "。他退后半步。"


def test_split_first_sentence():
    from backend.routes.chapter_generation.adaptive import _split_first_sentence

    assert _split_first_sentence("话连垫桌脚都嫌薄。他把书按进口袋。") == (
        "话连垫桌脚都嫌薄。", "他把书按进口袋。",
    )
    # 无句读极端长句 → 空锚（调用方退整稿路径）
    assert _split_first_sentence("一条没有句读的长句拖着走") == ("", "一条没有句读的长句拖着走")


def test_route_seam_kept_when_compressor_drops_first_sentence(monkeypatch):
    """03:40 现场：压缩模型删掉补完断点的首句 → 首句豁免强制拼回，接缝存活。

    画布『…在这个世道，这句』+ 落屏『话像块锈铁卡在齿缝里。…』拼合恰为
    「在这个世道，这句话像块锈铁卡在齿缝里」——事故前压缩稿以「扳手悬在
    传动轴旁」开头，半句悬空直接跳到不相关画面。
    """
    draft = (
        "话像块锈铁卡在齿缝里。"
        + "他蹲在机甲传动轴旁边，扳手悬在半空，机油顺着指缝往袖口里渗。" * 7
    )   # 221 字 > 192
    kimi_compress = "扳手悬在传动轴旁，机油顺着指缝往袖口里渗。"   # 删了首句的压缩稿
    req = StitchGhostRequest(
        fragment=FRAG_MID, mode="stitch",
        rolling_prefix="前文占位。", target_chars=120,
    )
    done, llm_calls, _ = _run_stitch(monkeypatch, req, [draft, kimi_compress])

    assert done["text"].startswith("话像块锈铁卡在齿缝里。")   # 衔接首句豁免
    assert "扳手悬在传动轴旁" in done["text"]                   # 压缩稿内容保留
    assert "作者正文停在" in llm_calls[1]["user_prompt"]        # 压缩带断点坐标
    assert len(done["text"]) <= 192                              # ×1.6 硬上限


def test_route_seam_kept_with_tail_repeat_draft(monkeypatch):
    """03:11 现场：草稿复读断点尾缀 + 超字压缩两连 → 尾缀剥净 + 首句豁免。"""
    draft = (
        "在这个世道，这句话连垫桌脚都嫌薄。"
        + "林尘把书往口袋深处按了按。" * 15
    )   # 212 字；剥尾缀 10 字后 202 > 192 仍触发压缩
    compressed = "他把书按进口袋，传送带还在转。"
    req = StitchGhostRequest(
        fragment=FRAG_MID, mode="stitch",
        rolling_prefix="前文占位。", target_chars=120,
    )
    done, llm_calls, _ = _run_stitch(monkeypatch, req, [draft, compressed])

    body = done["text"]
    assert body.startswith("话连垫桌脚都嫌薄。")    # 补完句存活（豁免）
    assert "在这个世道，这句" not in body            # 尾缀复读已剥净
    assert "他把书按进口袋" in body                  # 压缩稿内容保留
    assert len(llm_calls) == 2


def test_route_seam_anchor_oversize_degrades_to_whole_text(monkeypatch):
    """首句吃掉大半配额（>×0.6）→ 豁免失去意义，退整稿压缩（仍带断点坐标）。"""
    giant_first = "一句没有任何句读的超长首句拖着走" * 10 + "。"   # 130 字 > 120×0.6
    draft = giant_first + "".join(_sents("檐水", 10))
    compressed = "压缩后的整稿两句。"
    req = StitchGhostRequest(
        fragment=FRAG_MID, mode="stitch",
        rolling_prefix="前文占位。", target_chars=120,
    )
    done, llm_calls, _ = _run_stitch(monkeypatch, req, [draft, compressed])

    assert done["text"] == compressed                      # 整稿路径：压缩稿直接落屏
    assert giant_first not in llm_calls[1]["user_prompt"].split("--- 草稿 ---")[0]  # 无锚句声明
    assert "作者正文停在" in llm_calls[1]["user_prompt"]    # 断点坐标仍在
