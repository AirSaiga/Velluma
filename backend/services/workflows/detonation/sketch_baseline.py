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
自由速写对照器（V3.1 §5 新建）。

职责（规格 §5 自由速写对照——双轨速写的重生）：
写蓄势段（或长铺陈段）之前/之后，对同一区域生成一份【无约束自由速写】（creative，
不带距离标注、不带压抑约束，顺情节自然流），然后与正式稿对照，产出诊断信息。

诊断矩阵（规格 §5 表）：
| 对照发现                           | 诊断                | 处置                       |
|-----------------------------------|---------------------|---------------------------|
| 速写在某处自然达到情绪高点，        | 疑似泄底            | 泄底检查复核，确认则压低调子 |
| 正式稿同处也出现高点                |                     |                           |
| 速写明显比正式稿抓人（读者盲评）    | 压抑过度 = 无聊      | 注入小波折，局部升温        |
| 两者轮廓一致（低点对低点）          | 压抑执行正确         | 通过                       |

本质：速写给出"自然情绪轮廓"，铺垫结构给出"设计情绪轮廓"，
两者的差值就是诊断信息。

业务场景：
- UnifiedWorkflow 在 Phase 4（蓄势段写作）后调用，仅对 buildup 区启用
- 转折章以下档位默认关闭（成本：每蓄势段 +1 次 creative 调用）

设计要点：
- 复用 SketchGenerator 的 LLM 调用基础设施，但 prompt 完全去约束化
- 对照结论仅作"建议"，二次复核才动手（规格 §12 风险对策）
- 失败不静默：解析失败标 unaudited
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.services.llm import call_llm_with_usage

logger = logging.getLogger(__name__)


# 速写对照参数（规格 §5）
SKETCH_BASELINE_TEMPERATURE = 0.9   # 高创意，让自然情绪轮廓充分涌现
SKETCH_BASELINE_MAX_TOKENS = 3072
COMPARE_TEMPERATURE = 0.1          # 对照诊断用低温度，求稳
COMPARE_MAX_TOKENS = 2048

# 速写长度比例（规格 §5：速写长度为该段 40%）
SKETCH_LENGTH_RATIO = 0.40

# 诊断结论常量
DIAGNOSIS_CONSISTENT = "consistent"               # 轮廓一致，压抑执行正确
DIAGNOSIS_PREMATURE_SUSPICION = "premature_suspicion"  # 疑似泄底
DIAGNOSIS_OVER_SUPPRESSED = "over_suppressed"     # 压抑过度=无聊

# 处置动作常量
ACTION_NONE = "none"                # 通过
ACTION_TONE_DOWN = "tone_down"      # 压低调子
ACTION_MICRO_TWIST = "micro_twist"  # 注入小波折


async def run_sketch_baseline(
    zone: str,
    zone_text: str,
    payload_anchor: str,
    node_summaries: List[Dict[str, Any]],
    style_card: Any = None,
    author_samples: Optional[List[str]] = None,
    recorder: Optional[Any] = None,
) -> Dict[str, Any]:
    """对 buildup 或 development 区跑自由速写对照（规格 §5）。

    业务流程：
    1. 生成无约束自由速写（creative，长度为该区 40%）
    2. LLM 对照诊断（速写 vs 正式稿）
    3. 输出诊断结论 + 处置建议

    Args:
        zone: 对照的区（buildup 或 development）
        zone_text: 该区的正式稿文本
        payload_anchor: 高潮段成文（速写对齐用）
        node_summaries: 该区节点摘要列表（含 content/restraint_note）
        style_card: 可选 StyleCard ORM（文风契约）
        author_samples: 可选作者样本
        recorder: 可选 RunRecorder

    Returns:
        dict: SketchBaselineResult 字典
            {
                "zone": str,
                "sketch_text": str,
                "diagnosis": "consistent" | "premature_suspicion" | "over_suppressed",
                "diagnosis_reason": str,
                "action_taken": "none" | "tone_down" | "micro_twist",
                "degraded": Optional[dict],
            }
    """
    if not zone_text or len(zone_text) < 100:
        return {
            "zone": zone,
            "sketch_text": "",
            "diagnosis": DIAGNOSIS_CONSISTENT,
            "diagnosis_reason": "该区文本过短，跳过速写对照",
            "action_taken": ACTION_NONE,
            "degraded": None,
        }

    # ---- 1. 生成无约束自由速写 ----
    sketch_target_words = max(200, int(len(zone_text.replace(" ", "")) * SKETCH_LENGTH_RATIO))
    sketch_text, sketch_degraded = await _generate_free_sketch(
        zone=zone,
        payload_anchor=payload_anchor,
        node_summaries=node_summaries,
        target_words=sketch_target_words,
        style_card=style_card,
        author_samples=author_samples,
        recorder=recorder,
    )

    if sketch_degraded or not sketch_text:
        logger.warning(f"[SketchBaseline] 速写生成失败 zone={zone}: {sketch_degraded}")
        return {
            "zone": zone,
            "sketch_text": sketch_text or "",
            "diagnosis": DIAGNOSIS_CONSISTENT,
            "diagnosis_reason": "速写生成失败，跳过对照",
            "action_taken": ACTION_NONE,
            "degraded": sketch_degraded or {"reason": "empty_sketch", "action": "skip_compare"},
        }

    # ---- 2. LLM 对照诊断 ----
    diagnosis, diagnosis_reason, compare_degraded = await _compare_sketch_with_draft(
        sketch_text=sketch_text,
        draft_text=zone_text,
        zone=zone,
        node_summaries=node_summaries,
        recorder=recorder,
    )

    if compare_degraded:
        logger.warning(f"[SketchBaseline] 对照诊断失败 zone={zone}: {compare_degraded}")
        return {
            "zone": zone,
            "sketch_text": sketch_text,
            "diagnosis": DIAGNOSIS_CONSISTENT,
            "diagnosis_reason": "对照诊断失败，默认通过",
            "action_taken": ACTION_NONE,
            "degraded": compare_degraded,
        }

    # ---- 3. 推导处置动作（规格 §5 表）----
    action_taken = _derive_action(diagnosis)

    logger.info(
        f"[SketchBaseline] zone={zone} 诊断={diagnosis} 动作={action_taken} "
        f"reason={diagnosis_reason[:80]}"
    )

    return {
        "zone": zone,
        "sketch_text": sketch_text,
        "diagnosis": diagnosis,
        "diagnosis_reason": diagnosis_reason,
        "action_taken": action_taken,
        "degraded": None,
    }


