# Velluma - NLE-ADF 3.0 层 1 事实活性 + 画布取源单测
# AGPL-3.0
"""2026-08-25 加固回归：画布即事实源贯穿世界模型读取侧。

覆盖三层：
1. 纯函数：written_text（HTML 剥除/空段汤/段落拼接口径）+ normalize_for_match；
2. 真实 repo 栈（临时文件 SQLite）：snapshot 派生活性——活事实计入
   fact_count/total_words/live_facts，删改后过期、贴回来复活（不回写）；
   append_fact 连续同段精确去重；
3. 组件回归（LLM-mock）：future_projection / intent_inference 的 prompt
   锚定画布全文，层 1 过期事实不再进入；post_process._get_full_text
   返回画布纯文本（完稿审计对象=真实正文）。

配方同 test_chapter_style_override.py：独立 asyncio.run、UUID 带字母。
运行：python -m pytest backend/services/adaptive/test_world_model_liveness.py -v
"""

import asyncio
import json
import uuid

import pytest

from backend.services.adaptive.paragraph_source import (
    normalize_for_match,
    written_text,
)

# 事故现场数据（形状还原）——≥100 字：intent_inference 的正文闸
QUIET_TEXT = (
    "“一个人的力量是微薄的，世界的洪流不会因你而逆转；但只要你清醒地站着，"
    "你就没有被洪流淹没。”这是林尘昨晚睡前翻书时撇到的话，在这个世道，"
    "这句话值得被贴在工棚的每一面墙上。工地的轰鸣把它震得七零八落，"
    "只剩下最后半句还挂在林尘嘴边，混着机油味一起被咽了回去。"
)
STALE_TEXT = (
    "一架C级机甲砸穿了三层楼板，右臂的转管炮还在旋转，炮口擦着林尘的头皮扫过去。"
    "他被气浪掀翻，滚进一堆货箱后面，耳朵里全是嗡鸣。"
)
SOUP = "<p></p>" * 120
QUIET_HTML = f"<p>{QUIET_TEXT}</p>{SOUP}"

BOOK_ID = uuid.UUID("aa110000-0000-4000-8000-000000000001")
CH_ID = uuid.UUID("aa110000-0000-4000-8000-0000000000c1")


# ============================================================
# 1. 纯函数
# ============================================================

def test_written_text_strips_html_and_soup():
    got = written_text(QUIET_HTML)
    assert got == QUIET_TEXT


def test_written_text_joins_paragraphs():
    got = written_text("<p>第一段。</p><p>第二段。</p>")
    assert got == "第一段。\n\n第二段。"


def test_written_text_empty():
    assert written_text("") == ""
    assert written_text(SOUP) == ""


def test_normalize_for_match_removes_all_whitespace():
    assert normalize_for_match("一 个\n人\t的力 量") == "一个人的力量"
    assert normalize_for_match(None) == ""


# ============================================================
# 2. 真实 repo 栈：snapshot 派生活性 + append 去重
# ============================================================

def _make_stack(tmp_path):
    from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
    from backend.db_sqlite.schema import init_db_sqlite

    engine = build_sqlite_engine(tmp_path / "liveness.db")
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


async def _seed(session):
    import backend.models as m
    session.add(m.Book(id=BOOK_ID, title="活性测试书"))
    session.add(m.Chapter(
        id=CH_ID, book_id=BOOK_ID, chapter_number=1,
        title="第一章", content_text=QUIET_HTML,
    ))
    await session.flush()


def _fact(text, wc=None):
    return {"text": text, "entities": [], "state_changes": [],
            "settled_at": 1_700_000_000.0, "word_count": wc if wc is not None else len(text)}


