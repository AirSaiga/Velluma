# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 卡片舱「地面+重力场」在场制对拍（2026-09-08 红队审查施工）
"""
在场宇宙投影 / 情境模板 / 低频在场键 / T3 边界影子检 的纯函数与集成对拍。

背景（红队审查报告 R1-R4）：dock 曾是唯一不注入场景身份的生成路径——
凭空道具三通道（氛围件豁免/上手件出处含全书养料池/模型不知作者在哪）。
本文件锁定：

1. onstage_projection：在场（场景钉作用域∪存活）∪ 段落提及；私有不进册；
   legacy 书恒 None（零变化契约）；全空 → None（退化梯子）；
2. pick_shot_template：dialogue（同一把尺子复用）/combat/panorama/default；
3. presence_fingerprint：钉 id+叙事锚，空值恒定；
4. find_onstage_boundary_hits：非在册名×上手动词 → 影子命中；提及豁免；
5. 发电机对白场景集成（mocked run）：在册块+三档+对白分镜进 prompt、
   prop 的 anchor_ref 回查拼 note、越界件只落台账不丢件。

运行：python -m pytest backend/services/adaptive/test_dock_onstage.py -v
"""

import asyncio
import json
from types import SimpleNamespace

from backend.services.adaptive.components.dock_generator import (
    DOCK_PIPELINE_VERSION,
    detect_guest_names,
    ends_in_dialogue,
    find_onstage_boundary_hits,
    onstage_projection,
    pick_shot_template,
    presence_fingerprint,
)


# ============================================================
# 造假：world 桥适配器形状（鸭子类型——onstage_projection 三态取名）
# ============================================================

class _WEnt:
    def __init__(self, eid, name, aliases=None, dyn="", private=False):
        self.name = name
        self.entity_id = eid
        self.aliases = aliases or []
        self.world_entity = SimpleNamespace(id=eid, visibility="private" if private else "public")
        self.character = SimpleNamespace(dynamic_state=dyn)


class _WEntAdapter:
    """WorldEntityAdapter 真实形状（2026-09-09 实测事故）：**没有顶层 .name**
    ——名字/别名挂在 .character 命名空间下（_Ns）。08-26 canon_watch 同款坑
    的复发锁：onstage 取名读顶层致在册人物恒空。"""
    def __init__(self, eid, name, dyn="", aliases=None):
        self.world_entity = SimpleNamespace(id=eid, visibility="public")
        self.character = SimpleNamespace(name=name, dynamic_state=dyn, aliases=aliases or [])


class _WAsset:
    def __init__(self, name, desc="", private=False):
        self.name = name
        self.static_description = desc
        self.world_entity = SimpleNamespace(id=name, visibility="private" if private else "public")


def _loc(eid, name, intro="", parent=None):
    return SimpleNamespace(id=eid, name=name, intro=intro, parent_id=parent)


def _bundle(entities, assets, locations, char_states, world_sourced=True):
    return SimpleNamespace(
        world_sourced=world_sourced,
        world_state={"character_states": char_states},
        entities=entities,
        assets=assets,
        locations=locations,
    )


# 树：北岸要塞(loc-1) ← 机房(loc-2)；远端哨塔(loc-3)
_LOCS = [_loc("loc-1", "北岸要塞"), _loc("loc-2", "机房", intro="铁皮机房，柴油味重", parent="loc-1"),
         _loc("loc-3", "哨塔")]
_STATES = [
    {"entity_id": "e-lin", "alive": True, "location_id": "loc-2"},   # 机房在场
    {"entity_id": "e-zhou", "alive": True, "location_id": "loc-3"},  # 哨塔——不在场
    {"entity_id": "e-dead", "alive": False, "location_id": "loc-2"},  # 死者不进在场集
]


