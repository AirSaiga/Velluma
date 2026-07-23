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
CP4.4 Fortress 双候选 smoke test（独立运行）。

覆盖：
- score_candidate_async：基础评分（禁词/红线/CV penalty）
- score_candidate_async：fail-fast 失败 → 淘汰（penalty=9999）
- generate_and_pick_dual_candidates：两份都通过 → 选 penalty 低的
- generate_and_pick_dual_candidates：一份通过一份失败 → 选通过的
- generate_and_pick_dual_candidates：两份都失败 → fallback 单候选
- generate_and_pick_dual_candidates：生成异常 → fallback 单候选
- 默认关闭验证（DraftingFeatureFlags.enable_fortress_dual_candidate=False）
"""

import asyncio
import sys
from typing import List


async def main() -> int:
    from backend.services.workflows.fortress_candidate import (
        score_candidate_async, generate_and_pick_dual_candidates,
        FORTRESS_CANDIDATE_A_TEMP, FORTRESS_CANDIDATE_B_TEMP,
        CandidateScore,
    )
    from backend.schemas.generation import DraftingFeatureFlags

    failures: List[str] = []

    def check(cond: bool, msg: str) -> None:
        if cond:
            print(f"  [OK] {msg}")
        else:
            print(f"  [FAIL] {msg}")
            failures.append(msg)

    print("=== 1. DraftingFeatureFlags 默认关闭 Fortress ===")
    flags = DraftingFeatureFlags()
    check(flags.enable_fortress_dual_candidate is False,
          "默认 enable_fortress_dual_candidate=False")
    flags_on = DraftingFeatureFlags(enable_fortress_dual_candidate=True)
    check(flags_on.enable_fortress_dual_candidate is True,
          "可显式开启 enable_fortress_dual_candidate=True")

    print("\n=== 2. score_candidate_async：基础评分 ===")
    # 健康文本（CV 健康、无禁词/红线）
    healthy = "他站住。风吹过远处的山岗，带来一阵若有若无的草木气息。她笑了。"
    score = await score_candidate_async(healthy, validator_result=None)
    check(score.passed is True, "健康文本 passed=True")
    check(score.penalty >= 0, f"penalty ≥ 0（实际 {score.penalty}）")
    print(f"       健康 penalty={score.penalty}, CV={score.cv_value}")

    print("\n=== 3. score_candidate_async：fail-fast 失败 → 淘汰 ===")
    score = await score_candidate_async("某文本", validator_result=(False, "禁词超阈值", ["文风"]))
    check(score.passed is False, "fail-fast 失败 → passed=False")
    check(score.penalty >= 9999, f"fail-fast 失败 penalty=9999（实际 {score.penalty}）")

    print("\n=== 4. score_candidate_async：空文本 → 淘汰 ===")
    score = await score_candidate_async("", validator_result=None)
    check(score.passed is False, "空文本 → passed=False")

    print("\n=== 5. generate_and_pick_dual_candidates：两份都通过 → 选 penalty 低的 ===")
    call_temps: List[float] = []

    async def mock_generate_once(temp: float, hint: str) -> str:
        call_temps.append(temp)
        # A 温度（0.75）返回健康文本；B 温度（0.85）返回含禁词文本
        if abs(temp - FORTRESS_CANDIDATE_A_TEMP) < 0.01:
            return "他站住。风吹过山岗，带来草木气息。她笑了。"  # 健康
        else:
            return "他眼底闪过一丝惊愕，嘴角勾起一抹冷笑。"  # 含禁词（penalty 高）

    async def mock_validate(chunk: str):
        return (True, "", [])  # 都通过 fail-fast

    result = await generate_and_pick_dual_candidates(
        generate_once=mock_generate_once,
        validate=mock_validate,
        beat_index=1,
        fail_fast_max_attempts=2,
        initial_temperature=0.75,
        stage_name="test_fortress",
        recorder=None,
    )
    check(len(call_temps) == 2, f"并行生成 2 份（实际 {len(call_temps)} 次调用）")
    check(FORTRESS_CANDIDATE_A_TEMP in call_temps, "候选 A 温度 0.75")
    check(FORTRESS_CANDIDATE_B_TEMP in call_temps, "候选 B 温度 0.85")
    check(result.winner_label == "A", f"优选 A（健康，penalty 低；实际 winner={result.winner_label}）")
    check("A" in result.scores and "B" in result.scores, "scores 含 A 和 B")
    check(result.degraded is None, "两份都通过 → 无降级")
    print(f"       winner={result.winner_label}, A penalty={result.scores['A']['penalty']:.2f}, B penalty={result.scores['B']['penalty']:.2f}")

    print("\n=== 6. generate_and_pick_dual_candidates：一份通过一份失败 → 选通过的 ===")
    async def mock_generate_one_fail(temp: float, hint: str) -> str:
        if abs(temp - FORTRESS_CANDIDATE_A_TEMP) < 0.01:
            return "健康文本。他走过来。她笑了。"
        return "另一份文本"

    async def mock_validate_one_fail(chunk: str):
        # A 通过，B 失败
        if "健康文本" in chunk:
            return (True, "", [])
        return (False, "红线违反", ["红线"])

    result = await generate_and_pick_dual_candidates(
        generate_once=mock_generate_one_fail,
        validate=mock_validate_one_fail,
        beat_index=2,
        fail_fast_max_attempts=2,
        initial_temperature=0.75,
        stage_name="test_fortress",
        recorder=None,
    )
    check(result.winner_label == "A", f"一份通过一份失败 → 选通过的 A（实际 winner={result.winner_label}）")
    check("健康文本" in result.winner_text, "winner_text 是通过的候选")

    print("\n=== 7. generate_and_pick_dual_candidates：两份都失败 → fallback 单候选 ===")
    async def mock_generate_both(temp: float, hint: str) -> str:
        return f"候选 temp={temp}"

    async def mock_validate_both_fail(chunk: str):
        return (False, "都失败", ["红线"])

    # fallback 路径会调 execute_generation_with_retry，内部调 generate_once
    # 这里 mock generate_once 在 fallback 时也返回文本
    call_count_after_fallback = [0]

    async def mock_generate_with_fallback(temp: float, hint: str) -> str:
        call_count_after_fallback[0] += 1
        # 前 2 次（双候选并行）返回，后续 fallback 返回最终文本
        if call_count_after_fallback[0] <= 2:
            return f"候选 temp={temp}"
        return "fallback 最终文本"

    result = await generate_and_pick_dual_candidates(
        generate_once=mock_generate_with_fallback,
        validate=mock_validate_both_fail,
        beat_index=3,
        fail_fast_max_attempts=2,
        initial_temperature=0.75,
        stage_name="test_fortress",
        recorder=None,
    )
    check(result.degraded is not None, "两份都失败 → degraded 标记")
    check(result.degraded.get("reason") == "both_candidates_failed_validation",
          f"degraded.reason 正确（实际 {result.degraded.get('reason')}）")
    check(result.winner_label == "fallback_single", f"winner_label=fallback_single（实际 {result.winner_label}）")

    print("\n=== 8. generate_and_pick_dual_candidates：生成异常 → fallback 单候选 ===")
    async def mock_generate_exception(temp: float, hint: str) -> str:
        raise RuntimeError("模拟 LLM 服务不可用")

    result = await generate_and_pick_dual_candidates(
        generate_once=mock_generate_exception,
        validate=None,
        beat_index=4,
        fail_fast_max_attempts=1,
        initial_temperature=0.75,
        stage_name="test_fortress",
        recorder=None,
    )
    check(result.degraded is not None, "生成异常 → degraded 标记")
    check(result.winner_label == "fallback_single", "生成异常 → fallback_single")

    print("\n" + "=" * 50)
    if failures:
        print(f"FAILED: {len(failures)} 项")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CP4.4 SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
