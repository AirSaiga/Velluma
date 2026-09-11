# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - NLE-ADF 3.0 段落取源测试
"""2026-08-25 事故回归：挂件/感知锚定到已删除的旧事实。

事故链：作者 08-16 沉淀了机甲战斗段落 → 之后整段删掉重写为名言开场 →
dock_generator/canon_watch 的「作者当前段落」仍取 layer1 facts[-1]（旧战斗
段落），挂件全是已不存在文本的画面（且 content_text 尾部上百个空 <p> 使
HTML 原样截尾不可用）。修复后取源 = 心跳实时段 → 剥 HTML 的正文尾部，
层 1 事实不再参与。
"""
import asyncio
import json

from backend.services.adaptive.paragraph_source import resolve_current_paragraph

# 事故现场数据（形状还原）：正文 = 名言开场 + 大量尾部空段落
QUIET_OPENING = (
    "“一个人的力量是微薄的，世界的洪流不会因你而逆转；但只要你清醒地站着，"
    "你就没有被洪流淹没。”这是林尘昨晚睡前翻书时撇到的话，在这个世道，这句话"
)
STALE_FACT = (
    "一架C级机甲砸穿了三层楼板，右臂的转管炮还在旋转，炮口擦着林尘的头皮扫过去。"
    "他被气浪掀翻，滚进一堆货箱后面，耳朵里全是嗡鸣。"
)
SOUP = "<p></p>" * 120
QUIET_HTML = f"<p>{QUIET_OPENING}</p>{SOUP}"


# ============================================================
# 取源助手（纯算法）
# ============================================================

def test_live_recent_wins():
    # 实时段（作者正在写的）优先——即使正文里残留旧文本也盖不住
    got = resolve_current_paragraph(QUIET_OPENING, f"<p>{STALE_FACT}</p>{SOUP}")
    assert got == QUIET_OPENING


def test_content_tail_stripped_and_desouped():
    # 无实时段时回退正文尾部：HTML 剥标签、尾部空段落不成干扰
    got = resolve_current_paragraph("", QUIET_HTML)
    assert got == QUIET_OPENING


def test_none_and_whitespace_live():
    assert resolve_current_paragraph(None, QUIET_HTML) == QUIET_OPENING
    assert resolve_current_paragraph("   \n  ", QUIET_HTML) == QUIET_OPENING


def test_live_short_already_in_content_uses_content_tail():
    # 保存及时：短光标段已在画布尾里 → 用带上下文的画布尾（不重复拼接）
    got = resolve_current_paragraph("他抬起头。", f"<p>{QUIET_OPENING}他抬起头。</p>")
    assert got == QUIET_OPENING + "他抬起头。"


def test_live_short_not_in_content_fuses_tail_plus_live():
    # 保存滞后（2026-09-09 实测「接不上」）：短光标段还没落库 → 画布尾补
    # 上下文 + 实时光标段收尾——模型同时看见旧尾与新段，锚定不再滞后
    got = resolve_current_paragraph("“路上当心。”大爷咳了一声。", f"<p>{QUIET_OPENING}</p>")
    assert got == QUIET_OPENING + "“路上当心。”大爷咳了一声。"


def test_empty_live_in_empty_paragraph_returns_canvas_tail():
    # 光标在空新段（live 空）：纯画布尾，行为与旧版一致
    got = resolve_current_paragraph("", QUIET_HTML)
    assert got == QUIET_OPENING


def test_live_truncated_to_500():
    got = resolve_current_paragraph("字" * 600, QUIET_HTML)
    assert len(got) == 500
    assert got == "字" * 500


def test_insufficient_everywhere_returns_empty():
    assert resolve_current_paragraph("短句", "<p>也短</p>") == ""
    assert resolve_current_paragraph("", "") == ""


# ============================================================
# dock_generator.run 回归：层 1 旧事实不再进入「作者当前段落」
# ============================================================

class _Bundle:
    content_text = QUIET_HTML
    book_id = "b1"
    chapter_number = 1

    def nutrients(self):
        return {}

    def hard_constraints(self):
        return {}

    def soft_constraints(self):
        return {}


class _Result:
    def __init__(self, content):
        self.content = content


def _run_dock(monkeypatch, *, with_live: bool):
    from backend.services.adaptive.components import dock_generator as dg

    captured = {}

    async def fake_bundle(chapter_id, db):
        return _Bundle()

    async def fake_recall(db, **kw):
        return []

    async def fake_llm(system_prompt, user_prompt, **kw):
        captured["user"] = user_prompt
        part = json.dumps(
            {"parts": [{"type": "scene", "text": "工棚里机油混着旧书页的味道", "direction": "环境"}]},
            ensure_ascii=False,
        )
        return _Result(part)

    async def fake_spine(chapter_id, db):
        return ""

    class _Rec:
        def record_result(self, *a, **k):
            pass

    async def fake_cache(db, chapter_id, parts, guests=None):
        pass

    monkeypatch.setattr(dg, "load_chapter_settings_bundle", fake_bundle)
    monkeypatch.setattr(dg, "call_llm_with_usage", fake_llm)
    monkeypatch.setattr(dg, "get_adaptive_recorder", lambda cid: _Rec())
    monkeypatch.setattr(dg, "_spine_intent", fake_spine)
    monkeypatch.setattr(dg, "_cache_dock_parts", fake_cache)
    monkeypatch.setattr("backend.services.rag.recall.recall_memories", fake_recall)

    class _Repo:
        def __init__(self, db):
            pass

        async def set_dock_sig(self, chapter_id, sig):
            pass

    monkeypatch.setattr("backend.services.adaptive.world_model.WorldModelRepository", _Repo)

    # 快照里带着 08-16 的旧事实——修复前它会覆盖「作者当前段落」
    snapshot = {"facts": [{"text": STALE_FACT}], "projections": []}
    kw = {"recent_text": QUIET_OPENING[-60:]} if with_live else {}
    result = asyncio.run(dg.run("ch-test-1", None, snapshot, 1500, **kw))
    return result, captured["user"]


def test_dock_prompt_anchors_live_text_not_stale_fact(monkeypatch):
    result, user_prompt = _run_dock(monkeypatch, with_live=True)
    assert result == {"count": 1}
    assert "睡前翻书" in user_prompt          # 实时段（当前正写的名言开场）
    assert "转管炮" not in user_prompt        # 旧事实不得再进 prompt


def test_dock_prompt_content_fallback_without_live(monkeypatch):
    # 无实时段（旧调用方/异常路径）：回退剥 HTML 正文尾部，同样不吃旧事实
    result, user_prompt = _run_dock(monkeypatch, with_live=False)
    assert result == {"count": 1}
    assert "睡前翻书" in user_prompt
    assert "转管炮" not in user_prompt