class TestOnstageProjection:

    def test_present_union_mention(self):
        b = _bundle(
            entities=[
                _WEnt("e-lin", "林尘", dyn="此刻位于机房"),
                _WEnt("e-zhou", "老周"),                # 哨塔——但段落提及即在场
                _WEnt("e-dead", "老指挥官"),            # 死者且未提及 → 场外
            ],
            assets=[_WAsset("发电机", "机房尽头的老柴油机"), _WAsset("脚手架")],
            locations=_LOCS, char_states=_STATES,
        )
        view = onstage_projection(b, "loc-2", "老周咳嗽着问发电机的事")
        assert view is not None
        names = [e["name"] for e in view["entities"]]
        assert "林尘" in names          # 场景钉作用域内存活
        assert "老周" in names           # 提及兜底
        assert "老指挥官" not in names   # 死者不进在场集
        assert [p["name"] for p in view["props"]] == ["发电机"]   # 资产提及即在场
        assert "脚手架" in view["offstage_assets"]
        assert view["scene_line"].startswith("机房——铁皮机房")

    def test_carry_over_props_across_transit(self):
        """第三弹「上手即随行」：光标前扫描窗（≈2000 字）内提及过的资产在册——
        上一场的工具包换到新场景后不被物理抹杀；onstage 的提及窗参数即随行面
        （dock run 侧传入 pre_cursor 窗，见 run 的 mention_window）。"""
        window = (
            "他在机房里翻出工具包，把扳手别回侧袋。"      # 上一场（提及工具包/扳手）
            + "闲话了几句。" * 80                          # 拉开距离（>500 字旧窗）
            + "他推门进了哨塔，风灌进来。"
        )
        b = _bundle(
            entities=[_WEnt("e-lin", "林尘")],
            assets=[_WAsset("工具包"), _WAsset("脚手架")],
            locations=_LOCS,
            char_states=[{"entity_id": "e-lin", "alive": True, "location_id": "loc-3"}],
        )
        view = onstage_projection(b, "loc-3", window)
        assert view is not None
        assert [p["name"] for p in view["props"]] == ["工具包"]  # 随行入册
        assert "脚手架" in view["offstage_assets"]               # 未提及仍在场外

    def test_ancestor_scope_counts_as_present(self):
        """钉到房间（loc-2）时祖先（loc-1 要塞）上的角色也算在场。"""
        states = [{"entity_id": "e-guard", "alive": True, "location_id": "loc-1"}]
        b = _bundle([_WEnt("e-guard", "哨兵")], [], _LOCS, states)
        view = onstage_projection(b, "loc-2", "")
        assert [e["name"] for e in view["entities"]] == ["哨兵"]

    def test_private_excluded(self):
        b = _bundle([_WEnt("e-x", "暗桩", private=True)], [_WAsset("密匣", private=True)],
                    _LOCS, [{"entity_id": "e-x", "alive": True, "location_id": "loc-2"}])
        view = onstage_projection(b, "loc-2", "暗桩把密匣推了过来")
        assert view["entities"] == [] and view["props"] == []

    def test_adapter_shape_without_toplevel_name(self):
        """角色适配器名字在 character 命名空间（无顶层 .name）——在册照常命中。"""
        b = _bundle([_WEntAdapter("e-lin", "林尘", dyn="位于村子")], [], _LOCS,
                    [{"entity_id": "e-lin", "alive": True, "location_id": "loc-2"}])
        view = onstage_projection(b, "loc-2", "")
        assert view is not None
        assert [e["name"] for e in view["entities"]] == ["林尘"]
        assert view["offstage_characters"] == []

    def test_legacy_and_empty_return_none(self):
        legacy = _bundle([], [], _LOCS, [], world_sourced=False)
        assert onstage_projection(legacy, "loc-2", "林尘提到发电机") is None  # 零变化契约
        empty = _bundle([], [], _LOCS, [])
        assert onstage_projection(empty, "", "") is None                     # 退化梯子


class TestPickShotTemplate:

    def test_dialogue_uses_shared_ruler(self):
        tail = "老周咳嗽着问：「这发电机还能修好吗？」林尘没抬头：「得看皮带。」老周又咳了一声。"
        assert pick_shot_template(tail) == "dialogue"

    def test_combat_by_gesture_density(self):
        tail = "他挥拳砸向对方面门，对方侧身避开，又一记肘撞撞在他肋上，他踉跄摔进桌角。"
        assert pick_shot_template(tail) == "combat"

    def test_panorama_entry_gesture_with_scene(self):
        assert pick_shot_template("他走进机房。", scene_line="机房——铁皮机房") == "panorama"
        # 无场景行 → 不判 panorama（定场质感无源）
        assert pick_shot_template("他走进机房。") == "default"

    def test_default_fallback(self):
        assert pick_shot_template("林尘想着昨晚读过的那一页。") == "default"
        assert pick_shot_template("") == "default"


class TestPresenceFingerprint:

    def test_low_frequency_key(self):
        assert presence_fingerprint("loc-2", 1520) == "loc-2:1520"
        assert presence_fingerprint(None, None) == "-:0"      # 无钉书恒定 → 零失效增量
        assert presence_fingerprint("loc-2", 1520) != presence_fingerprint("loc-1", 1520)


