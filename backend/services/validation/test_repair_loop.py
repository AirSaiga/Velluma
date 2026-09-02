# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 缝合返修环单测（约束治理二期）
"""
run_repair_loop 泛型编排单测（纯算法——regenerate/recheck/excise 全部注入
假回调，不连 LLM/DB）。

锁定闭环契约（docs/constraint-governance.md §返修环）：
1. 无违规 → clean 放行，零返修调用（防御位——空调用方不该进这里）；
2. 首犯改写后净 → repaired（验收 = recheck 零违规，不采信模型自我声明）；
3. 改写死不悔改 → excise 切除成功 → excised；
4. 切除不可行（None=豁免/长度地板/定位失败）→ rejected，原稿随结果回传
   （调用方熔断降级/拒稿帧逃生舱要用原稿）；
5. 无切除兜底（excise=None）→ 改写失败直接 rejected；
6. 改写预算：max_retries 次封顶（延迟封顶纪律），max_retries=0 直跳切除；
7. regenerate 返 ""（失败约定）→ 不计验收直接下一轮；
8. fixed_kinds 去重排序；rejected 时 fixed_kinds 清空、remaining=原违规。

运行：python -m pytest backend/services/validation/test_repair_loop.py -v
"""
import asyncio

from backend.services.validation.repair_loop import (
    ACTION_CLEAN,
    ACTION_EXCISED,
    ACTION_REJECTED,
    ACTION_REPAIRED,
    run_repair_loop,
)

ORIGINAL = "违规原稿。他拧开流光的螺栓。"
CLEAN_DRAFT = "改写后的干净稿。他拧紧了自己那台旧机甲的螺栓。"
EXCISED_DRAFT = "切除后的稿子。"

VIOLATIONS = [
    {"kind": "out_of_scene", "message": "「流光」不在场"},
    {"kind": "out_of_scene", "message": "同种第二条"},
    {"kind": "canon_leak", "message": "泄底"},
]


def _run(text, violations, **kw):
    return asyncio.run(run_repair_loop(text, violations, **kw))


class _FakeRegen:
    """替身 regenerate：记录调用，按队列依次返回候选稿。"""

    def __init__(self, candidates):
        self.candidates = list(candidates)
        self.calls = []

    async def __call__(self, text, violations):
        self.calls.append((text, violations))
        return self.candidates.pop(0) if self.candidates else ""


def _recheck_clean(_text):
    return []


def _recheck_always_dirty(_text):
    return [{"kind": "out_of_scene", "message": "仍在违规"}]


def test_clean_passes_with_zero_calls():
    regen = _FakeRegen([CLEAN_DRAFT])
    result = _run(ORIGINAL, [], regenerate=regen, recheck=_recheck_clean)
    assert result.action == ACTION_CLEAN
    assert result.text == ORIGINAL
    assert result.attempts == 0
    assert regen.calls == []


def test_repaired_on_first_rewrite():
    regen = _FakeRegen([CLEAN_DRAFT])
    result = _run(ORIGINAL, VIOLATIONS, regenerate=regen, recheck=_recheck_clean)
    assert result.action == ACTION_REPAIRED
    assert result.text == CLEAN_DRAFT
    assert result.attempts == 1
    assert result.fixed_kinds == ["canon_leak", "out_of_scene"]  # 去重+排序
    assert result.remaining == []


def test_stubborn_draft_falls_to_excise():
    regen = _FakeRegen(["还是违规的改写稿。"])
    result = _run(
        ORIGINAL, VIOLATIONS,
        regenerate=regen, recheck=_recheck_always_dirty,
        excise=lambda text, violations: EXCISED_DRAFT,
    )
    # recheck 恒脏时切除稿也验收不过 → rejected；改用「改写稿脏、切除稿净」的
    # 分支 recheck 才能走到 excised——这里先锁「切除验收同样硬性」
    assert result.action == ACTION_REJECTED

    def selective_recheck(text):
        return [] if text == EXCISED_DRAFT else _recheck_always_dirty(text)

    regen2 = _FakeRegen(["还是违规的改写稿。"])
    result2 = _run(
        ORIGINAL, VIOLATIONS,
        regenerate=regen2, recheck=selective_recheck,
        excise=lambda text, violations: EXCISED_DRAFT,
    )
    assert result2.action == ACTION_EXCISED
    assert result2.text == EXCISED_DRAFT
    assert result2.attempts == 1
    assert result2.fixed_kinds == ["canon_leak", "out_of_scene"]


def test_rejected_when_excise_not_viable():
    regen = _FakeRegen(["仍旧违规。"])
    result = _run(
        ORIGINAL, VIOLATIONS,
        regenerate=regen, recheck=_recheck_always_dirty,
        excise=lambda text, violations: None,  # 豁免/长度地板 → 不可切
    )
    assert result.action == ACTION_REJECTED
    assert result.text == ORIGINAL            # 原稿回传（熔断降级/逃生舱要用）
    assert result.fixed_kinds == []
    assert result.remaining == VIOLATIONS


def test_rejected_without_excise_callback():
    regen = _FakeRegen(["仍旧违规。"])
    result = _run(
        ORIGINAL, VIOLATIONS,
        regenerate=regen, recheck=_recheck_always_dirty,
    )
    assert result.action == ACTION_REJECTED
    assert result.text == ORIGINAL


def test_retry_budget_respected():
    regen = _FakeRegen(["脏稿一", "脏稿二", "脏稿三"])
    result = _run(
        ORIGINAL, VIOLATIONS,
        regenerate=regen, recheck=_recheck_always_dirty,
        max_retries=2,
    )
    assert result.action == ACTION_REJECTED
    assert result.attempts == 2               # 封顶 2 次，第三候选永不被取
    assert len(regen.calls) == 2
    assert regen.candidates == ["脏稿三"]


def test_zero_retries_skips_regenerate_goes_excise():
    regen = _FakeRegen([CLEAN_DRAFT])
    result = _run(
        ORIGINAL, VIOLATIONS,
        regenerate=regen, recheck=_recheck_clean,
        excise=lambda text, violations: EXCISED_DRAFT,
        max_retries=0,
    )
    assert result.action == ACTION_EXCISED
    assert result.attempts == 0
    assert regen.calls == []


def test_empty_regenerate_counts_as_failed_attempt():
    # 第一次改写失败（""约定）→ 不计验收直接下一轮；第二次成功
    regen = _FakeRegen(["", CLEAN_DRAFT])
    result = _run(
        ORIGINAL, VIOLATIONS,
        regenerate=regen, recheck=_recheck_clean,
        max_retries=2,
    )
    assert result.action == ACTION_REPAIRED
    assert result.attempts == 2


def test_regenerate_receives_original_and_violations():
    regen = _FakeRegen([CLEAN_DRAFT])
    _run(ORIGINAL, VIOLATIONS, regenerate=regen, recheck=_recheck_clean)
    assert regen.calls == [(ORIGINAL, VIOLATIONS)]  # 带稿改写契约：原稿+清单
