# Velluma - NLE-ADF 3.0 意图加固批次对拍单测（2026-09-03 意图入舱）
# AGPL-3.0
"""
锁定意图感知入舱的代码侧契约（prompt 杠杆之外的可靠性全在这层）：

- ChapterIntent 新字段（next_direction/evidence）序列化往返 + 存量旧 dict 兼容
- 证据回查闸 _valid_evidence：逐字出自正文才算数，编造依据整类掐死
- 反推 prompt：作者材料块/纠正史块条件注入与缺席零变化；问窄字段在输出契约
- dock 源链：无大纲节拍时 toward_beat 由方向猜测供料，note 如实标注
  「AI 猜的」；有真节拍时猜测让位（作者材料永压猜测）；两皆无降级 ambient
- 纠正史读取 _recent_intent_corrections：按书过滤、新到旧、限量
"""
import json

from backend.services.adaptive.world_model import ChapterIntent
from backend.services.adaptive.components.intent_inference import (
    _recent_intent_corrections,
    _valid_evidence,
    _norm_for_match,
    DOCK_INTENT_MIN_CONFIDENCE,
)
from backend.services.adaptive.components.dock_generator import (
    _assemble_note,
    _finalize_parts,
)
from backend.services.prompts.adaptive_prompts import (
    build_dock_generator_prompt,
    build_intent_inference_prompt,
)


# ============================================================
# ChapterIntent 新字段
# ============================================================

class TestChapterIntentFields:
    def test_roundtrip_with_new_fields(self):
        intent = ChapterIntent(
            source="inferred", confidence=0.55, arc="他撑不住了",
            next_direction="压着怒火继续上工", evidence=["他把扳手攥得发白"],
        )
        d = intent.to_dict()
        assert d["next_direction"] == "压着怒火继续上工"
        assert d["evidence"] == ["他把扳手攥得发白"]
        back = ChapterIntent.from_dict(d)
        assert back.next_direction == "压着怒火继续上工"
        assert back.evidence == ["他把扳手攥得发白"]

    def test_legacy_dict_missing_new_keys(self):
        """存量 layer2 快照无新键 → 缺省空（零迁移契约）。"""
        legacy = {"source": "author", "confidence": 0.85, "arc": "旧弧线"}
        intent = ChapterIntent.from_dict(legacy)
        assert intent.next_direction == ""
        assert intent.evidence == []
        assert intent.arc == "旧弧线"


# ============================================================
# 证据回查闸
# ============================================================

WRITTEN = "林尘停下手里的活。他把扳手攥得发白，指节咯咯作响。工头从背后走来。"


class TestEvidenceGate:
    def test_verbatim_quote_passes(self):
        assert _valid_evidence(["他把扳手攥得发白"], WRITTEN) == ["他把扳手攥得发白"]

    def test_fabricated_evidence_dropped(self):
        """编造依据（正文没有的句子）整类掐死。"""
        assert _valid_evidence(["林尘转身一拳打倒工头"], WRITTEN) == []

    def test_punctuation_variant_passes(self):
        """模型摘句带标点出入 → 规范化骨架比对放行。"""
        assert _valid_evidence(["他把扳手攥得发白。"], WRITTEN)
        assert _valid_evidence(["「他把扳手攥得发白」"], WRITTEN)

    def test_too_short_rejected(self):
        """<4 规范化字符的「证据」没有约束力，不收。"""
        assert _valid_evidence(["扳手"], WRITTEN) == []

    def test_cap_three_and_empty_written(self):
        ev = ["他把扳手攥得发白", "林尘停下手里的活", "工头从背后走来", "指节咯咯作响"]
        assert len(_valid_evidence(ev, WRITTEN)) == 3
        assert _valid_evidence(ev, "") == []

    def test_norm_strips_punctuation(self):
        assert _norm_for_match("他把扳手，攥得发白。") == "他把扳手攥得发白"


# ============================================================
# 反推 prompt：条件块注入与缺席零变化
# ============================================================

