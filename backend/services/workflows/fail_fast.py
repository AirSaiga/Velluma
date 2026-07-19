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
Fail-Fast 起草即时校验设施（Phase 1 CP1.1）。

职责：
- 在每拍正文生成后立即跑代码级校验（零/低 token 成本）
- 命中阻断级问题（红线/题材污染/AI 腔超阈值）时带 fail_reason 重试
- 按失败类别调温：文风类升温至 0.9（释放创意），其他类降温 -0.1（精准修复）

业务场景：
- drafting._execute_unified_path 在 Standard/Fortress tier 调用本模块包装的 generate_once
- 校验失败时自动重试 ≤ max_attempts 轮（默认 2）
- Fast tier 不启用（灵气优先，参考调研报告 §4.6.1）

来源说明：
- 本模块从已删除的 drafting_prose.py 抽取并改造 _execute_generation_with_retry
  和 _adjust_after_failure（V4.1 文风升温策略原版保留）
- 删除了原实现的 BeatContext 依赖（仅用于读 max_attempts，改为参数直传）
- generate_once 返回值从 (chunk, sys_p, usr_p) 简化为 str（prompt 历史由调用方外部记录）

依赖项：
- backend.services.observability.run_recorder.RunRecorder：Phase 0 观测层，记录重试事件
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# 调温策略
# ============================================================

def adjust_after_failure(
    current_temp: float,
    fail_categories: List[str],
    fail_reason: str,
) -> tuple[float, str]:
    """根据失败类别调整温度并生成下一轮的修正提示。

    设计依据（V4.1 prose 版原策略，调研报告 §4.6.1 引用）：
    - 文风类失败（AI 腔/句长拖沓）：直接跳到高创意区 0.9+，正向引导大胆重写
    - 其他失败（红线/逻辑/物理幻觉）：降温 -0.1，精准修复冲突
    - 注意力预算原则：升温能让模型脱离默认分布，降温能让模型聚焦修复

    Args:
        current_temp: 当前温度
        fail_categories: 失败类别列表（红线/物理幻觉/OOC/关系/文风/逻辑/其他）
        fail_reason: 失败原因文本（直接拼入提示给 LLM 看）

    Returns:
        tuple: (新温度, 待追加到下轮 prompt 的修正提示)
    """
    # V4.1 人味增强：文风类失败不再保守小步升温，而是直接跳到高创意区
    # 并给出正向修正指令（而非负面清单）
    if "文风" in fail_categories:
        new_temp = max(current_temp, 0.9)
        pending_hint = (
            f"\n\n【文风修正要求】上一版本被批评为：{fail_reason}。"
            f"请保留原文中最有画面感的一句话，大胆重写其余部分。"
            f"增加 POV 角色的私人偏见、思维的噪音和口语化的呼吸感。允许不完美。"
        )
    else:
        new_temp = max(0.3, current_temp - 0.1)
        pending_hint = (
            f"\n\n【修正要求】上一版本存在以下问题：{fail_reason}。"
            f"请保持原语境，仅修复该冲突。"
        )
    return new_temp, pending_hint


# ============================================================
# 重试状态
# ============================================================

@dataclass
class RetryState:
    """内部重试状态。"""
    attempt: int = 0
    chunk: str = ""
    is_valid: bool = False
    current_temp: float = 0.8  # 由调用方在初始化时覆盖
    pending_hint: str = ""
    prompts_history: List[dict] = field(default_factory=list)


# ============================================================
# 重试执行器
# ============================================================

