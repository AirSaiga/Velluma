"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
Fortress 双候选生成器（Phase 3 CP4.4 新建，蓝图 §4.6.2）。

职责：TIER_3_FORTRESS 拍生成 2 份候选，代码级初筛优选一份（Re3 Rewrite 思想低成本版）。
默认关闭（enable_fortress_dual_candidate=False），章节卡/全局配置开启。

业务场景：
- drafting._generate_beat_with_failfast 在 tier=FORTRESS 且 enable 开关打开时调用
- 与单候选 fail-fast 路径互补：双候选是"横向优选"，fail-fast 是"纵向重试"

算法（蓝图 §4.6.2）：
1. 并行生成 2 份候选（不同温度：0.75 标准 / 0.85 高创意）
2. 代码级初筛（零 token）：跑 DraftValidatorPipeline（禁词/红线/句长）
   - 候选失败 → 淘汰
   - 两份都失败 → fallback 到 fail-fast 重试
3. 优选：两份都通过 → 选禁词命中少 + 句长 CV 健康的
4. 观测层记录候选数 / 优选依据 / 是否降级
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# 双候选生成参数（蓝图 §4.6.2）
# ============================================================

FORTRESS_CANDIDATE_A_TEMP = 0.75  # 标准温度（稳健）
FORTRESS_CANDIDATE_B_TEMP = 0.85  # 高创意温度（多样）


# ============================================================
# 候选评分结果
# ============================================================

@dataclass
class CandidateScore:
    """单份候选的代码级评分。

    越低越好（penalty 累加）：
    - passed=False（fail-fast 校验失败）→ penalty=9999（直接淘汰）
    - cliche_hits: 禁词命中数
    - red_line_violations: 红线违反数（每次 +10 penalty）
    - cv_penalty: 句长 CV 偏离健康区间 [0.35, 0.80] 的程度
    """
    passed: bool
    cliche_hits: int = 0
    red_line_violations: int = 0
    cv_value: Optional[float] = None
    penalty: float = 0.0
    reason: str = ""

    @classmethod
    def failed(cls, reason: str) -> "CandidateScore":
        return cls(passed=False, penalty=9999.0, reason=reason)


def score_candidate(
    text: str,
    validator_result: Optional[Tuple[bool, str, list]] = None,
) -> CandidateScore:
    """对单份候选做代码级评分（零 token）。

    Args:
        text: 候选正文
        validator_result: build_draft_validator 返回的 (is_valid, fail_reason, categories)；
                         None 表示未跑校验

    Returns:
        CandidateScore
    """
    from backend.services.validation.thresholds import CV_THRESHOLD_LO, CV_THRESHOLD_HI

    if not text or not text.strip():
        return CandidateScore.failed("empty_output")

    # fail-fast 校验结果
    if validator_result is not None:
        is_valid, fail_reason, _categories = validator_result
        if not is_valid:
            return CandidateScore.failed(f"fail_fast_rejected: {fail_reason[:80]}")

    # 跑代码级审计的零 token 指标（Cliché + RedLine + Rhythm）
    try:
        from backend.services.validation.code_auditors import (
            ClichéAuditor, RedLineAuditor, RhythmAuditor,
        )
        # 用空 context（禁词加载走 cliche_provider 缓存降级；红线/CV 不依赖 context）
        import asyncio
        async def _audit_all() -> Tuple[int, int, Optional[float]]:
            cliche_hits = 0
            red_line = 0
            cv: Optional[float] = None
            # Cliché
            try:
                cr = await ClichéAuditor().audit(text, {"book": {"style_blacklist": []}, "style_card": {}})
                per_1k = cr.metrics.get("cliche_hits_per_1k", 0) or 0
                # 估算命中数 = per_1k * 字数 / 1000
                word_count = max(1, len(text.replace(" ", "")))
                cliche_hits = int(per_1k * word_count / 1000)
            except Exception:
                pass
            # RedLine（无 red_lines context → 不会命中，penalty=0）
            try:
                rr = await RedLineAuditor().audit(text, {"beats": [], "book": {"core_motifs_taboos": ""}})
                red_line = int(rr.metrics.get("red_line_violations", 0) or 0)
            except Exception:
                pass
            # Rhythm CV
            try:
                rh = await RhythmAuditor().audit(text, {})
                cv = rh.metrics.get("sentence_len_cv")
            except Exception:
                pass
            return cliche_hits, red_line, cv

        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 已在 async 上下文 → 不能用 run_until_complete；改用同步近似
            # （score_candidate 在 async 调用方应改用 score_candidate_async）
            cliche_hits, red_line, cv = _score_sync_fallback(text)
        else:
            cliche_hits, red_line, cv = loop.run_until_complete(_audit_all())
    except Exception as e:
        logger.warning(f"[Fortress] score_candidate 审计失败，降级 0 penalty: {e}")
        return CandidateScore(passed=True, penalty=0.0, reason=f"audit_failed: {type(e).__name__}")

    # 计算 penalty
    penalty = 0.0
    penalty += cliche_hits * 1.0           # 每个禁词命中 +1
    penalty += red_line * 10.0             # 每个红线违反 +10（严重）
    if cv is not None:
        if cv < CV_THRESHOLD_LO:
            penalty += (CV_THRESHOLD_LO - cv) * 10.0  # CV 偏低 +penalty
        elif cv > CV_THRESHOLD_HI:
            penalty += 0.0  # CV 偏高不罚（节奏多变通常无问题）

    return CandidateScore(
        passed=True,
        cliche_hits=cliche_hits,
        red_line_violations=red_line,
        cv_value=cv,
        penalty=penalty,
    )