class TestIntentInferencePrompt:
    def test_narrow_question_and_evidence_in_contract(self):
        """问窄（next_direction）与证据（evidence）进输出契约。"""
        _sys, user = build_intent_inference_prompt("正文" * 60, "", {}, {})
        assert "next_direction" in user
        assert "evidence" in user
        assert "正文原句" in user

    def test_author_material_block_injected(self):
        _sys, user = build_intent_inference_prompt(
            "正文" * 60, "", {}, {},
            spine_anchors=["发现假信", "压住不表"],
            outline_notes=["让他先忍住，下班才爆发"],
        )
        assert "作者亲手材料" in user
        assert "发现假信" in user
        assert "速记胶囊" in user
        assert "让他先忍住" in user

    def test_correction_history_block_injected(self):
        _sys, user = build_intent_inference_prompt(
            "正文" * 60, "", {}, {},
            corrections=[{"guessed": "他要报仇", "corrected": "他其实想离开"}],
        )
        assert "纠正史" in user
        assert "他要报仇" in user
        assert "他其实想离开" in user

    def test_blocks_absent_zero_change(self):
        """无作者材料/无纠正史 → 块整段缺席（旧书零变化契约）。"""
        _sys, user = build_intent_inference_prompt("正文" * 60, "", {}, {})
        assert "作者亲手材料" not in user
        assert "纠正史" not in user

    def test_soft_context_lines_conditional(self):
        """喂全：开放伏笔/角色此刻状态有条件注入，无数据缺席。"""
        _sys, bare = build_intent_inference_prompt("正文" * 60, "", {}, {})
        assert "开放伏笔" not in bare
        _sys, fed = build_intent_inference_prompt(
            "正文" * 60, "", {}, {"open_hooks": "扳手的来历", "character_dynamics": "林尘在工地"},
        )
        assert "开放伏笔" in fed and "扳手的来历" in fed
        assert "角色此刻状态" in fed and "林尘在工地" in fed


# ============================================================
# 线 B（2026-09-03）：意图画像——前几章意图轨迹 + 纠正量统计
# ============================================================

class TestIntentProfilePrompt:
    def test_trajectory_block_injected(self):
        _sys, user = build_intent_inference_prompt(
            "正文" * 60, "", {}, {},
            intent_trajectory=["第1章：让他进厂第一天就忍一口气", "第2章：扳手第一次出现"],
        )
        assert "前几章亲手定的方向" in user
        assert "第1章：让他进厂第一天就忍一口气" in user
        assert "第2章：扳手第一次出现" in user

    def test_trajectory_absent_zero_change(self):
        _sys, bare = build_intent_inference_prompt("正文" * 60, "", {}, {})
        assert "前几章亲手定的方向" not in bare
        # 空表/全空白行同样缺席
        _sys, also_bare = build_intent_inference_prompt(
            "正文" * 60, "", {}, {}, intent_trajectory=["", "  "])
        assert also_bare == bare

    def test_correction_volume_conservative_line(self):
        """纠正频繁（≥2）→ 追加保守指令；仅 1 次不追加（偶发不算口味信号）。"""
        corr = [{"guessed": "他要报仇", "corrected": "他其实想离开"},
                {"guessed": "她原谅了", "corrected": "她只是忍住"}]
        _sys, user = build_intent_inference_prompt(
            "正文" * 60, "", {}, {}, corrections=corr, correction_count=2)
        assert "方向不明" in user
        _sys, user1 = build_intent_inference_prompt(
            "正文" * 60, "", {}, {}, corrections=corr[:1], correction_count=1)
        assert "纠正史" in user1
        assert "方向不明" not in user1

    def test_volume_line_requires_visible_examples(self):
        """纠正计数再高，没有可展示的有效条目就不出块（防空块+孤行指令）。"""
        _sys, user = build_intent_inference_prompt(
            "正文" * 60, "", {}, {},
            corrections=[{"guessed": "", "corrected": ""}], correction_count=9)
        assert "纠正史" not in user
        assert "方向不明" not in user