async def execute_generation_with_retry(
    generate_once: Callable[[float, str], Awaitable[str]],
    validate: Optional[Callable[[str], Awaitable[tuple[bool, str, List[str]]]]],
    max_attempts: int,
    beat_number: int,
    initial_temperature: float,
    strategy_name: str = "Generation",
    recorder: Optional[Any] = None,
) -> tuple[str, List[dict]]:
    """带 Fail-Fast 重试机制的生成执行器。

    业务流程：
    1. 调 generate_once(temperature, pending_hint) 生成文本
    2. 若 validate 不为 None，跑代码级校验
    3. 校验失败：按 categories 调温 + 拼 pending_hint + 进入下一轮
    4. 校验通过 / 重试耗尽：返回当前 chunk

    Args:
        generate_once: 单次生成闭包，接收 (temperature, pending_hint)，返回生成的 chunk 文本
        validate: 可选校验闭包，接收 chunk，返回 (is_valid, fail_reason, fail_categories)；
                  None 时跳过校验（Fast tier）
        max_attempts: 最大尝试次数（含首次）；1 = 不重试
        beat_number: Beat 序号（1-based，用于日志）
        initial_temperature: 初始温度
        strategy_name: 策略名（用于日志）
        recorder: 可选的 RunRecorder，记录重试事件（Phase 0 观测层）

    Returns:
        tuple: (最终文本, prompts 历史)
    """
    state = RetryState(current_temp=initial_temperature)

    logger.info(f"[{strategy_name}] Beat {beat_number} 开始生成（最多 {max_attempts} 次尝试）...")

    while state.attempt < max_attempts and not state.is_valid:
        state.attempt += 1
        try:
            # 单次生成
            chunk = await generate_once(state.current_temp, state.pending_hint)
            state.chunk = chunk

            # 处理空响应
            if not chunk:
                logger.warning(
                    f"[{strategy_name}] Beat {beat_number} 第{state.attempt}次返回空文本"
                )
                if state.attempt < max_attempts:
                    state.current_temp = min(1.0, state.current_temp + 0.1)
                    continue

            # Fail-Fast 校验
            if validate and state.attempt < max_attempts:
                is_valid, fail_reason, fail_categories = await validate(chunk)
                if not is_valid:
                    logger.warning(
                        f"[{strategy_name}] Beat {beat_number} 第{state.attempt}次断言失败: {fail_reason}"
                    )
                    # 调温 + 拼 pending_hint
                    state.current_temp, state.pending_hint = adjust_after_failure(
                        state.current_temp, fail_categories, fail_reason
                    )
                    # 观测层记录
                    if recorder is not None:
                        recorder.record_degraded(
                            stage=f"drafting.beat_{beat_number}.attempt_{state.attempt}",
                            reason="fail_fast_validation_failed",
                            action="retry_with_adjusted_temp",
                            model_slot="creative",
                            detail=f"categories={fail_categories}; reason={fail_reason[:200]}",
                        )
                else:
                    state.is_valid = True
            else:
                state.is_valid = True

        except Exception as e:
            logger.error(
                f"[{strategy_name}] Beat {beat_number} 第{state.attempt}次异常: "
                f"{type(e).__name__}: {e}"
            )
            if state.attempt >= max_attempts:
                break
            await asyncio.sleep(1)

    logger.info(
        f"[{strategy_name}] Beat {beat_number} 完成，"
        f"attempts={state.attempt} 字数={len(state.chunk)}"
    )
    return state.chunk, state.prompts_history


# ============================================================
# 校验闭包工厂
# ============================================================

def build_draft_validator(
    beat: dict,
    book: Any,
    pov_character: str,
    style_cliche_threshold: int = 2,
) -> Callable[[str], Awaitable[tuple[bool, str, List[str]]]]:
    """构造起草校验闭包，供 execute_generation_with_retry 使用。

    CP1.1 启用 3 个零/低依赖校验器（来自 validators.py）：
    - StyleClicheValidator（禁词正则，threshold 可配）
    - PlotLogicValidator（红线引号词硬校验）
    - PacingValidator（句长，仅 Fast tier 触发 error）

    CharacterOOCValidator（embedding）CP1 不启用，留 CP2 评估成本后开。

    Args:
        beat: Beat 字典（取 red_lines / pacing_type 等）
        book: 书籍对象（取 style_blacklist / core_motifs_taboos）
        pov_character: POV 角色名（作为 required_entities，至少必须出现）
        style_cliche_threshold: AI 腔命中阈值，Fortress tier 可降到 1 加严

    Returns:
        async 校验闭包：(chunk) -> (is_valid, fail_reason, fail_categories)
    """
    from backend.services.workflows.validators import (
        DraftValidatorPipeline,
        StyleClicheValidator,
        PlotLogicValidator,
        PacingValidator,
    )

    # 组装 pipeline：替换 StyleCliche 的 threshold
    pipeline = DraftValidatorPipeline()
    # 找到并替换 StyleClicheValidator 实例（保留顺序）
    new_validators = []
    for v in pipeline.validators:
        if isinstance(v, StyleClicheValidator):
            new_v = StyleClicheValidator()
            new_v.threshold = style_cliche_threshold
            new_validators.append(new_v)
        else:
            new_validators.append(v)
    # 过滤掉 CharacterOOCValidator（CP1 不启用，成本高）
    from backend.services.workflows.validators import CharacterOOCValidator
    pipeline.validators = [v for v in new_validators if not isinstance(v, CharacterOOCValidator)]

    # 预组装 context（每次校验调用时不变的部分）
    base_context = {
        "style_blacklist": getattr(book, "style_blacklist", None) or [],
        "red_lines": beat.get("red_lines", []) or [],
        "taboos": getattr(book, "core_motifs_taboos", "") or "",
        "pacing_type": (beat.get("pacing_type") or "medium").lower(),
        "required_entities": [pov_character] if pov_character else [],
        # CharacterOOCValidator 已移除，entities 字段无用，但保留以防其他校验器扩展
        "entities": [],
    }

    async def validate(chunk: str) -> tuple[bool, str, List[str]]:
        result = await pipeline.validate_draft(chunk, base_context)
        if result.is_valid:
            return True, "", []
        fail_reason = "; ".join(result.errors) if result.errors else "未知校验失败"
        # 合并各校验器的 categories（去重）
        cats = list(dict.fromkeys(result.categories)) if result.categories else ["其他"]
        return False, fail_reason, cats

    return validate

