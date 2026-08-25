# Velluma - B2 spine 锚点进度判定单测（P2 治理，2026-08-25）
# AGPL-3.0
"""docs/adaptive-assist-hardening.md P2 · B2 的对拍：spine 锚点进度判定改走
text_match 共享判据 + 首轮只记基线 + 缓存键改内容 hash。

锁定的修复后行为：
1. 通用词噪声不再误 hit——旧判据 jieba topK=3 通用词（他/没有）散落在任何
   文本里全命中即 hit，写库不可逆（hit 只前进不回退）；
2. 首轮（orchestrator 内存态归零，_last_content_len=-1）只记基线长度不判定
   ——旧行为 growth=全文大面积误 hit；宁漏勿误，漏判有 finish spine_note 兜底；
3. 缓存键=内容 md5——旧键=内容长度，等长改写吃到旧缓存的旧进度；
4. 临近岔路（near_branches）保留宽松提示语义，走共享判据低阈值档（1/3）。

配方同 test_projection_freshness.py：独立 asyncio.run、UUID 带字母、
FakeChapter/FakeDB（判定路径自身的写库失败已有吞异常护栏，no-op 即可）。
运行：python -m pytest backend/services/adaptive/test_spine_progress.py -v
"""

import asyncio
import uuid

from backend.routes.chapter_generation.adaptive import (
    _SPINE_PROG_CACHE,
    _spine_progress_for_heartbeat,
)
from backend.services.adaptive.orchestrator import AdaptiveOrchestrator

CH_ID = str(uuid.UUID("bb250000-0000-4000-8000-0000000000c1"))


class _FakeDB:
    """commit/refresh 全 no-op——hit 写库路径按真实语义走一遍但不触真库。"""

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


class _FakeChapter:
    def __init__(self, spine, content):
        self.id = CH_ID
        self.spine = spine
        self.content_text = content


def _fresh_orch():
    """每用例独立 orchestrator + 清模块级缓存（防用例间串味）。"""
    _SPINE_PROG_CACHE.pop(CH_ID, None)
    return AdaptiveOrchestrator(db_factory=None, chapter_id=CH_ID)


def _anchor(text, **extra):
    return {"id": "a1", "text": text, "status": "pending", **extra}


# ============================================================
# B2-2：首轮只记基线，不判定
# ============================================================

def test_first_round_records_baseline_without_judging():
    """重启后首轮：正文早已含锚点原文也不判 hit（growth=全文的误 hit 不可逆）。"""
    content = "<p>林尘行至高山遇伏，亲卫折损过半，只得退守隘口。</p>" * 5
    chapter = _FakeChapter(
        {"anchors": [_anchor("高山遇伏")]}, content,
    )
    orch = _fresh_orch()

    prog = asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))
    assert prog is not None
    assert prog["anchors"][0]["status"] == "pending"      # 首轮不判定
    assert prog["pending_count"] == 1
    assert orch._last_content_len == len(content)          # 基线已记

    # 基线之后的真增量（含锚点原文）→ 判 hit
    chapter.content_text = content + "<p>次日再报：高山遇伏，粮道亦断。</p>"
    prog2 = asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))
    assert prog2["anchors"][0]["status"] == "hit"


# ============================================================
# B2-1：共享判据（3 字滑窗全片段命中），通用词噪声不再误 hit
# ============================================================

def test_generic_words_do_not_hit():
    """旧判据受害者：通用词（他/没有）散落增量区，不再拼凑成 hit。"""
    chapter = _FakeChapter({"anchors": [_anchor("他没有说")]}, "<p>前文铺垫。</p>")
    orch = _fresh_orch()
    asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))  # 首轮基线

    chapter.content_text = (
        "<p>前文铺垫。</p><p>他停顿了一下，终究没有把话说完，转身走了。</p>"
    )
    prog = asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))
    assert prog["anchors"][0]["status"] == "pending"      # 旧 jieba 判据此处必误 hit


def test_verbatim_anchor_hits():
    """锚点原文写进增量区 → hit（整串捷径 + 全片段命中同判）。"""
    chapter = _FakeChapter({"anchors": [_anchor("北岸密谈")]}, "<p>开头。</p>")
    orch = _fresh_orch()
    asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))

    chapter.content_text = "<p>开头。</p><p>当夜，两人在北岸密谈了半个时辰。</p>"
    prog = asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))
    assert prog["anchors"][0]["status"] == "hit"


