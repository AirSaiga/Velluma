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
- 设定一致性写作期防线（纯代码 0 LLM）：专名表 + 知识边界约束 + 在场提示，
  组装为每段 user prompt 末尾的"# 本段硬约束"区块

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
import re
from typing import Any, Callable, List, Optional, Tuple

from backend.services.llm import call_llm_with_usage, LLMResult
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
from backend.services.workflows.adf.setting_resolver import (
    build_scene_setting_text,
    resolve_characters,
    resolve_hidden_constraints,
)
from backend.services.workflows.adf.name_registry import (
    NameRegistry,
    build_name_registry,
    registry_to_prompt_block,
)
from backend.services.workflows.adf.dedup_guard import segment_too_similar
from backend.services.workflows.adf.state_tracker import (
    SceneStateCard,
    card_to_prompt_block,
    check_segment_against_card,
    extract_state_card,
)

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


# 句末标点：用于 length 截断后清残句（截到最后一个完整句子）
_SENTENCE_END_CHARS = "。！？!?…"


def _trim_to_last_sentence(text: str) -> str:
    """length 截断兜底：把文本截到最后一个句末标点，避免半句话残留。

    业务场景：creative LLM 撞 max_tokens 后输出常停在连词/助词中段（如"……都得考，虽"），
    这种残句直接进 final_text 会卡住读者。本函数找到最后一个句末标点（。！？!?…），
    保留到该标点为止的内容；若全文无句末标点（极短或纯标点），返回原文不动。
    保留末尾的换行/空白以维持段落格式。
    """
    if not text:
        return text
    # 找最后一个句末标点的位置
    last_end = -1
    for ch in _SENTENCE_END_CHARS:
        idx = text.rfind(ch)
        if idx > last_end:
            last_end = idx
    if last_end < 0:
        return text  # 无句末标点，原样返回（极短段或纯对话）
    return text[: last_end + 1]


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


def _canon_section(canon_context: str, tag: str) -> str:
    """从 canon_context 提取指定标记（[public] / [private]）所在段落的文本。"""
    if not canon_context or tag not in canon_context:
        return ""
    start = canon_context.find(tag)
    end = canon_context.find("\n## ", start)
    if end < 0:
        end = len(canon_context)
    return canon_context[start:end]


def _build_compact_canon_hint(canon_context: str) -> str:
    """为后续段构建精简 Canon 提示（节省 token）。

    - private 部分：保留"标签+不许说出"提示（现状行为，不重复完整 canon_text）
    - public 部分：追加已建立事实的完整行（public 无泄露风险，直接保留原文行，
      ≤10 条×120 字）——修复"第 2 段起 public 事实完全丢失"导致的设定漂移
    """
    if not canon_context or "（Canon 为空" in canon_context:
        return ""
    parts = []

    # private：提取节点 label（每行开头的 "- XXX："），只提示不许说出
    private_section = _canon_section(canon_context, "[private]")
    if private_section:
        labels = re.findall(r"^-\s+([^：:]+)[：:]", private_section, re.MULTILINE)
        if labels:
            parts.append(
                "[private 提醒] 以下节点是作者脑中真相，本段写作绝不许直接说出：\n"
                + "\n".join(f"- {lbl.strip()}" for lbl in labels[:8])
            )

    # public：保留完整事实行（"- 标签：内容"），必须保持一致
    public_section = _canon_section(canon_context, "[public]")
    if public_section:
        fact_lines = [
            ln.strip() for ln in public_section.splitlines()
            if ln.strip().startswith("- ")
        ][:10]
        if fact_lines:
            fact_lines = [
                ln if len(ln) <= 120 else ln[:120] + "…" for ln in fact_lines
            ]
            parts.append(
                "[public 事实] 以下已建立事实必须与本段保持一致：\n"
                + "\n".join(fact_lines)
            )

    return "\n\n".join(parts)


# ============================================================
# 设定一致性防线：知识边界约束 / 在场提示 / 每段硬约束区块
# ============================================================

