# Velluma - stitch-ghost 上下文装配共享器（P5 B2 · AI 所见预览）
# AGPL-3.0
"""
stitch-ghost 的上下文装配段（单一装配源，docs/foundation-hardening.md §2.1）。

设计意图（防漂移红线）：此前装配逻辑内联在 stitch-ghost 路由里，预览只能
平行实现一份——「看到的是一套、注入的是另一套」。抽出为独立函数后，
stitch 路由与 GET /adaptive/context-preview 共用同一函数，预览与真实注入
保证同源；块渲染再下沉一层到 adaptive_prompts.render_system_blocks（四
builder 与预览共用），注入序只有一处定义。

内容（自 stitch 路由逐字迁移，行为逐字节不变）：
- load_chapter_settings_bundle（章级绑定 + Canon + 世界观 + world 桥接）
- proper_nouns / chapter_intent（请求值 or 大纲就近节拍兜底——只给接下来
  一两拍，防整章地图诱导冲章；2026-08-25 实测修复，原为前 200 字截断）
- 前情召回 recall_memories（query：open=大纲，其余=正文尾部150字+碎片）
- 文风执行层 render_style_positive + retrieve_author_samples（few-shot）

副作用：无写入（纯查询 + 只读检索）。任何子步骤失败均由下游各自降级为空，
不阻塞生成（见各模块降级契约）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.context.budget import (
    AUTHOR_SAMPLES_K_BURST,
    AUTHOR_SAMPLES_MAX_K,
    ECHOES_K_STITCH,
    STITCH_INTENT_OUTLINE_MAX_CHARS,
    STITCH_RECALL_QUERY_TAIL_CHARS,
)
from backend.services.context.settings_bundle import (
    SettingsBundle,
    load_chapter_settings_bundle,
    render_style_positive,
)
from backend.services.context.knowledge_plane import KnowledgeView, build_knowledge_view, kg_block_kwargs
# 大纲就近节拍共享判据（2026-08-25 实测修复：意图块只给接下来一两拍，防冲章）
from backend.services.adaptive.outline_nearby import outline_nearby
from backend.services.adaptive.paragraph_source import written_text
from backend.services.prompts.adaptive_prompts import (
    render_system_blocks,
    render_system_blocks_with_usage,
)
from backend.services.rag.recall import recall_memories
from backend.services.style.retrieval import retrieve_author_samples, retrieve_author_samples_with_meta
from backend.services.style.scene_hint import SCENE_HINT_TAIL_CHARS, detect_scene_type


# ============================================================
# 装配结果容器
# ============================================================

@dataclass
class StitchContext:
    """stitch-ghost 一次装配的上下文快照（路由与预览共用）。

    bundle 携带章级/书级全套设定（canon_context / spatial_brief /
    world_time 等直接从 bundle 取），其余字段是装配段产出的检索结果。
    mode（A3b）：装配时的 stitch 档名——system_blocks 据此过模式总预算，
    与四 builder 的真实注入同档同源；空串=不过预算（恒等）。
    """

    bundle: SettingsBundle = field(default_factory=SettingsBundle)
    proper_nouns: List[str] = field(default_factory=list)
    chapter_intent: str = ""
    recall_query: str = ""
    memory_echoes: List[str] = field(default_factory=list)
    style_positive: str = ""
    author_samples: List[str] = field(default_factory=list)
    # P5 回流埋点（2026-08-29）：本发注入的样本 id——GHOST_DONE 帧带回前端，
    # ghost_adopt/ghost_discard 事件据此回传，sample_prior 派生采纳先验
    sample_ids: List[str] = field(default_factory=list)
    mode: str = ""
    # C2 场景判定结果（"dialogue"/"general"；默认空串=未装配）——样本检索
    # 加成的输入，预览徽标据此展示（见 _block_source）
    scene_hint: str = ""
    # 知识检索平面 v3.1（docs/knowledge-retrieval-plane.md）：条目化+选择+
    # 完整渲染的知识视图——五模式/dock/预览共同消费，任务平权
    kg: KnowledgeView = field(default_factory=KnowledgeView)

    def _kg_kwargs(self) -> Dict[str, str]:
        """知识视图块参数（system_blocks 与 builder 调用同源同参）。"""
        return kg_block_kwargs(self.kg)

    def system_blocks(self) -> List[tuple]:
        """system 知识块渲染（key, block_text）——与真实 system prompt 逐字节同源。

        块内容 = 五 builder 实际拼进 system prompt 的知识块
        （adaptive_prompts.render_system_blocks 唯一权威，注入序=返回序：
        场景身份→在场实体→canon→私有→世界观→关系→禁词→回响→空间→画像→样本）。
        ⚠ A1 接线契约：stitch 路由侧 builder 调用需同传
        character_secrets=bundle.character_secrets 与 kg 块参数才与预览完全同源。
        """
        return render_system_blocks(
            style_positive=self.style_positive,
            author_samples=self.author_samples,
            proper_nouns=self.proper_nouns,
            canon_context=self.bundle.canon_context,
            character_secrets=self.bundle.character_secrets,
            memory_echoes=self.memory_echoes,
            spatial_brief=self.bundle.spatial_brief,
            mode=self.mode,
            **self._kg_kwargs(),
        )

    def system_blocks_with_usage(self) -> tuple:
        """知识块渲染 + A3b 配额使用明细（build_context_preview 预算条数据源）。

        与 system_blocks 同一渲染函数（同源红线），只是带回 allocate 的
        usages；mode 无预算档时 usages=None（预览侧降级为不显示预算条）。
        """
        return render_system_blocks_with_usage(
            style_positive=self.style_positive,
            author_samples=self.author_samples,
            proper_nouns=self.proper_nouns,
            canon_context=self.bundle.canon_context,
            character_secrets=self.bundle.character_secrets,
            memory_echoes=self.memory_echoes,
            spatial_brief=self.bundle.spatial_brief,
            mode=self.mode,
            **self._kg_kwargs(),
        )


# ============================================================
# 装配主入口（stitch 路由与 context-preview 共用）
# ============================================================

def _nearby_intent_from_outline(bundle: SettingsBundle) -> str:
    """章节意图兜底：大纲就近节拍（接下来一两拍原文，换行连接）。

    2026-08-25 实测修复：旧兜底是「大纲前 200 字粗暴截断」——整章剧情地图
    喂给轻量续写，模型直奔终点（冲章），且截断落在半截词（真实 trace 实证）。
    现在只给未写的就近一两拍（dock 挂件就近铁律的同源推广）；无大纲 /
    全部已写（章近尾声）→ 空串，意图块整块缺席（零变化契约）。
    """
    outline = getattr(bundle, "outline_text", "") or ""
    if not outline.strip():
        return ""
    beats = outline_nearby(outline, written_text(bundle.content_text or ""))
    return "\n".join(beats)


async def assemble_stitch_context(
    chapter_id: str,
    mode: str,
    fragment: str,
    rolling_prefix: str,
    db: AsyncSession,
    chapter_intent: str = "",
    drift_anchor: bool = False,
) -> StitchContext:
    """装配 stitch-ghost 的全套上下文（五模式共用，行为与旧路由内联段一致）。

    Args:
        chapter_id: 章节 ID
        mode: stitch|continue|burst|outline|open（open 的召回 query 走大纲）
        fragment: 作者原句碎片（outline 模式=细纲速记原文；预览传空串）
        rolling_prefix: 已写正文尾部（前端纯文本；预览由路由剥 HTML 后给）
        db: 异步 DB session
        chapter_intent: 请求携带的章节意图（空=大纲就近节拍兜底，见
            _nearby_intent_from_outline）

    Returns:
        StitchContext：装配快照。任何子查询失败由 bundle/检索层各自降级为空。
    """
    bundle = await load_chapter_settings_bundle(chapter_id, db)
    proper_nouns = bundle.proper_nouns()
    resolved_intent = chapter_intent or _nearby_intent_from_outline(bundle)

    # 前情召回（记忆倒灌·检索侧）：query = 当前写作上下文；open 模式无正文用大纲。
    # 降级为空列表时 prompt 零变化（不阻塞生成）
    if mode == "open":
        recall_query = bundle.outline_text[:STITCH_INTENT_OUTLINE_MAX_CHARS]
    else:
        recall_query = ((rolling_prefix or "")[-STITCH_RECALL_QUERY_TAIL_CHARS:] + " " + fragment.strip()).strip()
    memory_echoes = await recall_memories(
        db,
        book_id=bundle.book_id or "",
        chapter_id=chapter_id,
        chapter_number=bundle.chapter_number,
        query_text=recall_query,
        k=ECHOES_K_STITCH,
    )

    # 文风执行层（S2 E1/E2）：正面画像 + few-shot 笔迹示范注入全部四模式。
    # 检索锚 = 记忆召回同一 query（当前写作上下文）；无样本/无文风卡 → 空，
    # prompt 零变化（不阻塞生成）
    # C2 场景匹配：rolling_prefix 尾 300 字判两档——dialogue 时同型样本检索
    # 加成；general/空 → 检索行为与无 hint 逐一致（零变化契约）
    # C3 burst 样本加量（docs/foundation-hardening.md §5.3）：走向卡连写是
    # 段落级生成，范例权重最高 → burst 档 k=3；其余四模式维持 k=2（零变化）。
    # 预算连锁在 budget.MODE_CONTEXT_BUDGETS["burst"]（已同步上调，满配不裁剪）
    style_positive = render_style_positive(bundle.style_card)
    scene_hint = detect_scene_type((rolling_prefix or "")[-SCENE_HINT_TAIL_CHARS:])
    samples_k = AUTHOR_SAMPLES_K_BURST if mode == "burst" else AUTHOR_SAMPLES_MAX_K
    author_samples: List[str] = []
    sample_ids: List[str] = []
    if bundle.book_id:
        # P5/P6 选择平面（2026-08-29）：meta 变体带回样本 id（回流埋点），
        # 并把文风卡传入——旋钮/对话目标编译为样本排序条件；drift_anchor
        # 时收藏样本获加成（漂移检出 → 作者认证示范优先）
        pairs = await retrieve_author_samples_with_meta(
            db, bundle.book_id, recall_query, k=samples_k,
            scene_hint=scene_hint,
            style_card=bundle.style_card,
            drift_anchor=drift_anchor,
        )
        sample_ids = [sid for sid, _t in pairs]
        author_samples = [t for _sid, t in pairs]

    # 知识检索平面 v3.1：条目化→选择→完整渲染（纯 CPU 零新增查询；失败
    # 降级空视图=块缺席=零变化，不阻塞装配）
    try:
        kg = build_knowledge_view(bundle)
    except Exception:
        kg = KnowledgeView()

    return StitchContext(
        bundle=bundle,
        proper_nouns=proper_nouns,
        chapter_intent=resolved_intent,
        recall_query=recall_query,
        memory_echoes=memory_echoes,
        style_positive=style_positive,
        author_samples=author_samples,
        sample_ids=sample_ids,
        mode=mode,
        scene_hint=scene_hint,
        kg=kg,
    )


# ============================================================
# 预览载荷（B2 §2.1 JSON 契约）
# ============================================================

# 块 key → 展示标题（与 builder 块标题同词根；key 与 render_system_blocks 一一对应）
_BLOCK_TITLES = {
    "scene": "场景身份",
    "warm": "本章打算",
    "entities": "在场与相关",
    "proper_nouns": "在场专名",
    "canon": "Canon 图谱",
    "secrets": "私有设定",
    "worldview": "世界观",
    "relations": "人物关系",
    "negative": "禁词约束",
    "echoes": "前情回响",
    "spatial": "空间常识",
    "style_positive": "文风画像",
    "author_samples": "笔迹示范",
}


def _block_source(key: str, bundle: SettingsBundle, scene_hint: str = "") -> str:
    """块来源徽标文案（人话，前端原样展示）。

    走 world 桥接（世界页有实体）与旧章级绑定的来源要能区分——这是
    「设定体检」入口流量：作者据此知道某块的数据录在哪一页。
    """
    if key == "proper_nouns":
        return "世界实体" if bundle.world_sourced else "章级绑定"
    if key == "entities":
        return "知识平面 · " + ("世界实体" if bundle.world_sourced else "章级绑定")
    if key == "scene":
        return "场景钉 + 叙事时刻"
    if key == "warm":
        return "打算 tab · spine（章内冻结）"
    if key == "worldview":
        return "世界页 · 世界观"
    if key == "relations":
        return "世界页 · 关系（t 时刻活跃）"
    if key == "negative":
        return "文风页负面清单 + 系统陈词"
    if key == "canon":
        return "真相层（含私有）" if "[private]" in (bundle.canon_context or "") else "真相层"
    if key == "secrets":
        # A1 私有通道：只可能来自世界实体（旧表 Character 无 visibility 列）
        return "世界实体 · 私有设定"
    if key == "author_samples" and scene_hint == "dialogue":
        # C2 场景判定可见性（B2 §5.2 验收「直读换上了哪条样本」）：对话场景
        # 加成激活时徽标注明；general/空时徽标与旧版逐一致（零变化）
        return "文风样本库 · 对话场景优先"
    return {
        "style_positive": "文风卡",
        "author_samples": "文风样本库",
        "echoes": "记忆召回",
        "spatial": "世界比例尺",
    }.get(key, "")


def _trim_note(entries_total: int, entries_kept: int) -> str:
    """被裁信息人话文案（A3b 预算条旁的「哪块从几条减到几条」）。"""
    if entries_kept <= 0:
        return f"预算超支，整块缺席（原 {entries_total} 条）"
    return f"预算超支，{entries_total} 条 → {entries_kept} 条"


def build_context_preview(ctx: StitchContext, mode: str) -> Dict[str, Any]:
    """把装配快照转成预览 JSON（块序=注入序；空块原样返回，前端显示「未配置」）。

    A3b：每块带 budget_chars（该块配额=budget.BLOCK_CHAR_BUDGETS 常量上限）与
    trimmed（被裁信息；无裁剪省略该键）——预览即调参界面，占用条与被裁事件
    与真实注入同源（system_blocks_with_usage 同一渲染函数）。
    """
    rendered, usages = ctx.system_blocks_with_usage()
    usage_by_key = {u.key: u for u in usages} if usages is not None else {}
    blocks: List[Dict[str, Any]] = []
    for key, content in rendered:
        block: Dict[str, Any] = {
            "key": key,
            "title": _BLOCK_TITLES.get(key, key),
            "content": content,
            "chars": len(content),
            "source": _block_source(key, ctx.bundle, ctx.scene_hint),
            "budget_chars": usage_by_key[key].budget_chars if key in usage_by_key else 0,
        }
        usage = usage_by_key.get(key)
        if usage is not None and usage.trimmed:
            block["trimmed"] = _trim_note(usage.entries_total, usage.entries_kept)
        blocks.append(block)
    return {
        "mode": mode,
        "blocks": blocks,
        "total_chars": sum(b["chars"] for b in blocks),
        "world_time": ctx.bundle.world_time,
        "world_time_source": ctx.bundle.world_time_source,
        "world_sourced": ctx.bundle.world_sourced,
        # 知识平面审计面（v3.1 §5 纠正回路②）：未选清单含原因——完备性
        # 从暗箱变成可审计、可申诉；前端未消费前为向后兼容增量字段
        "unselected": ctx.kg.unselected[:60],
        "selected_keys": ctx.kg.selected_keys[:60],
    }