class TestOnstageBoundaryShadow:

    def test_offstage_name_with_interaction_verb_hits(self):
        hits = find_onstage_boundary_hits(
            "他拿起脚手架上的扳手", ["脚手架", "发电机"], ["发电机"], "老周问发电机")
        assert hits == [("脚手架", "拿")]

    def test_mentioned_and_onstage_exempt(self):
        # 正文已提及名豁免（作者自己写的不算编造）；在册名不触发
        assert find_onstage_boundary_hits("他把脚手架挪开", ["脚手架"], [], "正文里有脚手架") == []
        assert find_onstage_boundary_hits("他握住发电机的手柄", ["发电机"], ["发电机"], "") == []


# ============================================================
# 发电机对白场景集成（mocked run）：地面+重力场+分镜组全链贯通
# ============================================================

class _Result:
    def __init__(self, content):
        self.content = content


class _Rec:
    def record_result(self, *a, **k):
        pass


class _WorldBundle:
    book_id = "b-onstage"
    chapter_number = 3
    content_text = "<p>老周咳嗽着问：「这发电机还能修好吗？」林尘没抬头，手里的活没停。</p>" + "<p></p>" * 30
    outline_text = ""
    chapter_card = None
    world_sourced = True
    world_state = {"character_states": [
        {"entity_id": "e-lin", "alive": True, "location_id": "loc-2"},
        {"entity_id": "e-zhou", "alive": True, "location_id": "loc-3"},
    ]}
    entities = [_WEnt("e-lin", "林尘", dyn="此刻位于机房"), _WEnt("e-zhou", "老周")]
    assets = [_WAsset("发电机", "机房尽头的老柴油机"), _WAsset("脚手架", "工地临时租来的")]
    locations = _LOCS

    def nutrients(self):
        return {}

    def hard_constraints(self):
        return {}

    def soft_constraints(self):
        return {}


_RECENT = "老周咳嗽着问：「这发电机还能修好吗？」林尘没抬头，手里的活没停：「得看皮带。」老周又咳了一声。"

_PARTS = {
    "parts": [
        {"slot": "landing", "type": "action", "text": "林尘把掌心贴上发烫的外壳"},
        {"slot": "reply", "type": "action", "text": "他把到嘴边的答复咽了回去"},
        {"slot": "prop", "type": "scene", "text": "皮带在轮槽里打着滑", "anchor_ref": 3},
        {"slot": "ambient", "type": "action", "text": "他抄起脚手架上的短管", "direction": "环境"},
    ]
}


def _run_onstage_dock(monkeypatch, llm_parts, recent=None, snapshot=None, word_count=None,
                      suffix_anchor=None):
    from backend.services.adaptive.components import dock_generator as dg

    captured = {}

    async def fake_bundle(chapter_id, db):
        return _WorldBundle()

    async def fake_llm(system_prompt, user_prompt, **kw):
        captured["system"] = system_prompt
        captured["user"] = user_prompt
        return _Result(json.dumps(llm_parts, ensure_ascii=False))

    async def fake_spine(chapter_id, db):
        return ""

    async def fake_recall(db, **kw):
        return []

    async def fake_cache(db, chapter_id, parts, guests=None):
        captured["cached"] = parts
        captured["guests"] = guests or []

    events = []

    import backend.services.constraints.events as ce
    monkeypatch.setattr(ce, "log_constraint_event",
                        lambda *a, **k: events.append((a, k)))

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

    snap = snapshot or {"facts": [], "live_facts": [], "projections": []}
    extra = {"recent_text": _RECENT if recent is None else recent}
    if word_count is not None:
        extra["word_count"] = word_count
    if suffix_anchor is not None:
        extra["suffix_anchor"] = suffix_anchor
    # db=None：场景钉取数静默失败 → 纯提及制在场
    result = asyncio.run(dg.run("ch-onstage-1", None, snap, 1500, **extra))
    return result, captured, events


