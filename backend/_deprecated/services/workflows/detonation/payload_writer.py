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
高潮点双候选写作器（V3.0 新建）。

职责（设计文档 §5 Phase 3 + D2 爆炸先写）：
在信息最完备的时刻写全章最重要的一段（~800 字）。
- creative 槽、双候选生成（Re3 选优思想）
- 选优标准 = 情感强度 × 克制度 × 专属性（先代码初筛禁词/句长，再 LLM 评委 1 次）

业务场景：
- 闸门 3：POST /api/chapters/{id}/payload/write

设计要点：
- 复用 2.0 的 fortress_candidate.generate_and_pick_dual_candidates（最大礼物）
- 构造 generate_once 闭包注入高潮点专属 prompt（含 payload 字段 + 直接铺垫节点 + 角色卡 + 文风卡 + 作者样本 + 上文末尾）
- fail-fast 校验复用 build_draft_validator
- Slice A 阶段：代码级初筛选优（penalty）；LLM 评委留待 Slice B 的有锚审计高潮爆发分环节

降级路径：
- 双候选并行生成失败 → fallback 单候选
- 两份都校验失败 → fallback fail-fast 重试
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from backend.services.llm import call_llm_with_usage
from backend.services.workflows.detonation.types import PayloadWriteResult
from backend.services.workflows.fortress_candidate import (
    generate_and_pick_dual_candidates,
    FORTRESS_CANDIDATE_A_TEMP,
    FORTRESS_CANDIDATE_B_TEMP,
)

logger = logging.getLogger(__name__)


# 高潮点写作参数（设计文档 §5 Phase 3 + §7.3）
PAYLOAD_TEMPERATURE_A = 0.8   # 标准 creative 温度
PAYLOAD_TEMPERATURE_B = 0.9   # 高创意温度（多样性）


