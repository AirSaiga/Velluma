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
上下文引擎（Context Engine）- Phase 1 CP1.3 核心新建。

职责（蓝图 §4.3）：
- 为每次 LLM 起草调用组装 P0/P1/P1'/P2 四级 prompt 布局
- P0/P1 在 __init__ 冻结，跨拍字节级稳定（吃 prompt 缓存）
- P1'/P2 每次 build，承载拍级动态
- 预算控制：超额时按 P2→P1'→P1 优先级裁剪（P0 永不裁剪）

布局规范：
    system_prompt = P0_static_prefix + P1_chapter_block + P1'_beat_block
    user_prompt   = P2_dynamic_block
这样跨拍共享 P0+P1（本章前缀），缓存命中率最大化（调研报告估算 ~65% 复用）。

双通道召回（蓝图 §4.3.1）：
- 确定性通道：扫描 beat.pov_character / red_lines 中的角色名 → 强制注入对应角色状态卡
- 语义通道：调用方传入 loader.py 的 relevant_memories，由本引擎注入 P2

业务场景：
    engine = ContextEngine(book, chapter, entities, open_hooks, ...)
    for beat in beats:
        sys_p, usr_p = engine.build_draft_prompt(beat, previous_tail, sketch_segment, ...)

依赖项：
- backend.services.workflows.context_blocks：复用 Phase 0 T4 的渲染器
"""

import logging
from typing import Any, Dict, List, Optional

from backend.services.workflows.context_blocks import (
    MAX_CHARACTER_STATIC_LEN,
    MAX_OPEN_HOOKS,
    MAX_GOLDEN_SNIPPETS,
    MAX_GOLDEN_SNIPPET_LEN,
    MAX_SNAPSHOT_LEN,
    render_character_cards_block,
    render_open_hooks_block,
    render_world_snapshot_block,
    render_golden_snippets_block,
    render_author_intent_block,
)

logger = logging.getLogger(__name__)


# ============================================================
# 预算配置（蓝图 §8.3 每章预算表，CP1 简化为字符预算）
# ============================================================

# 各层字符预算（中文 1 字 ≈ 1.5 token，按字符控制更直观）
P0_BUDGET_CHARS = 2500       # 身份 + 文风卡 + 设定摘要 + 作者样本
P1_CHAPTER_BUDGET_CHARS = 2500   # 章节 purpose + 本章角色静态设定 + 开放伏笔
P1_BEAT_BUDGET_CHARS = 1200      # 本拍涉及角色动态状态 + 本拍红线
P2_BUDGET_CHARS = 2200           # BeatSpec + 滚动尾巴 + 速写片段 + 即时指令


# ============================================================
# 预算裁剪工具
# ============================================================

def _trim_to_budget(text: str, budget: int, label: str = "") -> str:
    """超预算时尾部截断 + 加省略号标记。"""
    if len(text) <= budget:
        return text
    trimmed = text[:budget].rstrip()
    if label:
        logger.info(f"[ContextEngine] {label} 超预算裁剪: {len(text)} → {budget} 字符")
    return trimmed + "…[裁剪]"


# ============================================================
# ContextEngine 主体
# ============================================================

class ContextEngine:
    """为每次起草调用组装 P0/P1/P1'/P2 四级 prompt（蓝图 §4.3）。

    使用模式：
        engine = ContextEngine(book, chapter, entities, open_hooks,
                                previous_world_snapshot, author_intent)
        # 此时 P0 + P1 已冻结为 self._chapter_prefix
        for i, beat in enumerate(beats):
            sys_p, usr_p = engine.build_draft_prompt(
                beat=beat,
                beat_index=i + 1,
                previous_tail=rolling_tail,
                sketch_segment=sketch_segments[i].text if sketch_segments else None,
                physical_state_lock=lock,
                extra_instruction=fail_fast_hint,
            )

    设计要点：
    - P0 + P1 在 __init__ 拼好并冻结（本章前缀，跨拍字节级稳定）
    - build_draft_prompt 只拼 P1' + P2（拍级动态），保证前缀稳定
    - 双通道召回：关键词触发由 _deterministic_recall 完成；
      语义通道结果由调用方通过 relevant_memories 参数传入
    """

    def __init__(
        self,
        book: Any,
        chapter: Any,
        entities: Optional[List[Any]] = None,
        relationships: Optional[List[Any]] = None,
        open_hooks: Optional[List[dict]] = None,
        previous_world_snapshot: Optional[Any] = None,
        author_intent: Optional[str] = None,
        relevant_memories: Optional[List[Any]] = None,
        style_card: Optional[Any] = None,
        chapter_card: Optional[Any] = None,
    ):
        """初始化并冻结 P0 + P1 章节前缀。

        Args:
            book: Book ORM 对象（取 global_sys_prompt / worldview_settings / genre /
                  golden_snippets / core_motifs_taboos）
            chapter: Chapter ORM 对象（取 chapter_name / chapter_goals /
                   outline_text / author_intent / pacing_style / tension_level）
            entities: ChapterEntity 列表（含 .character 关联）
            relationships: 角色关系列表（CP1.3 暂不强消费，留 P1 备用）
            open_hooks: 开放伏笔列表
            previous_world_snapshot: 前章世界快照（仅首拍注入 P1'）
            author_intent: 作者意图文本（CP1.3 注入 P1，作为本章高优先级指令）
            relevant_memories: RAG 语义检索结果（loader.load_relevant_memories 产出）
            style_card: 可选 StyleCard ORM 对象（CP2.2d 接入）
            chapter_card: 可选 ChapterCard ORM 对象（CP2.3e 接入）：
                        - purpose: 一句话主旨（CP2.3 优先用作 P1 章级块数据源）
                        - must_hit_events: 必达事件
                        无传入时 fallback 到 chapter.chapter_goals + author_intent
        """
        self.book = book
        self.chapter = chapter
        self.entities = entities or []
        self.relationships = relationships or []
        self.open_hooks = open_hooks or []
        self.previous_world_snapshot = previous_world_snapshot
        self.relevant_memories = relevant_memories or []
        # CP2.2d：StyleCard 在 __init__ 冻结（与 P0 同期，不破坏跨拍前缀）
        self.style_card = style_card
        # CP2.3e：ChapterCard 在 __init__ 冻结（与 P1 同期）
        self.chapter_card = chapter_card

        # 章节元信息（P1 用，CP2.3 优先读 chapter_card，fallback 到 Chapter 字段）
        self._chapter_purpose = self._derive_chapter_purpose(chapter, author_intent, chapter_card)

        # 冻结 P0 + P1（本章生成会话内不变，跨拍共享）
        self._p0_block = self._build_p0(book, chapter)
        self._p1_chapter_block = self._build_p1_chapter(book, chapter, author_intent)

        # 构建角色查找索引（用于双通道召回的确定性通道）
        self._character_by_name: Dict[str, Any] = {}
        self._character_aliases: Dict[str, Any] = {}
        for ent in self.entities:
            char = getattr(ent, "character", None)
            if char is None:
                continue
            name = (getattr(char, "name", "") or "").strip()
            if name:
                self._character_by_name[name] = char
            # 别名索引（Character.aliases）
            for alias in (getattr(char, "aliases", None) or []):
                if isinstance(alias, str) and alias.strip():
                    self._character_aliases[alias.strip()] = char

        logger.info(
            f"[ContextEngine] 初始化完成：P0={len(self._p0_block)}字 "
            f"P1={len(self._p1_chapter_block)}字 "
            f"purpose={len(self._chapter_purpose)}字 "
            f"角色索引={len(self._character_by_name)}个 "
            f"style_card={'有' if style_card else '无'} "
            f"chapter_card={'有' if chapter_card else '无'}"
        )

    # ============================================================
    # 公共入口
    # ============================================================

    def build_draft_prompt(
        self,
        beat: dict,
        beat_index: int,
        previous_tail: str = "",
        sketch_segment: Optional[str] = None,
        physical_state_lock: str = "",
        extra_instruction: str = "",
        tier: str = "TIER_2_STANDARD",
        target_words: int = 500,
    ) -> tuple[str, str]:
        """组装单拍起草 prompt。

        Args:
            beat: Beat 字典（含 summary / pov_character / location / red_lines /
                  entry_state / exit_state / pacing_type 等）
            beat_index: Beat 序号（1-based）
            previous_tail: 前拍末尾文本（Rolling Prefix，约 300 字）
            sketch_segment: 本拍对应的速写骨架片段（CP1.2 segments[i].text）
            physical_state_lock: 物理状态锁（exit_state 累积）
            extra_instruction: 即时指令（fail_fast 的 pending_hint / countdown）
            tier: TIER_1_FAST / TIER_2_STANDARD / TIER_3_FORTRESS
            target_words: 目标字数

        Returns:
            tuple: (system_prompt, user_prompt)
        """
        pov_character = beat.get("pov_character", "") or ""

        # ---- P1'：拍级半静态（本拍涉及角色动态状态 + 本拍红线 + 首拍的世界快照） ----
        p1_beat = self._build_p1_beat(
            beat=beat,
            beat_index=beat_index,
            pov_character=pov_character,
            physical_state_lock=physical_state_lock,
        )

        # ---- P2：动态尾部（BeatSpec + 滚动尾巴 + 速写片段 + 语义记忆 + 即时指令） ----
        p2_block = self._build_p2(
            beat=beat,
            beat_index=beat_index,
            pov_character=pov_character,
            previous_tail=previous_tail,
            sketch_segment=sketch_segment,
            extra_instruction=extra_instruction,
            target_words=target_words,
        )

        # ---- 拼接：system = P0 + P1 + P1'，user = P2 ----
        system_prompt = (
            self._p0_block
            + "\n" + self._p1_chapter_block
            + ("\n" + p1_beat if p1_beat else "")
        )
        user_prompt = p2_block

        return system_prompt, user_prompt

    # ============================================================
    # P0：静态前缀（跨章稳定，吃缓存）
    # ============================================================

    def _build_p0(self, book: Any, chapter: Any) -> str:
        """身份 + 文风卡（正负清单） + 书级设定摘要 + 作者样本 few-shot。

        CP2.2d：优先用 StyleCard（正面画像 + 负面清单）。
        无 StyleCard 时 fallback 到 golden_snippets（向下兼容）。
        """
        parts: List[str] = []

        # 1. 角色定位（用 global_sys_prompt 作基线）
        global_sys = (getattr(book, "global_sys_prompt", "") or "").strip()
        if not global_sys:
            global_sys = "你是一位技艺精湛的小说家。"
        parts.append(global_sys)

        # 2. 书级设定摘要（worldview_settings 是 JSONB，转紧凑文本）
        worldview = getattr(book, "worldview_settings", None) or {}
        if isinstance(worldview, dict) and worldview:
            import json
            worldview_text = json.dumps(worldview, ensure_ascii=False)
            if len(worldview_text) > 400:
                worldview_text = worldview_text[:400] + "…"
            parts.append(f"【书级设定】\n{worldview_text}")

        # 3. 主题/禁忌（core_motifs_taboos 是 Text）
        taboos = (getattr(book, "core_motifs_taboos", "") or "").strip()
        if taboos:
            parts.append(f"【主题与禁忌】\n{taboos[:400]}")

        # 4. CP2.2d：文风卡（优先 StyleCard，fallback 到 book 字段）
        if self.style_card is not None:
            style_block = self._render_style_card_block(self.style_card)
            if style_block:
                parts.append(style_block)
            # StyleCard 已含正面画像与负面清单，不再额外渲染 book 字段
            # 但作者样本（golden_snippets）仍可作为 few-shot 补充
            snippets_block = render_golden_snippets_block(getattr(book, "golden_snippets", None) or [])
            if snippets_block:
                parts.append(snippets_block)
        else:
            # Fallback：Phase 0 的 golden_snippets（书级黑名单读点已随双写收敛
            # 删除——历史数据已迁移并入 StyleCard.negative_list，该列冻结恒空）
            snippets_block = render_golden_snippets_block(getattr(book, "golden_snippets", None) or [])
            if snippets_block:
                parts.append(snippets_block)

        # 拼接并裁剪到预算
        joined = "\n\n".join(p for p in parts if p and p.strip())
        return _trim_to_budget(joined, P0_BUDGET_CHARS, "P0")

    def _render_style_card_block(self, style_card: Any) -> str:
        """渲染 StyleCard 为 P0 文风卡段（蓝图 §4.4）。"""
        parts: List[str] = []

        # 正面画像
        positive = getattr(style_card, "positive_profile", None) or {}
        if isinstance(positive, dict) and positive:
            lines = ["【文风画像·正面】（请严格模仿以下特征）"]
            for key, value in positive.items():
                if not value:
                    continue
                value_str = str(value)[:150]
                lines.append(f"- {key}：{value_str}")
            parts.append("\n".join(lines))

        # 负面清单（每条含替代规则）
        negative = getattr(style_card, "negative_list", None) or []
        if isinstance(negative, list) and negative:
            lines = ["【文风画像·负面】（严禁以下措辞，括号内为替代规则）"]
            for item in negative[:15]:  # 限 15 条
                if isinstance(item, dict):
                    word = item.get("word") or item.get("phrase") or ""
                    alt = item.get("alternative") or ""
                    if word:
                        line = f"- {word}"
                        if alt:
                            line += f"（→ {alt[:80]}）"
                        lines.append(line)
                elif isinstance(item, str):
                    lines.append(f"- {item}")
            parts.append("\n".join(lines))

        # 量化指标
        dialogue_target = getattr(style_card, "dialogue_ratio_target", None)
        paragraph_rhythm = getattr(style_card, "paragraph_rhythm", None)
        metric_lines = []
        if dialogue_target is not None:
            try:
                metric_lines.append(f"对话占比目标：{float(dialogue_target)*100:.0f}%")
            except (TypeError, ValueError):
                pass
        if paragraph_rhythm:
            metric_lines.append(f"段落节奏：{str(paragraph_rhythm)[:80]}")
        if metric_lines:
            parts.append("【文风量化指标】\n" + "\n".join(metric_lines))

        return "\n\n".join(p for p in parts if p and p.strip())

    # ============================================================
    # P1：章级块（章内稳定，吃缓存）
    # ============================================================

    def _build_p1_chapter(self, book: Any, chapter: Any, author_intent: Optional[str]) -> str:
        """章节 purpose + 本章涉及角色的【静态设定】+ 开放伏笔。

        设计：本章前缀，跨拍稳定。角色 current_state / dynamic_state 不放这里
        （它们随拍演进，放 P1' 拍级半静态）。
        """
        parts: List[str] = []

        # 1. 章节 purpose（CP1.3 用 Chapter 现有字段做代理，CP2 ChapterCard 落地后切换）
        purpose = self._chapter_purpose
        if purpose:
            parts.append(f"【本章主旨】\n{purpose}")

        # 2. 章节大纲（outline_text，给本章定调）
        outline = (getattr(chapter, "outline_text", "") or "").strip()
        if outline:
            outline_text = outline[:500] + ("…" if len(outline) > 500 else "")
            parts.append(f"【本章大纲】\n{outline_text}")

        # 3. 张力/节奏（轻量数值字段，定调用）
        tension = getattr(chapter, "tension_level", None)
        pacing = getattr(chapter, "pacing_style", None)
        meta_parts = []
        if tension is not None:
            meta_parts.append(f"张力 {tension}/5")
        if pacing:
            meta_parts.append(f"节奏 {pacing}")
        if meta_parts:
            parts.append("（" + "，".join(meta_parts) + "）")

        # 4. 作者意图（高优先级，注入章级让全章贯彻）
        if author_intent:
            intent_block = render_author_intent_block(author_intent)
            if intent_block:
                parts.append(intent_block)

        # 5. 本章角色【静态设定】（不含动态状态，动态留 P1'）
        static_chars_block = self._render_static_characters()
        if static_chars_block:
            parts.append(static_chars_block)

        # 6. 开放伏笔（章内稳定）
        hooks_block = render_open_hooks_block(self.open_hooks)
        if hooks_block:
            parts.append(hooks_block)

        joined = "\n\n".join(p for p in parts if p and p.strip())
        return _trim_to_budget(joined, P1_CHAPTER_BUDGET_CHARS, "P1_chapter")

    # ============================================================
    # P1'：拍级半静态（每拍变化）
    # ============================================================

    def _build_p1_beat(
        self,
        beat: dict,
        beat_index: int,
        pov_character: str,
        physical_state_lock: str,
    ) -> str:
        """本拍涉及角色【动态状态】 + 本拍红线 + 首拍的世界快照。

        设计：与 P1（章级）物理分离，因为它每拍变化。
        P1（章级）跨拍稳定 → 吃缓存；P1' 每拍变 → 不吃缓存但权重仍较高。
        """
        parts: List[str] = []

        # 1. 物理状态锁（exit_state 累积滚动）
        if physical_state_lock:
            parts.append(f"【角色状态】\n{physical_state_lock}")

        # 2. 首拍：前章世界快照（仅 beat_index==1 注入）
        if beat_index == 1 and self.previous_world_snapshot:
            snapshot_block = render_world_snapshot_block(self.previous_world_snapshot)
            if snapshot_block:
                parts.append(snapshot_block)

        # 3. 本拍涉及角色的动态状态（双通道召回 - 确定性通道）
        dynamic_state_block = self._deterministic_recall_dynamic_state(beat, pov_character)
        if dynamic_state_block:
            parts.append(dynamic_state_block)

        # 4. 本拍红线（每拍 red_lines 不同，放 P1' 而非 P1）
        red_lines = beat.get("red_lines", []) or []
        if red_lines:
            if isinstance(red_lines, list):
                red_text = "；".join(str(r) for r in red_lines)
            else:
                red_text = str(red_lines)
            parts.append(f"【本拍红线】{red_text[:200]}")

        joined = "\n\n".join(p for p in parts if p and p.strip())
        return _trim_to_budget(joined, P1_BEAT_BUDGET_CHARS, "P1_beat")

    # ============================================================
    # P2：动态尾部（每拍变化，权重最高）
    # ============================================================

    def _build_p2(
        self,
        beat: dict,
        beat_index: int,
        pov_character: str,
        previous_tail: str,
        sketch_segment: Optional[str],
        extra_instruction: str,
        target_words: int,
    ) -> str:
        """BeatSpec + 滚动尾巴 + 速写片段 + 语义记忆 + 即时指令。

        蓝图 §4.3.2 "位置即权重"原则：即时指令放最后，权重最高。
        """
        parts: List[str] = []

        # 1. 滚动尾巴（前拍末 300 字）- 蓝图要求靠近生成位置
        if previous_tail:
            tail = previous_tail[-300:] if len(previous_tail) > 300 else previous_tail
            parts.append(f"【前文衔接】\n{tail}")

        # 2. 速写骨架片段（CP1.2 segments[i].text）
        if sketch_segment:
            seg_text = sketch_segment.strip()
            if len(seg_text) > 600:
                seg_text = seg_text[:600] + "…"
            parts.append(f"【本拍骨架参考】（仅供连贯性参考）\n{seg_text}")

        # 3. 语义记忆（RAG top-k，由调用方传入）
        if self.relevant_memories:
            memory_texts = []
            for m in self.relevant_memories[:3]:  # 限 3 条
                text = ""
                if isinstance(m, dict):
                    text = m.get("chunk_text") or m.get("text") or ""
                else:
                    text = getattr(m, "chunk_text", "") or getattr(m, "text", "") or ""
                if text:
                    memory_texts.append(f"- {text[:150]}")
            if memory_texts:
                parts.append("【相关记忆】\n" + "\n".join(memory_texts))

        # 4. 本拍 BeatSpec（事件 + 场景 + POV + 字数）
        beat_spec_parts = []
        beat_spec_parts.append(f"角色：{pov_character or '未指定'}")
        location = beat.get("location", "") or ""
        if location:
            beat_spec_parts.append(f"场景：{location}")
        summary = beat.get("summary", "") or ""
        if summary:
            beat_spec_parts.append(f"剧情：{summary[:300]}")
        entry_state = beat.get("entry_state", "") or ""
        exit_state = beat.get("exit_state", "") or ""
        if entry_state:
            beat_spec_parts.append(f"入场状态：{entry_state[:100]}")
        if exit_state:
            beat_spec_parts.append(f"退场状态：{exit_state[:100]}")
        beat_spec_parts.append(f"目标字数：约 {target_words} 字")
        parts.append("【本拍情境】\n" + "\n".join(beat_spec_parts))

        # 5. 即时指令（fail_fast 的 pending_hint / 字数提醒等）- 放最后
        if extra_instruction:
            parts.append(extra_instruction.strip())

        # 6. 续写引导（最末，触发模型生成）
        parts.append("请直接输出本拍正文，不要解释，不要 Markdown。")

        joined = "\n\n".join(p for p in parts if p and p.strip())
        return _trim_to_budget(joined, P2_BUDGET_CHARS, "P2")

    # ============================================================
    # 辅助方法
    # ============================================================

    def _derive_chapter_purpose(
        self,
        chapter: Any,
        author_intent: Optional[str],
        chapter_card: Optional[Any] = None,
    ) -> str:
        """推导本章 purpose。

        CP2.3e：优先用 chapter_card.purpose + must_hit_events（合并闸门的核心数据源）。
        Fallback：CP1.3 代理方案（chapter.chapter_goals + author_intent）。
        """
        # CP2.3e：优先读章节卡
        if chapter_card is not None:
            parts = []
            purpose = (getattr(chapter_card, "purpose", "") or "").strip()
            if purpose:
                parts.append(purpose)
            must_hit_events = getattr(chapter_card, "must_hit_events", None) or []
            for ev in must_hit_events[:3]:
                if isinstance(ev, dict):
                    event_text = ev.get("event", "")
                    if event_text:
                        parts.append(f"必达：{event_text}")
            if parts:
                return "\n".join(parts)[:500]

        # Fallback：CP1.3 代理方案
        if chapter is None:
            return ""
        parts = []
        goals = getattr(chapter, "chapter_goals", None) or []
        if isinstance(goals, list):
            for g in goals[:3]:
                if isinstance(g, str):
                    parts.append(g)
                elif isinstance(g, dict):
                    text = g.get("goal") or g.get("purpose") or g.get("text") or ""
                    if text:
                        parts.append(text)
        if author_intent:
            parts.append(f"作者意图：{author_intent}")
        return "\n".join(parts)[:500]

    def _render_static_characters(self) -> str:
        """渲染本章涉及角色的【静态设定】（不含动态状态）。"""
        if not self.entities:
            return ""
        # 按 importance 降序取前 5
        chars = []
        for ent in self.entities:
            c = getattr(ent, "character", None)
            if c is not None:
                chars.append(c)
        if not chars:
            return ""
        chars.sort(key=lambda c: getattr(c, "importance_level", 1) or 1, reverse=True)
        chars = chars[:5]

        lines = ["【本章角色设定】（静态部分，不得违背）"]
        for c in chars:
            name = getattr(c, "name", "") or "未命名"
            static = (getattr(c, "static_prompt", "") or "").strip()
            if len(static) > MAX_CHARACTER_STATIC_LEN:
                static = static[:MAX_CHARACTER_STATIC_LEN] + "…"
            if static:
                lines.append(f"- {name}：{static}")
            else:
                lines.append(f"- {name}")
        return "\n".join(lines)

    def _deterministic_recall_dynamic_state(
        self, beat: dict, pov_character: str,
    ) -> str:
        """双通道召回 - 确定性通道：扫描 beat 中提到的角色名 → 注入其动态状态。

        蓝图 §4.3.1：弥补纯向量检索对专有名词的钝感。
        CP1.3 简化版：扫描 pov_character + red_lines 中出现的角色名，
        命中则注入该角色的 current_state / dynamic_state。
        """
        if not pov_character and not self._character_by_name:
            return ""

        # 收集本拍出现的角色名（pov + red_lines 文本扫描）
        mentioned_names = set()
        if pov_character:
            mentioned_names.add(pov_character)
        red_lines = beat.get("red_lines", []) or []
        red_text = " ".join(str(r) for r in red_lines) if isinstance(red_lines, list) else str(red_lines)
        summary_text = beat.get("summary", "") or ""
        scan_text = f"{red_text} {summary_text}"
        for name in self._character_by_name.keys():
            if name and name in scan_text:
                mentioned_names.add(name)
        for alias in self._character_aliases.keys():
            if alias and alias in scan_text:
                char = self._character_aliases[alias]
                mentioned_names.add(getattr(char, "name", ""))

        if not mentioned_names:
            return ""

        # 注入每个被提及角色的动态状态
        lines = ["【本拍涉及角色·动态状态】"]
        for name in mentioned_names:
            if not name:
                continue
            char = self._character_by_name.get(name)
            if char is None:
                continue
            current = (getattr(char, "current_state", "") or "").strip()
            dynamic = (getattr(char, "dynamic_state", "") or "").strip()
            # current_state 优先（从世界快照提取的此刻状态）
            state = current or dynamic
            if state:
                state_text = state[:150] + ("…" if len(state) > 150 else "")
                lines.append(f"- {name}【此刻状态：{state_text}】")

        if len(lines) == 1:
            return ""  # 只有标题行，无内容
        return "\n".join(lines)