def test_generator_dialogue_scene_end_to_end(monkeypatch):
    result, captured, events = _run_onstage_dock(monkeypatch, _PARTS)
    assert result == {"count": 4}
    # 地面：三档物质性 + 在册坐标系（提及制：林尘/老周/发电机均被提及）
    assert "道具三档" in captured["system"]
    assert "本场在册" in captured["user"]
    assert "[1] 林尘" in captured["user"]
    assert "发电机" in captured["user"]
    assert "场外物件：脚手架" in captured["user"]
    # 分镜组：对白模板分派（同一把尺子判 dialogue）
    assert "slot=reply【接话缓冲】" in captured["system"]
    # 重力场：无大纲 → 无配额子句；也未注入猜测（快照无意图）
    assert "toward_beat" not in captured["user"] or "含 1 枚 toward_beat" not in captured["user"]
    # 产物：prop 锚点回查拼 note（[3]=发电机：entities 林尘/老周 在前）
    parts = captured["cached"]
    by_slot = {p["source"]: p for p in parts}
    assert by_slot["prop"]["note"] == "镜头对准「发电机」"
    assert by_slot["reply"]["note"] == "受话人先接住那句话"
    # T3 影子检：脚手架（场外）× 抄（上手动词）→ 台账命中但件不丢
    # （log_constraint_event 位置参数序：book_id, chapter_id, constraint_id, outcome）
    assert any(a[2] == "dock-onstage-boundary" and a[3] == "hit" for a, k in events)
    assert any(p["text"] == "他抄起脚手架上的短管" for p in parts)


def test_bridge_semantic_shadow_dual_run_keeps_part(monkeypatch):
    """桥接后文语义撞车 shadow（2026-09-23）：命中只落台账不丢件。

    实测事故对拍：舱内「明姐在围裙上擦干手走向门口」预演后文「明姐端过来
    脸盆」——字面重合 <4 字过词法闸。语义版与词法闸双跑攒校准数据，
    转正（registry status 翻 live）后才执法。
    """
    from backend.services.validation import semantic_overlap as so

    async def fake_hits(text, targets, *, threshold):
        # 只对预演后文那枚报命中（真实现按向量相似度；shadow 对拍锁的是
        # 「命中→落台账→不丢件」的接缝，不是相似度算法本身）
        if "擦干手" in text:
            return [{"segment": text, "target": targets[0], "similarity": 0.91}]
        return []

    monkeypatch.setattr(so, "semantic_overlap_hits", fake_hits)

    raw = {
        "parts": [
            {"slot": "landing", "type": "action", "text": "林尘拎起工具包跨出门槛"},
            {"slot": "ambient", "type": "action", "text": "明姐在围裙上擦干手走向门口"},
        ]
    }
    suffix = "“好嘞，那王叔您早点休息啊。”说罢，林尘把包带往肩上紧了紧，侧身挤进夜色。" \
             "明姐端过来准备好的脸盆，满满的清水。"
    result, captured, events = _run_onstage_dock(
        monkeypatch, raw, suffix_anchor=suffix)

    # shadow 纪律：命中落台账，件一枚不丢
    assert result == {"count": 2}
    texts = [p["text"] for p in captured["cached"]]
    assert "明姐在围裙上擦干手走向门口" in texts
    assert any(a[2] == "dock-bridge-overlap-semantic" and a[3] == "hit" for a, k in events)
    # 未命中那枚不落事件（只有 1 条语义事件）
    sem_events = [a for a, k in events if a[2] == "dock-bridge-overlap-semantic"]
    assert len(sem_events) == 1


def test_bridge_semantic_shadow_skipped_without_suffix(monkeypatch):
    """无 suffix_anchor（非桥接态）→ 语义后文闸整段不跑——零调用零事件。"""
    from backend.services.validation import semantic_overlap as so

    calls = []

    async def fake_hits(text, targets, *, threshold):
        calls.append(text)
        return []

    monkeypatch.setattr(so, "semantic_overlap_hits", fake_hits)
    result, captured, events = _run_onstage_dock(monkeypatch, _PARTS)
    assert result == {"count": 4}
    assert calls == []
    assert not any(a[2] == "dock-bridge-overlap-semantic" for a, k in events)


# ============================================================
# 僵尸缓存修复（2026-09-08 实测）：版本盐值双侧失效 + 强制刷新旁路
# ============================================================