async def write_payload_dual_candidates(
    payload: Dict[str, Any],
    direct_setup_nodes: List[Dict[str, Any]],
    chapter: Any,
    chapter_card: Any,
    entities: List[Any],
    style_card: Any = None,
    author_samples: Optional[List[str]] = None,
    preceding_tail: Optional[str] = None,
    target_length: int = 1000,
    recorder: Optional[Any] = None,
) -> PayloadWriteResult:
    """高潮点双候选写作（复用 fortress_candidate）。

    Args:
        payload: PayloadMoment dict（含 description/emotional_target/answers_question/opens_question）
        direct_setup_nodes: distance_to_payload ≤ 2 的直接铺垫节点
        chapter: Chapter ORM 对象
        chapter_card: ChapterCard ORM 对象
        entities: 本章关联角色列表
        style_card: 可选 StyleCard ORM 对象
        author_samples: 可选作者样本列表（few-shot）
        preceding_tail: 上文末尾（衔接用，如有）
        target_length: 目标长度（默认 1000 字）
        recorder: 可选 RunRecorder

    Returns:
        PayloadWriteResult
    """
    from backend.services.workflows.fail_fast import build_draft_validator

    # 构建高潮点写作 prompt（system 静态 + user 动态）
    system_prompt, base_user_prompt = _build_payload_prompt(
        payload=payload,
        direct_setup_nodes=direct_setup_nodes,
        chapter=chapter,
        chapter_card=chapter_card,
        entities=entities,
        style_card=style_card,
        author_samples=author_samples,
        preceding_tail=preceding_tail,
        target_length=target_length,
    )

    # 构造 generate_once 闭包（fortress_candidate 要求的签名：(temperature, hint) -> str）
    async def _generate_once(temperature: float, hint: str = "") -> str:
        # hint 用于 fail-fast 重试时的反馈，这里拼到 user 段末尾
        user_prompt = base_user_prompt
        if hint:
            user_prompt = user_prompt + f"\n\n## 上次写作的问题（请修正）\n{hint}"
        if recorder is not None:
            async with recorder.record_call(
                stage="detonation.payload_write",
                model_slot="creative",
            ) as ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="creative",
                    temperature=temperature,
                    max_tokens=max(2048, target_length * 3),  # 中文字符约 1.5x token
                )
                ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=temperature,
                max_tokens=max(2048, target_length * 3),
            )
        return (result.content or "").strip()

    # fail-fast 校验闭包（fortress_candidate 要求：(chunk) -> (is_valid, fail_reason, categories)）
    # build_draft_validator 签名：(beat: dict, book: Any, pov_character: str)
    # 高潮点不绑定具体 beat/pov，构造一个最小化的 beat dict + book 代理
    minimal_beat = {
        "red_lines": [],
        "pacing_type": "medium",
    }

    class _BookProxy:
        """最小化 book 代理，供 build_draft_validator 取 style_blacklist / core_motifs_taboos。"""
        def __init__(self, style_card_obj: Any):
            # 从 style_card 取 negative_list 作为 style_blacklist
            negative = getattr(style_card_obj, "negative_list", []) or [] if style_card_obj else []
            self.style_blacklist = negative
            self.core_motifs_taboos = ""

    book_proxy = _BookProxy(style_card)
    validator = build_draft_validator(
        beat=minimal_beat,
        book=book_proxy,
        pov_character="",  # 高潮点不强制 POV 角色出现
    )

    async def _validate(chunk: str) -> Tuple[bool, str, list]:
        try:
            is_valid, fail_reason, categories = await validator(chunk)
            return is_valid, fail_reason or "", categories or []
        except Exception as e:
            logger.warning(f"[PayloadWriter] validator 异常，放行: {e}")
            return True, "", []

    # 调用 fortress 双候选优选
    dual_result = await generate_and_pick_dual_candidates(
        generate_once=_generate_once,
        validate=_validate,
        beat_index=0,  # 高潮点视为"第 0 拍"
        fail_fast_max_attempts=2,
        initial_temperature=PAYLOAD_TEMPERATURE_A,
        stage_name="detonation.payload_write",
        recorder=recorder,
    )

    return PayloadWriteResult(
        candidates=_collect_candidates(dual_result),
        scores=dual_result.scores,
        winner_label=dual_result.winner_label,
        winner_text=dual_result.winner_text,
        degraded=dual_result.degraded,
        prompts={"system": system_prompt, "user": base_user_prompt},
    )


def _collect_candidates(dual_result: Any) -> List[str]:
    """从 DualCandidateResult 收集候选文本列表。

    generate_and_pick_dual_candidates 内部消费了候选原文，这里尽力还原：
    - winner_text 一定有
    - 另一份候选原文在 DualCandidateResult 里没有直接暴露（设计如此）
    所以 Slice A 阶段：candidates 至少含 winner_text；若需要双候选对照，
    调用方应单独跑两次 _generate_once 拿原文。

    折中：返回 [winner_text]，并在 scores 里保留评分对照。
    """
    if dual_result.winner_text:
        return [dual_result.winner_text]
    return []