def test_snapshot_liveness_roundtrip(tmp_path):
    from backend.services.adaptive.world_model import WorldModelRepository, SettledSegment

    engine, maker = _make_stack(tmp_path)

    async def scenario():
        async with maker() as s:
            await _seed(s)
            repo = WorldModelRepository(s)
            # 活事实（画布子串，含多余空白——规范化后仍命中）
            await repo.append_fact(CH_ID, SettledSegment(text=QUIET_TEXT + "\n", word_count=len(QUIET_TEXT)))
            # 过期事实（作者已删改掉的旧段落）×2
            await repo.append_fact(CH_ID, SettledSegment(text=STALE_TEXT))
            await repo.append_fact(CH_ID, SettledSegment(text=STALE_TEXT + "（改）"))
            await s.commit()

            snap = await repo.snapshot(CH_ID)
            assert snap["fact_count"] == 1
            assert snap["total_words"] == len(QUIET_TEXT)
            assert len(snap["live_facts"]) == 1
            assert snap["stale_fact_count"] == 2
            # facts 原样全量返回（沉淀历史语义）
            assert len(snap["facts"]) == 3

    asyncio.run(scenario())
    asyncio.run(engine.dispose())


def test_snapshot_fact_revives_when_text_readded(tmp_path):
    """活性是派生态：作者把删掉的段落贴回来，事实自动复活（无回写）。"""
    import backend.models as m
    from backend.services.adaptive.world_model import WorldModelRepository, SettledSegment

    engine, maker = _make_stack(tmp_path)

    async def scenario():
        async with maker() as s:
            await _seed(s)
            repo = WorldModelRepository(s)
            await repo.append_fact(CH_ID, SettledSegment(text=STALE_TEXT))
            await s.commit()
            snap = await repo.snapshot(CH_ID)
            assert snap["fact_count"] == 0 and snap["stale_fact_count"] == 1

            ch = await s.get(m.Chapter, CH_ID)
            ch.content_text = f"<p>{QUIET_TEXT}</p><p>{STALE_TEXT}</p>"
            await s.commit()

            snap2 = await repo.snapshot(CH_ID)
            assert snap2["fact_count"] == 1 and snap2["stale_fact_count"] == 0

    asyncio.run(scenario())
    asyncio.run(engine.dispose())


def test_snapshot_empty_canvas_marks_all_stale(tmp_path):
    from backend.services.adaptive.world_model import WorldModelRepository, SettledSegment

    engine, maker = _make_stack(tmp_path)

    async def scenario():
        async with maker() as s:
            await _seed(s)
            repo = WorldModelRepository(s)
            await repo.append_fact(CH_ID, SettledSegment(text=STALE_TEXT))
            # 作者清空整章（只剩空段汤）
            import backend.models as m
            ch = await s.get(m.Chapter, CH_ID)
            ch.content_text = SOUP
            await s.commit()
            snap = await repo.snapshot(CH_ID)
            assert snap["fact_count"] == 0 and snap["stale_fact_count"] == 1

    asyncio.run(scenario())
    asyncio.run(engine.dispose())


def test_append_fact_exact_dedup(tmp_path):
    from backend.services.adaptive.world_model import WorldModelRepository, SettledSegment

    engine, maker = _make_stack(tmp_path)

    async def scenario():
        async with maker() as s:
            await _seed(s)
            repo = WorldModelRepository(s)
            await repo.append_fact(CH_ID, SettledSegment(text=STALE_TEXT))
            # 4 秒内连续沉淀同段（事故现场）——只记一条
            await repo.append_fact(CH_ID, SettledSegment(text=STALE_TEXT + " "))
            await s.commit()
            snap = await repo.snapshot(CH_ID)
            assert len(snap["facts"]) == 1

    asyncio.run(scenario())
    asyncio.run(engine.dispose())


# ============================================================
# 3. 组件回归：prompt 锚定画布，过期事实出局
# ============================================================

class _Bundle:
    book_id = "b1"
    chapter_number = 1
    content_text = QUIET_HTML
    outline_text = ""          # 空 → intent_inference 走 LLM 反推路径
    chapter_card = None

    def nutrients(self):
        return {}

    def hard_constraints(self):
        return {}

    def soft_constraints(self):
        return {}


class _Result:
    def __init__(self, content):
        self.content = content


class _Rec:
    def record_result(self, *a, **k):
        pass