class TestVersionSalt:

    def test_extract_filters_stale_version(self):
        """读取侧：__dock__ 项缺 ver（重构前旧缓存）或版本不符 → 视为无件。"""
        from backend.routes.chapter_generation.adaptive.heartbeat import _extract_dock_parts

        fresh = {"projections": [{"__dock__": True, "ver": DOCK_PIPELINE_VERSION,
                                  "parts": [{"key": "landing:x", "text": "他把书按深"}]}]}
        assert _extract_dock_parts(fresh) == [{"key": "landing:x", "text": "他把书按深"}]
        stale_no_ver = {"projections": [{"__dock__": True, "parts": [{"text": "旧零件"}]}]}
        assert _extract_dock_parts(stale_no_ver) == []
        stale_old_ver = {"projections": [{"__dock__": True, "ver": "v1.0_ancient",
                                          "parts": [{"text": "旧零件"}]}]}
        assert _extract_dock_parts(stale_old_ver) == []

    def test_signature_salt_keeps_hit_within_same_version(self):
        """签名侧：同版本盐值不空转（账两侧同盐 → 命中保持）；跨版本失效由
        读取侧过滤（test_extract_filters_stale_version）+ 进程重启空账首轮
        重算覆盖共同保证——进程内无法模拟「旧版本常量」故只锁同版行为。"""
        from backend.services.adaptive.change_detector import AuthorState
        from backend.services.adaptive.orchestrator import AdaptiveOrchestrator

        orch = AdaptiveOrchestrator(db_factory=None, chapter_id="ch-salt-1")
        snap = {"intent": {"source": "inferred", "confidence": 0.6},
                "projections": [], "fact_count": 0, "total_words": 0}

        def _state(**kw):
            base = dict(
                chapter_id="ch-salt-1", word_count=500, paused_ms=4001,
                cursor_at_paragraph_end=True, recent_text="这句话值得被贴在墙上。",
            )
            base.update(kw)
            return AuthorState(**base)

        # 第一次激活 → 手工落账（模拟 _commit_pending_sig 成功路径）
        assert any(a.component == "dock_generator" for a in orch._decide(_state(), snap, []))
        pending = orch._pending_sigs.pop("dock_generator")
        orch._last_dock_text_sig = pending["text"]
        orch._last_dock_proj_sig = pending["proj"]
        orch._last_dock_stage_sig = pending["stage"]

        # 同文本再判：命中（盐值在账两侧一致——现行版本不空转重算）
        acts = orch._decide(_state(), snap, [])
        assert all(a.component != "dock_generator" for a in acts)

    def test_word_count_change_invalidates_hit(self):
        """上下文变即重算（2026-09-09 实测拍板）：段落文本不变、全书字数变
        （他段增删/幽灵采纳推进）→ 命中被击穿重新激活；纯停顿不写字仍命中。"""
        from backend.services.adaptive.change_detector import AuthorState
        from backend.services.adaptive.orchestrator import AdaptiveOrchestrator

        orch = AdaptiveOrchestrator(db_factory=None, chapter_id="ch-wc-1")
        snap = {"intent": {"source": "inferred", "confidence": 0.6},
                "projections": [], "fact_count": 0, "total_words": 0}

        def _state(wc: int):
            return AuthorState(
                chapter_id="ch-wc-1", word_count=wc, paused_ms=4001,
                cursor_at_paragraph_end=True, recent_text="这句话值得被贴在墙上。",
            )

        assert any(a.component == "dock_generator" for a in orch._decide(_state(1000), snap, []))
        pending = orch._pending_sigs.pop("dock_generator")
        orch._last_dock_text_sig = pending["text"]
        orch._last_dock_proj_sig = pending["proj"]
        orch._last_dock_stage_sig = pending["stage"]
        # 同段同字数（纯停顿反复）→ 命中，省 ~90% 承诺保持
        assert all(a.component != "dock_generator" for a in orch._decide(_state(1000), snap, []))
        # 字数变（上下文变了）→ 击穿重算
        assert any(a.component == "dock_generator" for a in orch._decide(_state(1050), snap, []))

    def test_force_refresh_bypasses_cache_hit(self):
        """强制刷新：签名全同的缓存命中也被击穿 → 强行重算覆盖旧缓存。"""
        from backend.services.adaptive.change_detector import AuthorState
        from backend.services.adaptive.orchestrator import AdaptiveOrchestrator

        orch = AdaptiveOrchestrator(db_factory=None, chapter_id="ch-force-1")
        snap = {"intent": {"source": "inferred", "confidence": 0.6},
                "projections": [], "fact_count": 0, "total_words": 0}

        def _state(**kw):
            base = dict(
                chapter_id="ch-force-1", word_count=500, paused_ms=4001,
                cursor_at_paragraph_end=True, recent_text="这句话值得被贴在墙上。",
            )
            base.update(kw)
            return AuthorState(**base)

        assert any(a.component == "dock_generator" for a in orch._decide(_state(), snap, []))
        pending = orch._pending_sigs.pop("dock_generator")
        orch._last_dock_text_sig = pending["text"]
        orch._last_dock_proj_sig = pending["proj"]
        orch._last_dock_stage_sig = pending["stage"]

        # 命中态 + force_refresh=True → 仍然激活；待定账照常入账（下轮不空转）
        acts = orch._decide(_state(force_refresh=True), snap, [])
        assert any(a.component == "dock_generator" for a in acts)
        assert orch._pending_sigs["dock_generator"]["text"] == pending["text"]

        # 半句门禁不受 force_refresh 豁免（写完句子是续写的活，刷新不是免死金牌）
        mid = _state(force_refresh=True, recent_text="在这个世道，这句话")
        acts_mid = orch._decide(mid, snap, [])
        assert all(a.component != "dock_generator" for a in acts_mid)


