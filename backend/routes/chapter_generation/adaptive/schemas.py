# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""NLE-ADF 3.0 自适应路由的请求/响应模型（纯 schema，无业务逻辑）。"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================================
# 心跳 / 沉淀 / 缝合续写
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
    outline_notes: List[str] = Field(
        default_factory=list,
        description="正文里细纲胶囊的速记原文（意图反推素材；胶囊会话级不落库，经此供给）",
    )
    spine_intent: str = Field(
        "", description="打算一句话原文（打算变更即时感知：舱换向 + 层 2 转化触发）",
    )
    force_refresh: bool = Field(
        False,
        description="强制刷新挂件：跳过 dock 缓存命中判断强行重算并覆盖旧缓存（用户主动连续触发）",
    )
    suffix_anchor: str = Field(
        "",
        description="光标后文锚（中插桥接/FIM）：骨架跳写、光标停在上下文之间时，后文紧邻 1-2 句——"
                    "dock 切桥接机位、stitch 走双端边界扩写",
    )


class HeartbeatResponse(BaseModel):
    dock_parts: List[Dict] = Field(default_factory=list)
    # 句子级闸门触发位（2026-08-26）：True=作者半句悬停，挂件应静默——前端据此
    # 清舱收卡（区别于 dock_parts 空但可保留旧件供 Tab 的常态）
    dock_muted: bool = False
    # 临时在场通行证名单（2026-09-09 涌现角色闭环）：在册里的 is_guest 实体
    # 名单随心跳上帧——前端出「录入档案」直达入口，建档后自动转正
    onstage_guests: List[str] = Field(default_factory=list)
    # 本帧挂件的缓存年龄（秒；2026-09-15 槽位治理）：dock 重算失败时旧缓存照发
    # （成功落账/失败弃账，不逐出旧件），前端据此在舱内标「N 分钟前的旧卡」
    # 而非伪装新鲜。None=无件或缓存无时间戳
    dock_parts_age_s: Optional[int] = None
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
    # 第三弹（2026-09-14 光标派生取景框）：{loc_id, loc_name, derived, via}——
    # derived=True=按正文推导（前端切片条微标+一键钉定）；None=无景/派生失败
    active_scene: Optional[Dict] = Field(None)


class SettleRequest(BaseModel):
    text: str = Field(..., description="锁死的段落正文")
    entities: List[Dict] = Field(default_factory=list, description="本段涌现的实体（前端可预填）")
    commit: bool = Field(False, description="是否落库涌现实体")


class StitchGhostRequest(BaseModel):
    fragment: str = Field(..., description="作者原句碎片（outline 模式=细纲速记原文）")
    rolling_prefix: str = Field("")
    mode: str = Field("stitch", description="stitch|continue|burst（段落级连写）|outline（细纲扩写）|open（点火）")
    picked_parts: List[str] = Field(default_factory=list)
    picked_slots: List[str] = Field(default_factory=list, description="点选零件的功能槽位（与 picked_parts 同序：landing/toward_beat/echo/ambient）——双轨契约选档信号")
    suffix_anchor: str = Field("", description="中插桥接后文锚（FIM）：光标后紧邻 1-2 句——注入双端边界与桥接铁律，产出接缝归一")
    target_chars: int = 120
    chapter_intent: str = Field("")
    beat_guidance: str = Field("", description="burst 模式：选定走向卡的走向文本（空=自由发挥）")
    after_text: str = Field("", description="outline 模式：细纲之后的已写正文开头（双端缝合用，可空）")
    adopted_direction: Optional[str] = Field(None, description="作者缝合采纳的叙事方向（主线/伏笔/刻画/环境/关系），用于负反馈降权")
    serves_anchor: str = Field("", description="outline 模式：胶囊挂的谋篇锚点文本（M3 三锚定；空=双端锚定不变）")



# ============================================================
# AI 所见预览（context-preview）
# ============================================================

