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
去 AI 味洗涤器 —— LLM 编排层（唯一含 LLM I/O 的 NLG 模块）。

职责：
- 当 ai_taste_meter 判定段落 AI 味超阈值时，调 creative 槽单段重洗
- 洗涤 prompt 明确指示：删微操、去套路比喻、破匀速句式、保情节
- 洗后再跑一次密度评估验证；仍超标则记录 DEGRADED，用轻裁结果兜底

设计意图（"重wash兜底"防线）：
- 这是第二道防线，只在正则裁剪搞不定的复杂问题（匀速句式/后置修饰泛滥）时触发
- 单段重写而非全章重写：成本可控，延迟仅出现在超阈值段
- 复用 creative 槽（与正文同语感），低 temperature(0.5) 保证稳定
- 失败不阻塞：洗涤异常时退回 sanitized 原文，记 DEGRADED

成本控制：
- 单章洗涤段数上限 = DensityThresholds.wash_max_segments_per_chapter（默认3）
- 调用方（segment_writer）维护计数器，超限不再调用本模块

业务场景：
- segment_writer 段后处理：report.triggered 为真时调用
"""

import logging
from dataclasses import dataclass
from typing import Optional

from backend.services.llm import call_llm_with_usage
from backend.core.model_config import get_default_reasoning_config, has_dedicated_wash_profile
from backend.services.nlg.ai_taste_meter import DensityReport, measure_ai_taste
from backend.services.nlg.anti_ai_rules import DensityThresholds, DEFAULT_THRESHOLDS
from backend.services.nlg.text_sanitizer import sanitize_segment
from backend.services.observability.run_recorder import RunRecorder

logger = logging.getLogger(__name__)


@dataclass
class WashResult:
    """单段洗涤结果。

    Attributes:
        text: 最终文本（洗涤成功=洗后文；失败/未触发=裁剪后原文）
        washed: 是否实际触发了 LLM 洗涤
        original_score: 洗涤前综合分
        final_score: 洗涤后综合分（未洗则同 original_score）
        reason: 处置说明（人类可读，供日志/DEGRADED）
    """

    text: str
    washed: bool
    original_score: float
    final_score: float
    reason: str


# 洗涤模型槽位：独立的 "wash" 槽（llm.wash），未配置时回退 creative。
# 设计意图：正文由 creative 槽生成，AI 腔模板（"不是X是Y"/鼓点短段/三连排比）
# 是该模型采样分布的众数——让同一模型"去 AI 味"等于从同一分布再采样，
# 结构模板会再生。洗涤应与写作分模型；reasoning 槽承担着锚点设计/审计等
# 其他职责不能占用，故设独立 wash 槽（设置面板可配，可指向另一家 provider）。
_WASH_MODEL_TYPE = "wash"

# 洗涤温度：0.8（原 0.5）。
# 设计意图：低温度会贴近采样分布众数 = 更"AI 腔"，方向是反的；
# 编辑任务不需要高发散，0.8 在"推离高频句式"和"遵守情节零损失约束"之间折中。
_WASH_TEMPERATURE = 0.8

# 洗涤 system prompt（明确反 AI 腔指令 + 段落级修辞模板改法）
_WASH_SYSTEM = """你是顶级的中文小说文字编辑，专精"去 AI 腔"润色。

你收到一段 AI 生成的小说正文，它带有明显的机械感。你的任务：**在保留全部情节、人物、设定不变的前提下，重写这段文字，消除 AI 味**。

# 必须消除的 5 类 AI 腔

1. **病态微操**：无意义的微小动作（指尖颤动、瞳孔收缩、喉结滚动、睫毛轻颤、下巴微抬）。
   ——删掉，或替换为一个有信息量的具体动作。
2. **套路比喻**：伪深度填充词（冷冽、深邃、宛如、仿佛、不可名状、墨水滴进水里、沉睡的巨兽）。
   ——删掉套路意象。如需比喻，用一个具体、新鲜、贴合场景的意象。
3. **匀速句式**：长短句过于均匀，像节拍器。后置修饰语泛滥（"他看着远处，眼中带着一抹..."）。
   ——主动制造长短句交错。短句制造冲击，长句铺陈细节。删掉无信息量的后置修饰。
4. **解释性插嘴**："不是因为他想这样，而是因为...""仿佛在说..."
   ——删掉。让动作和细节自己说话。
5. **段落级修辞模板**（若"命中问题"中出现以下条目，必须对应处理）：
   - 单句段滥用：≤15字的独立短段过多（"警报响了。""迟了。"）。把它们合并进上下文，
     整段只保留极少数真正需要重锤的位置。
   - "不是X，是Y"否定反转句：删掉先否定再肯定的绕路，直接陈述事实。
   - 三连排比（"穿透A。穿透B。穿透C。""是X。是Y。是Z。"）：至多保留一处，其余拆散改写。
   - 喻体复用：同一意象在多个比喻中回收（巨兽/巨人/活物）。每个意象只用一次，
     其余换成贴合本场景的新鲜意象，或直接删掉比喻。

# 硬约束

- **情节零损失**：人物、事件、地点、对话内容、情绪走向必须 100% 保留。
- **字数浮动 ±15%**：不要大幅扩写或缩写。
- **不要加段标题、不要用 markdown、不要解释**。只输出润色后的正文本身。
- 不要新设情节、不要新加角色、不要改变对话的语义。"""

_WASH_USER_TEMPLATE = """# 待润色段落（AI 味超标，综合分 {score}/100）