# ============================================================
# 末句对白优先 / 通行证 / 意图衰老 / 桥接（2026-09-09 四线施工）
# ============================================================

class TestEndsInDialogue:
    """末句优先原则：末行整行以引号起收 → 无条件 dialogue；名言引用排除。"""

    def test_real_dialogue_line(self):
        assert ends_in_dialogue("他想了想，推门进屋。\n“明姐，我回来了。”")

    def test_quote_reference_is_not_dialogue(self):
        # 名言引用：引号在句中，行首是「他想起」——不是对白行
        assert not ends_in_dialogue("他想起那句“人定胜天”")

    def test_narration_and_empty(self):
        assert not ends_in_dialogue("林尘把工具包放在门边。")
        assert not ends_in_dialogue("")
        assert not ends_in_dialogue("\n  \n")

    def test_template_priority(self):
        # 叙述稀释整窗占比，但末行是对白 → dialogue（末句优先胜过占比尺）
        diluted = ("他想了想这一周的事。稻草堆、牛犊子、明姐的惊呼、村里的路灯。"
                   "夜晚村子的道路也不好走。\n“明姐，我回来了。”")
        assert pick_shot_template(diluted) == "dialogue"
        # suffix_anchor 最硬（光标位置事实）——压过对白
        assert pick_shot_template(diluted, suffix_anchor="“今晚回来得晚了些。”明姐说。") == "bridge"


class TestAliasCanonicalizer:
    """别名与昵称归一化拦截（2026-09-11 排毒批「阿尘≠第三人」事故）。

    尾字配尾字（昵称/姓氏称谓的取字惯例）+ 唯一命中才绑定；多命中=歧义
    同样抑制通行证（发证必致分裂建档）；零命中照发（明姐流程不受染）。
    """

    def _is_alias(self, name, known):
        from backend.services.adaptive.components.dock_generator import _is_alias_or_ambiguous
        return _is_alias_or_ambiguous(name, known)

    def test_prefix_nick_tail_char_binds(self):
        """阿尘 → 尾字「尘」唯一命中林尘 → 归主不发证。"""
        assert self._is_alias("阿尘", ["林尘", "大爷"]) is True

    def test_prefix_nick_ambiguous_suppressed(self):
        """林尘/周尘并存 → 阿尘歧义：不绑定也不发证（红队 Q2 防假同名）。"""
        assert self._is_alias("阿尘", ["林尘", "周尘"]) is True

    def test_honorific_surname_binds_to_laowang(self):
        """王叔 → 剥后缀核心「王」配尾字命中「工头老王」→ 归主。"""
        assert self._is_alias("王叔", ["工头老王"]) is True

    def test_honorific_no_false_bind(self):
        """王叔 vs 王阿婆（尾字婆）→ 零命中 → 照发通行证（不误绑）。"""
        assert self._is_alias("王叔", ["王阿婆"]) is False

    def test_mingjie_zero_match_keeps_pass(self):
        """明姐核心「明」不命中任何尾字 → 真·新人物，通行证照发。"""
        assert self._is_alias("明姐", ["林尘", "大爷"]) is False

    def test_three_char_prefix_contains(self):
        """三字昵称（阿明轩）核心两字走包含匹配。"""
        assert self._is_alias("阿明轩", ["周明轩"]) is True

    def test_unrelated_plain_name(self):
        """普通新人名（赵四）与已知无尾字/包含关系 → 照发。"""
        assert self._is_alias("赵四", ["林尘"]) is False

    def test_detect_guest_names_suppresses_alias(self):
        """集成：正文喊「阿尘啊」×2 → 在场有林尘 → 无通行证（不发独立芯片）。"""
        text = "“咳咳……阿尘啊……这发电机还能修得好吗？”阿尘慌忙摆手，阿尘把线头接上。"
        assert detect_guest_names(text, known_names=["林尘", "大爷"]) == []

    def test_registered_alias_exact_match_suppressed(self):
        """注册别名（非昵称形）精确命中抑制面 → 不发证。

        明姐是「明兰」的注册别名（称谓后缀提名不依赖 jieba NR 判定，确定性
        路径）——别名进 _known 后 detect_guest_names 的已知名排除直接拦下。
        """
        text = "“明姐，我回来了。”明姐端来脸盆。明姐问累不累。"
        assert detect_guest_names(text, known_names=["明兰", "明姐"]) == []

    def test_registered_alias_no_dual_identity(self):
        """端到端：注册别名（明姐→明兰）入抑制面——主实体经别名提及入册，
        别名绝不作为独立 guest 出现（同台双身份事故的锁，2026-09-13 B1）。"""
        b = _bundle(
            entities=[_WEnt("e-ming", "明兰", aliases=["明姐"], dyn="在灶间忙")],
            assets=[], locations=_LOCS, char_states=[],
        )
        view = onstage_projection(b, "loc-2", "“明姐，我回来了。”明姐端来脸盆。")
        assert view is not None
        names = [e["name"] for e in view["entities"]]
        assert "明兰" in names                     # 别名提及 → 主实体入册
        assert "明姐" not in names                 # 别名不发独立通行证
        assert not any(e.get("is_guest") for e in view["entities"])