def test_two_char_anchor_without_fragments_stays_pending():
    """<3 字锚点无可判片段：按未命中处理——2 字通用词裸子串命中正是旧噪声。"""
    chapter = _FakeChapter({"anchors": [_anchor("高山")]}, "<p>开头。</p>")
    orch = _fresh_orch()
    asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))

    chapter.content_text = "<p>开头。</p><p>他翻过高山往北去了。</p>"
    prog = asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))
    assert prog["anchors"][0]["status"] == "pending"


def test_growth_window_caps_far_text():
    """就近窗口：增量区超 SPINE_GROWTH_TAIL_CHARS 时窗口外老文本不参与判定。"""
    from backend.routes.chapter_generation.adaptive import SPINE_GROWTH_TAIL_CHARS

    chapter = _FakeChapter({"anchors": [_anchor("高山遇伏")]}, "<p>开头。</p>")
    orch = _fresh_orch()
    asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))  # 首轮基线

    # 锚点原文写在增量区开头，其后跟 >2000 字新文——窗口只看尾部，被更多
    # 新文推远的命中不参与判定（宁漏勿误：finish 报告 spine_note 兜底）
    filler = "风平浪静，无事发生。" * ((SPINE_GROWTH_TAIL_CHARS // 9) + 10)
    chapter.content_text = (
        "<p>开头。</p>"
        "<p>旧报里提过一句高山遇伏。</p>"
        f"<p>{filler}</p>"
    )
    prog = asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))
    assert prog["anchors"][0]["status"] == "pending"      # 窗口外的命中不算数


# ============================================================
# B2-3：缓存键=内容 hash（等长改写不再吃旧缓存）
# ============================================================

def test_equal_length_rewrite_invalidates_cache():
    """等长改写：旧键=长度会命中旧缓存（pending），新键=hash 重新判定出 hit。"""
    chapter = _FakeChapter({"anchors": [_anchor("北岸密谈")]}, "<p>一二三。</p>")
    orch = _fresh_orch()
    asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))  # 首轮基线

    # 增量不含锚点 → pending 进缓存
    chapter.content_text = "<p>一二三。</p><p>四五六十。</p>"
    prog = asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))
    assert prog["anchors"][0]["status"] == "pending"

    # 等长改写：锚点进尾段（len 与上一轮完全一致）
    chapter.content_text = "<p>一二三。</p><p>北岸密谈。</p>"
    assert len(chapter.content_text) == len("<p>一二三。</p><p>四五六十。</p>")
    prog2 = asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))
    assert prog2["anchors"][0]["status"] == "hit"


def test_same_content_served_from_cache():
    """内容未变 → 直接吃缓存（幂等；进度结构完整不缺字段）。"""
    chapter = _FakeChapter(
        {"intent": {"text": "退守北岸", "source": "author"},
         "anchors": [_anchor("北岸密谈")]},
        "<p>一二三。</p>",
    )
    orch = _fresh_orch()
    asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))
    chapter.content_text = "<p>一二三。</p><p>北岸密谈了半个时辰。</p>"
    prog1 = asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))
    prog2 = asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))
    assert prog1 == prog2
    assert prog2["intent"] == "退守北岸"
    assert prog2["anchors"][0]["status"] == "hit"
    assert prog2["pending_count"] == 0
    assert prog2["hint"] == "打算里的情节都写到了"


# ============================================================
# B2-4：临近岔路低阈值档（宽松提示语义保留）
# ============================================================

def test_near_branch_low_threshold_hint():
    """带岔路的锚点：单片段现身（1/3 档）→ near_branches 提示，状态不动。"""
    chapter = _FakeChapter(
        {"anchors": [_anchor("高山遇伏兵", branch={"options": ["死战", "退走"]})]},
        "<p>开头。</p>",
    )
    orch = _fresh_orch()
    asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))

    # 只含「高山遇」一个 3 字片段（1/3 命中率）——不到 hit 档，够提示档
    chapter.content_text = "<p>开头。</p><p>哨探回报：高山遇方向有烟尘。</p>"
    prog = asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))
    assert prog["anchors"][0]["status"] == "pending"      # 提示不等于兑现
    assert len(prog["near_branches"]) == 1
    assert prog["near_branches"][0]["options"] == ["死战", "退走"]


def test_near_branch_absent_without_evidence():
    """无任何片段现身 → 无 near_branches 键（静默缺席）。"""
    chapter = _FakeChapter(
        {"anchors": [_anchor("高山遇伏兵", branch={"options": ["死战", "退走"]})]},
        "<p>开头。</p>",
    )
    orch = _fresh_orch()
    asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))

    chapter.content_text = "<p>开头。</p><p>海面平静，商船如期抵港。</p>"
    prog = asyncio.run(_spine_progress_for_heartbeat(chapter, orch, _FakeDB()))
    assert "near_branches" not in prog
