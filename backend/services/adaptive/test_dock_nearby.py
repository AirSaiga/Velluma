# Velluma - NLE-ADF 3.0 挂件就近生发单测
# AGPL-3.0
"""2026-08-25 就近铁律回归：挂件是「下一屏」的画面，不是章末预告。

事故：意图（血噬的觉醒）+ 养料（流光/白霆/红月/血噬）天然指向章末，
挂件一步跳到高潮场面（「白霆将红月机甲的检测报告推过桌面」）——作者
明明还在写开场名言。修复两道闸：prompt 就近铁律（system）+ 大纲就近
节拍注入（user，作者自己的大纲接下来 1-2 拍原文，纯算法判定已写）。

运行：python -m pytest backend/services/adaptive/test_dock_nearby.py -v
"""

import asyncio
import json

from backend.services.adaptive.components.dock_generator import _outline_nearby

# 事故章节的真实大纲（形状还原）
OUTLINE = """以罗曼·罗兰的巨著《约翰·克利斯朵夫》
“一个人的力量是微薄的，世界的洪流不会因你而逆转；但只要你清醒地站着，你就没有被洪流淹没。”
名言开篇
林尘喜欢读书，干着活的期间想到昨天晚上读到的内容，正在发愣，突然被工头打断
无奈自嘲自己的处境
不多时，基地遭到反抗组织的袭击
流光带领大批武装机甲侵入内部，他们得到情报意欲尚未的血噬"""

# 作者当前画布：只写到开场（名言 + 转述句）
WRITTEN_NOW = (
    "“一个人的力量是微薄的，世界的洪流不会因你而逆转；但只要你清醒地站着，"
    "你就没有被洪流淹没。”这是林尘昨晚睡前翻书时撇到的话"
)


# ============================================================
# 纯算法：_outline_nearby
# ============================================================

def test_nearby_picks_next_unwritten_beats():
    got = _outline_nearby(OUTLINE, WRITTEN_NOW)
    # 2026-09-03 卷首致辞过滤：出处行（含《》）与名言原文行（整行引语）是
    # 元信息不是节拍——旧断言把它们当第一拍，正是「致辞进意图块」事故本体。
    # 现在第一拍=工头打断，第二拍=自嘲处境
    assert len(got) == 2
    assert "工头打断" in got[0]
    assert "自嘲" in got[1]
    # 致辞/引语行进不了节拍供给
    assert all("罗曼" not in b and "一个人的力量" not in b for b in got)
    # 远处的袭击/机甲侵入不得出现在就近节拍里
    assert all("袭击" not in b and "侵入" not in b for b in got)


def test_nearby_advances_as_author_writes():
    written_later = WRITTEN_NOW + "\n\n" + \
        "以罗曼·罗兰的巨著《约翰·克利斯朵夫》里的话开篇。" + \
        "林尘喜欢读书，干着活的期间想到昨天晚上读到的内容，正在发愣，突然被工头打断。"
    got = _outline_nearby(OUTLINE, written_later)
    assert got and "自嘲" in got[0]


def test_nearby_empty_when_no_outline_or_all_written():
    assert _outline_nearby("", WRITTEN_NOW) == []
    assert _outline_nearby(None, WRITTEN_NOW) == []
    # 结构性短行（名言开篇）无可判片段按已写跳过；唯一行已写 → 空
    assert _outline_nearby("名言开篇\n" + WRITTEN_NOW, WRITTEN_NOW) == []


# ============================================================
# prompt 集成：铁律入 system、节拍入 user、无大纲零变化
# ============================================================

class _Bundle:
    book_id = "b1"
    chapter_number = 1
    content_text = f"<p>{WRITTEN_NOW}</p>" + "<p></p>" * 30
    outline_text = OUTLINE
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


def _run_dock(monkeypatch, bundle):
    from backend.services.adaptive.components import dock_generator as dg

    captured = {}

    async def fake_bundle(chapter_id, db):
        return bundle

    async def fake_llm(system_prompt, user_prompt, **kw):
        captured["system"] = system_prompt
        captured["user"] = user_prompt
        part = json.dumps(
            {"parts": [{"type": "line", "text": "“林尘！发什么呆！手别停！”工头的呵斥", "direction": "主线"}]},
            ensure_ascii=False,
        )
        return _Result(part)

    async def fake_spine(chapter_id, db):
        return ""

    async def fake_recall(db, **kw):
        return []

    async def fake_cache(db, chapter_id, parts):
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

    snapshot = {"facts": [], "live_facts": [], "projections": []}
    result = asyncio.run(dg.run("ch-nearby-1", None, snapshot, 1500, recent_text=WRITTEN_NOW))
    return result, captured