class TestGuestPass:
    """临时在场通行证：正文高频未建档人名入册；普通名词/泛称不污染。"""

    def test_mingjie_gets_pass(self):
        text = "“明姐，我回来了。”明姐端来脸盆。“累了吧？”明姐问。"
        assert "明姐" in detect_guest_names(text, known_names=["林尘"])

    def test_common_nouns_rejected(self):
        text = "村子里的路灯亮着。村子很安静。发电机在村子中央轰鸣。"
        assert detect_guest_names(text, known_names=[]) == []

    def test_generic_kinship_stopped(self):
        assert detect_guest_names("姐姐说。姐姐又说了。", known_names=[]) == []

    def test_known_names_excluded_and_freq_floor(self):
        # 已在册的名不发通行证；单次出现不到频次地板
        assert detect_guest_names("林尘回来了。林尘坐下。", known_names=["林尘"]) == []
        assert detect_guest_names("老李打了个招呼。", known_names=[]) == []

    def test_e2e_guest_in_onstage_and_cached(self, monkeypatch):
        """端到端：明姐两现 → 在册带 is_guest + prompt 点名 + 缓存随件带 guests。"""
        recent = "林尘推门进屋，把工具包放在门边。“明姐，我回来了。”明姐端来准备好的脸盆。"
        saved = (_WorldBundle.entities, _WorldBundle.assets, _WorldBundle.content_text)
        try:
            _WorldBundle.entities = [_WEnt("e-lin", "林尘", dyn="位于机房")]
            _WorldBundle.assets = []
            _WorldBundle.content_text = f"<p>{recent}</p>"
            result, captured, events = _run_onstage_dock(monkeypatch, _PARTS, recent=recent)
        finally:
            (_WorldBundle.entities, _WorldBundle.assets, _WorldBundle.content_text) = saved
        assert result == {"count": 4}
        assert "明姐" in captured["user"]                       # 在册点名
        assert "未建档" in captured["user"] and "临时在场" in captured["user"]   # 通行证状态行
        assert captured.get("guests") == ["明姐"]               # 随件缓存（路由上帧用）


class TestIntentStaleness:
    """意图衰老（2026-09-09 时序冻结修复）：反推后正文推进 >100 字 → 不绑旧意图。"""

    def test_stale_intent_not_bound(self, monkeypatch):
        snapshot = {
            "facts": [], "live_facts": [], "projections": [],
            "intent": {
                "source": "inferred", "confidence": 0.6,
                "next_direction": "他借着昏暗的路灯往明姐家走。",
                "prose_chars": 300,
            },
        }
        result, captured, _ = _run_onstage_dock(
            monkeypatch, _PARTS,
            snapshot=snapshot, recent="“明姐，我回来了。”他说完把工具包放在门边。", word_count=500,
        )
        assert result == {"count": 4}
        assert "往明姐家走" not in captured["user"]            # 陈旧意图不上桌

    def test_fresh_intent_bound(self, monkeypatch):
        snapshot = {
            "facts": [], "live_facts": [], "projections": [],
            "intent": {
                "source": "inferred", "confidence": 0.6,
                "next_direction": "他坐下吃明姐做的饭。",
                "prose_chars": 480,
            },
        }
        result, captured, _ = _run_onstage_dock(
            monkeypatch, _PARTS,
            snapshot=snapshot, recent="“明姐，我回来了。”他说完把工具包放在门边。", word_count=500,
        )
        assert "他坐下吃明姐做的饭" in captured["user"]         # 新鲜意图照常供料


