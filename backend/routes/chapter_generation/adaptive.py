# Velluma - NLE-ADF 3.0 自适应辅助路由
# AGPL-3.0
"""
作者主导写作流程的自适应辅助端点（NLE-ADF 3.0）。

核心协议：心跳模式。前端双档防抖发 heartbeat（活跃 3s / 停顿 4s+光标段尾），
后端调度器决定激活哪些组件（意图反推/未来推测/挂件生发/Canon 感知/沉淀/
后处理/候选事件抽取），异步跑、写回世界模型。活跃档下次心跳拿到组件产出；
停顿档同步等 dock/projection/canon 组件，本次响应直接带回挂件。

端点（路径省略前缀 /api/chapters/{chapter_id}，以本文件 @router 装饰器为准）：
- POST /adaptive/heartbeat：作者状态心跳 → 触发调度器 → 返回快照 + 挂件/走向卡/感知带
- POST /adaptive/stitch-ghost：幽灵草稿缝合续写（SSE 五模式 stitch/continue/burst/open/outline）
- POST /adaptive/settle：手动沉淀（Ctrl+Enter）→ 层1追加 + 涌现实体抽取 + 候选事件回流
- POST /adaptive/finish：完稿审计（残句/覆盖率/Canon 合规/整章审阅）
- POST /adaptive/fix-sentence：残句定点修复（作者裁决式，只产修复句不改正文）
- GET/PATCH /adaptive/spine：章级谋篇软脉络（chapters.spine 部分合并）
- POST /adaptive/spine-suggest：谋篇建议（1×creative，产出不落库）
- GET  /adaptive/model：世界模型快照（副驾调试视图）
- GET  /adaptive/context-preview：AI 此刻所见注入预览
- POST /adaptive/event + GET /adaptive/events/summary：协作埋点（本地 jsonl，零上报）

设定数据来源：services.context.settings_bundle（分级访问 hard/soft/nutrients）。
副作用：settle 写设定库（可选）；heartbeat 触发异步组件（写世界模型）。
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from backend.core.dependencies import get_db
from backend.database import AsyncSessionLocal
from backend.models import Chapter
from backend.repositories.world_repository import WorldRepository
from backend.services.adaptive.orchestrator import get_orchestrator
from backend.services.adaptive.change_detector import AuthorState
# P1-2（A4）碎片拼回判定规范化：抹空白共用组件侧同一把规范化尺子
from backend.services.adaptive.paragraph_source import normalize_for_match
# B2（2026-08-25 治理）：spine 锚点进度判定换 text_match 共享判据（勿另写滑窗）
from backend.services.adaptive.text_match import matches as text_matches
# 学着闭嘴（2026-08-25 战略定稿）：心跳提醒静音过滤的唯一权威在 quiet_learning
from backend.services.adaptive.quiet_learning import hint_mute_key, load_muted_keys
# 视野配比（2026-08-25 实测调窗）：滚动窗口句界净截，防窗首半截句误导续写锚点
from backend.services.adaptive.paragraph_source import sentence_clean_tail
# 就近节拍共享判据：点火剂量闸（open 只给开头一两拍）与意图块兜底同消费
from backend.services.adaptive.outline_nearby import outline_nearby
from backend.services.adaptive.observing import (
    bind_adaptive_trace,
    flush_adaptive_records,
    get_adaptive_recorder,
)
from backend.services.adaptive.world_model import WorldModelRepository
from backend.services.context.settings_bundle import load_chapter_settings_bundle
from backend.services.context.stitch_context import (
    assemble_stitch_context,
    build_context_preview,
)
# A3a 截断常量收敛（docs/foundation-hardening.md §4.1）：stitch 注入剂量改引 budget 表
from backend.services.context.budget import (
    SPINE_SUGGEST_MAX_TOKENS,
    STITCH_AFTER_TEXT_MAX_CHARS,
    STITCH_OUTLINE_MAX_CHARS,
    STITCH_ROLLING_LONG_MAX_CHARS,
    STITCH_ROLLING_SHORT_MAX_CHARS,
    STITCH_WORLDVIEW_MAX_CHARS,
)
from backend.services.llm.client import REASONING_DISABLED, call_llm_with_usage
from backend.services.prompts.adaptive_prompts import (
    build_burst_prompt,
    build_continue_prompt,
    build_opening_prompt,
    build_outline_expand_prompt,
)
# C1 上屏前快检（P5 §5.1）：完整文本生成后纯算法三类疑点（死者开口/canon
# 泄底/私有秘密外泄），随 GHOST_DONE 附 warnings——只提示不拦截（§9 红线）
from backend.services.validation.ghost_guard import check_ghost_text
from backend.services.observability.run_trace import trace_event
from backend.services.utils.logging import get_runtime_logger
from backend.services.utils.sse import build_sse_event, build_sse_error

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["adaptive"])


# ============================================================
# 细纲扩写字数硬闸门（对齐 bsadf/downgrade 的实测经验：软约束段均超写
# 近 2 倍。细纲的产品承诺是「生成字数不多、改起来轻」，必须硬保证。
# SSE 先生成后播放 → 压缩重试/截断对前端完全透明）
# ============================================================

OUTLINE_WC_HARD_RATIO = 1.6      # 超过 target×1.6 → 带压缩反馈重试一次
OUTLINE_WC_TRUNCATE_RATIO = 1.5  # 仍超 → 句界硬截断（截断上限必须 ≤ HARD）

# stitch LLM 预算下限（C2，P1-4）：deepseek 类推理模型即使传 REASONING_DISABLED
# 仍烧 ~800-1000 隐藏思考 tokens，1200 下限时正文余量太薄 → 「续写产出为空」；
# 抬到 2200 给隐藏推理留足死余量。纯上限放宽——非推理模型产出短于上限不多花。
STITCH_MAX_TOKENS_FLOOR = 2200


def _truncate_at_sentence(text: str, limit: int) -> str:
    """句界硬截断：在 limit 内找最后一个句末标点切断。

    复制自 bsadf/downgrade._truncate_at_sentence（无依赖纯函数，刻意不
    import bsadf——adaptive 链路不依赖步进流任何设施）。找不到句末标点
    （极端长句）退化为按字截断：字数硬闸门优先级高于单句完整性。
    """
    if len(text) <= limit:
        return text
    cut = max(text.rfind(p, 0, limit) for p in ("。", "！", "？", "…"))
    if cut > 0:
        return text[: cut + 1]
    return text[:limit]


def _truncate_keep_tail(text: str, limit: int) -> str:
    """保尾截断（P1-1，A3）：末段完整保留，超字从前往后按句界删节到 ≤ limit。

    outline 模式的价值重心在末段——双端锚定的「后端缝合」全靠末段引向
    after_text，现有尾截砍掉的恰是承接段，等于砍掉整次扩写的意义；与旧
    引擎「末段（结局段）豁免截断」护栏思想对齐。仅 outline 字数硬闸使用，
    其他模式维持尾截口径不变。

    退化路径（防死循环）：全文单段（末段即全文）或末段自身 ≥ limit 时，
    已没有「删前保尾」的操作空间，回落现有尾截 _truncate_at_sentence。
    入参契约：text 已 strip（路由侧字数闸前的统一清洗）。
    """
    if len(text) <= limit:
        return text
    # 段落切分保留分隔符形态：[段, 分隔, 段, 分隔, 末段]
    parts = re.split(r"(\n+)", text)
    if len(parts) < 3 or not parts[-1]:
        return _truncate_at_sentence(text, limit)
    sep, tail = parts[-2], parts[-1]
    if len(tail) + len(sep) >= limit:
        # 末段自身超限：保不住，回落尾截
        return _truncate_at_sentence(text, limit)
    head = "".join(parts[:-2])
    head_limit = limit - len(tail) - len(sep)
    if len(head) <= head_limit:
        return text
    # 从前往后找最早能装进 head_limit 的句界：head[:p] 整句让位（删最少句数
    # 优先）；找不到（前段末句是超长单句）则整个前段让位、只留末段
    for i, ch in enumerate(head):
        if ch in ("。", "！", "？", "…") and len(head) - (i + 1) <= head_limit:
            return head[i + 1:] + sep + tail
    return tail


# ============================================================
# 碎片拼回判定规范化（P1-2，A4）
# ============================================================
# 模型常在「已把作者碎片复述进产出」时换了同类标点/夹了空白（「他握紧刀。」
# →「他握紧刀 !」）——裸子串 `fragment in text` 会误判「不含」，把作者原句
# 再拼回句首造成开头重复。判定口径：抹全部空白（normalize_for_match，与
# 组件侧同一把尺子）+ 标点折叠为等价类；字符内容（语义）变了仍判不含。
_PUNCT_FOLD = str.maketrans({
    # 句末等价类：句/叹/问/省略（全半角）视为同一种「一句终了」
    "。": ".", "．": ".", ".": ".",
    "！": ".", "!": ".", "？": ".", "?": ".", "…": ".",
    # 停顿等价类：逗/顿/分号
    "，": ",", ",": ",", "、": ",", "；": ",", ";": ",",
    # 冒号
    "：": ":", ":": ":",
    # 引号/括号
    "“": "\"", "”": "\"", "\"": "\"",
    "‘": "'", "’": "'", "'": "'", "「": "'", "」": "'", "『": "'", "』": "'",
    "（": "(", "(": "(", "）": ")", ")": ")",
    # 破折号
    "—": "-", "－": "-", "―": "-", "-": "-",
})


def _contains_fragment(text: str, fragment: str) -> bool:
    """stitch 碎片复述判定（规范化）：抹空白 + 标点折叠等价类后的子串命中。

    只容纳「模型已复述碎片」的形态微差（标点/空白变体）；字符内容变了
    （加字/换词，如「他握紧刀」→「他握紧了刀」）仍判不含。
    """
    key = normalize_for_match(fragment).translate(_PUNCT_FOLD)
    if not key:
        return True  # 空碎片按已含处理（路由层已有 fragment 真值门，防御位）
    return key in normalize_for_match(text).translate(_PUNCT_FOLD)


def _strip_fragment_prefix(text: str, fragment: str) -> str:
    """剥离模型复读的原句前缀（追加式幽灵契约，2026-08-26 实测修复）。

    幽灵是纯追加插入（光标后落文档），作者原句已在画布里——模型若把原句
    再吐回来（含标点/空白变体），屏幕上会出现「原句 + 幽灵复读原句 + 续写」
    的重复。此处把复读前缀剥掉，只留纯续写；语义变体（换词/加字）不是复读，
    不剥（旧拼回判定的等价类口径，_contains_fragment 同款规范化）。
    """
    frag = (fragment or "").strip()
    if not frag:
        return text
    if text.startswith(frag):
        return text[len(frag):].lstrip()
    key = normalize_for_match(frag).translate(_PUNCT_FOLD)
    if not key:
        return text
    acc: list = []
    for i, ch in enumerate(text):
        n = normalize_for_match(ch).translate(_PUNCT_FOLD)
        if not n:
            continue
        acc.append(n)
        joined = "".join(acc)
        if joined == key:
            return text[i + 1:].lstrip()   # 等价复读完整复现原句 → 剥到此处
        if len(joined) > len(key):
            break                            # 内容已偏离原句 → 不是复读
    return text


# ============================================================
# Schemas
# ============================================================

class HeartbeatRequest(BaseModel):
    word_count: int = 0
    segment_count: int = 0
    paused_ms: int = 0
    cursor_at_paragraph_end: bool = False
    has_outline: bool = False
    outline_text: str = ""
    recent_text: str = Field("", description="当前段落尾部（≤500字）")
    summoned: bool = Field(False, description="Tab 显式点名要零件（豁免句子级闸门）")


class HeartbeatResponse(BaseModel):
    dock_parts: List[Dict] = Field(default_factory=list)
    # 句子级闸门触发位（2026-08-26）：True=作者半句悬停，挂件应静默——前端据此
    # 清舱收卡（区别于 dock_parts 空但可保留旧件供 Tab 的常态）
    dock_muted: bool = False
    direction_cards: List[Dict] = Field(default_factory=list)  # 走向卡（层3推测首 beat：event+anchors）
    intent_source: str = "none"
    intent_arc: str = ""
    intent_confidence: float = 0.0
    fact_count: int = 0
    total_words: int = 0
    activated: List[str] = Field(default_factory=list)
    signals: List[str] = Field(default_factory=list)
    canon_hints: List[Dict] = Field(default_factory=list)  # Canon 感知（角色出场/伏笔回收/private 泄露），canon_watch 写入
    # 世界数据版本（写作页切片条保鲜比对；路由层附带，查询失败为 None）
    world_version: Optional[Dict] = Field(None)
    # 章级谋篇进度（P1.4 M2）：无脉络/无锚点为 None（感知带进度行静默缺席）
    spine_progress: Optional[Dict] = Field(None)
    # P3-1（C5）组件失败可见化：最近一次失败的辅助组件（组件名 → 秒级时间戳 +
    # 一行错误摘要；成功即清）。空 dict = 一切正常（增量字段，旧前端忽略无碍）
    last_component_errors: Dict[str, Dict] = Field(default_factory=dict)


class SettleRequest(BaseModel):
    text: str = Field(..., description="锁死的段落正文")
    entities: List[Dict] = Field(default_factory=list, description="本段涌现的实体（前端可预填）")
    commit: bool = Field(False, description="是否落库涌现实体")


class StitchGhostRequest(BaseModel):
    fragment: str = Field(..., description="作者原句碎片（outline 模式=细纲速记原文）")
    rolling_prefix: str = Field("")
    mode: str = Field("stitch", description="stitch|continue|burst（段落级连写）|outline（细纲扩写）|open（点火）")
    picked_parts: List[str] = Field(default_factory=list)
    target_chars: int = 120
    chapter_intent: str = Field("")
    beat_guidance: str = Field("", description="burst 模式：选定走向卡的走向文本（空=自由发挥）")
    after_text: str = Field("", description="outline 模式：细纲之后的已写正文开头（双端缝合用，可空）")
    adopted_direction: Optional[str] = Field(None, description="作者缝合采纳的叙事方向（主线/伏笔/刻画/环境/关系），用于负反馈降权")
    serves_anchor: str = Field("", description="outline 模式：胶囊挂的谋篇锚点文本（M3 三锚定；空=双端锚定不变）")


# ============================================================
# 端点 1：heartbeat — 作者状态心跳
# ============================================================

@router.post("/{chapter_id}/adaptive/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    chapter_id: str,
    request: HeartbeatRequest,
    db: AsyncSession = Depends(get_db),
):
    """作者状态心跳 → 触发调度器（异步激活组件）→ 返回当前快照 + 挂件。

    前端双档防抖发（活跃 3s / 停顿 4s，见 useAdaptiveAssist.ts）。活跃档组件
    异步跑、下次心跳拿到产出；停顿档（paused_ms ≥4000）同步等 dock/projection/
    canon 组件，本次响应直接带回挂件。
    """
    bind_adaptive_trace(chapter_id)
    orch = get_orchestrator(chapter_id, lambda: AsyncSessionLocal())
    state = AuthorState(
        chapter_id=chapter_id,
        word_count=request.word_count,
        segment_count=request.segment_count,
        paused_ms=request.paused_ms,
        cursor_at_paragraph_end=request.cursor_at_paragraph_end,
        has_outline=request.has_outline,
        outline_text=request.outline_text,
        recent_text=request.recent_text,
        summoned=request.summoned,
    )
    result = await orch.on_heartbeat(state)
    snapshot = result.get("snapshot", {})

    # 章节对象提前取（谋篇进度/世界版本/漂移提示共用；失败静默 None 不阻塞心跳本体）
    chapter = None
    try:
        chapter = await db.get(Chapter, str(chapter_id))
    except Exception:
        chapter = None

    # 从世界模型拉挂件缓存（dock_generator 写入的 __dock__ 项）
    dock_parts = _extract_dock_parts(snapshot)
    # 句子级闸门（2026-08-25）：作者段落停在半句（无句末标点）时挂件闭嘴——
    # 此刻要的是把句子写完（Space 续写的活），缓存旧件也一并藏起；
    # 空段=段界不判半句（写完一段回车进新段是挂件黄金时机）；
    # Tab 显式点名（summoned）豁免，作者主权优先
    # dock_muted（2026-08-26 实测补强）：此前只清响应不清前端——旧件在舱里
    # 留存（章节恢复兜底/上一轮缓存），作者半句悬停时卡照样在屏。信号位让
    # 前端把「闭嘴」执行到端上：清舱收卡（Tab 点名会带 summoned 重取，无损）。
    from backend.services.adaptive.paragraph_source import ends_mid_sentence
    dock_muted = False
    if ends_mid_sentence(request.recent_text) and not request.summoned:
        dock_parts = []
        dock_muted = True
    # 走向卡（层 3 推测首 beat）——Ctrl+Space 走向卡舱的数据源
    direction_cards = _extract_direction_cards(snapshot, spine=chapter.spine if chapter is not None else None)
    # Canon 感知（canon_watch 写入的 __canon_watch__ 项）
    canon_hints = _extract_canon_hints(snapshot)

    intent = snapshot.get("intent", {})

    # 世界数据版本（写作页切片保鲜比对搭心跳便车；失败静默 None 不阻塞心跳本体）
    world_version = None
    try:
        if chapter is not None:
            world_version = await WorldRepository(db).world_version(str(chapter.book_id))
    except Exception:
        world_version = None

    # 文风漂移轻提示（完整落地批，设计稿 §5 心跳感知通道）：以 kind=style_drift
    # 并入 canon_hints——前端感知带零新增管线直接渲染。纯 code + 按内容长度缓存
    drift_hint = await _style_drift_hint_for_heartbeat(chapter, db)
    if drift_hint:
        canon_hints = list(canon_hints) + [drift_hint]

    # A5c 收件箱积压提醒（P5 §3.2）：全书 pending 候选 >5 条时以 kind=world_inbox
    # 并入 canon_hints——同走感知带柔性通道，不弹窗不抢焦点。短 TTL 缓存防抖
    inbox_hint = await _world_inbox_hint_for_heartbeat(chapter, db)
    if inbox_hint:
        canon_hints = list(canon_hints) + [inbox_hint]

    # 学着闭嘴（2026-08-25 战略定稿）：作者多次收起（感知带 ×）的提醒类别在此静音。
    # 安全类（leak/contradiction）永不进静音集——quiet_learning 白名单保证；
    # 失败静默：学习链路故障不阻塞心跳本体（静音集派生侧已内兜，此处再兜一层）。
    if chapter is not None and canon_hints:
        try:
            _muted_keys = await load_muted_keys(db, str(chapter.book_id))
            if _muted_keys:
                canon_hints = [
                    h for h in canon_hints
                    if hint_mute_key(str((h or {}).get("kind") or "")) not in _muted_keys
                ]
        except Exception:
            pass

    # 章级谋篇进度（P1.4 M2 §4.3）：纯算法零 LLM，宁漏勿误（B2 治理后走
    # text_match 共享判据的全片段命中 + 就近窗口；误报破坏信任，漏报作者自己
    # 划掉即可 + finish 报告兜底）。按内容 hash 缓存；pending→hit 迁移才写库
    spine_progress = await _spine_progress_for_heartbeat(chapter, orch, db)

    # 观测（P0-2）：心跳事件进 chapter 级 trace；顺路冲走累积的组件调用账
    # （含上一次心跳派生的后台组件——它们自开 session，只能靠后续请求落库）
    trace_event(
        "adaptive_heartbeat",
        word_count=request.word_count,
        paused_ms=request.paused_ms,
        activated=result.get("activated", []),
        dock_parts=len(dock_parts),
        direction_cards=len(direction_cards),
        canon_hints=len(canon_hints),
    )
    await flush_adaptive_records(chapter_id)

    return HeartbeatResponse(
        dock_parts=dock_parts,
        dock_muted=dock_muted,
        direction_cards=direction_cards,
        intent_source=intent.get("source", "none"),
        intent_arc=intent.get("arc", ""),
        intent_confidence=intent.get("confidence", 0.0),
        fact_count=snapshot.get("fact_count", 0),
        total_words=snapshot.get("total_words", 0),
        activated=result.get("activated", []),
        signals=result.get("signals", []),
        canon_hints=canon_hints,
        world_version=world_version,
        spine_progress=spine_progress,
        last_component_errors=orch.last_component_errors(),
    )


def _extract_dock_parts(snapshot: Dict) -> List[Dict]:
    """从世界模型快照的 projections 里提取 dock_generator 缓存的挂件。"""
    for proj in (snapshot.get("projections") or []):
        if isinstance(proj, dict) and proj.get("__dock__"):
            return proj.get("parts", [])
    return []


# 文风漂移提示缓存（chapter_id → (content_len, hint|None)）——内容没变不重算
_STYLE_HINT_CACHE: Dict[str, tuple] = {}


# 谋篇进度缓存（chapter_id → (content_md5, progress|None)）——键为内容 hash
# （B2 治理 2026-08-25：旧键=内容长度，等长改写会吃到旧缓存的旧进度）
_SPINE_PROG_CACHE: Dict[str, tuple] = {}


# ---- B2（2026-08-25 治理，docs/adaptive-assist-hardening.md P2）：判定参数 ----
# hit 档阈值=全部滑窗片段命中：hit 是「3 字滑窗」一族三处判定里唯一写库的
# （pending→hit 只前进不回退，不可逆），取最严档。旧判据 jieba topK=3 通用词
# 全命中——「他没有」「不多时」类词几乎必然散落在任何长文本里，大面积误 hit；
# 3 字滑窗片段比 jieba 单词具体得多，全命中可把通用词噪声压到近零。
SPINE_HIT_THRESHOLD = 1.0
# 临近岔路低阈值档（有意保留的宽松提示语义，M3 §5）：1/3 等效「任一~两个
# 片段现身」≈ 旧『任一关键词现身』的提示强度。它只多一张走向卡舱硬提示卡
# （不写库、作者可无视），宽松无害。
SPINE_NEAR_BRANCH_THRESHOLD = 1.0 / 3.0
# 增量区段就近窗口：常规心跳增量几十字；幽灵草稿连写采纳/心跳停跳后一次
# 可能积数千字。封顶 2000（≈ 两轮 burst 连写 700 字 + 一轮打字）覆盖真实
# 增量上限，同时把「大块文本里任意散落拼凑命中」的噪声面封住；窗口外的
# 更早文本属于已判定区段，漏判由 finish 报告 spine_note 兜底（宁漏勿误）。
SPINE_GROWTH_TAIL_CHARS = 2000


def _build_spine_progress(
    spine: Any, anchors: List[Any], near_branches: Optional[List[Dict]] = None,
) -> Dict:
    """进度组装（纯函数）：意图一句话 + 锚点清单 + pending 计数 + 人话 hint。"""
    pending_count = sum(1 for a in anchors if isinstance(a, dict) and a.get("status") == "pending")
    progress = {
        "intent": (spine or {}).get("intent", {}).get("text", ""),
        "anchors": [
            {"id": a.get("id", ""), "text": a.get("text", ""), "status": a.get("status", "pending")}
            for a in anchors if isinstance(a, dict)
        ],
        "pending_count": pending_count,
        "hint": f"还有 {pending_count} 条情节没写到" if pending_count else "打算里的情节都写到了",
    }
    if near_branches:
        progress["near_branches"] = near_branches
    return progress


async def _spine_progress_for_heartbeat(chapter: Any, orch, db: AsyncSession) -> Optional[Dict]:
    """章级谋篇进度判定（P1.4 M2，设计稿 §4.3——纯算法零 LLM）。

    B2 治理（2026-08-25）：判定走 text_match 共享判据（3 字滑窗片段命中率，
    禁止在此另写滑窗逻辑）——hit=全部片段命中**新增区段**（就近窗口内）；
    临近岔路走低阈值档宽松提示。增量区段由 orchestrator 记录的上次正文长度
    推（**首轮只记基线不判定**——进程重启后 growth=全文的大面积误 hit 不可逆，
    宁漏勿误，漏判由 finish 报告 spine_note 兜底；改写收缩退化为尾部 500 字）。
    结果按内容 hash 缓存；pending→hit 迁移才写库（progress 只前进不回退）。
    """
    if chapter is None:
        return None
    cid = str(chapter.id)
    spine = chapter.spine if isinstance(chapter.spine, dict) else None
    anchors = list((spine or {}).get("anchors") or [])
    content = chapter.content_text or ""
    content_md5 = hashlib.md5(content.encode("utf-8")).hexdigest()
    if not anchors:
        orch._last_content_len = len(content)
        _SPINE_PROG_CACHE.pop(cid, None)
        return None

    cached = _SPINE_PROG_CACHE.get(cid)
    if cached is not None and cached[0] == content_md5:
        orch._last_content_len = len(content)
        return cached[1]

    # 首轮（orchestrator 内存态归零——进程重启/重新进章后 _last_content_len=-1）：
    # 只记基线长度，不做 hit 判定。旧行为本轮 growth=全文，通用关键词大面积
    # 误 hit 写库不可逆（hit 只前进不回退）；宁漏勿误——漏判有 finish 报告
    # spine_note 兜底提醒，误判没有出路
    if getattr(orch, "_last_content_len", -1) < 0:
        orch._last_content_len = len(content)
        progress = _build_spine_progress(spine, anchors)
        _SPINE_PROG_CACHE[cid] = (content_md5, progress)
        return progress

    prev_len = orch._last_content_len
    growth = content[prev_len:] if len(content) > prev_len else content[-500:]

    changed = False
    near_branches = []
    try:
        for a in anchors:
            if not isinstance(a, dict) or a.get("status") != "pending" or not a.get("text"):
                continue
            anchor_text = str(a["text"])
            # hit：全片段命中新增区段（就近窗口内）。整串捷径仅对 ≥3 字锚点
            # 开放——2 字通用词的裸子串命中（「高山」∈「高山上」）正是旧噪声
            # 之源；无可判片段（<3 字锚点）按未命中处理，不给它留回归的门
            # （漏判有 finish 报告 spine_note 兜底）
            if text_matches(
                anchor_text, growth,
                threshold=SPINE_HIT_THRESHOLD,
                tail_chars=SPINE_GROWTH_TAIL_CHARS,
                exact_shortcut=len(anchor_text) >= 3,
            ):
                a["status"] = "hit"
                changed = True
            # 临近岔路（M3 §5）：带岔路标记的 pending 锚点走低阈值档宽松判定
            # （写到附近了但还没兑现）→ 走向卡舱硬提示置顶其走向选项。
            # 有意宽松：只多一张提示卡、不写任何库，作者可无视
            elif (
                isinstance(a.get("branch"), dict)
                and a["branch"].get("options")
                and text_matches(
                    anchor_text, growth,
                    threshold=SPINE_NEAR_BRANCH_THRESHOLD,
                    tail_chars=SPINE_GROWTH_TAIL_CHARS,
                )
            ):
                near_branches.append({
                    "id": a.get("id", ""),
                    "text": a.get("text", ""),
                    "options": a["branch"]["options"],
                })
    except Exception as e:
        logger.debug(f"[adaptive/spine] 进度判定失败（不阻塞心跳）: {e}")

    if changed:
        # 防并发 PATCH 整包覆盖：commit 前重读，hit 只前进。
        # spine 在本函数开头读入，判 hit 期间作者侧防抖 PATCH /adaptive/spine 可能
        # 已落库（改意图/增删锚点/划掉锚点）——直接把「旧快照+hit」整包写回会静默
        # 回滚作者的编辑。这里先结束当前读事务再 refresh 整行拿最新 spine，把已判
        # hit 的锚点（按 id 匹配、仅 pending→hit 单向，不碰其他字段）应用到新鲜
        # anchors 上再整体写回：作者的编辑保留，hit 迁移不丢。
        # refresh/commit 异常沿用现状语义：debug 吞掉，绝不阻塞心跳返回（此时
        # progress 仍用本地 anchors 组装，hit 只是不落库、下轮重判）。
        try:
            # 先 commit 结束本会话至今的读事务（本会话到此只读，无写入副作用）——
            # 防 SQLite WAL/PG 快照语义下 refresh 仍读到旧事务快照
            await db.commit()
            await db.refresh(chapter)  # 同 session 强制重 SELECT 整行
            fresh_spine = chapter.spine if isinstance(chapter.spine, dict) else {}
            # 逐锚点浅拷贝（dict(a)），两个目的：
            # ① JSONB 列无 mutable 追踪——直接改 ORM 值对象内层 dict 不会产生脏标记，
            #    且 SQLAlchemy 标量属性按「值相等」判变更，共享内层 dict 会让
            #    改写后的新包与 committed 值判等 → flush 静默跳过 UPDATE（实测踩坑）；
            # ② 新旧值可区分，保证整体赋值一定被识别为变更、落库一定发生。
            fresh_anchors = [
                dict(a) if isinstance(a, dict) else a
                for a in (fresh_spine.get("anchors") or [])
            ]
            if fresh_anchors:
                hit_ids = {
                    a.get("id") for a in anchors
                    if isinstance(a, dict) and a.get("status") == "hit" and a.get("id")
                }
                for fa in fresh_anchors:
                    if (
                        isinstance(fa, dict) and fa.get("id")
                        and fa.get("id") in hit_ids and fa.get("status") == "pending"
                    ):
                        fa["status"] = "hit"
                chapter.spine = {**fresh_spine, "anchors": fresh_anchors}
                await db.commit()
            else:
                # 作者已清空锚点（编辑权在作者）：无 hit 可迁移，不回写防污染
                pass
            # 局部变量同步到新鲜值：后续 progress 组装（intent/锚点清单）以最新为准
            spine = fresh_spine or None
            anchors = fresh_anchors
        except Exception as e:
            logger.debug(f"[adaptive/spine] 进度写库失败（不阻塞心跳）: {e}")

    progress = _build_spine_progress(spine, anchors, near_branches)
    _SPINE_PROG_CACHE[cid] = (content_md5, progress)
    orch._last_content_len = len(content)
    return progress


async def _style_drift_hint_for_heartbeat(chapter: Any, db: AsyncSession) -> Optional[Dict]:
    """文风漂移心跳轻提示（设计稿 §5）：章尾 3000 字同尺测量 vs 目标/健康带。

    纯 code 零 LLM；显著偏离才返回提示卡（kind=style_drift，走 canon_hints 管线）。
    任何失败/文本过短 → None（绝不阻塞心跳）。
    """
    if chapter is None:
        return None
    # 同一把尺子红线：content_text 是 HTML（编辑器 getHTML 落库），测量前必须
    # 先剥——与文风页章指纹/负面命中/章节收编同一剥法（routes/style._plain_text）
    from backend.routes.style import _plain_text

    content = _plain_text(getattr(chapter, "content_text", "") or "")
    cache_key = str(chapter.id)
    cached = _STYLE_HINT_CACHE.get(cache_key)
    if cached is not None and cached[0] == len(content):
        return cached[1]

    hint: Optional[Dict] = None
    if len(content) >= 400:
        try:
            from backend.repositories import StyleCardRepository
            from backend.services.style.fingerprint import compute_style_drift_hint
            from backend.services.validation.thresholds import CV_THRESHOLD_LO, CV_THRESHOLD_HI

            # Phase 4：漂移参照取生效卡（章级特例整卡覆盖，回退书级）
            card = await StyleCardRepository(db).get_effective_card(
                chapter.book_id, chapter.id,
            )
            target = None
            if card is not None and card.dialogue_ratio_target is not None:
                target = float(card.dialogue_ratio_target)
            message = compute_style_drift_hint(
                content[-3000:], target, CV_THRESHOLD_LO, CV_THRESHOLD_HI,
            )
            if message:
                hint = {
                    "kind": "style_drift",
                    "node_label": "文风",
                    "node_type": "style",
                    "detail": message,
                }
        except Exception:
            hint = None
    _STYLE_HINT_CACHE[cache_key] = (len(content), hint)
    return hint


# ============================================================
# A5c 收件箱积压提醒（P5 §3.2）：全书 pending 候选计数 → 柔性感知带提示
# ============================================================
# 红线（P5 §9 提示不拦截）：只提示，永不阻断写作动作；查询失败静默缺席。
# ============================================================

WORLD_INBOX_HINT_THRESHOLD = 5
WORLD_INBOX_CACHE_TTL_S = 10.0  # 心跳 3-4s 一次，10s TTL 砍掉约 2/3 计数查询

# 积压计数缓存（book_id → (monotonic_ts, count)）——settle/finish 落新候选时主动失效
_WORLD_INBOX_CACHE: Dict[str, tuple] = {}


def build_world_inbox_hint(
    pending_count: int, threshold: int = WORLD_INBOX_HINT_THRESHOLD,
) -> Optional[Dict]:
    """纯函数：pending 计数 → world_inbox 提示卡（≤阈值返回 None，宁静默勿刷屏）。"""
    if pending_count <= threshold:
        return None
    return {
        "kind": "world_inbox",
        "node_label": "世界收件箱",
        "node_type": "world",
        "detail": f"收件箱积压 {pending_count} 条世界变化待确认",
        "severity": "info",
    }


async def _pending_candidates_count(db: AsyncSession, book_id: str) -> int:
    """全书 pending 候选计数（book 级；调用方各自兜异常——提醒是柔性信号，不阻塞）。"""
    from backend.models import WorldEventCandidate

    result = await db.execute(
        select(func.count(WorldEventCandidate.id)).where(
            WorldEventCandidate.book_id == book_id,
            WorldEventCandidate.status == "pending",
        )
    )
    return int(result.scalar() or 0)


async def _world_inbox_hint_for_heartbeat(chapter: Any, db: AsyncSession) -> Optional[Dict]:
    """心跳积压提醒：短 TTL 计数缓存（防抖 + 省查询），超阈值才产卡。"""
    if chapter is None:
        return None
    book_id = str(chapter.book_id)
    cached = _WORLD_INBOX_CACHE.get(book_id)
    now = time.monotonic()
    if cached is not None and now - cached[0] < WORLD_INBOX_CACHE_TTL_S:
        count = cached[1]
    else:
        try:
            count = await _pending_candidates_count(db, book_id)
            _WORLD_INBOX_CACHE[book_id] = (now, count)
        except Exception as e:
            logger.debug(f"[adaptive/heartbeat] 收件箱计数失败（不阻塞心跳）: {e}")
            return None
    return build_world_inbox_hint(count)


def _extract_canon_hints(snapshot: Dict) -> List[Dict]:
    """从世界模型快照的 projections 里提取 canon_watch 缓存的 Canon 感知 hints。"""
    for proj in (snapshot.get("projections") or []):
        if isinstance(proj, dict) and proj.get("__canon_watch__"):
            return proj.get("hints", [])
    return []


def _extract_direction_cards(snapshot: Dict, spine: Any = None) -> List[Dict]:
    """从层 3 推测提取走向卡（跳过 __dock__ 缓存项；每个推测取首个 beat）。

    走向卡 = {event, anchors}，一句话剧情走向，供 Ctrl+Space 走向卡舱选择。
    P1.4 M2：推测带合法 serves_anchor（命中本章非 dropped 锚点 id）时随卡透传——
    防御第二道（写入侧 future_projection 已闸过一道）。
    """
    valid_ids = {
        a.get("id") for a in ((spine or {}).get("anchors") or [])
        if isinstance(a, dict) and a.get("status") != "dropped" and a.get("id")
    }
    cards: List[Dict] = []
    for proj in (snapshot.get("projections") or []):
        if not isinstance(proj, dict) or proj.get("__dock__"):
            continue
        for beat in (proj.get("possible_beats") or [])[:1]:
            event = (beat.get("event") or "").strip() if isinstance(beat, dict) else ""
            if not event:
                continue
            card = {
                "event": event[:60],
                "anchors": [str(a)[:20] for a in (beat.get("anchors") or [])][:3],
            }
            sa = beat.get("serves_anchor") if isinstance(beat, dict) else None
            if sa and sa in valid_ids:
                card["serves_anchor"] = sa
            if isinstance(beat, dict) and beat.get("from_encounter") is True:
                card["from_encounter"] = True
            cards.append(card)
    return cards[:3]


# ============================================================
# 端点 2：settle — 段落锁死 + 沉淀倒灌
# ============================================================

@router.post("/{chapter_id}/adaptive/settle")
async def settle(
    chapter_id: str,
    request: SettleRequest,
    db: AsyncSession = Depends(get_db),
):
    """段落锁死 → 层1追加 + 异步触发沉淀组件（抽涌现实体 + 冲突检测）。"""
    bind_adaptive_trace(chapter_id)
    orch = get_orchestrator(chapter_id, lambda: AsyncSessionLocal())
    result = await orch.on_settle(request.text, request.entities, commit=request.commit)
    # settle 落新候选 → 失效心跳积压缓存（下轮心跳拿到新计数）
    try:
        chapter = await db.get(Chapter, str(chapter_id))
        if chapter is not None:
            _WORLD_INBOX_CACHE.pop(str(chapter.book_id), None)
    except Exception:
        pass
    trace_event(
        "adaptive_settle",
        words=len(request.text),
        commit=request.commit,
        emergent_facts=len((result.get("emergent_facts") or {})),
        candidates_created=result.get("candidates_created", 0),
    )
    await flush_adaptive_records(chapter_id)
    return result


# ============================================================
# 端点 3：finish — 作者完稿 → 后处理
# ============================================================

@router.post("/{chapter_id}/adaptive/finish")
async def finish(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """作者完稿 → 异步触发后处理（审计/一致性/残句/章节卡覆盖）+ 章级记忆索引。"""
    bind_adaptive_trace(chapter_id)
    _SENTENCE_FIX_COUNT.pop(chapter_id, None)  # 新一轮审计 → 残句修复上限重置
    orch = get_orchestrator(chapter_id, lambda: AsyncSessionLocal())
    result = await orch.on_finish()

    # ---- 记忆倒灌（写入侧）：完稿 = 章级定稿时刻，整章重索引（章级替换，幂等）----
    # 画布即事实源：索引正文取 chapters.content_text；失败绝不让完稿失败
    memory_indexed = 0
    try:
        from backend.services.rag.memory_indexing import index_chapter_memories
        bundle = await load_chapter_settings_bundle(chapter_id, db)
        if bundle.book_id and bundle.content_text:
            memory_indexed = await index_chapter_memories(
                db,
                book_id=bundle.book_id,
                chapter_id=chapter_id,
                chapter_number=bundle.chapter_number,
                text=bundle.content_text,
            )
    except Exception as e:
        logger.warning(f"[adaptive/finish] 记忆索引失败（不影响完稿结果）: {e}")

    if isinstance(result, dict):
        result["memory_indexed"] = memory_indexed

    # ---- D 包语义扫描：embedding 相似度抓「换字逃逸」变体（疑似 AI 味）----
    # 精确匹配（prohibitions.finditer）抓不到改写变体，这里用语义相似度补位。
    # 红线：只进报告由作者裁决；未配置 embedding（SQLite 默认恒未配置）/
    # 零命中不设键（响应增量最小）；不进收件箱、不进 scan-negative、
    # 不进任何 SSE 流式路径；任何失败仅 log，绝不阻塞完稿。
    semantic_hits: List[Dict] = []
    try:
        from backend.models import Book
        from backend.repositories import StyleCardRepository
        from backend.routes.style import _plain_text
        from backend.services.style.prohibitions import load_prohibition_set
        from backend.services.style.semantic_match import semantic_scan_text

        chapter = await db.get(Chapter, str(chapter_id))
        if chapter is not None:
            book = await db.get(Book, str(chapter.book_id))
            # Phase 4：语义扫描禁忌面取生效卡（章级特例整卡覆盖，回退书级）
            ps = await load_prohibition_set(
                db, book=book,
                style_card=await StyleCardRepository(db).get_effective_card(
                    chapter.book_id, chapter.id,
                ),
            )
            content = _plain_text(chapter.content_text or "")
            semantic_hits = await semantic_scan_text(content, ps)
    except Exception as e:
        logger.warning(f"[adaptive/finish] 语义扫描失败（不影响完稿结果）: {e}")
    if semantic_hits and isinstance(result, dict):
        result["semantic_hits"] = semantic_hits

    # ---- A5c①：完稿报告附收件箱积压计数（book 级 pending；失败 0 不阻塞完稿）----
    # 与 candidates_created/memory_indexed 同层（响应顶层）——报告区「收件箱」块消费；
    # 完稿整章抽取刚落过候选，顺路失效心跳积压缓存让下轮心跳拿到新计数
    candidates_pending = 0
    try:
        chapter = await db.get(Chapter, str(chapter_id))
        if chapter is not None:
            candidates_pending = await _pending_candidates_count(db, str(chapter.book_id))
            _WORLD_INBOX_CACHE.pop(str(chapter.book_id), None)
    except Exception as e:
        logger.debug(f"[adaptive/finish] 收件箱计数失败（不影响完稿结果）: {e}")
    if isinstance(result, dict):
        result["candidates_pending"] = candidates_pending

    trace_event(
        "adaptive_finish",
        finished=result.get("finished", False) if isinstance(result, dict) else False,
        memory_indexed=memory_indexed,
        candidates_created=result.get("candidates_created", 0) if isinstance(result, dict) else 0,
        candidates_pending=candidates_pending,
        semantic_hits=len(semantic_hits),
    )
    await flush_adaptive_records(chapter_id)
    return result


# ============================================================
# 端点 4：model — 拉取世界模型快照
# ============================================================

@router.get("/{chapter_id}/adaptive/model")
async def get_model(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """拉取世界模型快照（前端恢复/调试用）。"""
    repo = WorldModelRepository(db)
    snapshot = await repo.snapshot(chapter_id)
    # P3-1（C5）：快照附带最近失败组件（副驾「AI 视角」调试区消费；空 dict 零变化，
    # 与心跳响应同源——per-orchestrator 内存态，进程重启自然归零）
    orch = get_orchestrator(chapter_id, lambda: AsyncSessionLocal())
    snapshot["last_component_errors"] = orch.last_component_errors()
    return snapshot


# ============================================================
# 端点 5：stitch-ghost — 微缝合（SSE，保留不变）
# ============================================================

@router.post("/{chapter_id}/adaptive/stitch-ghost")
async def stitch_ghost(
    chapter_id: str,
    request: StitchGhostRequest,
    db: AsyncSession = Depends(get_db),
):
    """续写/缝合幽灵草稿，SSE 打字机推流。不依赖 run_id（自由路径）。"""
    bind_adaptive_trace(chapter_id)
    trace_event("adaptive_stitch_start", mode=request.mode, target_chars=request.target_chars)
    # 方向采纳回报：作者缝合了某方向的碎片 → 通知调度器降权（负反馈）
    if request.adopted_direction:
        orch = get_orchestrator(chapter_id, lambda: AsyncSessionLocal())
        orch.on_direction_adopted(request.adopted_direction)

    # 上下文装配（B2 单一装配源）：bundle/召回/文风检索统一下沉到
    # services/context/stitch_context.py——本路由与 context-preview 端点共用
    # 同一函数（预览与注入同源红线），行为与旧内联段逐字节一致。
    ctx = await assemble_stitch_context(
        chapter_id=chapter_id,
        mode=request.mode,
        fragment=request.fragment,
        rolling_prefix=request.rolling_prefix,
        db=db,
        chapter_intent=request.chapter_intent,
    )
    bundle = ctx.bundle
    proper_nouns = ctx.proper_nouns
    chapter_intent = ctx.chapter_intent
    memory_echoes = ctx.memory_echoes
    style_positive = ctx.style_positive
    author_samples = ctx.author_samples

    # P1-3（C1）短窗观测→2026-08-25 实测调窗：观测埋点回收的真实案例坐实短窗是
    # 「驴头不对马嘴」主因（used_len 长期钉死 200 上限）——常量已按实测上调
    # （SHORT 800 / LONG 1200，见 budget.py），观测键保留以持续回收配比数据。
    # 截窗走句界净截（窗首丢弃半截句，防模型误以为要续窗首）；
    # open 模式不消费 rolling_prefix。
    _rolling_cap = (
        0 if request.mode == "open"
        else STITCH_ROLLING_LONG_MAX_CHARS if request.mode in ("outline", "burst")
        else STITCH_ROLLING_SHORT_MAX_CHARS
    )
    rolling_windowed = (
        sentence_clean_tail(request.rolling_prefix or "", _rolling_cap).strip() if _rolling_cap else ""
    )

    if request.mode == "open":
        # 点火（冷启动）：空章 + 大纲 → 开篇引子。大纲是唯一燃料，无已写正文
        # 点火剂量闸（2026-08-25 实测修复）：全章地图在场模型就往终点冲（真实事故：
        # 700 字点火写完了袭击+跌落全序列，作者整段删除）——空章就近=开头一两拍，
        # 只给开头；无合格节拍行的短大纲回退原文截断（剂量天然小，不算破闸）
        _open_beats = outline_nearby(bundle.outline_text or "", "")
        open_outline = (
            "\n".join(_open_beats) if _open_beats
            else bundle.outline_text[:STITCH_OUTLINE_MAX_CHARS]
        )
        system_prompt, user_prompt = build_opening_prompt(
            outline_text=open_outline,
            previous_summary=bundle.previous_summary or "",
            worldview_text=bundle.worldview_text[:STITCH_WORLDVIEW_MAX_CHARS] if bundle.worldview_text else "",
            proper_nouns=proper_nouns,
            canon_context=bundle.canon_context,
            target_chars=request.target_chars,
            memory_echoes=memory_echoes,
            style_positive=style_positive,
            author_samples=author_samples,
            spatial_brief=bundle.spatial_brief,
            character_secrets=bundle.character_secrets,
        )
    elif request.mode == "outline":
        # 细纲扩写：作者亲笔速记 + 双端正文锚定 → 小段正文（前文承接 + 后文引向）
        # M3 三锚定：胶囊挂了锚点时，锚点文本一并注入意图块
        # C3（docs/foundation-hardening.md §5.3）：spine 全锚点行——全章谋篇
        # 盘面（含兑现状态）随意图区注入；无 spine → 行缺席，prompt 逐字节不变
        spine_anchor_rows = await _spine_anchor_rows_for_prompt(chapter_id, db)
        system_prompt, user_prompt = build_outline_expand_prompt(
            outline_note=request.fragment.strip(),
            rolling_prefix=rolling_windowed,
            after_text=(request.after_text or "")[:STITCH_AFTER_TEXT_MAX_CHARS].strip(),
            proper_nouns=proper_nouns,
            canon_context=bundle.canon_context,
            target_chars=request.target_chars,
            chapter_intent=chapter_intent,
            memory_echoes=memory_echoes,
            style_positive=style_positive,
            author_samples=author_samples,
            spatial_brief=bundle.spatial_brief,
            character_secrets=bundle.character_secrets,
            serves_anchor=request.serves_anchor.strip(),
            spine_anchors=spine_anchor_rows,
        )
    elif request.mode == "burst":
        # 段落级连写：走向卡驱动 + 更大衔接窗口 + 更快打字机节奏
        system_prompt, user_prompt = build_burst_prompt(
            fragment=request.fragment.strip(),
            rolling_prefix=rolling_windowed,
            beat_guidance=request.beat_guidance.strip(),
            proper_nouns=proper_nouns,
            canon_context=bundle.canon_context,
            target_chars=request.target_chars,
            chapter_intent=chapter_intent,
            memory_echoes=memory_echoes,
            style_positive=style_positive,
            author_samples=author_samples,
            spatial_brief=bundle.spatial_brief,
            character_secrets=bundle.character_secrets,
        )
    else:
        system_prompt, user_prompt = build_continue_prompt(
            fragment=request.fragment.strip(),
            rolling_prefix=rolling_windowed,
            mode=request.mode,
            picked_parts=request.picked_parts,
            proper_nouns=proper_nouns,
            canon_context=bundle.canon_context,
            target_chars=request.target_chars,
            chapter_intent=chapter_intent,
            memory_echoes=memory_echoes,
            style_positive=style_positive,
            author_samples=author_samples,
            spatial_brief=bundle.spatial_brief,
            character_secrets=bundle.character_secrets,
        )

    async def _stream():
        recorder = get_adaptive_recorder(chapter_id)
        try:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=0.7,
                # 推理模型预算余量见 STITCH_MAX_TOKENS_FLOOR（C2）：deepseek 类
                # 即使 REASONING_DISABLED 仍烧 ~800-1000 隐藏思考 tokens，
                # 下限太薄会「续写产出为空」
                max_tokens=max(STITCH_MAX_TOKENS_FLOOR, request.target_chars * 2 + 1000),
                reasoning_config=REASONING_DISABLED,
            )
            recorder.record_result(f"adaptive.stitch_ghost.{request.mode}", result, model_slot="creative")
            text = (result.content or "").strip().strip('"').strip('"').strip()
            if not text:
                yield build_sse_error("续写产出为空，请重试")
                return
            # 字数硬闸门（outline 模式）：超 target×1.6 先带压缩反馈重试一次，
            # 仍超则保尾截断到 ×1.5（末段承接段豁免，P1-1）。先生成后播放，
            # 对前端完全透明
            if request.mode == "outline" and request.target_chars > 0:
                hard_limit = int(request.target_chars * OUTLINE_WC_HARD_RATIO)
                if len(text) > hard_limit:
                    compressed = await call_llm_with_usage(
                        system_prompt=system_prompt,
                        user_prompt=(
                            f"{user_prompt}\n\n# 上次输出被拒\n"
                            f"上次输出 {len(text)} 字，超过 {hard_limit} 字硬上限。"
                            f"请压缩到 {request.target_chars} 字以内：删减重复修饰与冗余动作，"
                            f"细纲核心事件必须全部保留。只输出压缩后的正文。"
                        ),
                        model_type="creative",
                        temperature=0.7,
                        # 压缩重试同烧隐藏思考 tokens，同 STITCH_MAX_TOKENS_FLOOR 下限（C2）
                        max_tokens=max(STITCH_MAX_TOKENS_FLOOR, request.target_chars * 2 + 1000),
                        reasoning_config=REASONING_DISABLED,
                    )
                    recorder.record_result("adaptive.stitch_ghost.compress", compressed, model_slot="creative")
                    cand = (compressed.content or "").strip()
                    if cand:
                        text = cand
                if len(text) > hard_limit:
                    # P1-1（A3）：保尾截断——末段承接段（引向 after_text）完整
                    # 保留，超字从前往后句界删节；末段自身超限在 helper 内退化
                    # 为尾截。仅 outline 模式进此分支，其他模式口径不变
                    text = _truncate_keep_tail(text, int(request.target_chars * OUTLINE_WC_TRUNCATE_RATIO))
                    logger.info(
                        f"[adaptive/stitch-ghost] 细纲扩写字数末次仍超上限，"
                        f"保尾截断到 {len(text)} 字（目标 {request.target_chars}）"
                    )
            fragment = request.fragment.strip()
            # P1-2（A4→2026-08-26 契约反转）：幽灵是纯追加插入，作者原句已在
            # 画布里——拼回（把原句塞回句首）必造成屏幕重复，改为**复读剥离**：
            # 模型若仍把原句吐回来（prompt 已禁，等价类变体兜底），剥掉前缀只留续写
            if request.mode == "stitch" and fragment:
                text = _strip_fragment_prefix(text, fragment)
            # C1 上屏前快检（P5 §5.1）：完整文本（含字数闸截断/碎片拼回后的
            # 最终形态）生成后、GHOST_DONE 帧前跑纯算法三类疑点检查（<10ms
            # 零 LLM）。快检自身零报错（内部吞异常恒返回列表），此处再包一层
            # 防御——warnings 是柔性增量字段，绝不让它阻塞幽灵推送。
            ghost_warnings: List[Dict] = []
            try:
                ghost_warnings = check_ghost_text(text, bundle)
            except Exception as e:
                logger.debug(f"[adaptive/stitch-ghost] 快检失败（不阻塞生成）: {e}")
            yield build_sse_event("GHOST_START", "", mode=request.mode)
            # burst/open/outline 文本长 → 更大步长更快节奏（700 字约 2.3s 播完），短档保持原速
            chunk_size = 12 if request.mode in ("burst", "open", "outline") else 6
            frame_delay = 0.04 if request.mode in ("burst", "open", "outline") else 0.09
            for pos in range(0, len(text), chunk_size):
                yield build_sse_event("GHOST_CHUNK", "", delta=text[pos: pos + chunk_size])
                await asyncio.sleep(frame_delay)
            # warnings 为向后兼容增量字段（无命中/旧前端缺省均为空/忽略）
            yield build_sse_event(
                "GHOST_DONE", "", text=text, word_count=len(text),
                warnings=ghost_warnings,
            )
            trace_event(
                "adaptive_stitch_complete",
                mode=request.mode,
                target_chars=request.target_chars,
                actual_chars=len(text),
                warnings=len(ghost_warnings),
                # P1-3（C1）短窗观测：原始上送 vs 截窗后实际进 prompt 的长度
                rolling_prefix_raw_len=len(request.rolling_prefix or ""),
                rolling_prefix_used_len=len(rolling_windowed),
            )
        except Exception as e:
            logger.warning(f"[adaptive/stitch-ghost] 失败: {e}")
            yield build_sse_error(f"续写失败: {e}")
        finally:
            # SSE 流结束（正常/异常/客户端断连）统一冲账——stitch 是请求内直接调 LLM，
            # 不冲就没人冲（下一个心跳也能兜底，但那要等作者继续打字）
            await flush_adaptive_records(chapter_id)

    return StreamingResponse(_stream(), media_type="text/event-stream")


# ============================================================
# 端点 5.1：context-preview — AI 此刻所见预览（P5 B2，docs/foundation-hardening.md §2.1）
# ============================================================
# 跑 stitch-ghost 全套上下文装配（与真实注入同源——共用 assemble_stitch_context
# + adaptive_prompts.render_system_blocks，禁止平行实现），**不调 LLM 文本生成**
# （retrieve_author_samples 向量流的一次 embedding 调用属可接受例外，未配置
# embedding 自动走兜底流）。空块原样返回（前端「未配置」灰字——设定体检入口）。
# ============================================================

_PREVIEW_MODES = ("stitch", "continue", "burst", "outline", "open")


class ContextPreviewBlock(BaseModel):
    key: str          # style_positive|author_samples|proper_nouns|canon|secrets|echoes|spatial
    title: str        # 展示标题（文风画像/笔迹示范/…）
    content: str      # 块渲染文本（与真实 system prompt 对应段逐字节一致；空块=""）
    chars: int
    source: str       # 来源徽标（世界实体/章级绑定/真相层/文风卡/…）
    # A3b 预算条数据（docs/foundation-hardening.md §4.2）：配额=块常量上限；
    # 0=该次渲染未过预算器（mode 无档）。trimmed 只在被裁时出现（exclude_none）。
    budget_chars: int = 0
    trimmed: Optional[str] = None


class ContextPreviewResponse(BaseModel):
    mode: str
    blocks: List[ContextPreviewBlock] = Field(default_factory=list)
    total_chars: int = 0
    world_time: int = 0
    world_time_source: str = "zero"  # chapter_anchor|prev_anchor|max_event|zero
    world_sourced: bool = False


@router.get(
    "/{chapter_id}/adaptive/context-preview",
    response_model=ContextPreviewResponse,
    response_model_exclude_none=True,  # A3b：trimmed 无裁剪时省略（其余字段均非 None）
)
async def context_preview(
    chapter_id: str,
    mode: str = "continue",
    db: AsyncSession = Depends(get_db),
):
    """AI 此刻所见预览：stitch-ghost 将注入的全部上下文块，按注入序返回。

    query 构造与 stitch 路由同口径——预览无作者碎片（fragment=""），
    rolling_prefix 取章节正文纯文本尾部（stitch 由前端送纯文本；这里从落库
    HTML 剥成纯文本，与 memory_indexing 同口径），assemble 内部仍按各模式
    统一截 [-150:] 拼 query。open 模式 query 走大纲（同 stitch）。
    """
    if mode not in _PREVIEW_MODES:
        raise HTTPException(422, detail=f"mode 仅支持 {'/'.join(_PREVIEW_MODES)}")

    # rolling_prefix = 章节正文尾部（剥 HTML；失败/无章退化为空串，open 模式不消费）
    # 句界净截与 stitch 路由同源（预览与注入同源红线，2026-08-25 调窗后同步）
    rolling_prefix = ""
    try:
        chapter = await db.get(Chapter, chapter_id)
        if chapter is not None:
            from backend.services.rag.memory_indexing import _html_to_plain

            rolling_prefix = sentence_clean_tail(
                _html_to_plain(chapter.content_text or ""), STITCH_ROLLING_LONG_MAX_CHARS,
            )
    except Exception:
        rolling_prefix = ""

    ctx = await assemble_stitch_context(
        chapter_id=chapter_id,
        mode=mode,
        fragment="",
        rolling_prefix=rolling_prefix,
        db=db,
    )
    # 显式构造 response model：response_model 只在路由层做文档/序列化，直调
    # （单测/内部复用）也拿到结构化对象而非裸 dict
    return ContextPreviewResponse(**build_context_preview(ctx, mode))


# ============================================================
# 端点 5.5：fix-sentence — 残句定点修复（审校闭环 P1.2，作者裁决式）
# ============================================================
# 红线：只产修复句，**不改正文**——采纳与否由前端作者裁决（作者裁决即闸门，
# 不引入自动改稿）。1×creative + REASONING_DISABLED + max_tokens=1600 +
# 安全网（still_defective/length_out_of_bounds/name_dropped），与 BS-ADF
# Phase 7.5 同参数同代码路径（services/workflows/sentence_integrity.py）。
# 上限：每轮审计后每章最多修 5 处（沿 Phase 7.5 成本上限）；finish 重置计数。
# ============================================================

_SENTENCE_FIX_CAP = 5
_SENTENCE_FIX_COUNT: Dict[str, int] = {}  # chapter_id → 本轮已修复数（finish 时重置）


class FixSentenceRequest(BaseModel):
    sentence: str = Field(..., description="缺陷句原文（scan_sentence_defects 的 sentence 字段）")
    defect_type: str = ""
    description: str = ""


@router.post("/{chapter_id}/adaptive/fix-sentence")
async def fix_sentence(
    chapter_id: str,
    request: FixSentenceRequest,
    db: AsyncSession = Depends(get_db),
):
    """残句定点修复：返回修复句供作者过目，正文不动。"""
    bind_adaptive_trace(chapter_id)
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    if _SENTENCE_FIX_COUNT.get(chapter_id, 0) >= _SENTENCE_FIX_CAP:
        raise HTTPException(status_code=429, detail="本章修复已达上限（5 处），重新完稿审计后可继续")

    sentence = request.sentence.strip()
    # 画布即事实源：完稿审计对象 = 画布剥 HTML 全文（post_process._get_full_text），
    # 匹配与修复上下文同口径走 written_text——含内联标签/跨段的句子在原始 HTML
    # 里未必子串命中；层 1 事实不再兜底（作者删改后过期，曾致两源不一致假阳性）
    from backend.services.adaptive.paragraph_source import written_text
    content = written_text(chapter.content_text or "")
    if not sentence or sentence not in content:
        raise HTTPException(status_code=409, detail="未在当前正文找到该句（正文可能已改动，请重新审计）")

    from backend.services.workflows.sentence_integrity import repair_single_defect
    defect = {
        "sentence": sentence,
        "type": request.defect_type or "unknown",
        "description": request.description or "",
    }
    fixed, reason = await repair_single_defect(
        defect, content, recorder=get_adaptive_recorder(chapter_id),
    )
    trace_event("adaptive_fix_sentence", ok=fixed is not None, reason=reason, defect_type=defect["type"])
    await flush_adaptive_records(chapter_id)
    if fixed is None:
        return {"fixed": None, "reason": reason}
    _SENTENCE_FIX_COUNT[chapter_id] = _SENTENCE_FIX_COUNT.get(chapter_id, 0) + 1
    return {"fixed": fixed, "reason": "ok"}


# ============================================================
# 端点 5.6：spine — 章级谋篇软脉络（P1.4 M1，docs/chapter-planning-spine.md）
# ============================================================
# 度优先（设计稿第一原则）：意图一句话可空、锚点硬上限 5、AI 建议不落库（D-4
# 预填红线）、无脉络的书一切 UI 静默缺席（D-3）。轻量存取——不进正文版本
# 历史、不触发 world-refresh。
# ============================================================

SPINE_MAX_ANCHORS = 5
SPINE_ANCHOR_TEXT_MIN = 2
SPINE_ANCHOR_TEXT_MAX = 12   # 锚点是短语不是句子（D-5 防膨胀成第二大纲）
SPINE_INTENT_TEXT_MAX = 60


class SpineAnchor(BaseModel):
    id: str = ""
    text: str
    source: str = "author"    # author | ai
    status: str = "pending"   # pending | hit | dropped
    # 作者声明岔路（M3 §5）：该锚点处有剧情分岔，2-3 个走向短语；临近时走向卡舱硬提示
    branch: Optional[Dict] = None   # {options: ["...", "..."]}


class SpineUpdateRequest(BaseModel):
    intent: Optional[Dict] = None            # {text, source}
    anchors: Optional[List[SpineAnchor]] = None


def _normalize_branch(branch: Optional[Dict]) -> Optional[Dict]:
    """岔路标记校验（M3）：2-3 个走向短语（2-12 字），非法整个丢弃（宁缺勿脏）。"""
    if not isinstance(branch, dict):
        return None
    options = []
    for o in (branch.get("options") or [])[:3]:
        t = str(o or "").strip()[:SPINE_ANCHOR_TEXT_MAX]
        if len(t) >= SPINE_ANCHOR_TEXT_MIN:
            options.append(t)
    if len(options) < 2:
        return None
    return {"options": options}


def _normalize_spine(current: Optional[Dict], req: SpineUpdateRequest) -> Dict:
    """合并校验：None 字段保持原值；锚点数/长度硬校验（422 带人话劝阻文案）。"""
    spine = dict(current or {})
    if req.intent is not None:
        text = str(req.intent.get("text", "") or "").strip()[:SPINE_INTENT_TEXT_MAX]
        spine["intent"] = {"text": text, "source": req.intent.get("source") or "author"}
    if req.anchors is not None:
        anchors = []
        for i, a in enumerate(req.anchors):
            text = a.text.strip()
            if len(text) < SPINE_ANCHOR_TEXT_MIN:
                raise HTTPException(422, detail=f"「{text or '（空）'}」太短——每条情节用 2-12 个字记个意思就行，细节请留给大纲")
            if len(text) > SPINE_ANCHOR_TEXT_MAX:
                raise HTTPException(422, detail=f"「{text[:12]}…」超过 12 字——这里只记个意思，展开请写进大纲")
            anchors.append({
                "id": a.id or f"a{i + 1}",
                "text": text,
                "source": a.source if a.source in ("author", "ai") else "author",
                "status": a.status if a.status in ("pending", "hit", "dropped") else "pending",
                **({"branch": _normalize_branch(a.branch)} if a.branch else {}),
            })
        if len(anchors) > SPINE_MAX_ANCHORS:
            raise HTTPException(422, detail=f"情节超过 {SPINE_MAX_ANCHORS} 条——说明在写大纲了。细节留给大纲，这里只记最要紧的")
        spine["anchors"] = anchors
    return spine


async def _spine_anchor_rows_for_prompt(chapter_id: str, db: AsyncSession) -> List[dict]:
    """outline 档 stitch-ghost 的 spine 锚点行数据源（C3 · docs/foundation-hardening.md §5.3）。

    从 chapter.spine（JSONB，字段口径同 _normalize_spine：{intent, anchors}）
    抽 [{text, status}] 供 build_outline_expand_prompt 渲染全锚点行——胶囊
    扩写不只看到自己挂的单锚（serves_anchor），还有全章谋篇盘面（含兑现
    状态）。builder 侧再滤 dropped、截 STITCH_OUTLINE_SPINE_ANCHORS_MAX；
    无脉络/章节不存在/读取失败 → 空列表（锚点行缺席，prompt 逐字节零变化）。
    纯读无写，不触发 world-refresh。
    """
    try:
        chapter = await db.get(Chapter, str(chapter_id))
        spine = chapter.spine if chapter is not None else None
        if not isinstance(spine, dict):
            return []
        rows: List[dict] = []
        for a in (spine.get("anchors") or []):
            if isinstance(a, dict) and str(a.get("text") or "").strip():
                rows.append({
                    "text": str(a["text"]).strip(),
                    "status": str(a.get("status") or "").strip() or "pending",
                })
        return rows
    except Exception as e:
        logger.debug(f"[adaptive/stitch-ghost] spine 锚点读取失败（行缺席）: {e}")
        return []


@router.get("/{chapter_id}/adaptive/spine")
async def get_spine(chapter_id: str, db: AsyncSession = Depends(get_db)):
    """读软脉络（NULL → {"spine": null}，前端据此静默缺席）。"""
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return {"spine": chapter.spine}


@router.patch("/{chapter_id}/adaptive/spine")
async def patch_spine(
    chapter_id: str,
    request: SpineUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """存软脉络（部分合并：只改传了的字段）。"""
    chapter = await db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    spine = _normalize_spine(chapter.spine, request)
    if not spine.get("intent", {}).get("text") and not spine.get("anchors"):
        spine = None  # 全空 = 无脉络（静默缺席契约）
    chapter.spine = spine
    await db.commit()
    trace_event(
        "adaptive_spine_saved",
        has_intent=bool(spine and spine.get("intent", {}).get("text")),
        anchors=len((spine or {}).get("anchors", [])),
    )
    return {"spine": spine}


@router.post("/{chapter_id}/adaptive/spine-suggest")
async def spine_suggest(chapter_id: str, db: AsyncSession = Depends(get_db)):
    """AI 谋篇建议（1×creative）——**不落库**（D-4：建议只在作者收下/编辑后才入库）。"""
    bind_adaptive_trace(chapter_id)
    bundle = await load_chapter_settings_bundle(chapter_id, db)
    soft = bundle.soft_constraints()

    # 上一章未兑现锚点（作者上章想写没写到的，建议可顺延）
    prev_pending: List[str] = []
    try:
        chapter = await db.get(Chapter, chapter_id)
        if chapter is not None:
            prev_result = await db.execute(
                select(Chapter)
                .where(Chapter.book_id == chapter.book_id, Chapter.chapter_number < chapter.chapter_number)
                .order_by(Chapter.chapter_number.desc())
                .limit(1)
            )
            prev = prev_result.scalar_one_or_none()
            if prev is not None and isinstance(prev.spine, dict):
                prev_pending = [
                    a.get("text", "") for a in prev.spine.get("anchors", [])
                    if isinstance(a, dict) and a.get("status") == "pending" and a.get("text")
                ]
    except Exception:
        prev_pending = []

    from backend.services.prompts.adaptive_prompts import build_spine_suggest_prompt
    sys_p, usr_p = build_spine_suggest_prompt(
        outline_text=bundle.outline_text or "",
        open_hooks=str(soft.get("open_hooks") or ""),
        canon_context=bundle.canon_context or "",
        worldview_text=bundle.worldview_text or "",
        prev_pending_anchors=prev_pending,
        previous_summary=bundle.previous_summary or "",
    )
    result = await call_llm_with_usage(
        system_prompt=sys_p, user_prompt=usr_p,
        # 谋篇建议要质量：走 creative 槽、保留默认 thinking（设计稿 §4.1）。
        # 预算提额（2026-08-25 实证：800 曾被 MiMo 隐藏思考烧光返回空，
        # finish=length——谋篇建议空输出是静默失败，作者只会看到「没建议」）
        model_type="creative", temperature=0.4, max_tokens=SPINE_SUGGEST_MAX_TOKENS,
    )
    get_adaptive_recorder(chapter_id).record_result("adaptive.spine_suggest", result, model_slot="creative")

    from backend.services.utils.json_safe import parse_json_safe
    parsed = parse_json_safe(result.content or "") or {}
    if not (parsed.get("intent") or parsed.get("anchors")):
        # 空输出兜底重试一次：关思考小预算再试（烧光预算型空输出的针对性解法）；
        # 还空就算了——建议本就柔性，空结果契约不变
        retry = await call_llm_with_usage(
            system_prompt=sys_p, user_prompt=usr_p,
            model_type="creative", temperature=0.4, max_tokens=800,
            reasoning_config=REASONING_DISABLED,
        )
        get_adaptive_recorder(chapter_id).record_result(
            "adaptive.spine_suggest.retry", retry, model_slot="creative")
        retry_parsed = parse_json_safe(retry.content or "") or {}
        if retry_parsed.get("intent") or retry_parsed.get("anchors"):
            parsed = retry_parsed
    intent = str(parsed.get("intent", "") or "").strip()[:SPINE_INTENT_TEXT_MAX]
    anchors = []
    for a in (parsed.get("anchors") or [])[:SPINE_MAX_ANCHORS]:
        text = str(a or "").strip()[:SPINE_ANCHOR_TEXT_MAX]
        if len(text) >= SPINE_ANCHOR_TEXT_MIN:
            anchors.append(text)
    trace_event("adaptive_spine_suggest", intent=bool(intent), anchors=len(anchors))
    await flush_adaptive_records(chapter_id)
    return {"intent": intent, "anchors": anchors}


# ============================================================
# 端点 5.7：auto-read / read-entities — 系统自己去读（2026-08-25 战略定稿）
# ============================================================
# 观察触发权从手动（Ctrl+Enter 沉淀）扩展到系统自然时机：切章发枪、全书通读。
# 红线不变：只产候选进 pending 池（物理隔离），作者 ✓ 才转正——喂养从
# 「作者要做的事」变成「作者要批的事」。成本护栏全在 read_budget（哈希幂等 +
# 章级间隔 + 每书每日上限）；event_scout 内部已有「学着闭嘴」静音双闸。
# read-entities 只产草稿不落库（实体建设永远是作者动作，批量确认走前端）。


class AutoReadResponse(BaseModel):
    ran: bool
    created: int = 0
    suppressed_muted: int = 0
    skipped: Optional[Dict[str, str]] = None
    budget: Optional[Dict[str, int]] = None


@router.post("/{chapter_id}/adaptive/auto-read", response_model=AutoReadResponse)
async def auto_read_chapter(chapter_id: str, db: AsyncSession = Depends(get_db)):
    """读一章 → 世界事件候选进收件箱。幂等（哈希不变不重读），随处发枪安全。"""
    from backend.services.adaptive.read_budget import (
        AUTO_READ_DAILY_CAP,
        AUTO_READ_SKIP_REASONS,
        content_fingerprint,
        count_auto_reads_24h,
        decide_auto_read,
    )

    chapter = await db.get(Chapter, chapter_id)
    if chapter is None:
        return AutoReadResponse(ran=False, skipped={"code": "no_chapter", "reason": "章节不存在"})

    from backend.services.rag.memory_indexing import _html_to_plain
    plain = _html_to_plain(chapter.content_text or "").strip()
    book_id = str(chapter.book_id)
    daily_used = await count_auto_reads_24h(db, book_id)
    state = dict(chapter.auto_read_state or {})
    fp = content_fingerprint(plain)
    ok, code = decide_auto_read(
        text_len=len(plain), state=state, fingerprint=fp, daily_used=daily_used,
    )
    if not ok:
        return AutoReadResponse(
            ran=False,
            skipped={"code": code or "", "reason": AUTO_READ_SKIP_REASONS.get(code or "", "")},
        )

    from backend.services.world import event_scout
    result = await event_scout.run(str(chapter.id), db, {}, 0, source="auto_read", text=plain)
    await flush_adaptive_records(chapter_id)
    if result.get("skipped"):
        # 跳过（无实体/LLM 失败等）不写幂等锚——保留下次重试的资格
        return AutoReadResponse(ran=False, skipped=result["skipped"])

    chapter.auto_read_state = {
        **state,
        "hash": fp,
        "last_run_at": datetime.now(timezone.utc).isoformat(),
        "last_created": result.get("created", 0),
    }
    await db.commit()
    return AutoReadResponse(
        ran=True,
        created=result.get("created", 0),
        suppressed_muted=result.get("suppressed_muted", 0),
        budget={"daily_used": daily_used + 1, "daily_cap": AUTO_READ_DAILY_CAP},
    )


class ReadEntitiesRequest(BaseModel):
    """force=True：豁免幂等闸（unchanged/too_soon），用于全书通读刷新丢 review
    状态后的「重新认人」补救；预算闸（short_text/daily_cap）不豁免。"""
    force: bool = False


class ReadEntitiesResponse(BaseModel):
    ran: bool
    entities: List[Dict[str, Any]] = Field(default_factory=list)
    locations: List[Dict[str, Any]] = Field(default_factory=list)
    skipped: Optional[Dict[str, str]] = None


@router.post("/{chapter_id}/adaptive/read-entities", response_model=ReadEntitiesResponse)
async def read_chapter_entities(
    chapter_id: str,
    payload: Optional[ReadEntitiesRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """全书通读·阶段 A：从正文抽实体/地点候选——只产草稿不落库（作者批量过目后才建）。

    长章折叠策略：≤5000 字全量；超长取头 4000 + 尾 1000（实体介绍密度
    前重后轻，尾部带上防漏后期登场角色）。
    """
    from backend.services.adaptive.emergent_facts import extract_emergent_facts
    from backend.services.adaptive.read_budget import (
        AUTO_READ_DAILY_CAP,
        AUTO_READ_SKIP_REASONS,
        content_fingerprint,
        count_auto_reads_24h,
        decide_auto_read,
    )

    chapter = await db.get(Chapter, chapter_id)
    if chapter is None:
        return ReadEntitiesResponse(ran=False, skipped={"code": "no_chapter", "reason": "章节不存在"})

    from backend.services.rag.memory_indexing import _html_to_plain
    plain = _html_to_plain(chapter.content_text or "").strip()
    book_id = str(chapter.book_id)
    daily_used = await count_auto_reads_24h(db, book_id)
    state = dict(chapter.auto_read_state or {})
    fp = content_fingerprint(plain)
    ok, code = decide_auto_read(
        text_len=len(plain), state=state, fingerprint=fp,
        hash_key="entities_hash", ts_key="entities_last_run_at",
        daily_used=daily_used,
        force=bool(payload and payload.force),
    )
    if not ok:
        return ReadEntitiesResponse(
            ran=False,
            skipped={"code": code or "", "reason": AUTO_READ_SKIP_REASONS.get(code or "", "")},
        )

    # 已有实体名单注入前文摘要位（防重复提名已有角色；语义复用 prev_state_summary
    # 槽——它本就是「前文已知状态」的注入口）
    from backend.repositories.world_repository import WorldRepository
    existing = await WorldRepository(db).entities.list_by_book(book_id)
    known = [str(getattr(e, "name", "") or "") for e in existing if getattr(e, "name", None)]
    prev_state = ("已知实体名单（勿重复抽取）：" + "、".join(known[:50])) if known else ""

    segment = plain if len(plain) <= 5000 else plain[:4000] + "\n……\n" + plain[-1000:]
    facts = await extract_emergent_facts(
        segment,
        beat_id=f"auto_read_{chapter_id}",
        prev_state_summary=prev_state,
        recorder=get_adaptive_recorder(str(chapter_id)),
    )
    await flush_adaptive_records(chapter_id)

    # 空结果无法区分「没有涌现」与「LLM 失败」（extract 契约静默），照样写锚——
    # 重试入口是全书通读的整批重跑或正文变化，不为罕见失败保留热路径。
    # 间隔时间键与事件侧分立（entities_last_run_at）：认人刚跑完不封锁记事
    chapter.auto_read_state = {
        **state,
        "entities_hash": fp,
        "entities_last_run_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.commit()
    return ReadEntitiesResponse(
        ran=True,
        entities=list(facts.new_entities or []),
        locations=list(facts.new_locations or []),
    )


# ============================================================
# 端点 6：event — 协作交互埋点（P0-3，本地 JSONL 零上报）
# ============================================================
# 用途定位（roadmap §0.1/§1）：个人镜子——自我可见性（协作质量与 token 成本），
# 非增长分析。事件词表（前端 dispatchCollabEvent / logCollabEvent）：
#   cards_delivered {count}      走向卡亮出（前端按卡集签名去重，防心跳重复计）
#   card_burst {event}           走向卡连写（Ctrl+Space 选卡）
#   ghost_request {mode}         Space 续写/缝合触发
#   ghost_adopt / ghost_discard  Enter 落地 / Esc 蒸发
#   capsule_create / capsule_expand {note_id}  细纲胶囊创建 / 落笔扩写
#   slice_mode {mode}            切片条读者视角档切换
#   context_card                 情境浮卡打开
#   quick_note {action}          世界速记 commit / undo
#   batch_accept {count, undone} 批量采纳候选（A5b；undone=1 表示整批已撤销）
#   ignition / settle {commit} / finish / sentence_fix {action: propose|adopt|reject}
#   spine_intent_set / spine_anchor_add|drop|remove / spine_suggest /
#   spine_suggest_adopt {part} / spine_suggest_discard（P1.4 章级谋篇）
# ============================================================

# 埋点文件路径锚定项目根（与 backend/database.py 的 _sqlite_db_path 同款推导）：
# 相对路径 "data/…" 会随服务启动 CWD 漂移（不同目录启动各写一份）。惰性函数而非
# 模块常量——尊重 VELLUMA_DATA_DIR 运行时覆盖（打包/便携场景启动后才注入）。
# 注：本文件位于 backend/routes/chapter_generation/，上三级即项目根。
_COLLAB_EVENTS_MAX_BYTES = 5 * 1024 * 1024  # 单文件 5MB 上限：超出轮转一份（个人镜子只需近期数据）


def _collab_events_path() -> Path:
    """协作埋点 JSONL 路径（<data>/collab_events.jsonl，锚定项目根不随 CWD 漂移）。"""
    root = Path(__file__).resolve().parents[3]
    data_dir = Path(os.getenv("VELLUMA_DATA_DIR") or (root / "data"))
    return data_dir / "collab_events.jsonl"


def _collab_events_rotated_path() -> Path:
    """轮转文件路径（collab_events.jsonl.1，写侧超限时当前文件 rename 过来）。"""
    base = _collab_events_path()
    return base.with_name(base.name + ".1")


class CollabEventRequest(BaseModel):
    kind: str
    detail: Dict = Field(default_factory=dict)


def _append_collab_event(book_id: str, chapter_id: str, kind: str, detail: Dict) -> None:
    """追加事件到本地 JSONL（失败静默——埋点绝不阻塞业务）。

    无界增长防护：追加前检查当前文件超 5MB 则先轮转（当前 → .1，覆盖旧 .1——
    单文件曾承载所有书所有章，不轮转会无限膨胀且 summary 全文件逐行扫越扫越慢）。
    读侧 summary 对称读两份。轮转自身失败随外层静默契约吞掉（继续追加原文件）。
    """
    import json as _json
    from datetime import datetime, timezone as _tz

    try:
        path = _collab_events_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.exists() and path.stat().st_size > _COLLAB_EVENTS_MAX_BYTES:
                rotated = _collab_events_rotated_path()
                rotated.unlink(missing_ok=True)  # Windows 下 rename 目标存在会报错，先清位
                path.rename(rotated)
        except Exception as e:
            logger.debug(f"[CollabEvent] 轮转失败（继续追加原文件）: {e}")
        with path.open("a", encoding="utf-8") as f:
            f.write(_json.dumps({
                "ts": datetime.now(_tz.utc).isoformat(),
                "book_id": book_id,
                "chapter_id": chapter_id,
                "kind": kind,
                "detail": detail or {},
            }, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        logger.debug(f"[CollabEvent] 写入失败（静默）: {e}")


@router.post("/{chapter_id}/adaptive/event", status_code=204)
async def log_collab_event(
    chapter_id: str,
    payload: CollabEventRequest,
    db: AsyncSession = Depends(get_db),
):
    """记录协作交互事件（book_id 服务端从章节解析，前端不传防伪）。"""
    book_id = ""
    try:
        chapter = await db.get(Chapter, chapter_id)
        if chapter is not None:
            book_id = str(chapter.book_id)
    except Exception:
        pass
    _append_collab_event(book_id, chapter_id, payload.kind, payload.detail)


@router.get("/{chapter_id}/adaptive/events/summary")
async def collab_events_summary(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """协作交互汇总（个人镜子：走向卡/幽灵稿/胶囊的采纳率——P0 出口标准）。"""
    import json as _json
    from collections import Counter as _Counter

    book_id = ""
    try:
        chapter = await db.get(Chapter, chapter_id)
        if chapter is not None:
            book_id = str(chapter.book_id)
    except Exception:
        pass

    counts: Dict = _Counter()
    # quick_note 的 action 拆分计数（独立于 counts）：前端同 kind 发 commit/undo
    # 两种 action，quick_note_commit 出口只应计入落账动作。不并入 counts——
    # total/by_kind 保持纯 kind 口径（insights「协作」面板消费 by_kind['quick_note']
    # 总数，并入会双计 total 且污染 by_kind）。
    quick_note_actions: Dict = _Counter()
    # batch_accept 的 count 求和（独立于 counts）：A5b 批量裁决采纳条数总量
    batch_accept_count = 0
    encounter_cards = 0
    encounter_bursts = 0
    try:
        # 读侧与写侧轮转对称：当前文件 + 单份 .1 轮转（两次 open 复用同一段逐行统计）
        for path in (_collab_events_path(), _collab_events_rotated_path()):
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        ev = _json.loads(line)
                        if ev.get("chapter_id") == chapter_id:
                            kind = ev.get("kind", "?")
                            counts[kind] += 1
                            detail = ev.get("detail") or {}
                            if kind == "quick_note":
                                quick_note_actions[detail.get("action") or "commit"] += 1
                            if kind == "batch_accept" and not detail.get("undone"):
                                batch_accept_count += int(detail.get("count") or 0)
                            # W5 桥验证指标：地图来源卡的亮出/连写（roadmap §3.2）
                            if kind == "cards_delivered":
                                encounter_cards += int(detail.get("encounter_count") or 0)
                            elif kind == "card_burst" and detail.get("from_encounter"):
                                encounter_bursts += 1
                    except Exception:
                        continue
    except Exception:
        pass

    def _rate(num: str, den: str):
        n, d = counts.get(num, 0), counts.get(den, 0)
        return round(n / d, 3) if d > 0 else None

    return {
        "chapter_id": chapter_id,
        "book_id": book_id,
        "total": sum(counts.values()),
        "by_kind": dict(counts),
        "card_burst_rate": _rate("card_burst", "cards_delivered"),
        "ghost_adopt_rate": _rate("ghost_adopt", "ghost_request"),
        "capsule_expand_count": counts.get("capsule_expand", 0),
        # 只含 action=='commit'（世界速记落账）；undo 不计（防误计拉高采纳面貌）
        "quick_note_commit": quick_note_actions.get("commit", 0),
        # A5b 批量裁决：累计采纳条数（by_kind['batch_accept'] 是操作次数，这是条数）
        "batch_accept_count": batch_accept_count,
        "encounter_card_burst_rate": round(encounter_bursts / encounter_cards, 3) if encounter_cards > 0 else None,
    }
