# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 单焦距主体守恒律对拍（第二冲程 2026-09-09：极速单镜头展开）
"""
视点锁三件套回归：选择器互斥真值表 + prompt 注入边界 + 零变化契约。

运行：python -m pytest backend/services/prompts/test_subject_lock.py -v
"""

from backend.services.prompts.adaptive_prompts import (
    SUBJECT_LOCK_HANDOFF,
    SUBJECT_LOCK_PROP,
    SUBJECT_LOCK_REPLY,
    SUBJECT_LOCK_SPEAKER,
    _SUBJECT_LOCK_TEXTS,
    build_continue_prompt,
    pick_subject_lock,
)


class TestPickSubjectLock:
    """槽位 → 锁的互斥真值表（优先序 物镜 > 静音 > 发话）。"""

    def test_slot_mapping(self):
        assert pick_subject_lock(["prop"]) == SUBJECT_LOCK_PROP
        assert pick_subject_lock(["ambient"]) == SUBJECT_LOCK_PROP
        assert pick_subject_lock(["reply"]) == SUBJECT_LOCK_REPLY
        assert pick_subject_lock(["landing"]) == SUBJECT_LOCK_SPEAKER
        assert pick_subject_lock(["speaker"]) == SUBJECT_LOCK_SPEAKER

    def test_priority_when_mixed(self):
        # 物镜锁最独特（零人物契约混入人物动作即失效）→ 多枚同缝时优先
        assert pick_subject_lock(["landing", "prop"]) == SUBJECT_LOCK_PROP
        assert pick_subject_lock(["reply", "ambient"]) == SUBJECT_LOCK_PROP
        assert pick_subject_lock(["reply", "landing"]) == SUBJECT_LOCK_REPLY

    def test_unlocked_slots_and_empty(self):
        # toward_beat/echo/custom/空 → 默认缝合契约（零变化）
        assert pick_subject_lock([]) == ""
        assert pick_subject_lock(None) == ""
        assert pick_subject_lock(["toward_beat"]) == ""
        assert pick_subject_lock(["echo"]) == ""
        assert pick_subject_lock(["custom"]) == ""
        assert pick_subject_lock(["", " "]) == ""

    def test_bridge_arbitration_speaker_to_handoff(self):
        """2026-09-13 模式仲裁：桥接态下发话锁切交交接锁——桥接引渡权
        （过渡留在主角一侧）高于静态发话锁（焦点钉死发话者）。"""
        assert pick_subject_lock(["landing"], bridge=True) == SUBJECT_LOCK_HANDOFF
        assert pick_subject_lock(["speaker"], bridge=True) == SUBJECT_LOCK_HANDOFF
        assert pick_subject_lock(["landing", "echo"], bridge=True) == SUBJECT_LOCK_HANDOFF

    def test_bridge_no_arbitration_for_prop_reply(self):
        """物镜/静音锁不定义镜头跟谁（只写器物/只写开腔前缓冲），与桥接
        不冲突——桥接态下维持原映射，不仲裁。"""
        assert pick_subject_lock(["prop"], bridge=True) == SUBJECT_LOCK_PROP
        assert pick_subject_lock(["ambient"], bridge=True) == SUBJECT_LOCK_PROP
        assert pick_subject_lock(["reply"], bridge=True) == SUBJECT_LOCK_REPLY

    def test_no_bridge_keeps_speaker(self):
        """非桥接态（缺省）零破坏：landing/speaker 仍映射发话锁。"""
        assert pick_subject_lock(["landing"]) == SUBJECT_LOCK_SPEAKER
        assert pick_subject_lock(["landing"], bridge=False) == SUBJECT_LOCK_SPEAKER


class TestLockInjection:

    def _build(self, **kw):
        base = dict(
            fragment="老周咳嗽着问：「这发电机还能修好吗？」",
            rolling_prefix="林尘蹲在机房里。",
            mode="stitch",
            picked_parts=["皮带在轮槽里打着滑"],
            target_chars=50,
        )
        base.update(kw)
        return build_continue_prompt(**base)

    def test_prop_lock_rendered_after_parts_block(self):
        _, user = self._build(subject_lock=SUBJECT_LOCK_PROP)
        assert "单焦距·物镜锁" in user
        assert "情绪不走人物走物件" in user          # 文学温度防御（红队 Q4）
        assert "不推进到下一拍剧情" in user           # 硬刹车底线
        # 紧贴零件块（相机契约读作「这枚零件的拍法」）
        assert user.index("选定镜头零件") < user.index("单焦距·物镜锁")

    def test_speaker_and_reply_locks_rendered(self):
        _, user = self._build(subject_lock=SUBJECT_LOCK_SPEAKER)
        assert "单焦距·发话锁" in user and "不替他说下一句" in user
        _, user = self._build(subject_lock=SUBJECT_LOCK_REPLY)
        assert "单焦距·静音锁" in user and "不出任何回应台词" in user

    def test_handoff_lock_rendered_with_bridge_context(self):
        """交接锁随桥接态渲染（发话者话音落下→切交主角侧），且只出现
        交接锁不出现发话锁——同位双主体死锁在 prompt 层不可复现。"""
        _, user = self._build(
            subject_lock=SUBJECT_LOCK_HANDOFF,
            suffix_anchor="“这样啊，那你路上当心点。”王叔弓着腰咳嗽了几声。",
        )
        assert "单焦距·交接锁" in user
        assert "镜头切回主角一侧" in user
        assert "单焦距·发话锁" not in user

    def test_zero_change_without_lock(self):
        """空锁 = 逐字节零变化（与不传参数的产物完全一致）。"""
        a = self._build(subject_lock="")
        b = self._build()
        assert a == b
        for phrase in ("物镜锁", "发话锁", "静音锁"):
            assert phrase not in a[1]

    def test_lock_texts_dosage_restraint(self):
        """锁文本措辞纪律：不用 lint 词典的强措辞（禁令走「不写/不出」）。"""
        for text in _SUBJECT_LOCK_TEXTS.values():
            for word in ("铁律", "绝不", "必须", "禁止", "不许", "严禁", "务必"):
                assert word not in text, f"锁文本残留强措辞「{word}」"