class ContextPreviewBlock(BaseModel):
    key: str          # scene|entities|proper_nouns|canon|secrets|worldview|relations|negative|echoes|spatial|style_positive|author_samples
    title: str        # 展示标题（场景身份/在场与相关/…）
    content: str      # 块渲染文本（与真实 system prompt 对应段逐字节一致；空块=""）
    chars: int
    source: str       # 来源徽标（世界实体/章级绑定/真相层/文风卡/…）
    # A3b 预算条数据（docs/foundation-hardening.md §4.2）：配额=块常量上限；
    # 0=该次渲染未过预算器（mode 无档）。trimmed 只在被裁时出现（exclude_none）。
    budget_chars: int = 0
    trimmed: Optional[str] = None


class ContextPreviewUnselectedItem(BaseModel):
    """知识平面审计面（v3.1 §5 纠正回路②）：未选条目及原因。"""
    key: str
    title: str
    reason: str


class ContextPreviewBriefingScene(BaseModel):
    """简报·场景行：光标派生取景（derived=True）或本章钉回退。"""
    name: str = ""
    derived: bool = False
    via: str = ""          # 派生命中的转场动词（钉回退空串）
    bridge: bool = False   # FIM 中插态（光标后有正文，简报按光标现场装配）


class ContextPreviewBriefing(BaseModel):
    """战局态势简报（2026-09-15 轻量化）：装配快照的结构化提炼，零 LLM 零新查询。

    行级静音契约：某行数据缺失时该键为 None（response_model_exclude_none
    直接省略），前端整行不渲染——简报层不做「还没录」式催收。数据从同一
    StitchContext 派生（同源红线），不另起查询链。
    """
    scene: Optional[ContextPreviewBriefingScene] = None
    onstage: Optional[List[str]] = None   # 在场存活人物（含此刻状态后缀）
    props: Optional[List[str]] = None     # 焦点物件（在场投影提及资产）
    secrets: Optional[List[str]] = None   # 守死秘密摘要（整人私有 + 字段级 secret）
    intent: Optional[str] = None          # 当前引力（意图文本）
    intent_source: Optional[str] = None   # request/outline/inferred/baton/spine


class ContextPreviewResponse(BaseModel):
    mode: str
    blocks: List[ContextPreviewBlock] = Field(default_factory=list)
    total_chars: int = 0
    world_time: int = 0
    world_time_source: str = "zero"  # chapter_anchor|prev_anchor|max_event|zero
    world_sourced: bool = False
    # 战局态势简报（增量字段：旧客户端可忽略；空书各键省略）
    briefing: ContextPreviewBriefing = Field(default_factory=ContextPreviewBriefing)
    # 知识平面「已选/未选」两栏（向后兼容增量字段：前端未消费前可忽略）
    unselected: List[ContextPreviewUnselectedItem] = Field(default_factory=list)


# ============================================================
# 残句定点修复 / 章级谋篇 / 系统自己去读 / 协作埋点
# ============================================================

class FixSentenceRequest(BaseModel):
    sentence: str = Field(..., description="缺陷句原文（scan_sentence_defects 的 sentence 字段）")
    defect_type: str = ""
    description: str = ""


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


class AutoReadResponse(BaseModel):
    ran: bool
    created: int = 0
    suppressed_muted: int = 0
    skipped: Optional[Dict[str, str]] = None
    budget: Optional[Dict[str, int]] = None


class ReadEntitiesRequest(BaseModel):
    """force=True：豁免幂等闸（unchanged/too_soon），用于全书通读刷新丢 review
    状态后的「重新认人」补救；预算闸（short_text/daily_cap）不豁免。"""
    force: bool = False


class ReadEntitiesResponse(BaseModel):
    ran: bool
    entities: List[Dict[str, Any]] = Field(default_factory=list)
    locations: List[Dict[str, Any]] = Field(default_factory=list)
    skipped: Optional[Dict[str, str]] = None


class CollabEventRequest(BaseModel):
    kind: str
    detail: Dict = Field(default_factory=dict)
