"""
BS-ADF Phase 4a：槽位卡生成（SLOT_BUILD）。

职责：把 ADF Phase 1-3 产出的 anchor + spine 派生为 List[BeatSlotCard]
业务场景：Phase 4a，纯算法（0 LLM）+ 可选 1× enrichment LLM（见 enrich_slots）
主要功能：
  - soft_assign_preconditions：把无序 preconditions 软分配到各段
  - shot_type/transition/rhythm 映射
  - emotion 采样
  - target_word_count 动态分摊
依赖项：ADF types、storyboard、anti_ai_rules

注意：本模块纯算法，enrich_slots（LLM 扩写）单独在 P1.4 加入。
"""
# Velluma - BS-ADF slot_builder
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from backend.services.llm import call_llm_with_usage
from backend.services.llm.client import REASONING_DISABLED
from backend.services.observability.run_recorder import RunRecorder
from backend.services.observability.run_trace import trace_event
from backend.services.prompts.bsadf_prompts import build_slot_enrich_prompt
from backend.services.workflows.adf.types import (
    ChapterClimax, Precondition, StoryContext,
)
from backend.services.workflows.adf.storyboard import plan_storyboard
from backend.services.workflows.adf.beat_patcher import parse_outline_beats
from backend.services.workflows.adf.climax_designer import _extract_json
from backend.services.workflows.bsadf.types import BeatSlotCard

logger = logging.getLogger(__name__)

try:
    import jieba.posseg as _pseg
except ImportError:  # pragma: no cover
    _pseg = None
    logger.warning("[slot_builder] jieba.posseg 不可用，enrich 零接地过滤将被跳过")

_MAX_WORD_LEN = 20  # enrichment 单词长度上限

# 每卡强制词预算（方案书对齐：槽位卡是"极轻量级物理白描槽位"，
# 示例卡 key_anchor 仅 3 个词；上限留一点富余，锚点词 6 个）。
# 任何上游（precondition 词表、enrichment 扩写）膨胀都在此截断，
# 防止强制词数量膨胀到渲染不可能完成（实测累积分配曾达单卡 43 词）。
MAX_ANCHOR_TERMS = 6

# 代码级幻觉闸门（enrichment 用）：剧情级关键词清单。
# enrichment 的职责只是"把物理动作/感官词写丰富"，无权发明剧情级内容
# （身体变异、形态转换、超能力觉醒等）。命中这些词的新词，若该关键词
# 本身不在本章大纲/高潮设计/原种子里（即故事从未授权），一律剥离。
# 真实事故：enrichment 为"跌落仓库"节拍发明"眼球虹膜分裂成复眼阵列"，
# 渲染执行后被状态卡继承，扩散成全章设定污染（融合前两段就长出复眼）。
_PLOT_LEVEL_KEYWORDS = (
    "复眼", "虹膜", "变异", "蜕变", "融合", "甲壳", "外骨骼",
    "骨刺", "触手", "液化", "液态金属", "鳞片", "寄生", "夺舍",
    "变身", "机械化", "纳米", "增生", "晶体", "觉醒", "血脉", "基因",
)

# outline_beat 关键实体抽取（enforce_outline_entities 用）
_TITLE_RE = re.compile(r"《[^》\n]{1,30}》")
_QUOTE_RE = re.compile(r"[“\"]([^“”\"'\n]{8,120})[”\"]")


def _strip_off_context_terms(
    terms: List[str],
    allowed_text: str,
    beat_id: str,
) -> List[str]:
    """剥离越权发明的剧情级新词（enrichment 幻觉闸门，0 LLM）。

    判定：词中含剧情级关键词，且该关键词不在 allowed_text（本章大纲 +
    高潮设计 + 原种子 + 冲突触发）里 → 故事从未授权该剧情元素 → 剥离。
    例如"融合"出现在高潮设计里则末段卡可用，出现在第 2 段卡里即超前。
    """
    kept: List[str] = []
    for term in terms:
        offender = next(
            (kw for kw in _PLOT_LEVEL_KEYWORDS if kw in term and kw not in allowed_text),
            None,
        )
        if offender is None:
            kept.append(term)
        else:
            logger.warning(
                f"[enrich_slots] {beat_id} 剥离越权剧情词「{term}」"
                f"（关键词「{offender}」不在大纲/锚点/种子里）"
            )
    return kept