def _build_payload_prompt(
    payload: Dict[str, Any],
    direct_setup_nodes: List[Dict[str, Any]],
    chapter: Any,
    chapter_card: Any,
    entities: List[Any],
    style_card: Any,
    author_samples: Optional[List[str]],
    preceding_tail: Optional[str],
    target_length: int,
) -> Tuple[str, str]:
    """构建高潮点写作 prompt（§5 Phase 3）。

    返回 (system_prompt, user_prompt)。
    """
    import json as _json

    # ---- system：文风契约 + 高潮点写作核心约束 ----
    style_contract = "（未提供文风卡；按通用文学小说风格写作）"
    if style_card is not None:
        positive = getattr(style_card, "positive_profile", {}) or {}
        negative = getattr(style_card, "negative_list", []) or []
        parts = []
        if positive:
            parts.append(f"正面画像：{_json.dumps(positive, ensure_ascii=False)[:300]}")
        if negative:
            neg_items = []
            for item in negative[:10]:
                if isinstance(item, dict):
                    word = item.get("word") or item.get("phrase") or ""
                    alt = item.get("alternative", "")
                    if word:
                        neg_items.append(f"「{word}」→「{alt}」" if alt else f"「{word}」")
            if neg_items:
                parts.append(f"禁用表达：{', '.join(neg_items)}")
        if parts:
            style_contract = "\n".join(parts)

    author_samples_block = ""
    if author_samples:
        sample_lines = []
        for i, s in enumerate(author_samples[:3], 1):
            sample_lines.append(f"【样本 {i}】\n{str(s)[:400]}")
        author_samples_block = "\n## 作者样本（对齐这种文风）\n" + "\n\n".join(sample_lines)

    system_prompt = f"""你是一位技艺精湛的小说家，正在写作一章小说中【最重要的一段】——爆发段。

这是全章情绪势能的爆发瞬间。它必须被写得最高规格：情感强度最大、克制最深、专属性最强。

## 文风契约（务必遵守）
{style_contract}{author_samples_block}

## 爆发段写作的核心约束

1. **情感强度 × 克制 × 专属**：这一段要让人心头一震，但不是靠堆形容词或情绪爆发——靠的是一个具体的、只属于这个人物、这个时刻的动作或细节。
2. **感动是读者自己干的活**：文本只布置条件。不要解释角色的情绪，不要写"他很难过"。写他做了什么、看见了什么、没说什么。
3. **专属性检验**：这段文字挪到另一本书、另一个场景里是否照样成立？若成立则失败。它必须只属于此刻。
4. **节奏即呼吸**：句长跟着情绪的生理状态走。压迫时短促窒息，释放时绵长。
5. **允许生产性的"错"**：突然的短句、不合逻辑的联想、悲伤场景里的笑话——这些是人味的栖息地，不要熨平。
6. **禁止段末升华、禁止总结、禁止解释**。把活留给读者。"""

    # ---- user：高潮点字段 + 直接铺垫 + 角色 + 衔接 ----
    payload_description = payload.get("description", "")
    payload_emotional_target = payload.get("emotional_target", "")
    payload_answers = payload.get("answers_question", "")
    payload_opens = payload.get("opens_question", "") or "（未指定）"

    # 直接铺垫节点（distance ≤ 2）
    setup_lines = []
    for n in (direct_setup_nodes or [])[:5]:
        nid = n.get("id", "")
        content = n.get("content", "")[:150]
        restraint = n.get("restraint_note") or "（无）"
        setup_lines.append(f"- [{nid}] {content}（其 restraint：{restraint}）")
    setup_block = "\n".join(setup_lines) if setup_lines else "（无显式铺垫节点；自由发挥）"

    # 角色（含动态状态）
    char_lines = []
    for ent in (entities or [])[:6]:
        char = getattr(ent, "character", None)
        if char is None:
            continue
        name = getattr(char, "name", "") or "未命名"
        dynamic = (getattr(char, "dynamic_state", "") or "").strip()[:150]
        if dynamic:
            char_lines.append(f"- {name}（当前状态）：{dynamic}")
        else:
            char_lines.append(f"- {name}")
    characters_block = "\n".join(char_lines) if char_lines else "（未指定）"

    preceding_block = (preceding_tail or "（本章是第一章或无前文衔接）")[:500]

    user_prompt = f"""## 你的任务：写本章的爆发段（约 {target_length} 字）

## 高潮点（本章情绪势能的爆发瞬间）
- 描述：{payload_description}
- 情绪目标：{payload_emotional_target}
- 回答的读者问题：{payload_answers}
- 打开的新问题：{payload_opens}

## 直接铺垫节点（读者此刻之前必须相信/感到/误会什么；爆发段要对这些做出回应）
{setup_block}

## 在场角色（含动态状态）
{characters_block}

## 上文末尾（衔接，保持呼吸连续）
{preceding_block}

## 写作要求
- 直接输出爆发段正文，不要任何前言/解释/标题。
- 约 {target_length} 字，边写边倒数，接近目标时自然收束。
- 这是全章最重要的一段，请拿出最高规格。"""

    return system_prompt, user_prompt
