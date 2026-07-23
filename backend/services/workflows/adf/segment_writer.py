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
Phase 4: 正向流写作器（Forward Flow Writer，V3.2 §4.4，核心创新 #2）。

职责：
- 串行逐段写作，每段三方约束 + 运行时条件扫描
- 每段后扫描未落地 Precondition，软提示 LLM 在下段自然融入

设计意图（ADF 灵魂）：
- rolling_prefix 500 字保证呼吸连续（继承双轨优点）
- 情绪曲线进度条代替整数 distance_to_climax（连续约束）
- 远端锚作为牵引而非路径（高潮描述每段注入但不强制路径）
- 软提示而非硬指令（让前文涌现决定埋设位置）
- 关键词检测验证 Precondition 落地

业务场景：
- workflows/adf/adf_workflow.py Phase 4 调用

使用方式：
    segments, anchor = await write_chapter_segments(
        anchor=anchor, spine=spine, chapter=chapter, chapter_card=cc,
        entities=entities, style_card=sc, author_samples=...,
        tier="climax", target_word_count=5000, max_segments=6,
        recorder=recorder, progress_callback=cb,
    )
"""

import asyncio
import logging
from typing import Any, Callable, List, Optional, Tuple

from backend.services.llm import call_llm_with_usage
from backend.services.observability.run_recorder import RunRecorder
from backend.services.prompts.adf_prompts import (
    build_forward_flow_prompt,
    build_anti_ai_perturbation,
    format_climax_anchor,
    format_emotion_curve,
)
from backend.services.nlg import (
    measure_ai_taste,
    preprocess_segment,
    sanitize_segment,
    sanitize_rolling_prefix,
    wash_segment_if_too_ai,
)
from backend.services.nlg.anti_ai_rules import DEFAULT_THRESHOLDS
from backend.services.workflows.adf.story_context_builder import (
    format_entry_state_for_prompt,
)
from backend.services.workflows.adf.types import (
    ChapterClimax,
    StoryContext,
    SegmentResult,
    Precondition,
)
from backend.services.workflows.adf.storyboard import (
    plan_storyboard,
    get_shot_constraint,
    get_transition_hint,
)
from backend.services.workflows.adf.setting_resolver import build_scene_setting_text

logger = logging.getLogger(__name__)


# ============================================================
# 常量
# ============================================================

ROLLING_PREFIX_TAIL = 500  # 每段输入含前段末尾 500 字
TARGET_WORDS_FALLBACK_PER_SEG = 700  # 单段目标字数兜底

# 单段正文 LLM 调用超时（秒）。
# creative 槽位用重模型（如 deepseek-v4-pro）时，单段 700 字合理耗时 1-4 分钟；
# 超过本阈值视为挂起，跳过该段（降级空段 + DEGRADED），保证整章能跑完而非死等。
# 详见 adf.py 的实时 SSE 设计：超时会通过 progress_callback 上浮为 DEGRADED 事件。
SEGMENT_TIMEOUT = 180


# ============================================================
# 条件扫描（condition_scanner，集成在写作器内）
# ============================================================

def scan_unlanded_preconditions(
    anchor: ChapterClimax,
    current_segment_index: int,
    total_segments: int,
    current_word_count: int,
    estimated_total_words: int,
) -> List[Precondition]:
    """扫描未落地的 Precondition，找出"建议在下段埋设"的条件。

    优先级：
    1. min_landing_offset 即将违反的（高潮前的字数剩余不多了）
    2. 尚未落地的、距高潮中等距离的

    Args:
        anchor: 远端锚（运行时会更新 preconditions[*].landed）
        current_segment_index: 即将写的段序号（0-based）
        total_segments: 总段数
        current_word_count: 已写的字数
        estimated_total_words: 预估总字数

    Returns:
        建议下段埋设的 Precondition 列表
    """
    unlanded = [pc for pc in anchor.preconditions if not pc.landed]
    if not unlanded:
        return []

    # 剩余字数 = 预估总字数 - 已写字数
    remaining_words = max(0, estimated_total_words - current_word_count)
    # 高潮大概在最后一段，距高潮的字数 ≈ remaining_words - (一段字数)
    words_to_climax = max(0, remaining_words - TARGET_WORDS_FALLBACK_PER_SEG)

    # 第一优先：min_landing_offset 即将违反
    urgent = []
    normal = []
    for pc in unlanded:
        # 如果距离高潮的字数 < 该条件的 min_landing_offset，说明快来不及了
        if words_to_climax < pc.min_landing_offset:
            urgent.append(pc)
        else:
            normal.append(pc)

    # 取前 2 个紧急的 + 1 个普通的（避免一段塞太多）
    result = urgent[:2]
    if len(result) < 2 and normal:
        result.append(normal[0])
    return result


def build_soft_hints(
    suggested_pcs: List[Precondition],
) -> str:
    """把建议埋设的 Precondition 转为软提示文本。"""
    if not suggested_pcs:
        return "（无特别建议，让前文自然涌出）"
    lines = []
    for pc in suggested_pcs:
        terms_text = "、".join(pc.must_use_terms) if pc.must_use_terms else "（无强制关键词）"
        lines.append(
            f"- 建议自然融入 [{pc.id}]：{pc.description}（可自然带出的关键词：{terms_text}）"
        )
    header = "下段建议埋设以下前置条件（**软提示，不强制**，请让场景自然涌现，不要为埋设而切换场景）："
    return header + "\n" + "\n".join(lines)


def update_precondition_landed_state(
    anchor: ChapterClimax,
    segment_text: str,
    segment_index: int,
) -> List[str]:
    """检测本段是否让某些 Precondition 落地（关键词检测），返回本段落地的 PC id 列表。"""
    landed_ids: List[str] = []
    for pc in anchor.preconditions:
        if pc.landed:
            continue
        # 关键词检测：must_use_terms 任一出现即认为落地
        if pc.must_use_terms:
            for term in pc.must_use_terms:
                if term and term in segment_text:
                    pc.landed = True
                    pc.landed_segment = segment_index
                    # 取关键词前后 40 字作为证据
                    idx = segment_text.find(term)
                    start = max(0, idx - 40)
                    end = min(len(segment_text), idx + len(term) + 40)
                    pc.landed_evidence = segment_text[start:end]
                    landed_ids.append(pc.id)
                    break
    return landed_ids


# ============================================================
# 辅助：构造 system 层固定文本（吃 prompt 缓存）
# ============================================================

def _build_style_contract(style_card: Any) -> str:
    """从 StyleCard 抽取文风契约文本。

    修正历史：此前误读 positive_traits/negative_traits（不存在），
    导致 StyleCard 从未注入正文生成。现对齐 ORM 字段
    positive_profile(dict)/negative_list(list)/dialogue_ratio_target/paragraph_rhythm，
    渲染逻辑参照 context/engine.py:_render_style_card_block。
    """
    if style_card is None:
        return "（未指定，按通用中文文学小说风格）"
    parts = []

    # 正面画像：dict（句长节奏/词汇层级/语域/开头结尾习惯）
    positive = getattr(style_card, "positive_profile", None)
    if positive:
        if isinstance(positive, dict):
            lines = []
            for key, value in positive.items():
                if not value:
                    continue
                lines.append(f"- {key}：{str(value)[:150]}")
            if lines:
                parts.append("正向特征：\n" + "\n".join(lines[:10]))
        else:
            # 兜底：非 dict（旧数据可能是 list/str）原样取
            parts.append(f"正向特征：{str(positive)[:300]}")

    # 负面清单：list of {word/phrase, alternative}
    negative = getattr(style_card, "negative_list", None)
    if negative:
        if isinstance(negative, list):
            lines = []
            for item in negative[:15]:
                if isinstance(item, dict):
                    word = item.get("word") or item.get("phrase") or ""
                    alt = item.get("alternative") or ""
                    if word:
                        line = f"- {word}"
                        if alt:
                            line += f"（→ {alt[:80]}）"
                        lines.append(line)
                elif isinstance(item, str) and item:
                    lines.append(f"- {item}")
            if lines:
                parts.append("避免特征：\n" + "\n".join(lines))
        else:
            parts.append(f"避免特征：{str(negative)[:300]}")

    # 量化指标：对话占比目标 + 段落节奏
    metric_lines = []
    dialogue_target = getattr(style_card, "dialogue_ratio_target", None)
    if dialogue_target is not None:
        try:
            metric_lines.append(f"对话占比目标 {float(dialogue_target)*100:.0f}%")
        except (TypeError, ValueError):
            pass
    paragraph_rhythm = getattr(style_card, "paragraph_rhythm", None)
    if paragraph_rhythm:
        metric_lines.append(f"段落节奏：{str(paragraph_rhythm)[:80]}")
    if metric_lines:
        parts.append("；".join(metric_lines))

    return "\n".join(parts) if parts else "（未指定，按通用中文文学小说风格）"


def _build_author_samples(author_samples: Any) -> str:
    """构造作者样本文本（最多 3 条，每条 400 字）。"""
    if not author_samples:
        return "（无样本）"
    if isinstance(author_samples, str):
        return author_samples[:1200]
    parts = []
    for i, sample in enumerate(author_samples[:3]):
        text = getattr(sample, "text", None) or (sample.get("text") if isinstance(sample, dict) else None) or str(sample)
        parts.append(f"【样本 {i + 1}】\n{str(text)[:400]}")
    return "\n\n".join(parts)


def _build_characters_text(entities: Any) -> str:
    """构造本章角色文本（system 层固定）。

    V3.5 修复：加入 static_prompt（永恒设定），之前只有 dynamic_state（瞬时状态），
    导致正文写作时角色"他是谁"的底层设定丢失，容易写出 OOC。
    """
    lines = []
    for ent in (entities or [])[:8]:
        char = getattr(ent, "character", None) if not isinstance(ent, dict) else ent.get("character")
        if char is None:
            continue
        name = getattr(char, "name", None) or (char.get("name") if isinstance(char, dict) else None) or "未命名"
        static = getattr(char, "static_prompt", None) or (char.get("static_prompt") if isinstance(char, dict) else None)
        dynamic = getattr(char, "dynamic_state", None) or (char.get("dynamic_state") if isinstance(char, dict) else None)
        parts = []
        if static:
            parts.append(str(static)[:200])
        if dynamic:
            parts.append(f"此刻：{str(dynamic)[:150]}")
        if parts:
            lines.append(f"- {name}：{'｜'.join(parts)}")
        else:
            lines.append(f"- {name}")
    return "\n".join(lines) if lines else "（未指定）"


def _build_character_arc_text(spine: StoryContext) -> str:
    """构造角色弧推进文本。"""
    if not spine.character_arc_advances:
        return "（未指定）"
    return "；".join(f"{k}→{v}" for k, v in spine.character_arc_advances.items())


def _build_compact_canon_hint(canon_context: str) -> str:
    """为后续段构建精简 Canon 提示（节省 token）。

    只保留 private 部分的"标签+不许说出"提示，不重复完整 canon_text。
    """
    if not canon_context or "（Canon 为空" in canon_context:
        return ""
    import re
    # 提取 private 区块里的节点标签（- XXX：...）
    private_section = ""
    if "[private]" in canon_context:
        start = canon_context.find("[private]")
        end = canon_context.find("\n## ", start)
        if end < 0:
            end = len(canon_context)
        private_section = canon_context[start:end]
    if not private_section:
        return ""
    # 提取节点 label（每行开头的 "- XXX："）
    labels = re.findall(r"^-\s+([^：：]+)[：:]", private_section, re.MULTILINE)
    if not labels:
        return ""
    return (
        f"[private 提醒] 以下节点是作者脑中真相，本段写作绝不许直接说出：\n"
        + "\n".join(f"- {lbl.strip()}" for lbl in labels[:8])
    )


# ============================================================
# 主入口：正向流写作
# ============================================================

async def write_chapter_segments(
    anchor: ChapterClimax,
    spine: StoryContext,
    chapter: Any,
    chapter_card: Any,
    entities: Any,
    style_card: Any,
    author_samples: Any,
    tier: str,
    target_word_count: int,
    max_segments: int,
    recorder: Optional[RunRecorder] = None,
    progress_callback: Optional[Callable[[str, dict], Any]] = None,
    canon_context: str = "",
    author_intent: str = "",
    # V3.5 新增：设定感知层数据
    locations: Any = None,
    assets: Any = None,
    relationships: Any = None,
    worldview_text: str = "",
    # 题材（用于本地预处理层白名单等，None=通用）
    genre: Optional[str] = None,
) -> Tuple[List[SegmentResult], ChapterClimax]:
    """Phase 4: 正向流写作（N 次 creative LLM，串行）。

    Args:
        anchor: 远端锚（Phase 2 产出，运行时会更新 preconditions[*].landed）
        spine: 脉络轨（Phase 1 产出）
        chapter: Chapter ORM
        chapter_card: ChapterCard ORM
        entities: 本章角色列表
        style_card: StyleCard ORM
        author_samples: 作者样本列表
        tier: 章节定档
        target_word_count: 目标字数
        max_segments: 段数上限
        recorder: RunRecorder
        progress_callback: 进度回调（推 ADF_PROGRESS / ADF_PRECONDITION_LANDED 事件）
        canon_context: V4.0 作者脑中世界图谱（private 节点绝不许泄露到正文）
        author_intent: V4.2 介入点 1 作者意图（强约束）

    Returns:
        tuple: (segments, anchor)  anchor 是更新了 landed 状态的引用（同一对象）
    """
    # ---- 段数规划 ----
    total_segments = max(3, min(max_segments, target_word_count // 600))
    target_words_per_seg = max(400, target_word_count // total_segments)

    # ---- V4.3 镜头景别分镜（纯算法）----
    # 多 POV 判断：本章涉及角色 >= 2 且情绪曲线有高能量段（高潮常需多视角反打）
    character_count = len(spine.character_arc_advances) if spine.character_arc_advances else 0
    has_multiple_pov = character_count >= 2 and any(
        s.energy >= 8 for s in anchor.emotion_curve.samples
    )
    storyboard = plan_storyboard(
        total_segments=total_segments,
        emotion_curve=anchor.emotion_curve,
        has_multiple_pov=has_multiple_pov,
    )

    # ---- system 层固定文本（每段复用，吃缓存）----
    climax_anchor_text = format_climax_anchor({
        "description": anchor.climax.description,
        "emotional_target": anchor.climax.emotional_target,
        "payoff_question": anchor.climax.payoff_question,
        "open_question": anchor.climax.open_question,
        "intensity": anchor.climax.intensity,
    })
    emotion_curve_text = format_emotion_curve([
        {"progress": s.progress, "register": s.register, "energy": s.energy}
        for s in anchor.emotion_curve.samples
    ])
    style_contract = _build_style_contract(style_card)
    author_samples_text = _build_author_samples(author_samples)

    purpose = ""
    if chapter_card is not None:
        purpose = (getattr(chapter_card, "purpose", "") or "").strip()
    if not purpose:
        outline = getattr(chapter, "outline_text", "") or ""
        purpose = outline[:300] if outline else "（未指定）"

    characters_text = _build_characters_text(entities)
    character_arc_text = _build_character_arc_text(spine)
    entry_state_text = format_entry_state_for_prompt(spine)

    # V3.5：场景设定文本（用户章级指定的角色/地点/资产/关系，全章复用）
    scene_setting_text = build_scene_setting_text(entities, locations, assets, relationships)

    # ---- 逐段写作 ----
    segments: List[SegmentResult] = []
    rolling_prefix = spine.entry_state.last_scene_image or "（本章开篇）"
    current_word_count = 0
    wash_count = 0  # 本章已洗涤段数（成本控制：超 wash_max_segments_per_chapter 不再洗）

    for i in range(total_segments):
        # 字数提前终止：已写字数超过目标 130% 时跳过剩余段（防上下文爆掉）
        # 留 30% 容差是因为最后一段通常是高潮段，不该因为前面略长就丢弃高潮
        if current_word_count > target_word_count * 1.3 and i > 0:
            logger.info(
                f"[ADF] 字数提前终止：已写 {current_word_count} 字 > 目标 {target_word_count}×1.3，"
                f"跳过第 {i + 1}-{total_segments} 段"
            )
            break

        progress = (i + 1) / total_segments

        # 动态调整本段目标字数：根据剩余字数和剩余段数均摊
        remaining_segments = total_segments - i
        remaining_words = max(200, target_word_count - current_word_count)
        dynamic_target_words = max(300, remaining_words // remaining_segments)

        # 情绪曲线采样
        cur_sample = anchor.emotion_curve.sample_at(progress - (0.5 / total_segments) if i > 0 else 0.0)
        next_sample = anchor.emotion_curve.next_sample_after(progress) or cur_sample

        # 条件扫描：建议下段埋设什么
        suggested_pcs = scan_unlanded_preconditions(
            anchor=anchor,
            current_segment_index=i,
            total_segments=total_segments,
            current_word_count=current_word_count,
            estimated_total_words=target_word_count,
        )
        soft_hints = build_soft_hints(suggested_pcs)

        # V4.3 镜头景别约束（注入 soft_hints）
        if i < len(storyboard):
            shot_type, transition = storyboard[i]
            shot_constraint = get_shot_constraint(shot_type)
            trans_hint = get_transition_hint(transition)
            # 反 AI 味扰动：按景别动态注入比喻密度上限与句式倾向（打破全章匀速感）
            anti_ai_hint = build_anti_ai_perturbation(shot_type)
            soft_hints = f"{trans_hint}\n{shot_constraint}\n{anti_ai_hint}\n\n{soft_hints}"

        # 构造 prompt
        system_prompt, user_prompt = build_forward_flow_prompt(
            style_contract=style_contract,
            author_samples=author_samples_text,
            climax_anchor=climax_anchor_text,
            emotion_curve=emotion_curve_text,
            segment_index=i + 1,
            total_segments=total_segments,
            progress=progress,
            current_register=cur_sample.register,
            current_energy=cur_sample.energy,
            next_register=next_sample.register,
            next_energy=next_sample.energy,
            rolling_prefix=sanitize_rolling_prefix(rolling_prefix[-ROLLING_PREFIX_TAIL:]) if rolling_prefix else "（本章开篇）",
            purpose=purpose,
            entry_state=entry_state_text,
            characters=characters_text,
            character_arc_advances=character_arc_text,
            soft_hints=soft_hints,
            target_words=dynamic_target_words,
        )

        # V3.5：世界观设定注入（system 层最顶部，比 Canon 更基础——先有世界规则，再有 private 真相）
        # 全章不变，每段注入（吃 prompt 缓存）
        if worldview_text:
            system_prompt = f"# 世界观设定（这个世界的基础规则）\n\n{worldview_text}\n\n{system_prompt}"

        # V4.0：把 Canon 作为强约束 prepend 到 system_prompt
        # ★ 核心：private 字段绝不许在正文出现；public 事实必须遵守
        # 为节省 token，只在第一段注入完整 Canon；后续段注入精简版（private 关键词清单）
        if i == 0:
            canon_inject = canon_context
        else:
            # 后续段只保留 private 节点的标签（提示有不许说出的内容）
            canon_inject = _build_compact_canon_hint(canon_context)
        if canon_inject and canon_inject.strip() and "（Canon 为空" not in canon_inject:
            system_prompt = (
                f"# ★★★ 作者脑中世界（Canon，最高优先级约束）★★★\n\n"
                f"{canon_inject}\n\n"
                f"--- 写作约束：\n"
                f"- private 字段可作为角色隐藏动机影响其行为，但绝不许用对话/叙述/心理独白直接说出\n"
                f"- public 事实是已建立的真相，正文必须与之保持一致\n"
                f"---\n\n"
                f"{system_prompt}"
            )

        # V4.2：把作者意图（介入点 1 决策）作为强约束 prepend 到 system_prompt
        # 只在第一段注入完整版，后续段不重复（节省 token）
        if i == 0 and author_intent and author_intent.strip():
            system_prompt = (
                f"# ★★★ 作者意图（介入点 1 确认）★★★\n\n"
                f"{author_intent}\n\n"
                f"--- 写作时严格遵守：作者说释放的必须释放，说累积的不许释放。---\n\n"
                f"{system_prompt}"
            )

        # V3.5：场景设定注入（用户章级指定的角色/地点/资产/关系）
        # 每段都注入（全章复用，吃 prompt 缓存），确保正文写作时能看到设定
        if scene_setting_text:
            system_prompt = f"# 场景设定（本章涉及的设定数据）\n\n{scene_setting_text}\n\n{system_prompt}"

        # 调用 LLM（带单段超时，防止重模型挂起导致整章死等）
        try:
            if recorder is not None:
                async with recorder.record_call(
                    stage=f"adf.forward_flow.segment_{i + 1}",
                    model_slot="creative",
                ) as call_ctx:
                    result = await asyncio.wait_for(
                        call_llm_with_usage(
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            model_type="creative",
                            temperature=0.75,
                            max_tokens=max(2048, min(8192, dynamic_target_words * 4)),
                        ),
                        timeout=SEGMENT_TIMEOUT,
                    )
                    call_ctx.set_result(result)
            else:
                result = await asyncio.wait_for(
                    call_llm_with_usage(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        model_type="creative",
                        temperature=0.75,
                        max_tokens=max(2048, min(8192, dynamic_target_words * 4)),
                    ),
                    timeout=SEGMENT_TIMEOUT,
                )
            segment_text = (result.content or "").strip()
        except asyncio.TimeoutError:
            # 单段超时：降级空段（保持段序号连续），记 DEGRADED 供前端上浮
            # 注：超时发生在 record_call 上下文内时，RunRecorder 会自动追加一条
            # reason="exception_during_call" 的降级；此处再追加 reason="segment_timeout"
            # 的精简记录，提供段号与超时阈值。两条都会经 adf.py 的 DEGRADED 上浮前端。
            logger.warning(f"[ADF] 第 {i + 1} 段超时（>{SEGMENT_TIMEOUT}s），降级空段")
            if recorder is not None:
                recorder.record_degraded(
                    stage=f"adf.forward_flow.segment_{i + 1}",
                    reason="segment_timeout",
                    action="skipped_empty",
                    model_slot="creative",
                    detail=f"creative LLM 调用超过 {SEGMENT_TIMEOUT}s 未返回，该段留空",
                )
            segment_text = ""
        except Exception as e:
            logger.warning(f"[ADF] 第 {i + 1} 段写作失败，降级空段: {e}")
            segment_text = ""

        if not segment_text:
            logger.warning(f"[ADF] 第 {i + 1} 段返回空文本")
            segment_text = ""

        # ---- 反 AI 味后处理（触点3：本地抽脂 → 密度评估 → 正则裁剪 / LLM 洗涤）----
        # 三道防线：
        # 1. 本地预处理（0 Token）：jieba 词性抽脂 + 硬断句，删冗余修饰、制造顿挫
        # 2. 正则安全裁剪（确定性、零延迟）：删黑名单词/微操
        # 3. 超阈值时 LLM 洗涤（creative 槽单段）
        if segment_text:
            # [Tier 2] 本地预处理：jieba 抽脂 + 硬断句（0 Token，微秒级）
            # 放在 measure_ai_taste 之前：让评估基于更干净的文本，且减轻下游洗涤负担
            segment_text = preprocess_segment(segment_text, genre=genre)
            density_report = measure_ai_taste(segment_text)
            if density_report.triggered and wash_count < DEFAULT_THRESHOLDS.wash_max_segments_per_chapter:
                # 超阈值且有洗涤配额 → LLM 重洗该段
                wash_result = await wash_segment_if_too_ai(segment_text, density_report)
                segment_text = wash_result.text
                if wash_result.washed:
                    wash_count += 1
                    logger.info(
                        f"[ADF] 第 {i + 1} 段去AI洗涤：{wash_result.original_score}→"
                        f"{wash_result.final_score}（{wash_result.reason}）"
                    )
                else:
                    logger.info(f"[ADF] 第 {i + 1} 段洗涤未生效：{wash_result.reason}")
            else:
                # 未超阈值或洗涤配额用尽 → 仅正则轻裁
                if density_report.triggered:
                    logger.info(
                        f"[ADF] 第 {i + 1} 段AI味{density_report.overall_score}超标但洗涤配额已尽"
                        f"({wash_count}/{DEFAULT_THRESHOLDS.wash_max_segments_per_chapter})，仅正则裁剪"
                    )
                segment_text = sanitize_segment(segment_text)

        # 更新 Precondition 落地状态（关键词检测）
        landed_ids = update_precondition_landed_state(anchor, segment_text, i)

        # 记录段产出
        seg = SegmentResult(
            index=i,
            text=segment_text,
            scene_summary=segment_text[-100:] if segment_text else "",
            emotion_register=cur_sample.register,
            landed_preconditions=landed_ids,
            planted_hooks=[],
            shot_type=storyboard[i][0] if i < len(storyboard) else "",
            transition=storyboard[i][1] if i < len(storyboard) else "",
        )
        segments.append(seg)

        # 更新 rolling_prefix
        rolling_prefix = segment_text
        current_word_count += len(segment_text)

        # 推送进度
        if progress_callback:
            try:
                await progress_callback("ADF_PROGRESS", {
                    "segment_index": i + 1,
                    "total_segments": total_segments,
                    "progress": progress,
                    "register": cur_sample.register,
                    "energy": cur_sample.energy,
                    "word_count": len(segment_text),
                    "shot_type": seg.shot_type,
                    "transition": seg.transition,
                })
            except Exception as cb_err:
                logger.warning(f"[ADF] progress_callback ADF_PROGRESS 失败: {cb_err}")

            # 推送条件落地事件
            for pc_id in landed_ids:
                pc = next((p for p in anchor.preconditions if p.id == pc_id), None)
                if pc:
                    try:
                        await progress_callback("ADF_PRECONDITION_LANDED", {
                            "precondition_id": pc_id,
                            "segment": i + 1,
                            "evidence": pc.landed_evidence or "",
                            "category": pc.category,
                        })
                    except Exception as cb_err:
                        logger.warning(f"[ADF] progress_callback ADF_PRECONDITION_LANDED 失败: {cb_err}")

    logger.info(
        f"[ADF] 正向流写作完成：{len(segments)} 段，"
        f"总 {current_word_count} 字，"
        f"{sum(1 for pc in anchor.preconditions if pc.landed)}/{len(anchor.preconditions)} 个 preconditions 已落地"
    )
    return segments, anchor