def _strip_ungrounded_terms(
    terms: List[str],
    allowed_text: str,
    seed_terms: List[str],
    beat_id: str,
) -> List[str]:
    """零接地过滤（enrichment 幻觉闸门第二道，0 LLM，在关键词闸门之后跑）。

    判定：对每个 LLM 扩写词，jieba.posseg 切出内容词（名词/动词，len≥2），
    若该词的【所有】内容词都与接地语料零关联 → 剥离。接地判定（双向）：
    内容词出现在 allowed_text 中，或语料/种子中的 ≥2 字词是它的子串。
    例：大纲说"工头"→扩出"工头摘下黄色安全帽"，内容词"工头"接地 → 保留；
    "雷电劈裂古树"（雷电/劈裂/古树均不在语料）→ 剥离。

    真实事故：种子为空的卡被 LLM 凭空扩出"雷电劈裂古树/岩浆喷涌/冰雹砸穿
    瓦片"（机甲仓库场景），第一道关键词闸门只拦剧情级词（变异/复眼类），
    自然灾害词全放行，渲染器照抄成正文灾难。

    权衡（宁漏勿误的边界）：
    - 只取 len≥2 的内容词：单字词（如"火"）在语料中命中率过高（任何"火"
      字出现就放行一切火相关幻觉），且单字切分噪声大；代价是全新单字词
      无法被本闸门拦截（由第一道关键词闸门与渲染约束兜底）。
    - 切不出 ≥2 字名/动内容词的词（虚词短语等）保守保留。
    - jieba 不可用时整道闸门跳过（保守全保留）。
    """
    if _pseg is None:
        return list(terms)
    # 接地词表：种子词 + 语料中切出的全部 ≥2 字词
    ground = {t for t in seed_terms if t and len(t) >= 2}
    for w, _flag in _pseg.lcut(allowed_text or ""):
        if len(w) >= 2:
            ground.add(w)
    kept: List[str] = []
    for term in terms:
        if not term or term in allowed_text:
            kept.append(term)
            continue
        content_words = [
            w for w, flag in _pseg.lcut(term)
            if len(w) >= 2 and flag[:1] in ("n", "v")
        ]
        if not content_words:
            kept.append(term)
            continue
        grounded = any(
            w in allowed_text or any(g in w for g in ground)
            for w in content_words
        )
        if grounded:
            kept.append(term)
        else:
            logger.warning(
                f"[enrich_slots] {beat_id} 剥离零接地词「{term}」"
                f"（内容词 {content_words} 均不在大纲/锚点/种子里）"
            )
    return kept


# ============================================================================
# 映射函数（纯算法）
# ============================================================================
_SHOT_TO_BEAT_TYPE = {
    "wide": "ESTABLISH",
    "full": "ESTABLISH",
    "medium": "CONFRONT",
    "close": "CONFRONT",
    "macro": "CLIMACTIC",
}

_TRANSITION_TO_RHYTHM = {
    "cut": "SHORT_PUNCHY",
    "fade": "LAYERED",
    "push_in": "VARIED",
    "pull_out": "VARIED",
    "counter": "VARIED",
}


def shot_type_to_beat_type(shot_type: str) -> str:
    """storyboard shot_type → beat_type。"""
    return _SHOT_TO_BEAT_TYPE.get(shot_type, "CONFRONT")


def transition_to_rhythm(transition: str) -> str:
    """storyboard transition → sentence_rhythm。"""
    return _TRANSITION_TO_RHYTHM.get(transition, "VARIED")