async def _generate_free_sketch(
    zone: str,
    payload_anchor: str,
    node_summaries: List[Dict[str, Any]],
    target_words: int,
    style_card: Any,
    author_samples: Optional[List[str]],
    recorder: Optional[Any],
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """生成无约束自由速写（creative，去所有压抑约束）。

    与 fuse_writer/development_writer 的关键区别：
    - 不注入任何节点任务书（distance/assignment/question/restraint 全部去掉）
    - 只给高潮方向 + 角色动机纲要，让 LLM 顺情节"自然流"
    - 输出 = 自然情绪轮廓（参照系）
    """
    # 节点纲要（只取 content 作为情节提示，不带任何约束）
    outline_lines = []
    for n in (node_summaries or [])[:6]:
        content = (n.get("content") or "")[:100]
        if content:
            outline_lines.append(f"- {content}")
    outline_block = "\n".join(outline_lines) if outline_lines else "（无显式纲要）"

    # 文风契约（保留文风锚定，但不加任何情绪约束）
    style_contract = ""
    if style_card is not None:
        positive = getattr(style_card, "positive_profile", {}) or {}
        if positive:
            style_contract = f"\n## 文风画像（参考）\n{json.dumps(positive, ensure_ascii=False)[:200]}"

    author_block = ""
    if author_samples:
        author_block = "\n## 作者样本（文风锚定）\n" + str(author_samples[0])[:300]

    system_prompt = f"""你是一位技艺精湛的小说家，正在【自由速写】一章小说中靠近高潮的段落。

这是一份"自然情绪轮廓"探针——你的任务是顺情节自然流地写一段，不要任何压抑/克制约束：
- 不要刻意压着情绪
- 不要刻意制造悬念
- 顺人物此刻最自然的反应写
- 情绪到哪里就写到那里

输出将作为"参照系"，与正式稿对照，诊断正式稿是否压抑过度或提前泄底。{style_contract}{author_block}

## 写作要求
- 中文写作，顺情节自然流，不施加任何情绪约束
- 不要任何前言/解释/标题，直接输出正文
- 约 {target_words} 字（自然收束，不硬凑）"""

    user_prompt = f"""【本章高潮方向】（仅供你了解走向，不要复述）：
{payload_anchor[:500]}

【本段情节纲要】（顺这些情节自然推进）：
{outline_block}

请自由速写这段（不要压抑、不要克制，情绪自然流露）："""

    try:
        if recorder is not None:
            async with recorder.record_call(
                stage=f"detonation.sketch_baseline.{zone}.generate",
                model_slot="creative",
            ) as ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="creative",
                    temperature=SKETCH_BASELINE_TEMPERATURE,
                    max_tokens=SKETCH_BASELINE_MAX_TOKENS,
                )
                ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=SKETCH_BASELINE_TEMPERATURE,
                max_tokens=SKETCH_BASELINE_MAX_TOKENS,
            )
    except Exception as e:
        logger.warning(f"[SketchBaseline] 速写 LLM 调用异常 zone={zone}: {e}")
        return "", {
            "reason": "sketch_llm_exception",
            "action": "skip_compare",
            "detail": f"{type(e).__name__}: {str(e)[:200]}",
        }

    sketch = (result.content or "").strip()
    if not sketch:
        return "", {"reason": "empty_sketch_output", "action": "skip_compare"}

    return sketch, None