MAX_KNOWLEDGE_CONSTRAINTS = 8  # 每段知识边界约束上限（防 prompt 膨胀）


def _build_knowledge_constraints(
    canon_context: str,
    hidden_constraints: List[str],
) -> List[str]:
    """构建知识边界约束行（写作期防知识越界，纯代码 0 LLM）。

    来源：
    - Canon [private] 区块的节点 label → "任何角色都不得说出、暗示或提及「X」的内容"
    - hidden_constraints（is_public=False 关系，resolve_hidden_constraints 输出）

    上限 MAX_KNOWLEDGE_CONSTRAINTS 条（去重后截取）。
    """
    constraints: List[str] = []

    private_section = _canon_section(canon_context, "[private]")
    if private_section:
        labels = re.findall(r"^-\s+([^：:]+)[：:]", private_section, re.MULTILINE)
        for lbl in labels:
            lbl = lbl.strip()
            if lbl:
                constraints.append(f"任何角色都不得说出、暗示或提及「{lbl}」的内容")

    for h in (hidden_constraints or []):
        h = (h or "").strip()
        if h:
            constraints.append(h)

    # 去重保序 + 上限
    seen = set()
    unique: List[str] = []
    for c in constraints:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique[:MAX_KNOWLEDGE_CONSTRAINTS]


def _build_presence_hint(
    segments_so_far: List[Any],
    registry: Optional[NameRegistry],
) -> str:
    """在场角色提示：纯代码统计最近 2 段出现的注册角色名。

    设计意图：段间连续性此前只靠 500 字 rolling_prefix，LLM 容易"忘记"
    谁在场（写出不在场角色的反应）。纯代码统计零成本，只报角色
    （不含地点/资产），首段返回空。

    Returns:
        "本段在场角色（按前文）：林尘、老赵"；首段或无匹配时返回空串
    """
    if not segments_so_far or registry is None or not registry.character_names:
        return ""
    recent = "".join(
        getattr(s, "text", "") or "" for s in segments_so_far[-2:]
    )
    if not recent:
        return ""
    present: List[str] = []
    for form in registry.all_surface_forms:
        canonical = registry.alias_to_canonical.get(form, form)
        if canonical in registry.character_names and canonical not in present and form in recent:
            present.append(canonical)
    if not present:
        return ""
    return "本段在场角色（按前文）：" + "、".join(sorted(present)[:8])