命中问题：
{reasons}

# 原文

{text}

# 要求

重写这段，消除上述 AI 腔，保留全部情节。只输出润色后的正文。"""


async def wash_segment_if_too_ai(
    text: str,
    report: DensityReport,
    thresholds: DensityThresholds = DEFAULT_THRESHOLDS,
    max_tokens: int = 4096,
    recorder: Optional[RunRecorder] = None,
    stage: str = "adf.wash",
) -> WashResult:
    """对 AI 味超标的段落执行 LLM 洗涤。

    仅在 report.triggered 为真时实际调用 LLM；否则直接返回裁剪后原文。
    洗涤后再跑一次密度评估验证；若仍超标或 LLM 失败，退回 sanitized 原文。

    Args:
        text: 原始段落文本
        report: 该段落的密度报告（来自 measure_ai_taste）
        thresholds: 阈值（用于判断洗后是否仍超标）
        max_tokens: 洗涤 LLM max_tokens 上限
        recorder: RunRecorder（可选）。提供时洗涤 LLM 调用计入 generation_runs
            （stage 默认 adf.wash，model_slot=wash），供章级成本报告聚合
        stage: 计量 stage 名（segment_writer 传入 adf.wash.segment_N）

    Returns:
        WashResult：含最终文本、是否洗涤、前后分数、处置说明

    使用方式（segment_writer 段后处理）：
        report = measure_ai_taste(segment_text)
        if report.triggered and wash_count < thresholds.wash_max_segments_per_chapter:
            result = await wash_segment_if_too_ai(segment_text, report)
            segment_text = result.text
            wash_count += 1 if result.washed else 0
        else:
            segment_text = sanitize_segment(segment_text)
    """
    # 基线：裁剪后原文（无论是否洗涤，这都是兜底）
    sanitized = sanitize_segment(text)
    original_score = report.overall_score

    if not report.triggered:
        return WashResult(
            text=sanitized,
            washed=False,
            original_score=original_score,
            final_score=original_score,
            reason="未超阈值，仅正则轻裁",
        )

    reasons = "\n".join(f"- {r}" for r in report.flagged_reasons) or "综合分超标"
    user_prompt = _WASH_USER_TEMPLATE.format(
        score=original_score,
        reasons=reasons,
        text=text,
    )

    try:
        # thinking 配置：独立 wash 槽尊重其 enabled/effort（默认关）；
        # 回退 creative 时显式传 {} 关闭 thinking——编辑任务不需要深度思考，
        # 避免继承 creative 的 effort=max 拖慢每次洗涤。
        wash_reasoning_config = (
            get_default_reasoning_config("wash") if has_dedicated_wash_profile() else {}
        )
        if recorder is not None:
            async with recorder.record_call(stage=stage, model_slot="wash") as call_ctx:
                llm_result = await call_llm_with_usage(
                    system_prompt=_WASH_SYSTEM,
                    user_prompt=user_prompt,
                    model_type=_WASH_MODEL_TYPE,
                    temperature=_WASH_TEMPERATURE,
                    max_tokens=max_tokens,
                    reasoning_config=wash_reasoning_config,
                )
                call_ctx.set_result(llm_result)
        else:
            llm_result = await call_llm_with_usage(
                system_prompt=_WASH_SYSTEM,
                user_prompt=user_prompt,
                model_type=_WASH_MODEL_TYPE,
                temperature=_WASH_TEMPERATURE,
                max_tokens=max_tokens,
                reasoning_config=wash_reasoning_config,
            )
        washed_text = (llm_result.content or "").strip()
    except Exception as e:
        logger.warning(f"[DeAI] 洗涤 LLM 调用失败，退回正则裁剪: {e}")
        return WashResult(
            text=sanitized,
            washed=False,
            original_score=original_score,
            final_score=original_score,
            reason=f"洗涤失败({type(e).__name__})，退回正则裁剪",
        )

    if not washed_text:
        logger.warning("[DeAI] 洗涤返回空文本，退回正则裁剪")
        return WashResult(
            text=sanitized,
            washed=False,
            original_score=original_score,
            final_score=original_score,
            reason="洗涤返回空，退回正则裁剪",
        )

    # 验证洗后文本的密度
    post_report = measure_ai_taste(washed_text, thresholds=thresholds)
    if post_report.triggered:
        # 洗后仍超标：取分数较低者（洗后通常更低，但也可能 LLM 越洗越糟）
        if post_report.overall_score < original_score:
            logger.info(
                f"[DeAI] 洗后仍超标但改善：{original_score}→{post_report.overall_score}，"
                f"采用洗后文 + 正则轻裁"
            )
            return WashResult(
                text=sanitize_segment(washed_text),
                washed=True,
                original_score=original_score,
                final_score=post_report.overall_score,
                reason=f"洗后仍超标({post_report.overall_score})但已改善",
            )
        else:
            logger.warning(
                f"[DeAI] 洗后更糟：{original_score}→{post_report.overall_score}，退回原文裁剪"
            )
            return WashResult(
                text=sanitized,
                washed=False,
                original_score=original_score,
                final_score=post_report.overall_score,
                reason=f"洗后更糟({post_report.overall_score})，退回原文裁剪",
            )

    logger.info(f"[DeAI] 洗涤成功：{original_score}→{post_report.overall_score}")
    return WashResult(
        text=washed_text,
        washed=True,
        original_score=original_score,
        final_score=post_report.overall_score,
        reason=f"洗涤成功 {original_score}→{post_report.overall_score}",
    )