def dynamic_spread(total_target: int, segment_index: int, total_segments: int) -> int:
    """把总字数目标均摊到单段，最小 500（NLE-ADF 黄金粒度）。"""
    per_segment = max(500, total_target // total_segments)
    return per_segment


# ============================================================================
# precondition 定点分配
# ============================================================================

def _assign_pc_target_segments(
    preconditions: List[Precondition],
    total_segments: int,
    per_segment_words: int = 600,
) -> Dict[int, List[Precondition]]:
    """把每个 precondition 定点分配到唯一目标段。

    设计意图（方案书对齐）：旧实现是累积式软分配——只要 PC 的最早可落地段
    ≤ 当前段，就把该 PC 复制进当前卡。min_landing_offset 通常为 0，导致从
    第 2 段起每张卡背上全章 PC 的 must_use_terms 并集（实测单卡 23~43 个
    强制词，渲染必然 coverage 失败）。定点分配让每个 PC 全章只落一个目标段：
    按 min_landing_offset 推导目标段，同段超容量时向后顺延摊铺。

    Args:
        preconditions: ADF Phase 2 产出的前置条件列表
        total_segments: 全章段数
        per_segment_words: 估算的每段字数（offset→段号换算用）

    Returns:
        {segment_index: [Precondition, ...]}
    """
    if not preconditions or total_segments <= 0:
        return {}
    sorted_pcs = sorted(
        preconditions, key=lambda p: (p.min_landing_offset, p.id or "")
    )
    capacity = max(1, -(-len(sorted_pcs) // total_segments))  # ceil 均摊容量
    assignments: Dict[int, List[Precondition]] = {}
    for pc in sorted_pcs:
        seg = min(
            total_segments - 1, max(0, pc.min_landing_offset // per_segment_words)
        )
        # 同段已达均摊容量则顺延到下一段（末段兜底接收）
        while len(assignments.get(seg, [])) >= capacity and seg < total_segments - 1:
            seg += 1
        assignments.setdefault(seg, []).append(pc)
    return assignments


def soft_assign_preconditions(
    preconditions: List[Precondition],
    segment_index: int,
    progress: float,
    total_segments: int,
) -> List[Precondition]:
    """取定点分配到本段的 preconditions（每个 PC 全章只落一段）。

    progress 参数保留仅为签名兼容，定点分配不使用。
    """
    assignments = _assign_pc_target_segments(preconditions, total_segments)
    return list(assignments.get(segment_index, []))


# ============================================================================
# 主函数：build_beat_slots（纯算法版，enrichment 在 P1.4 加）
# ============================================================================

def build_beat_slots(
    anchor: ChapterClimax,
    spine: StoryContext,
    total_segments: int,
    target_word_count: int,
    chapter_number: int,
    locations: List[Any] = None,
    assets: List[Any] = None,
    chapter: Any = None,
) -> List[BeatSlotCard]:
    """从 anchor+spine 派生全章 BeatSlotCard 列表（纯算法，0 LLM）。

    Args:
        anchor: ADF Phase 2 产出的 ChapterClimax
        spine: ADF Phase 1 产出的 StoryContext
        total_segments: 段数（来自 tier_decide）
        target_word_count: 全章目标字数
        chapter_number: 章节号（用于 beat_id）
        locations: 保留参数（感官词种子已下沉为静态渲染规则，不再消费）
        assets: 保留参数（同上）
        chapter: chapter ORM 对象（可选，用于大纲节拍按序分配）

    Returns:
        List[BeatSlotCard]，长度 == total_segments
    """
    locations = locations or []
    assets = assets or []

    # 大纲节拍按序分配到段（防大纲偏移：渲染器此前完全看不到大纲文本，
    # 段序由 storyboard 景别决定，实测会出现"第 1~3 拍跑到袭击戏之后"的乱序）
    outline_beats: List[str] = []
    if chapter is not None:
        try:
            outline_beats = parse_outline_beats(
                getattr(chapter, "outline_text", "") or ""
            )
        except Exception as e:
            logger.warning(f"[build_beat_slots] 大纲节拍解析失败（跳过注入）: {e}")
    beat_by_segment: Dict[int, List[str]] = {}
    if outline_beats:
        n = len(outline_beats)
        for k, beat in enumerate(outline_beats):
            seg = min(total_segments - 1, k * total_segments // n)
            beat_by_segment.setdefault(seg, []).append(beat)

    storyboard = plan_storyboard(
        total_segments=total_segments,
        emotion_curve=anchor.emotion_curve,
        has_multiple_pov=len(spine.character_arc_advances) >= 2,
    )

    cards: List[BeatSlotCard] = []
    for i in range(total_segments):
        progress = (i + 1) / total_segments
        shot_type, transition = storyboard[i]

        sample_progress = max(0.0, progress - 0.5 / total_segments)
        emotion_sample = anchor.emotion_curve.sample_at(sample_progress)

        landed_pcs = soft_assign_preconditions(
            anchor.preconditions, segment_index=i, progress=progress,
            total_segments=total_segments,
        )

        # 强制词种子：只取定点落到本段的 PC 的词，去重后按预算截断
        key_anchor_seeds = list(dict.fromkeys(
            term for pc in landed_pcs for term in (pc.must_use_terms or [])
        ))[:MAX_ANCHOR_TERMS]

        card = BeatSlotCard(
            beat_id=f"BS_CH{chapter_number}_BEAT_{i:02d}",
            segment_index=i,
            beat_type=shot_type_to_beat_type(shot_type),
            target_word_count=dynamic_spread(target_word_count, i, total_segments),
            key_anchors=key_anchor_seeds,
            text_carrier="",
            core_plot_event=_pick_core_plot_event(
                "；".join(beat_by_segment.get(i, [])),
                landed_pcs, anchor.climax, i, total_segments,
            ),
            outline_beat="；".join(beat_by_segment.get(i, [])),
            sentence_rhythm=transition_to_rhythm(transition),
            emotion_register=emotion_sample.register,
            emotion_energy=emotion_sample.energy,
            landed_preconditions=[pc.id for pc in landed_pcs],
            shot_type=shot_type,
            transition=transition,
        )
        cards.append(card)

    return cards


def _pick_core_plot_event(
    outline_beat_text: str,
    landed_pcs: List[Precondition],
    climax: Any,
    segment_index: int,
    total_segments: int,
) -> str:
    """派生本段核心剧情转折（纯算法，可能为空）。

    派生优先级（2026-07-28 校准：核心转折必须与本段剧情时间线同源）：
    1. 本段的 outline_beat（大纲节拍按序分配，与"最高叙事约束"同一来源——
       旧实现取定点 PC 的描述，PC 按 min_landing_offset 摊铺、与剧情时间线
       无关，导致卡片核心转折跨时间线跳跃，且与 outline_beat 给渲染器
       矛盾指令，实测出现"PC 错段硬插回忆"）
    2. 末段附加高潮描述（大纲末拍未必含高潮细节）
    3. 本段无 outline_beat 时回退到定点 PC 描述（大纲节拍数 < 段数的兜底）
    """
    base = (outline_beat_text or "").strip()
    if segment_index == total_segments - 1:
        climax_desc = (getattr(climax, "description", "") or "").strip()
        if climax_desc and climax_desc not in base:
            base = f"{base}；{climax_desc}" if base else climax_desc
    if base:
        return base
    for pc in landed_pcs:
        if pc.description:
            return pc.description
    return ""


# ============================================================================
# Phase 4a：Slot Enrichment（可选 1× creative LLM/卡）
# ============================================================================

async def enrich_slots(
    cards: List[BeatSlotCard],
    recorder: Optional[RunRecorder] = None,
    enable: bool = True,
    guard_context: str = "",
    progress_callback: Optional[Callable[[int, int, str], Any]] = None,
) -> List[BeatSlotCard]:
    """对全章槽位卡跑 1× LLM 扩写（每张卡独立扩写，串行）。

    失败判定（任一即视为该卡失败，保留原种子）：
    (a) LLM 抛异常/超时
    (b) 返回无法 JSON 解析
    (c) 解析出的锚点词为空
    (d) 任一词超过 _MAX_WORD_LEN 字

    幻觉闸门（0 LLM，两道，见 _strip_off_context_terms /
    _strip_ungrounded_terms）：
    1. 剧情关键词闸门：扩写词含剧情级关键词且该关键词不在授权上下文 → 剥离
    2. 零接地闸门：扩写词的全部内容词（≥2 字名/动词）都与语料零关联 → 剥离
    空种子禁自由扩写：卡的初始 key_anchors（4a 从 anchor+spine 派生的种子，
    不含后置 enforce_outline_entities 注入的实体）为空时直接跳过该卡的
    LLM 扩写——没有接地起点的扩写只会凭空发明。

    Args:
        cards: 待扩写的槽位卡列表（in-place 修改 key_anchors）
        recorder: RunRecorder（记 token 用量，可选）
        enable: 是否启用（False 则直接返回原卡）
        guard_context: 幻觉闸门的授权上下文（本章大纲全文 + 高潮设计描述，
            由调用方提供；空串则闸门只认卡本身字段，更严格）
        progress_callback: 进度回调 (current_index, total, beat_id)，
            每张卡开始扩写前调用一次，让前端实时看到"槽位扩写 3/6"

    Returns:
        扩写后的 cards（同一引用，in-place 修改）
    """
    if not enable:
        return cards

    for i, card in enumerate(cards):
        # 进度回调：让前端实时看到"槽位扩写 i/total"（SLOT_BUILD 60s 沉默的根因修复）
        if progress_callback:
            try:
                await progress_callback(i, len(cards), card.beat_id)
            except Exception:
                pass
        # 空种子禁自由扩写：种子（4a 从 anchor+spine 派生的初始 key_anchors，
        # 此时 enforce_outline_entities 尚未注入大纲实体）为空的卡没有接地
        # 起点，LLM 只能凭空发明（真实事故：机甲仓库场景产出"雷电劈裂古树/
        # 岩浆喷涌"等自然灾害词并被渲染器照抄成正文灾难）。跳过该卡，仅保留
        # 后置 enforce_outline_entities 注入的大纲实体。
        if not card.key_anchors:
            logger.info(
                f"[enrich_slots] {card.beat_id} 种子为空，跳过 LLM 扩写（防凭空发明）"
            )
            continue
        try:
            system_prompt, user_prompt = build_slot_enrich_prompt(
                seed_anchors=card.key_anchors,
                shot_type=card.shot_type,
                emotion_register=card.emotion_register,
                scene_entities=[],
            )
            # 用 recorder.record_call 上下文管理器（与 climax_designer 一致）
            # 注意 max_tokens：creative 槽被禁用时会 fallback 到 reasoning 槽
            # （如 deepseek-v4-pro），reasoning 模型的推理过程消耗大量 token。
            # 4096 与 climax_designer / de_ai_washer 等同类调用对齐，
            # 实测 512/2048 在 effort=max 下会因推理耗尽预算导致 content 为空
            # （finish_reason=length）。
            # reasoning_config=REASONING_DISABLED：显式关闭 thinking（扩写是
            # 机械任务，思考预算与正文共享 max_tokens，实测 thinking 曾吃掉
            # 3900+/4096）。必须传 REASONING_DISABLED——空 dict 会被 client
            # 的 truthy 检查吞掉，等于没关。
            if recorder is not None:
                async with recorder.record_call(
                    stage=f"bsadf.enrich.{card.beat_id}",
                    model_slot="creative",
                ) as call_ctx:
                    result = await call_llm_with_usage(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        model_type="creative",
                        temperature=0.7,
                        max_tokens=4096,
                        response_format={"type": "json_object"},
                        reasoning_config=REASONING_DISABLED,
                    )
                    call_ctx.set_result(result)
            else:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="creative",
                    temperature=0.7,
                    max_tokens=4096,
                    response_format={"type": "json_object"},
                    reasoning_config=REASONING_DISABLED,
                )

            data = _extract_json(result.content)
            if not data:
                logger.warning(
                    f"[enrich_slots] {card.beat_id} JSON 解析失败（content 非法或为空），"
                    f"finish_reason={getattr(result, 'finish_reason', '?')}，保留种子"
                )
                continue
            new_anchors = data.get("key_anchors", [])

            # 失败判定
            if not new_anchors:
                logger.warning(f"[enrich_slots] {card.beat_id} 扩写结果为空，保留种子")
                continue
            if any(len(w) > _MAX_WORD_LEN for w in new_anchors):
                logger.warning(f"[enrich_slots] {card.beat_id} 扩写结果含超长词，保留种子")
                continue

            # 幻觉闸门（0 LLM，两道）：剥离越权发明的剧情级新词（如超前变异），
            # 再剥离与语料零接地的词（如机甲仓库场景发明"雷电劈裂古树"）。
            # 授权上下文 = 本章大纲/高潮设计（guard_context）+ 卡自身字段 + 原种子
            allowed_text = (
                guard_context
                + (card.outline_beat or "")
                + (card.core_plot_event or "")
                + (card.text_carrier or "")
                + "".join(card.key_anchors)
            )
            new_anchors = _strip_off_context_terms(new_anchors, allowed_text, card.beat_id)
            new_anchors = _strip_ungrounded_terms(
                new_anchors, allowed_text, card.key_anchors, card.beat_id,
            )
            if not new_anchors:
                logger.warning(
                    f"[enrich_slots] {card.beat_id} 扩写词全部被幻觉闸门剥离，保留种子"
                )
                continue

            # 合并：扩写词 + 原种子（去重，保序），按预算截断
            card.key_anchors = list(dict.fromkeys(
                new_anchors + card.key_anchors
            ))[:MAX_ANCHOR_TERMS]
        except Exception as e:
            logger.warning(f"[enrich_slots] {card.beat_id} LLM 调用失败：{e}，保留种子")

    return cards


# ============================================================================
# Phase 4b 后置：outline 关键实体强制映射（0 LLM 代码闸门）
# ============================================================================

def _extract_outline_entities(outline_beat: str) -> Dict[str, List[str]]:
    """从 outline_beat 抽取必须入文的关键实体（0 LLM）。

    抽取三类：
    - titles: 《书名/作品名》
    - quotes: 引号包裹的 ≥8 字引文（名言/对白/铭文，保留原引号）
    - 角色名由调用方单独比对（known_names ⊆ outline_beat）
    """
    titles = _TITLE_RE.findall(outline_beat or "")
    quotes = ["“" + m + "”" for m in _QUOTE_RE.findall(outline_beat or "")]
    return {"titles": titles, "quotes": quotes}


def enforce_outline_entities(
    cards: List[BeatSlotCard],
    known_names: Optional[List[str]] = None,
) -> List[str]:
    """代码级闸门：outline_beat 的关键实体必须映射进槽位（0 LLM）。

    设计意图（不能完全信任 prompt 约束）：outline_beat 虽然作为"最高叙事
    约束"注入渲染 prompt，但模型可能漏写——实测《约翰·克利斯朵夫》书名
    出现在 outline_beat 里，槽位生成器却给了空的 text_carrier，正文书名
    彻底丢失。本闸门把关键实体物理写进被 verify_slot_coverage 校验的槽位
    （text_carrier / key_anchors），让"缺失"在 coverage 校验层面可发现、
    可重试，而不是依赖模型自觉。

    注入规则（幂等，已存在则跳过）：
    - 缺失的引文/书名 → text_carrier（多项以 "；" 分隔追加，
      与 verify_slot_coverage 的分段校验约定一致）
    - 缺失的角色名（出现在 outline_beat 但不在任何槽位）→ key_anchors
      尾部追加（允许超 MAX_ANCHOR_TERMS 两个预算外名额——人名渲染成本
      极低，且大纲点名即最高约束）

    Args:
        cards: 槽位卡列表（enrichment 之后调用，in-place 修改）
        known_names: 本章可涉及角色名清单（entities 的 name）

    Returns:
        注入说明列表（供 trace/日志；空列表 = 全部已覆盖）
    """
    known_names = [n for n in (known_names or []) if n]
    injected: List[str] = []

    for card in cards:
        outline = (card.outline_beat or "").strip()
        if not outline:
            continue
        # 卡内容 blob：所有槽位字段拼一起做存在性判定
        blob = "".join(card.key_anchors) \
            + (card.text_carrier or "") + (card.core_plot_event or "")

        entities = _extract_outline_entities(outline)
        # 书名 + 引文 → text_carrier（多项用 "；" 分隔，
        # verify_slot_coverage 按 "；" 分段逐项校验，互不牵连）
        missing_items = [t for t in entities["titles"] if t not in blob]
        missing_items += [q for q in entities["quotes"] if q not in blob]
        if missing_items:
            addition = "；".join(missing_items)
            card.text_carrier = (
                f"{card.text_carrier}；{addition}"
                if card.text_carrier else addition
            )
            injected.append(f"{card.beat_id}: text_carrier 注入 {missing_items}")

        # 角色名 → key_anchors
        for name in known_names:
            if name in outline and name not in blob:
                if len(card.key_anchors) < MAX_ANCHOR_TERMS + 2:
                    card.key_anchors.append(name)
                    injected.append(f"{card.beat_id}: key_anchors 注入角色名「{name}」")

    if injected:
        logger.info(f"[enforce_outline_entities] 注入 {len(injected)} 项：{injected}")
        trace_event("outline_entities_injected", items=injected)
    return injected