STALE_SNAPSHOT = {
    "facts": [{"text": STALE_TEXT}, {"text": STALE_TEXT + "（改）"}],
    "live_facts": [],
    "intent": {"source": "inferred", "confidence": 0.6, "arc": "觉醒", "must_hits": [], "foreshadows": []},
    "projections": [],
}


def test_future_projection_prompt_uses_canvas(tmp_path, monkeypatch):
    from backend.services.adaptive.components import future_projection as fp

    captured = {}

    async def fake_bundle(chapter_id, db):
        return _Bundle()

    async def fake_llm(system_prompt, user_prompt, **kw):
        captured["user"] = user_prompt
        return _Result(json.dumps({"projections": [
            {"event": "工头打断发愣", "anchors": ["林尘"], "emotion": "无奈"},
        ]}, ensure_ascii=False))

    class _Repo:
        def __init__(self, db):
            pass

        async def set_projections(self, chapter_id, projections):
            captured["proj_count"] = len(projections)

    monkeypatch.setattr(fp, "load_chapter_settings_bundle", fake_bundle)
    monkeypatch.setattr(fp, "call_llm_with_usage", fake_llm)
    monkeypatch.setattr(fp, "get_adaptive_recorder", lambda cid: _Rec())
    monkeypatch.setattr(fp, "WorldModelRepository", _Repo)

    result = asyncio.run(fp.run(str(CH_ID), None, dict(STALE_SNAPSHOT), 1500))
    assert result == {"count": 1}
    assert "睡前翻书" in captured["user"]        # 画布全文（剥 HTML、去空段汤）
    assert "转管炮" not in captured["user"]      # 过期事实不进 prompt
    assert "<p>" not in captured["user"]         # HTML 标签不进 prompt


def test_intent_inference_prompt_uses_canvas(monkeypatch):
    from backend.services.adaptive.components import intent_inference as ii

    captured = {}

    async def fake_bundle(chapter_id, db):
        return _Bundle()

    async def fake_llm(system_prompt, user_prompt, **kw):
        captured["user"] = user_prompt
        return _Result(json.dumps({"arc": "名言开篇的觉醒前夜", "emotion_curve": []}, ensure_ascii=False))

    class _Repo:
        def __init__(self, db):
            pass

        async def set_intent(self, chapter_id, intent):
            pass

    monkeypatch.setattr(ii, "load_chapter_settings_bundle", fake_bundle)
    monkeypatch.setattr(ii, "call_llm_with_usage", fake_llm)
    monkeypatch.setattr(ii, "get_adaptive_recorder", lambda cid: _Rec())
    monkeypatch.setattr(ii, "WorldModelRepository", _Repo)

    result = asyncio.run(ii.run(str(CH_ID), None, dict(STALE_SNAPSHOT), 1500))
    assert result["source"] == "inferred"
    assert "睡前翻书" in captured["user"]
    assert "转管炮" not in captured["user"]
    assert "<p>" not in captured["user"]


def test_intent_inference_skips_when_canvas_thin(monkeypatch):
    from backend.services.adaptive.components import intent_inference as ii

    class _ThinBundle(_Bundle):
        content_text = "<p>太短</p>"

    async def fake_bundle(chapter_id, db):
        return _ThinBundle()

    called = {"llm": False}

    async def fake_llm(*a, **k):
        called["llm"] = True
        return _Result("{}")

    monkeypatch.setattr(ii, "load_chapter_settings_bundle", fake_bundle)
    monkeypatch.setattr(ii, "call_llm_with_usage", fake_llm)
    # 层 1 有大段旧事实也不得救场（曾致反推被已删除文本带偏）
    result = asyncio.run(ii.run(str(CH_ID), None, dict(STALE_SNAPSHOT), 1500))
    assert result == {"skipped": True, "reason": "正文不足"}
    assert called["llm"] is False


def test_post_process_full_text_is_canvas():
    from backend.services.adaptive.components.post_process import _get_full_text

    got = _get_full_text(_Bundle())
    assert got == QUIET_TEXT          # 完稿审计对象=真实正文（剥 HTML）
    assert "转管炮" not in got