class TestChapterIntentTrajectory:
    """_chapter_intent_trajectory 取数口径（假 db 纯 SELECT 对拍）。"""

    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Db:
        def __init__(self, rows):
            self._rows = rows

        async def execute(self, stmt):
            return TestChapterIntentTrajectory._Rows(self._rows)

    def _bundle(self, chapter_number=5):
        from types import SimpleNamespace
        return SimpleNamespace(book_id="bk-1", chapter_number=chapter_number)

    def test_picks_prior_spine_intents_chronological(self):
        import asyncio

        from backend.services.adaptive.components.intent_inference import (
            _chapter_intent_trajectory,
        )
        rows = [
            (6, {"intent": {"text": "未来章不算"}}),   # 本章之后——排除
            (5, {"intent": {"text": "本章自己不算"}}),  # 本章——排除
            (4, {"intent": {"text": "第四章的打算"}}),
            (3, None),                                   # 无 spine——跳过
            (2, {"intent": {"text": ""}}),               # 空意图——跳过
            (1, {"intent": {"text": "第一章的打算"}}),
        ]
        got = asyncio.run(_chapter_intent_trajectory(self._bundle(5), self._Db(rows)))
        assert got == ["第1章：第一章的打算", "第4章：第四章的打算"]

    def test_empty_and_failure_zero_change(self):
        import asyncio

        from backend.services.adaptive.components.intent_inference import (
            _chapter_intent_trajectory,
        )
        assert asyncio.run(_chapter_intent_trajectory(self._bundle(5), self._Db([]))) == []
        assert asyncio.run(_chapter_intent_trajectory(self._bundle(5), None)) == []
        # 无章号/无书号不查
        from types import SimpleNamespace
        assert asyncio.run(_chapter_intent_trajectory(
            SimpleNamespace(book_id=None, chapter_number=5), self._Db([]))) == []


# ============================================================
# 线 C（2026-09-03）：章首接力棒 + 闸门序重排
# ============================================================