def test_dock_prompt_carries_nearby_discipline(monkeypatch):
    result, captured = _run_dock(monkeypatch, _Bundle())
    assert result == {"count": 1}
    # system：就近铁律在
    assert "下一屏" in captured["system"]
    assert "绝不提前搬上来" in captured["system"]
    # system：文流第一（2026-08-26 定位修正——碎片贴文流，节拍是目的地非内容）
    assert "文流第一" in captured["system"]
    # 2026-08-27 导师裁决：旧「绝不直接呈现节拍场面」升级为节拍保全检验
    assert "节拍保全检验" in captured["system"]
    assert "写不坏节拍的才是第一步" in captured["system"]
    # system：场景锚定铁律在（2026-08-26 实测补强；08-27 道具两分——氛围件/上手件）
    assert "道具分两类" in captured["system"]
    assert "上手件" in captured["system"]
    assert "不复述已写" in captured["system"]
    assert "空间不瞬移" in captured["system"]
    assert "保底本场景" in captured["system"]
    # user：作者大纲·就近节拍块带出工头打断拍
    assert "作者大纲·就近节拍" in captured["user"]
    assert "工头打断" in captured["user"]
    # 远处节拍（袭击/侵入）不进 prompt（养料块除外——那是设定素材不是剧情）
    nearby_zone = captured["user"].split("# 作者大纲·就近节拍")[1].split("# 接下来的画面方向")[0]
    assert "袭击" not in nearby_zone and "侵入" not in nearby_zone


def test_dock_prompt_zero_change_without_outline(monkeypatch):
    class _NoOutlineBundle(_Bundle):
        outline_text = ""

    _, captured = _run_dock(monkeypatch, _NoOutlineBundle())
    assert "作者大纲·就近节拍" not in captured["user"]   # 无大纲 → 块缺席
    assert "下一屏" in captured["system"]                # 铁律仍生效（通用约束）


# ============================================================
# 句子级闸门：半句悬停挂件闭嘴，Tab 点名豁免
# ============================================================

def test_ends_mid_sentence():
    from backend.services.adaptive.paragraph_source import ends_mid_sentence

    assert ends_mid_sentence("在这个世道，这句话") is True          # 半句悬着
    assert ends_mid_sentence("他把扳手放在了桌上") is True          # 无句末标点
    assert ends_mid_sentence("") is False                          # 空段=段界不是半句
    assert ends_mid_sentence("   ") is False                       # 纯空白同空段
    assert ends_mid_sentence("这句话值得被贴在墙上。") is False
    assert ends_mid_sentence("“手别停！”工头吼道。") is False
    assert ends_mid_sentence("“……就这样。”") is False              # 收尾引号
    assert ends_mid_sentence("他停住了……") is False                 # 省略号收束


def _gate_state(recent: str, summoned: bool = False):
    from backend.services.adaptive.change_detector import AuthorState
    return AuthorState(
        chapter_id="ch-gate-1", word_count=500, paused_ms=4001,
        cursor_at_paragraph_end=True, recent_text=recent, summoned=summoned,
    )


def test_decide_sentence_gate_blocks_and_summon_overrides():
    from backend.services.adaptive.orchestrator import AdaptiveOrchestrator

    orch = AdaptiveOrchestrator(db_factory=None, chapter_id="ch-gate-1")
    snap = {"intent": {"source": "inferred", "confidence": 0.6},
            "projections": [], "fact_count": 0, "total_words": 0}

    # 半句悬停 → 不激活 dock_generator
    acts = orch._decide(_gate_state("在这个世道，这句话"), snap, [])
    assert all(a.component != "dock_generator" for a in acts)

    # 句子写完 → 正常激活
    acts2 = orch._decide(_gate_state("这句话值得被贴在墙上。"), snap, [])
    assert any(a.component == "dock_generator" for a in acts2)

    # 写完一段回车进空新段（段界）→ 正常激活：空段不是半句，
    # 挂件锚定文本由 resolve_current_paragraph 回退画布尾
    acts_empty = orch._decide(_gate_state(""), snap, [])
    assert any(a.component == "dock_generator" for a in acts_empty)

    # 半句但 Tab 显式点名 → 豁免（作者主权）
    acts3 = orch._decide(_gate_state("在这个世道，这句话", summoned=True), snap, [])
    assert any(a.component == "dock_generator" for a in acts3)