def _score_sync_fallback(text: str) -> Tuple[int, int, Optional[float]]:
    """同步评分兜底（不跑 Auditor，仅基础统计）。

    用于 score_candidate 在 async 上下文外被调用时（不应发生，但兜底）。
    """
    # 极简：只算字数 + 估 CV
    import re
    sentences = [s.strip() for s in re.split(r"[。！？!?\n]", text) if len(s.strip()) > 2]
    cv = None
    if len(sentences) >= 2:
        lengths = [float(len(s)) for s in sentences]
        mean = sum(lengths) / len(lengths)
        if mean > 0:
            variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
            cv = (variance ** 0.5) / mean
    return 0, 0, cv


async def score_candidate_async(
    text: str,
    validator_result: Optional[Tuple[bool, str, list]] = None,
) -> CandidateScore:
    """score_candidate 的 async 版本（推荐在 async 调用方使用）。

    跑完整代码级审计（Cliché + RedLine + Rhythm），零 token。
    """
    from backend.services.validation.code_auditors import (
        ClichéAuditor, RedLineAuditor, RhythmAuditor,
    )
    from backend.services.validation.thresholds import CV_THRESHOLD_LO, CV_THRESHOLD_HI

    if not text or not text.strip():
        return CandidateScore.failed("empty_output")

    if validator_result is not None:
        is_valid, fail_reason, _categories = validator_result
        if not is_valid:
            return CandidateScore.failed(f"fail_fast_rejected: {fail_reason[:80]}")

    # 跑三个零 token Auditor
    cliche_hits = 0
    red_line = 0
    cv: Optional[float] = None
    empty_ctx = {"book": {"style_blacklist": [], "core_motifs_taboos": ""},
                 "style_card": {}, "beats": []}
    try:
        cr = await ClichéAuditor().audit(text, empty_ctx)
        per_1k = cr.metrics.get("cliche_hits_per_1k", 0) or 0
        word_count = max(1, len(text.replace(" ", "")))
        cliche_hits = int(per_1k * word_count / 1000)
    except Exception:
        pass
    try:
        rr = await RedLineAuditor().audit(text, empty_ctx)
        red_line = int(rr.metrics.get("red_line_violations", 0) or 0)
    except Exception:
        pass
    try:
        rh = await RhythmAuditor().audit(text, {})
        cv = rh.metrics.get("sentence_len_cv")
    except Exception:
        pass

    penalty = 0.0
    penalty += cliche_hits * 1.0
    penalty += red_line * 10.0
    if cv is not None and cv < CV_THRESHOLD_LO:
        penalty += (CV_THRESHOLD_LO - cv) * 10.0

    return CandidateScore(
        passed=True,
        cliche_hits=cliche_hits,
        red_line_violations=red_line,
        cv_value=cv,
        penalty=penalty,
    )


# ============================================================
# 双候选优选
# ============================================================

@dataclass
class DualCandidateResult:
    """双候选生成 + 优选结果。"""
    winner_text: str
    winner_label: str  # "A" / "B" / "fallback_single"
    scores: dict  # {"A": CandidateScore dict, "B": ...}
    degraded: Optional[dict] = None  # 降级标记（两份都失败时）