class TestBatonChain:
    """冷启动章不空猜：材料短路先于正文体量闸门；无材料时摘要接管。"""

    def _bundle(self, **kw):
        from types import SimpleNamespace
        base = dict(content_text="", outline_text="", book_id="b1",
                    previous_summary="", chapter_card=None)
        base.update(kw)
        return SimpleNamespace(**base)

    class _Repo:
        """捕获 set_intent 的假仓库（run() 内直构造，monkeypatch 掉类）。"""

        saved = None

        def __init__(self, db):
            pass

        async def set_intent(self, chapter_id, intent):
            TestBatonChain._Repo.saved = intent

    def _patch_common(self, monkeypatch, bundle, spine=("", [])):
        import backend.services.adaptive.components.intent_inference as mod
        monkeypatch.setattr(mod, "WorldModelRepository", self._Repo)
        self._Repo.saved = None

        async def _load(chapter_id, db):
            return bundle
        monkeypatch.setattr(mod, "load_chapter_settings_bundle", _load)

        async def _spine(chapter_id, db):
            return spine
        monkeypatch.setattr(mod, "_spine_material", _spine)
        return mod

    def test_spine_short_circuit_before_length_gate(self, monkeypatch):
        """章首空章（正文 <100 字）写了打算 → 立刻 author 意图上桌（旧序被
        「正文不足」挡掉）。"""
        import asyncio
        mod = self._patch_common(monkeypatch, self._bundle(),
                                 spine=("让他忍住不发作", ["锚点一"]))
        out = asyncio.run(mod.run("ch-1", None, {}))
        assert out == {"source": "author", "confidence": 0.9, "via": "spine"}
        assert self._Repo.saved.arc == "让他忍住不发作"
        assert self._Repo.saved.source == "author"

    def test_outline_short_circuit_before_length_gate(self, monkeypatch):
        import asyncio
        mod = self._patch_common(monkeypatch, self._bundle(
            outline_text="本章大纲：林尘发现假信之后决定装没看见。"))
        out = asyncio.run(mod.run("ch-1", None, {}))
        assert out["source"] == "author" and out["confidence"] == 0.85
        assert "林尘发现假信" in self._Repo.saved.arc

    def test_baton_from_previous_summary(self, monkeypatch):
        """无材料+正文不足+有上一章摘要 → baton 接管（零 LLM，不空猜）。"""
        import asyncio
        mod = self._patch_common(monkeypatch, self._bundle(
            previous_summary="上一章结尾：林尘把扳手塞进床底，熄了灯。"))
        out = asyncio.run(mod.run("ch-1", None, {}))
        assert out["source"] == "baton"
        baton = self._Repo.saved
        assert baton.source == "baton"
        assert baton.confidence == 0.6
        assert baton.arc.startswith("承接上一章：")
        assert "扳手" in baton.arc
        # dock 猜测链只认 inferred——baton 不进舱（防摘要复读成挂件）
        assert baton.source != "inferred"
        # stitch 兜底（线 A）消费阈：0.6 ≥ DOCK_INTENT_MIN_CONFIDENCE
        assert baton.confidence >= DOCK_INTENT_MIN_CONFIDENCE

    def test_first_chapter_no_summary_still_skips(self, monkeypatch):
        """全书第一章（无摘要）保持旧跳过——零变化契约。"""
        import asyncio
        mod = self._patch_common(monkeypatch, self._bundle())
        out = asyncio.run(mod.run("ch-1", None, {}))
        assert out == {"skipped": True, "reason": "正文不足"}
        assert self._Repo.saved is None

    def test_baton_builder_pure(self):
        from backend.services.adaptive.components.intent_inference import (
            _baton_from_previous,
        )
        from types import SimpleNamespace
        assert _baton_from_previous(SimpleNamespace(previous_summary="  ")) is None
        assert _baton_from_previous(SimpleNamespace(previous_summary=None)) is None
        got = _baton_from_previous(SimpleNamespace(previous_summary="上章：雨停了。"))
        assert got.arc == "承接上一章：上章：雨停了。"
        assert got.next_direction == ""




# ============================================================
# dock 源链：猜测供料 / 让位 / 降级
# ============================================================

class TestDockIntentChain:
    def test_guess_block_only_when_no_nearby(self):
        """无大纲节拍 + 有方向猜测 → 猜测块注入且如实标注 AI 猜的。"""
        _sys, user = build_dock_generator_prompt(
            "林尘停下手里的活，在这个世道，这句话",
            projections=[], nutrients={}, hard_constraints={},
            intent_guess="压着怒火继续上工",
        )
        assert "本章方向猜测" in user
        assert "压着怒火继续上工" in user
        assert "AI 从正文反推" in user
        assert "通往方向猜测" in user  # beat_clause

    def test_guess_yields_to_real_beats(self):
        """有真就近节拍 → 猜测块/猜测子句整段缺席（作者材料永压猜测）。"""
        sys_p, user = build_dock_generator_prompt(
            "林尘停下手里的活，在这个世道，这句话",
            projections=[], nutrients={}, hard_constraints={},
            outline_nearby=["工头拍肩打断"],
            intent_guess="压着怒火继续上工",
        )
        assert "本章方向猜测" not in user
        assert "通往方向" not in sys_p
        assert "作者大纲·就近节拍" in user

    def test_no_guess_no_nearby_zero_change(self):
        """两皆无 → 与旧形态一致（零变化契约）。"""
        sys_p, user = build_dock_generator_prompt(
            "林尘停下手里的活，在这个世道，这句话",
            projections=[], nutrients={}, hard_constraints={},
        )
        assert "本章方向猜测" not in user
        assert "通往方向" not in sys_p
        assert "给了就近节拍" not in user
        # 旧兜底子句仍在
        assert "没有大纲节拍可用时" in sys_p

    def test_guess_driven_toward_beat_section(self):
        """猜测供料形态编译出 toward_beat 变体子句（系统层）。"""
        sys_p, _user = build_dock_generator_prompt(
            "林尘停下手里的活，在这个世道，这句话",
            projections=[], nutrients={}, hard_constraints={},
            intent_guess="压着怒火继续上工",
        )
        assert "通往「本章方向猜测」" in sys_p

    def test_note_labels_guess_honestly(self):
        """note 后端拼装：猜测供料的 toward_beat 如实标注「AI 猜的」。"""
        note = _assemble_note("toward_beat", {}, None, None, None,
                              intent_guess="压着怒火继续上工等私下质问的机会")
        assert "AI 猜的" in note
        assert "压着怒火继续上工" in note

    def test_note_real_beat_wins_over_guess(self):
        note = _assemble_note("toward_beat", {}, ["工头拍肩打断"], None, None,
                              intent_guess="压着怒火继续上工")
        assert "工头拍肩打断" in note
        assert "AI 猜的" not in note

    def test_finalize_toward_beat_from_guess(self):
        """整链：无节拍有猜测时 toward_beat 件带标注 note 存活；无猜测降级 ambient。"""
        raw = [{"slot": "toward_beat", "type": "action", "text": "他拎起墙边最沉的备件箱"}]
        parts = _finalize_parts(raw, intent_guess="压着怒火继续上工")
        assert parts[0]["source"] == "toward_beat"
        assert "AI 猜的" in parts[0]["note"]
        # 无猜测 → 槽位拿不到出处降级 ambient（旧行为不变）
        parts2 = _finalize_parts(raw)
        assert parts2[0]["source"] == "ambient"
        assert "note" not in parts2[0]