def _build_hard_constraints_block(
    registry_block: str,
    knowledge_constraints: List[str],
    presence_hint: str,
    state_card_block: str = "",
) -> str:
    """组装每段 user prompt 末尾的"# 本段硬约束"区块（放末尾吃近因效应）。

    组成：专名表（compact）+ 知识边界约束（≤8 条）+ 在场提示 + 剧情状态卡。
    全部为空时返回空串（prompt 里不出现该区块，行为与旧版一致）。
    """
    parts = []
    if registry_block:
        parts.append(registry_block)
    if knowledge_constraints:
        parts.append(
            "# 知识边界（绝不许越界）\n\n"
            + "\n".join(f"- {c}" for c in knowledge_constraints)
        )
    if presence_hint:
        parts.append(presence_hint)
    if state_card_block:
        parts.append(state_card_block)
    if not parts:
        return ""
    return "# 本段硬约束（违例即生成失败）\n\n" + "\n\n".join(parts)


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
    # Agent Loop 1：段级状态卡（每段 1 次小 creative 抽取 + 统一闸门校验）
    enable_state_tracker: bool = True,
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
        enable_state_tracker: Agent Loop 1 段级状态卡开关（每段 1 次小 creative
            抽取 + 下段注入 + 代码闸门校验；关闭时零额外调用、行为与旧版一致）

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

    # ---- 设定一致性防线（纯代码 0 LLM，全章复用）----
    # 专名注册表 + 知识边界约束：写作期防专名漂移/知识越界，
    # 生成后由 Phase 7 一致性守卫用同一基准审计（基准一致才有意义）。
    try:
        name_registry = build_name_registry(entities, locations, assets, canon_context)
        registry_block = registry_to_prompt_block(name_registry, max_entries=15)
    except Exception as e:
        logger.warning(f"[ADF] 专名注册表构建失败（降级无专名约束）: {e}")
        name_registry = None
        registry_block = ""
    try:
        hidden_constraints = resolve_hidden_constraints(
            relationships, resolve_characters(entities),
        )
        knowledge_constraints = _build_knowledge_constraints(canon_context, hidden_constraints)
    except Exception as e:
        logger.warning(f"[ADF] 知识边界约束构建失败（降级无约束）: {e}")
        knowledge_constraints = []

    # ---- 逐段写作 ----
    segments: List[SegmentResult] = []
    rolling_prefix = spine.entry_state.last_scene_image or "（本章开篇）"
    current_word_count = 0
    wash_count = 0  # 本章已洗涤段数（成本控制：超 wash_max_segments_per_chapter 不再洗）
    # Agent Loop 1：剧情状态卡（空卡自举——首段写完后由 LLM 抽取第一张，
    # 不预填 entry_state 角色，避免猜错在场阵容）
    state_card = SceneStateCard()

    for i in range(total_segments):
        # 字数提前终止：已写字数超过目标 130% 时跳过剩余段（防上下文爆掉）。
        # 远端锚段保护（修 segment_writer 历史事故）：高潮段是 Phase 2 设计的远端锚，
        # 正向写作逼近的目标就是它，绝不能因前面段写偏长而被无差别 break 掉。
        # 故仅当当前段不是末段时才允许提前终止——末段（高潮锚段）强制写完。
        if current_word_count > target_word_count * 1.3 and i < total_segments - 1:
            logger.info(
                f"[ADF] 字数提前终止：已写 {current_word_count} 字 > 目标 {target_word_count}×1.3，"
                f"保留末段（高潮锚段），跳过第 {i + 1}-{total_segments - 1} 段"
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
        # 设定一致性硬约束：专名表 + 知识边界 + 在场提示 + 剧情状态卡，
        # 放 user 末尾吃近因效应（i=0 时空卡不渲染）
        hard_constraints = _build_hard_constraints_block(
            registry_block=registry_block,
            knowledge_constraints=knowledge_constraints,
            presence_hint=_build_presence_hint(segments, name_registry),
            state_card_block=card_to_prompt_block(state_card) if enable_state_tracker else "",
        )
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
            hard_constraints=hard_constraints,
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
        # 提取为闭包：段级回路护栏的重试复用同一调用与后处理逻辑，避免复制
        #
        # max_tokens 计算：中文一字 ≈ 1.5–2 token（BPE），×3 已含约 50% 裕量。
        # 旧公式 ×4 表面裕量大，但当下限 dynamic_target_words 被压到 300 时（末段/
        # 提前终止后），max_tokens 仅 1200，叠加 LLM 引导性废话极易撞顶触发
        # finish_reason="length" 把句子切在半句上。故下限提到 3072。
        seg_max_tokens = max(3072, min(8192, dynamic_target_words * 3))

        async def _call_llm_once(max_tokens: int, extra_note: str = "") -> "Optional[LLMResult]":
            """单次调 creative LLM 写本段，返回 LLMResult（含 finish_reason）；失败返 None。"""
            call_user_prompt = f"{user_prompt}{extra_note}" if extra_note else user_prompt
            try:
                if recorder is not None:
                    async with recorder.record_call(
                        stage=f"adf.forward_flow.segment_{i + 1}",
                        model_slot="creative",
                    ) as call_ctx:
                        result = await asyncio.wait_for(
                            call_llm_with_usage(
                                system_prompt=system_prompt,
                                user_prompt=call_user_prompt,
                                model_type="creative",
                                temperature=0.75,
                                max_tokens=max_tokens,
                            ),
                            timeout=SEGMENT_TIMEOUT,
                        )
                        call_ctx.set_result(result)
                else:
                    result = await asyncio.wait_for(
                        call_llm_with_usage(
                            system_prompt=system_prompt,
                            user_prompt=call_user_prompt,
                            model_type="creative",
                            temperature=0.75,
                            max_tokens=max_tokens,
                        ),
                        timeout=SEGMENT_TIMEOUT,
                    )
                return result
            except asyncio.TimeoutError:
                # 单段超时：降级空段（保持段序号连续），记 DEGRADED 供前端上浮
                logger.warning(f"[ADF] 第 {i + 1} 段超时（>{SEGMENT_TIMEOUT}s），降级空段")
                if recorder is not None:
                    recorder.record_degraded(
                        stage=f"adf.forward_flow.segment_{i + 1}",
                        reason="segment_timeout",
                        action="skipped_empty",
                        model_slot="creative",
                        detail=f"creative LLM 调用超过 {SEGMENT_TIMEOUT}s 未返回，该段留空",
                    )
                return None
            except Exception as e:
                logger.warning(f"[ADF] 第 {i + 1} 段写作失败，降级空段: {e}")
                return None

        async def _call_llm(extra_note: str = "") -> str:
            """调 creative LLM 写本段，返回清洗后的字符串。

            length 截断兜底（修"句子被切在半句上"事故）：旧链路对 finish_reason="length"
            零检测，半句话原样进 final_text 且连带吃掉事件触发描述。现策略——
              1) 首次返回若未撞 max_tokens，照常返回；
              2) 若 length 截断，max_tokens 提到 8192 上限重试一次；
              3) 重试仍截断，则清残句（截到最后一个句末标点），记 DEGRADED。
            重试只触发一次，避免成本失控。
            """
            result = await _call_llm_once(seg_max_tokens, extra_note)
            if result is None:
                return ""
            content = (result.content or "").strip()
            if result.finish_reason != "length":
                return content
            logger.warning(f"[ADF] 第 {i + 1} 段首次撞 max_tokens 截断，提额度重试一次")
            retry = await _call_llm_once(8192, extra_note)
            if retry is not None:
                retry_content = (retry.content or "").strip()
                if retry.finish_reason != "length" and len(retry_content) > 50:
                    return retry_content
                content = retry_content or content
            # 仍截断：清残句保留可读部分，记降级
            cleaned = _trim_to_last_sentence(content)
            if recorder is not None and len(cleaned) < len(content):
                recorder.record_degraded(
                    stage=f"adf.forward_flow.segment_{i + 1}",
                    reason="length_truncated",
                    action="trimmed_residual",
                    model_slot="creative",
                    detail=(
                        f"creative LLM 撞 max_tokens 截断且重试仍截断，"
                        f"原文 {len(content)} 字→清残句后 {len(cleaned)} 字"
                    ),
                )
            return cleaned

        # ---- 反 AI 味后处理（触点3：本地抽脂 → 密度评估 → 正则裁剪 / LLM 洗涤）----
        # 三道防线：
        # 1. 本地预处理（0 Token）：jieba 词性抽脂 + 硬断句，删冗余修饰、制造顿挫
        # 2. 正则安全裁剪（确定性、零延迟）：删黑名单词/微操
        # 3. 超阈值时 LLM 洗涤（creative 槽单段）
        async def _postprocess(text: str) -> str:
            """对单段产出跑反 AI 味后处理；洗涤配额与本章 wash_count 共用。"""
            nonlocal wash_count
            if not text:
                return text
            # [Tier 2] 本地预处理：jieba 抽脂 + 硬断句（0 Token，微秒级）
            # 放在 measure_ai_taste 之前：让评估基于更干净的文本，且减轻下游洗涤负担
            text = preprocess_segment(text, genre=genre)
            density_report = measure_ai_taste(text)
            if density_report.triggered and wash_count < DEFAULT_THRESHOLDS.wash_max_segments_per_chapter:
                # 超阈值且有洗涤配额 → LLM 重洗该段
                wash_result = await wash_segment_if_too_ai(
                    text, density_report,
                    recorder=recorder, stage=f"adf.wash.segment_{i + 1}",
                )
                text = wash_result.text
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
                text = sanitize_segment(text)
            return text

        segment_text = await _call_llm()
        if not segment_text:
            logger.warning(f"[ADF] 第 {i + 1} 段返回空文本")
            segment_text = ""
        segment_text = await _postprocess(segment_text)

        # ---- 统一段级闸门（0 LLM 检测 + 最多 1 次重写）----
        # 闸门链：任一闸门违规 → 合并所有 note 一次重写；重写后重跑全部闸门，
        # 仍违规按第一个闸门类型记 reason 弃段。无违规时零额外调用。
        # 闸门 1（剧情回路）：与任一前段高度重复（真实故障：块 A′ 逐字重写块 A）
        # 闸门 2（状态矛盾）：与剧情状态卡冲突（真实故障：老周死后"喊了一嗓子"）
        def _run_gates(text: str) -> List[Tuple[str, str]]:
            """跑全部闸门，返回 (gate_name, note) 违规列表；空 = 全部通过。"""
            found: List[Tuple[str, str]] = []
            if not text:
                return found
            # 闸门 1：剧情回路
            if any(segment_too_similar(text, prev.text) for prev in segments):
                dup_seg = next(
                    prev for prev in segments
                    if segment_too_similar(text, prev.text)
                )
                found.append((
                    "segment_loop_duplicate",
                    f"你上一版输出与前面第{dup_seg.index + 1}段内容高度重复"
                    f"（同一场景已经写过）。必须写全新的、推进剧情的内容："
                    f"接着上一段结尾往后走，绝对不许重复任何已写过的场景、画面或事件。",
                ))
            # 闸门 2：状态卡矛盾（仅开启状态追踪且已有非空卡时）
            if enable_state_tracker and not state_card.is_empty():
                for violation in check_segment_against_card(text, state_card):
                    found.append((
                        "state_contradiction",
                        f"你上一版输出违反了剧情状态卡：{violation}。"
                        f"必须改写使其与状态卡一致（该角色可以出现在回忆、"
                        f"遗体或他人的叙述中，但不能以活人身份行动或说话）。",
                    ))
            return found

        violations = _run_gates(segment_text)
        if violations:
            logger.warning(
                f"[ADF] 第 {i + 1} 段触发闸门 {[v[0] for v in violations]}，"
                f"触发重写（最多 1 次）"
            )
            notes = "\n".join(f"- {note}" for _, note in violations)
            retry_text = await _call_llm(
                extra_note=f"\n\n# ⚠ 重写要求（最高优先级）\n{notes}"
            )
            retry_text = await _postprocess(retry_text)
            remaining = _run_gates(retry_text) if retry_text else violations
            if retry_text and not remaining:
                segment_text = retry_text
                logger.info(f"[ADF] 第 {i + 1} 段重写成功，闸门通过")
            else:
                # 重写仍违规（或重写失败）→ 弃段，按第一个闸门类型记 reason
                final_violations = remaining or violations
                gate_reason = final_violations[0][0]
                logger.warning(f"[ADF] 第 {i + 1} 段重写后仍违规（{gate_reason}），弃段")
                if recorder is not None:
                    recorder.record_degraded(
                        stage=f"adf.forward_flow.segment_{i + 1}",
                        reason=gate_reason,
                        action="skipped_empty",
                        model_slot="creative",
                        detail=(
                            f"触发闸门 {[v[0] for v in final_violations]}，"
                            f"重写 1 次后仍违规，该段留空"
                        ),
                    )
                segment_text = ""

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

        # Agent Loop 1：段定稿后抽取新状态卡（末段不抽——没人用；
        # 空段不抽；任何失败在 extract_state_card 内部降级保留旧卡）
        if enable_state_tracker and segment_text and i < total_segments - 1:
            state_card = await extract_state_card(
                prev_card=state_card,
                segment_text=segment_text,
                registry=name_registry,
                recorder=recorder,
                segment_index=i,
            )

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