async def _compare_sketch_with_draft(
    sketch_text: str,
    draft_text: str,
    zone: str,
    node_summaries: List[Dict[str, Any]],
    recorder: Optional[Any],
) -> Tuple[str, str, Optional[Dict[str, Any]]]:
    """LLM 对照诊断（速写 vs 正式稿）。

    输出契约（规格 §5 表）：
    {
        "diagnosis": "consistent" | "premature_suspicion" | "over_suppressed",
        "reason": "一句话理由",
        "sketch_peak_quote": "速写中的情绪高点引用（若有）",
        "draft_same_position_quote": "正式稿同处引用（若有）"
    }
    """
    # restraint_note 清单（用于判断正式稿是否在应克制处泄底）
    restraint_lines = []
    for n in (node_summaries or [])[:6]:
        r = n.get("restraint_note")
        if r:
            restraint_lines.append(f"- {r[:80]}")
    restraint_block = "\n".join(restraint_lines) if restraint_lines else "（无显式克制要求）"

    system_prompt = """你是结构诊断员。给你两段文本：
- 【自由速写】：无约束自然流的情绪轮廓（参照系）
- 【正式稿】：经过压抑/克制设计的目标稿

你的任务是对照诊断（只给结论与证据，不做文学评价）：

诊断矩阵：
1. **疑似泄底**（premature_suspicion）：速写在某处自然达到情绪高点，正式稿同处也出现了情绪高点或真相泄露——说明正式稿没压住。
2. **压抑过度**（over_suppressed）：速写明显比正式稿抓人、有情绪起伏，正式稿过于平淡——压抑压成了无聊。
3. **轮廓一致**（consistent）：两者低点对低点、高点对高点（若正式稿在应克制处确实克制），压抑执行正确。

## 输出格式
先用 1-2 段自由分析（哪里对照、差值在哪里），然后用如下 JSON：
```json
{
    "diagnosis": "consistent | premature_suspicion | over_suppressed",
    "reason": "一句话理由",
    "sketch_peak_quote": "速写中的情绪高点引用（若适用）",
    "draft_same_position_quote": "正式稿同处引用（若适用）"
}
```
JSON 必须放在 ```json ``` 围栏内。"""

    user_prompt = f"""## 本区节点应克制的内容（restraint 清单）
{restraint_block}

## 【自由速写】（参照系，自然情绪轮廓）
{sketch_text[:2000]}

## 【正式稿】（目标稿，经过压抑设计）
{draft_text[:3000]}

## 要求
对照诊断，输出 JSON。"""

    try:
        if recorder is not None:
            async with recorder.record_call(
                stage=f"detonation.sketch_baseline.{zone}.compare",
                model_slot="reasoning",
            ) as ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="reasoning",
                    temperature=COMPARE_TEMPERATURE,
                    max_tokens=COMPARE_MAX_TOKENS,
                )
                ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="reasoning",
                temperature=COMPARE_TEMPERATURE,
                max_tokens=COMPARE_MAX_TOKENS,
            )
    except Exception as e:
        return DIAGNOSIS_CONSISTENT, "对照 LLM 异常，默认通过", {
            "reason": "compare_llm_exception",
            "action": "default_pass",
            "detail": f"{type(e).__name__}: {str(e)[:200]}",
        }

    # 解析 JSON
    raw = result.content or ""
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL)
    raw_json = json_match.group(1) if json_match else None
    if not raw_json:
        # fallback：找最外层 {...}
        brace_match = re.search(r"\{[^{}]*\"diagnosis\"[^{}]*\}", raw, re.DOTALL)
        if brace_match:
            raw_json = brace_match.group(0)
    if not raw_json:
        return DIAGNOSIS_CONSISTENT, "对照响应无 JSON，默认通过", {
            "reason": "no_json_fence",
            "action": "default_pass",
        }

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        return DIAGNOSIS_CONSISTENT, "对照 JSON 解析失败，默认通过", {
            "reason": "json_decode_failed",
            "action": "default_pass",
            "detail": str(e)[:120],
        }

    diagnosis = str(data.get("diagnosis", DIAGNOSIS_CONSISTENT)).strip()
    if diagnosis not in (DIAGNOSIS_CONSISTENT, DIAGNOSIS_PREMATURE_SUSPICION, DIAGNOSIS_OVER_SUPPRESSED):
        diagnosis = DIAGNOSIS_CONSISTENT
    reason = str(data.get("reason", "")).strip() or "（未给出理由）"

    return diagnosis, reason, None


def _derive_action(diagnosis: str) -> str:
    """根据诊断结论推导处置动作（规格 §5 表）。"""
    if diagnosis == DIAGNOSIS_PREMATURE_SUSPICION:
        return ACTION_TONE_DOWN
    if diagnosis == DIAGNOSIS_OVER_SUPPRESSED:
        return ACTION_MICRO_TWIST
    return ACTION_NONE