# ============================================================
# 纠正史读取（intent_correct 埋点 → 反推 few-shot 教材）
# ============================================================

class TestCorrectionHistory:
    def _write_events(self, tmp_path, events):
        p = tmp_path / "collab_events.jsonl"
        p.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")
        return p

    def test_filters_by_book_newest_first(self, tmp_path, monkeypatch):
        import backend.services.adaptive.components.intent_inference as mod

        path = self._write_events(tmp_path, [
            {"kind": "intent_correct", "book_id": "b1", "ts": "2026-09-01T10:00:00",
             "detail": {"guessed": "旧猜A", "corrected": "旧改A"}},
            {"kind": "intent_correct", "book_id": "b2", "ts": "2026-09-03T10:00:00",
             "detail": {"guessed": "别书的", "corrected": "别书的"}},
            {"kind": "intent_correct", "book_id": "b1", "ts": "2026-09-02T10:00:00",
             "detail": {"guessed": "新猜A", "corrected": "新改A"}},
            {"kind": "ghost_adopt", "book_id": "b1", "ts": "2026-09-03T11:00:00", "detail": {}},
        ])
        monkeypatch.setattr(mod, "_collab_paths", lambda: [path])
        mod._CORR_SCAN_CACHE.clear()
        got = mod._recent_intent_corrections("b1")
        assert [g["corrected"] for g in got] == ["新改A", "旧改A"]

    def test_empty_and_missing_file(self, tmp_path, monkeypatch):
        import backend.services.adaptive.components.intent_inference as mod

        monkeypatch.setattr(mod, "_collab_paths", lambda: [tmp_path / "nope.jsonl"])
        mod._CORR_SCAN_CACHE.clear()
        assert mod._recent_intent_corrections("b1") == []
        assert mod._recent_intent_corrections("") == []

    def test_dock_confidence_gate_constant(self):
        """证据不过闸的信度（0.4）必须跌破 dock 消费阈——舱不吃存疑方向。"""
        assert 0.4 < DOCK_INTENT_MIN_CONFIDENCE <= 0.55

    def test_collab_paths_anchor_project_root(self):
        """2026-09-03 审计 F1 回归锁：本模块比 quiet_learning 深一层
        （components/ 子包），parents 索引差一层就指向 backend/data——
        纠正史回喂曾因此静默失效。锁默认路径锚在项目根 data/ 下。"""
        import backend.services.adaptive.components.intent_inference as mod

        path = mod._collab_paths()[-1]
        assert path.name == "collab_events.jsonl"
        assert path.parent.name == "data"
        # 项目根的标志：data/ 的父目录必须含 backend 包
        assert (path.parent.parent / "backend" / "__init__.py").exists()