class TestBridgeDock:
    """中插桥接（FIM）：模板分派 + 后文禁区块 + 撞车闸。"""

    def test_bridge_prompt_sections(self):
        from backend.services.prompts.adaptive_prompts import build_dock_generator_prompt
        onstage = {
            "entities": [{"name": "林尘", "state": ""}],
            "props": [], "scene_line": "", "offstage_characters": [], "offstage_assets": [],
        }
        sys_p, user = build_dock_generator_prompt(
            "上文。", projections=[], nutrients={}, hard_constraints={},
            onstage=onstage, template="bridge",
            suffix_anchor="“今晚回来得晚了些。”明姐端来脸盆。",
        )
        assert "中插桥接" in sys_p
        assert "下文已写的事实是禁区" in sys_p
        assert "下文已写" in user and "明姐端来脸盆" in user
        # 桥不吃大纲引力/意图配额
        assert "贴近就近节拍" not in user

    def test_suffix_overlap_part_dropped(self):
        from backend.services.adaptive.components.dock_generator import _finalize_parts
        raw = [
            {"slot": "landing", "type": "action", "text": "他在门边解开鞋带"},
            {"slot": "ambient", "type": "scene", "text": "明姐端来脸盆放在桌上"},   # 撞后文
        ]
        dropped = []
        parts = _finalize_parts(
            raw, on_drop=lambda r, t="", outcome="drop": dropped.append(r),
            suffix_anchor="明姐端来了准备好的脸盆，满满的清水。",
        )
        assert [p["text"] for p in parts] == ["他在门边解开鞋带"]
        assert "suffix_overlap" in dropped

    def test_suffix_noun_overlap_exempted(self):
        """2026-09-13 动词门：纯景物名词 4-5 字共现豁免——后文「窗纸透出」
        被卡片当环境锚点引用（「望向窗纸透出的微光」）不再丢件（旧 n=4
        无差别判据致卡片舱选项饥饿的病灶形态）。"""
        from backend.services.adaptive.components.dock_generator import _finalize_parts
        raw = [
            {"slot": "ambient", "type": "scene", "text": "望向窗纸透出的微光"},
        ]
        parts = _finalize_parts(
            raw, on_drop=lambda *a, **k: None,
            suffix_anchor="巷子里没灯，只有谁家窗纸透出一点黄。",
        )
        assert [p["text"] for p in parts] == ["望向窗纸透出的微光"]

    def test_suffix_verb_overlap_still_dropped(self):
        """动词门另一半：4 字窗口含情节动作字仍丢件（豁免不放走事件抢拍）。"""
        from backend.services.adaptive.components.dock_generator import _suffix_overlap_hit
        assert _suffix_overlap_hit(
            "接过明姐递来的碗", "明姐递来了准备好的碗筷", onstage_names=["明姐"]) is True
        # 豁免走安全构成：感知动词不入动作表，主体感知不推进事件
        assert _suffix_overlap_hit(
            "望向窗纸透出的微光", "窗纸透出一点黄") is False

    def test_suffix_long_noun_overlap_dropped(self):
        """≥6 字连续重合即使无动作字也丢件——长段重合难以「巧合引用」解释。"""
        from backend.services.adaptive.components.dock_generator import _suffix_overlap_hit
        assert _suffix_overlap_hit(
            "巷子深处没有灯", "巷子深处没有灯，只有谁家窗纸透出一点黄。") is True

    def test_suffix_onstage_name_chars_join_safe_set(self):
        """在册实体名字符并入安全集：卡片引用在册景物不因后文提及同一物件
        而丢件（onstage_names 参数的实际作用）。"""
        from backend.services.adaptive.components.dock_generator import _suffix_overlap_hit
        # 「流光银白」4 字重合，「流」不在内建安全表——不传在册名单时保守丢件
        assert _suffix_overlap_hit(
            "它流光银白的外壳", "流光银白色的流线造型。") is True
        # 传入在册名单后，「流」入安全集 → 全安全构成 → 豁免
        assert _suffix_overlap_hit(
            "它流光银白的外壳", "流光银白色的流线造型。",
            onstage_names=["流光"]) is False