async def generate_and_pick_dual_candidates(
    generate_once: Callable[[float, str], Awaitable[str]],
    validate: Optional[Callable[[str], Awaitable[Tuple[bool, str, list]]]],
    beat_index: int,
    fail_fast_max_attempts: int,
    initial_temperature: float,
    stage_name: str,
    recorder: Optional[Any] = None,
) -> DualCandidateResult:
    """Fortress 双候选生成 + 优选（蓝图 §4.6.2）。

    Args:
        generate_once: 单次生成闭包（来自 _generate_beat_with_failfast）；
                       接收 (temperature, hint)，返回生成的 chunk 文本
        validate: fail-fast 校验闭包；接收 chunk，返回 (is_valid, fail_reason, categories)
        beat_index: Beat 序号（1-based，用于日志/观测）
        fail_fast_max_attempts: 失败后单候选重试次数上限（fallback 路径用）
        initial_temperature: 初始温度（仅 fallback 用）
        stage_name: 阶段名（日志）
        recorder: 可选 RunRecorder

    Returns:
        DualCandidateResult
    """
    from backend.services.workflows.fail_fast import execute_generation_with_retry

    # 1. 并行生成 2 份候选（不同温度）
    try:
        cand_a, cand_b = await asyncio.gather(
            generate_once(FORTRESS_CANDIDATE_A_TEMP, ""),
            generate_once(FORTRESS_CANDIDATE_B_TEMP, ""),
        )
    except Exception as e:
        # 并行生成整体失败 → 降级 fallback
        logger.warning(f"[Fortress] Beat {beat_index} 双候选并行生成失败，降级单候选: {e}")
        if recorder is not None:
            recorder.record_degraded(
                stage=f"fortress.beat_{beat_index}",
                reason="dual_generation_exception",
                action="fallback_single_candidate",
                model_slot="creative",
                detail=f"{type(e).__name__}: {str(e)[:200]}",
            )
        # fallback：单候选 fail-fast 重试
        chunk, _ = await execute_generation_with_retry(
            generate_once=generate_once, validate=validate,
            max_attempts=fail_fast_max_attempts, beat_number=beat_index,
            initial_temperature=initial_temperature, strategy_name=stage_name,
            recorder=recorder,
        )
        return DualCandidateResult(
            winner_text=chunk, winner_label="fallback_single",
            scores={}, degraded={
                "reason": "dual_generation_exception",
                "action": "fallback_single_candidate",
            },
        )

    # 2. 跑 fail-fast 校验 + 代码级评分（零 token）
    val_a = await validate(cand_a) if validate else None
    val_b = await validate(cand_b) if validate else None
    score_a = await score_candidate_async(cand_a, val_a)
    score_b = await score_candidate_async(cand_b, val_b)

    # 3. 优选
    if not score_a.passed and not score_b.passed:
        # 两份都失败 → fallback 到 fail-fast 重试
        logger.warning(
            f"[Fortress] Beat {beat_index} 双候选均校验失败，降级 fail-fast 重试"
        )
        if recorder is not None:
            recorder.record_degraded(
                stage=f"fortress.beat_{beat_index}",
                reason="both_candidates_failed_validation",
                action="fallback_fail_fast_retry",
                model_slot="creative",
                detail=f"A={score_a.reason}; B={score_b.reason}",
            )
        chunk, _ = await execute_generation_with_retry(
            generate_once=generate_once, validate=validate,
            max_attempts=fail_fast_max_attempts, beat_number=beat_index,
            initial_temperature=initial_temperature, strategy_name=stage_name,
            recorder=recorder,
        )
        return DualCandidateResult(
            winner_text=chunk, winner_label="fallback_single",
            scores={"A": score_a.__dict__, "B": score_b.__dict__},
            degraded={
                "reason": "both_candidates_failed_validation",
                "action": "fallback_fail_fast_retry",
            },
        )

    # 至少一份通过 → 选 penalty 低的
    if score_a.passed and score_b.passed:
        winner = "A" if score_a.penalty <= score_b.penalty else "B"
    elif score_a.passed:
        winner = "A"
    else:
        winner = "B"

    winner_text = cand_a if winner == "A" else cand_b
    winner_score = score_a if winner == "A" else score_b

    logger.info(
        f"[Fortress] Beat {beat_index} 双候选优选完成: winner={winner} "
        f"(A penalty={score_a.penalty:.2f}, B penalty={score_b.penalty:.2f})"
    )

    return DualCandidateResult(
        winner_text=winner_text,
        winner_label=winner,
        scores={
            "A": score_a.__dict__,
            "B": score_b.__dict__,
        },
        degraded=None,
    )