# ============================================================
# 大纲弧线提取：卷首致辞过滤（2026-09-03 实测修复）
# ============================================================

class TestArcExtraction:
    """作者大纲常以致辞/名言开篇——弧线必须取第一条像剧情的行。"""

    def test_skips_epigraph_preamble(self):
        from backend.services.adaptive.components.intent_inference import (
            _extract_arc_from_outline,
        )
        outline = (
            "以罗曼·罗兰的巨著《约翰·克利斯朵夫》\n"
            "“一个人的力量是微薄的，世界的洪流不会因你而逆转”\n"
            "名言开篇\n"
            "林尘喜欢读书，干着活的时候想到昨晚读到的内容，突然被工头打断"
        )
        arc = _extract_arc_from_outline(outline)
        assert arc.startswith("林尘喜欢读书")

    def test_fallback_first_line_when_all_meta(self):
        from backend.services.adaptive.components.intent_inference import (
            _extract_arc_from_outline,
        )
        assert _extract_arc_from_outline("“引语”\n短行") == "“引语”"
        assert _extract_arc_from_outline("") == ""

    def test_normal_outline_unchanged(self):
        from backend.services.adaptive.components.intent_inference import (
            _extract_arc_from_outline,
        )
        assert _extract_arc_from_outline("林尘发现真相并决定反抗\n细节") == "林尘发现真相并决定反抗"


# ============================================================
# 编排层：纠正→舱换向的缓存机械（_decide 纯决策面对拍）
# ============================================================

class TestDockCacheIntentBust:
    """dock 缓存签名 = 段落文本+打算一句话 签名 × projection 签名×意图版本——
    三者任一变化都换料：作者纠正打算的瞬间段落文本没变，舱也必须换向。"""

    def _orch(self):
        from backend.services.adaptive.orchestrator import AdaptiveOrchestrator
        return AdaptiveOrchestrator(None, "ch-test")  # _decide 不触 db_factory

    def _state(self, spine_intent=""):
        from backend.services.adaptive.change_detector import AuthorState
        return AuthorState(
            chapter_id="ch-test", word_count=500, paused_ms=5000,
            cursor_at_paragraph_end=True, recent_text="他握紧扳手。",
            spine_intent=spine_intent,
        )

    @staticmethod
    def _snapshot(intent_version=1):
        return {
            "intent": {"source": "author", "confidence": 0.9},
            "fact_count": 3, "total_words": 500,
            "intent_version": intent_version,
            "projections": [{
                "possible_beats": [{"event": "继续上工", "stage": "now"}],
                "intent_version": intent_version,
            }],
        }

    def test_spine_change_busts_dock_cache(self):
        orch = self._orch()
        snap = self._snapshot()
        a1 = orch._decide(self._state(""), snap, [])
        assert any(a.component == "dock_generator" for a in a1)  # 冷缓存激活
        a2 = orch._decide(self._state(""), snap, [])
        assert not any(a.component == "dock_generator" for a in a2)  # 命中复用
        # 纠正打算（段落文本未变）→ 缓存 bust，dock 重跑换料
        a3 = orch._decide(self._state("他其实想离开"), snap, [])
        assert any(a.component == "dock_generator" for a in a3)

    def test_intent_version_busts_dock_cache(self):
        orch = self._orch()
        a1 = orch._decide(self._state(""), self._snapshot(1), [])
        assert any(a.component == "dock_generator" for a in a1)
        a2 = orch._decide(self._state(""), self._snapshot(1), [])
        assert not any(a.component == "dock_generator" for a in a2)
        # 反推重算（版本递增）→ 猜测方向换料，缓存 bust
        a3 = orch._decide(self._state(""), self._snapshot(2), [])
        assert any(a.component == "dock_generator" for a in a3)
