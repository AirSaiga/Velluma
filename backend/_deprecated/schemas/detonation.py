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
引爆链（Detonation Chain）Pydantic schemas（V3.0 新建，V3.1 统一引擎演进）。

涵盖（对齐 docs/generation-v3-design.md §4 + generation-v3.1-unified.md §6）：
- PayloadCandidate / PayloadMoment：高潮点候选与确认态（3.1 新增 climax_score 强度自评）
- SetupNode：铺垫节点（3.1 双键兼容 distance_to_payload / distance_to_climax）
- DetonationChainData / DetonationChainResponse：完整铺垫结构图（3.1 加 tier/zones）
- 各闸门请求/响应（章节卡+候选 / 树生长 / 编辑 / 引爆点写作 / 选定）
- V3.1 统一引擎：GenerateUnifiedRequest（tier 参数）、TierDecision（定档结果）

业务场景：
- routes/chapter_generation.detonation 的闸门端点（3.0 旧路径，保留）
- routes/chapter_generation.unified 的统一 /generate 端点（3.1 新增）
- 前端 detonation-gate feature 与 TierSelector 的类型契约
- services/workflows/detonation 包的输入输出

设计要点：
- 字段命名严格对齐设计文档 §4.2/4.3 + 3.1 §6，便于前端直接消费
- 全部 JSONB 字段在 Pydantic 侧用强类型模型，避免 dict 漂移
- 可选字段用 Optional，新建态与确认态共用同一模型
- 3.1 双键兼容（差异清单决策 #1）：SetupNode 同时支持 distance_to_payload（旧）和
  distance_to_climax（新），序列化时同时输出两者，读取时优先 climax 键
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================================
# 基础枚举（字符串字面量，沿用 PlotLedgerStatus 风格）
# ============================================================

# SetupNode.type
NODE_TYPE_PLANT = "plant"                 # 埋设（伏笔/锚点）
NODE_TYPE_DEVELOPMENT = "development"      # 发展（收紧张力）
NODE_TYPE_DIVERSION = "diversion"          # 转移（红鲱鱼/岔笔）
NODE_TYPE_TEXTURE = "texture"              # 闲笔（质感元素，预算 ≤15%）

# SetupNode.assignment（写作情绪任务）
# 注意：规格附录 A 中文标准名为"收拢|压抑|部分释放|闲笔"，代码标识符沿用 3.0 英文短码
# （tighten=收拢 / suppress=压抑 / release_partial=部分释放 / texture=闲笔）
ASSIGNMENT_SUPPRESS = "suppress"           # 压抑（积累势能）
ASSIGNMENT_TIGHTEN = "tighten"             # 收拢（逼近高潮）
ASSIGNMENT_RELEASE_PARTIAL = "release_partial"  # 部分释放（台阶）
ASSIGNMENT_TEXTURE = "texture"             # 闲笔呼吸段

# DetonationChain.status
CHAIN_STATUS_DRAFT = "draft"               # 候选已生成待选定
CHAIN_STATUS_GROWING = "growing"           # 已确认 payload，正在/已长树
CHAIN_STATUS_CONFIRMED = "confirmed"       # 树闸门通过
CHAIN_STATUS_WRITING = "writing"           # 进入引线写作 SSE 流
CHAIN_STATUS_DONE = "done"                 # 定稿回写完成

# ============================================================
# V3.1 统一引擎：章节定档 tier（docs/generation-v3.1-unified.md §2.1 + 附录 A）
# ============================================================
TIER_CLIMAX = "climax"            # 高潮章：大高潮/揭盅/决裂/卷尾
TIER_TURN = "turn"               # 转折章：中等转折、重要推进
TIER_PROGRESS = "progress"        # 推进章：小转折、日常推进
TIER_TRANSITION = "transition"    # 过渡章：纯过渡、衔接
TIER_AUTO = "auto"               # 自动定档（请求参数，非实际档位）

# 有效档位集合（auto 不在其中）
VALID_TIERS = {TIER_CLIMAX, TIER_TURN, TIER_PROGRESS, TIER_TRANSITION}

# 三分区 zone 标识符（规格附录 A：development / buildup / climax）
ZONE_DEVELOPMENT = "development"  # 铺陈段（双轨工艺）
ZONE_BUILDUP = "buildup"         # 蓄势段（高潮倒推工艺）
ZONE_CLIMAX = "climax"           # 高潮段（高潮倒推工艺）


# ============================================================
# 引爆点（Payload）
# ============================================================

class PayloadCandidate(BaseModel):
    """高潮点候选（章节卡生成时同步产出，闸门 1 的输入）。

    对齐设计文档 §7.1 输出契约。
    V3.1（规格 §2.2 决策依据 1）：增加 climax_score 强度自评字段，
    由 LLM 在生成候选时同步给出（1-10 分 + 一句话理由），供 tier_classifier 决策。
    """

    description: str = Field(
        ...,
        description="高潮瞬间描述（场景化语言，如『男主把渡口票据拍在桌上，却烧掉了它』）",
    )
    emotional_target: str = Field(
        ...,
        description="情绪目标（具体可感，如『压迫感在最高点反转成失望』）",
    )
    answers_question: str = Field(
        ...,
        description="该高潮点回答的读者正抱着的问题",
    )
    opens_question: str = Field(
        ...,
        description="该高潮点打开的新问题（保持问题流保温）",
    )
    why_now: Optional[str] = Field(
        None,
        description="为何在此章引爆（由前文张力自然导出，禁止天降）",
    )
    # V3.1：高潮强度自评（供定档器决策，规格 §2.2 依据 1）
    climax_score: Optional[int] = Field(
        None,
        ge=1,
        le=10,
        description="高潮强度自评（1-10），由 LLM 同步给出。≥8 倾向 climax，5-7 倾向 turn，3-4 倾向 progress，≤2 倾向 transition",
    )
    climax_score_reason: Optional[str] = Field(
        None,
        description="强度自评理由（一句话，透明化定档依据）",
    )


class PayloadMoment(BaseModel):
    """高潮点确认态（用户选定/编辑后的候选，进入铺垫树生长）。

    对齐设计文档 §4.2。id 固定为 "PAYLOAD"，作为阅读序末位。
    V3.1：保留 climax_score 透传，供下游生成阶段使用。
    """

    id: str = Field("PAYLOAD", description="固定标识")
    description: str = Field(..., description="高潮瞬间描述")
    emotional_target: str = Field(..., description="情绪目标")
    answers_question: str = Field(..., description="回答的读者问题")
    opens_question: Optional[str] = Field(None, description="打开的新问题")
    must_land: bool = Field(True, description="是否必须落地（图校验硬约束）")
    candidate_index: Optional[int] = Field(
        None,
        description="选定自哪个候选（0-based；手动新建为 None）",
    )
    text: Optional[str] = Field(
        None,
        description="高潮段成文（Phase 3 双候选选定/人审后冻结）",
    )
    approved: bool = Field(False, description="是否已通过人审冻结")
    # V3.1：高潮强度（沿用自候选的 climax_score，供高潮验收对照）
    climax_score: Optional[int] = Field(
        None,
        ge=1,
        le=10,
        description="高潮强度评分（来自候选自评或高潮验收 LLM 打分）",
    )
    # V3.1：高潮验收打分（anchored_auditor 产出，与 climax_score 区分）
    # climax_score=设计期自评；climax_check_score=验收期读者模型打分
    climax_check_score: Optional[int] = Field(
        None,
        ge=1,
        le=10,
        description="高潮验收打分（读者模型 1-10），<7 触发高潮段重写",
    )


# ============================================================
# 铺垫树节点（SetupNode）
# ============================================================

class SetupNode(BaseModel):
    """铺垫节点（逆向递归长出）。

    对齐设计文档 §4.3 + 3.1 §6。每个节点回答"要让它（指向 sets_up）炸响，
    读者此刻之前必须相信/感到/误会什么"。

    V3.1 双键兼容（差异清单决策 #1）：
    - distance_to_payload（旧，3.0 已落库使用）
    - distance_to_climax（新，3.1 规格附录 A 标准名）
    序列化时同时输出；读取时优先 climax 键，fallback 到 payload 键。
    通过 model_validator 同步两者，保证下游代码用任一键都能读到值。
    """

    id: str = Field(..., description="节点唯一标识（如 n1/n2/PAYLOAD）")
    type: str = Field(
        NODE_TYPE_PLANT,
        description="节点类型：plant | development | diversion | texture",
    )
    content: str = Field(..., description="节点内容（读者需相信/感到/误会什么）")
    sets_up: List[str] = Field(
        default_factory=list,
        description="该节点为哪些节点铺垫（指向节点 id，通常是 PAYLOAD）",
    )
    # 旧键（3.0）：保留向后兼容，存量数据零迁移
    distance_to_payload: int = Field(
        1,
        ge=0,
        description="[旧键] 距高潮点的节点数（高潮点直接前置=1）。3.1 起改用 distance_to_climax，本字段保留兼容",
    )
    # 新键（3.1，规格附录 A 标准名）
    distance_to_climax: Optional[int] = Field(
        None,
        ge=0,
        description="[新键] 距高潮点的节点数（与 distance_to_payload 同义，3.1 标准名）",
    )
    assignment: str = Field(
        ASSIGNMENT_TIGHTEN,
        description="写作情绪任务：suppress(压抑) | tighten(收拢) | release_partial(部分释放) | texture(闲笔)",
    )
    question_delays: Optional[str] = Field(
        None,
        description="本节点让读者抱着走的问题（不回答它，保温用）",
    )
    restraint_note: Optional[str] = Field(
        None,
        description="本节点明确不说破的内容（人味：感动是读者自己干的活）",
    )
    subtext: Optional[str] = Field(
        None,
        description="人物未说出口的真实动机（潜台词层）",
    )
    satisfied_by_existing: Optional[str] = Field(
        None,
        description="递归终止标记：该前提已被前章事实满足（引用 established_facts id）",
    )
    planted_in_text: Optional[Dict[str, Any]] = Field(
        None,
        description="审计回填：该节点在正文中的落地证据（{quote, offset}）",
    )
    future_payoff: Optional[Dict[str, Any]] = Field(
        None,
        description="跨章伏笔标记：指向未来章节的 payoff（Slice B PlotLedger 落账用）",
    )
    beat_id: Optional[str] = Field(
        None,
        description="承载该节点的 StoryBeat id（阅读序→拍映射后回填）",
    )
    trivial: bool = Field(
        False,
        description="一句话可带过的节点（递归终止条件 b）",
    )
    # V3.1：所属分区（development/buildup/climax，由 zone_classifier 写入）
    zone: Optional[str] = Field(
        None,
        description="所属写作分区：development(铺陈段) | buildup(蓄势段) | climax(高潮段)",
    )

    def model_post_init(self, __context: Any) -> None:
        """双键同步：保证 distance_to_payload 与 distance_to_climax 一致。

        优先级：distance_to_climax（新键）> distance_to_payload（旧键）。
        若只设了其中一个，自动填充另一个。
        """
        super().model_post_init(__context) if hasattr(super(), "model_post_init") else None
        if self.distance_to_climax is not None:
            # 新键优先：同步到旧键
            if self.distance_to_payload != self.distance_to_climax:
                self.distance_to_payload = self.distance_to_climax
        elif self.distance_to_payload is not None:
            # 只有旧键：回填新键
            self.distance_to_climax = self.distance_to_payload

    def effective_distance(self) -> int:
        """读取有效距离（双键统一的访问口子，供下游代码使用）。"""
        return self.distance_to_climax if self.distance_to_climax is not None else self.distance_to_payload


# ============================================================
# 引爆链（DetonationChain）
# ============================================================

class DetonationChainData(BaseModel):
    """引爆链核心数据（ORM 无关的纯数据视图）。

    对齐设计文档 §4.1。payload + nodes + reading_order 构成完整因果脊柱。
    """

    payload: PayloadMoment = Field(..., description="引爆点")
    nodes: List[SetupNode] = Field(default_factory=list, description="铺垫树节点列表")
    reading_order: List[str] = Field(
        default_factory=list,
        description="阅读序（节点 id 序，末位是 PAYLOAD）",
    )
    status: str = Field(CHAIN_STATUS_DRAFT, description="链状态")
    version: int = Field(1, description="版本号")


class DetonationChainResponse(BaseModel):
    """引爆链响应（含 ORM 元字段）。

    V3.1（规格 §6）：增加 tier / tier_reason / zones 字段。
    旧端点的响应也会包含这三个新字段（默认 None / {}），不破坏旧前端解析。
    """

    id: str
    book_id: str
    chapter_id: Optional[str] = None
    version: int = 1
    payload: PayloadMoment
    nodes: List[SetupNode] = Field(default_factory=list)
    reading_order: List[str] = Field(default_factory=list)
    status: str = CHAIN_STATUS_DRAFT
    confirmed_by: Optional[str] = None
    # V3.1：定档信息（3.0 旧数据此字段为 None）
    tier: Optional[str] = Field(None, description="章节定档：climax/turn/progress/transition")
    tier_reason: Optional[str] = Field(None, description="定档理由")
    zones: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="三分区映射 {climax/buildup/development: [node_id...]}",
    )
    meta: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ============================================================
# 闸门端点请求/响应
# ============================================================

# --- 闸门 1：章节卡 + 引爆候选 ---

class CardV3Request(BaseModel):
    """POST /api/chapters/{id}/card-v3 请求。

    与现有 /plan 端点语义一致（生成章节卡），额外产出 payload_candidates。
    payload 为空时由 AI 生成；非空时（用户编辑后重规划）跳过 LLM。
    """

    edited_card_fields: Optional[Dict[str, Any]] = Field(
        None,
        description="用户编辑后的章节卡字段（重规划场景，沿用 /plan 语义）",
    )
    payload_count: int = Field(
        3,
        ge=1,
        le=5,
        description="引爆点候选数量（默认 3）",
    )


class CardV3Response(BaseModel):
    """POST /api/chapters/{id}/card-v3 响应。"""

    chapter_card: Dict[str, Any] = Field(..., description="章节卡字段（含 purpose/must_hit_events 等）")
    payload_candidates: List[PayloadCandidate] = Field(
        default_factory=list,
        description="引爆点候选列表（对齐 §7.1 输出契约）",
    )
    degraded: Optional[Dict[str, Any]] = Field(None, description="降级标记")
    debug_prompt: Optional[Dict[str, Any]] = Field(None, description="调试用 prompt 历史")


# --- 闸门 2：铺垫树 ---

class DetonationChainCreateRequest(BaseModel):
    """POST /api/chapters/{id}/detonation-chain 请求（首次创建 + 选定 payload）。

    用户从候选中选定一个（或手写）作为 payload，触发树生长。
    """

    payload: PayloadMoment = Field(..., description="确认的引爆点")
    confirmed_by: str = Field("user", description="确认方")


class DetonationChainGrowRequest(BaseModel):
    """POST /api/chapters/{id}/detonation-chain/grow 请求。

    重新生长整棵树，或局部重长（Slice C：换引爆点时）。
    """

    partial_from_node_id: Optional[str] = Field(
        None,
        description="局部重长起点（Slice C）：仅重长该节点的子树，其余保留",
    )
    max_depth: int = Field(6, ge=1, le=10, description="递归深度上限")
    texture_budget_ratio: float = Field(
        0.15,
        ge=0.0,
        le=0.5,
        description="texture（闲笔）节点占比上限",
    )


class DetonationChainUpdateRequest(BaseModel):
    """PUT /api/chapters/{id}/detonation-chain 请求（编辑/确认树）。"""

    payload: Optional[PayloadMoment] = Field(None, description="更新引爆点")
    nodes: Optional[List[SetupNode]] = Field(None, description="更新节点列表（增删改）")
    reading_order: Optional[List[str]] = Field(None, description="更新阅读序")
    status: Optional[str] = Field(
        None,
        description="更新状态（如 confirmed 表示树闸门通过）",
    )
    confirmed_by: Optional[str] = Field(None, description="确认方")


# --- 闸门 3：引爆点写作 ---

class PayloadWriteRequest(BaseModel):
    """POST /api/chapters/{id}/payload/write 请求。

    双候选写作（复用 fortress_candidate），可选附加上文末尾衔接。
    """

    preceding_tail: Optional[str] = Field(
        None,
        description="上文末尾（如有，用于衔接）",
    )
    target_length: int = Field(
        1000,
        ge=300,
        le=3000,
        description="引爆段目标长度（默认 1000 字，约一章 15-25%）",
    )


class PayloadWriteResponse(BaseModel):
    """POST /api/chapters/{id}/payload/write 响应。"""

    candidates: List[str] = Field(
        default_factory=list,
        description="双候选成文（通常 2 份）",
    )
    scores: Dict[str, Any] = Field(
        default_factory=dict,
        description="各候选的代码级评分（禁词/句长/红线）",
    )
    winner_label: Optional[str] = Field(
        None,
        description="代码初筛推荐的候选（A/B/fallback_single）",
    )
    degraded: Optional[Dict[str, Any]] = Field(None, description="降级标记")


class PayloadTextUpdateRequest(BaseModel):
    """PUT /api/chapters/{id}/payload/text 请求（选定/编辑/冻结）。"""

    text: str = Field(..., description="引爆段成文（人选定/手改后）")
    approved: bool = Field(
        True,
        description="是否冻结为锚（true=通过人审，进入引线写作）",
    )


# --- SSE 生成 ---

class GenerateV3Request(BaseModel):
    """POST /api/chapters/{id}/generate-v3 请求（SSE 引线写作 + 组装 + 审计）。

    前置：detonation-chain.status=confirmed 且 payload.text 已冻结。
    """

    enable_anchored_audit: bool = Field(
        True,
        description="是否启用 Layer 1 有锚审计（Slice B；Slice A 阶段无消费方）",
    )
    enable_refinement: bool = Field(
        True,
        description="是否启用局部精修（Slice B）",
    )
    enable_human_flavor: bool = Field(
        False,
        description="是否启用人味工序（减法引擎，Slice B 末开启）",
    )


# --- 落地报告 ---

class DetonationReportResponse(BaseModel):
    """GET /api/chapters/{id}/detonation-chain/report 响应。

    Slice A：仅 Layer 0 图校验结论。
    Slice B：扩展有锚审计结论（断线/起爆分/早泄）。
    """

    chapter_id: str
    chain_id: str
    graph_audit: Dict[str, Any] = Field(
        default_factory=dict,
        description="图校验结论（断线节点/texture 占比/阅读序合法性）",
    )
    anchored_audit: Optional[Dict[str, Any]] = Field(
        None,
        description="有锚审计结论（Slice B）",
    )
    degraded: Optional[Dict[str, Any]] = Field(None, description="降级标记")


# ============================================================
# V3.1 统一引擎 schemas（docs/generation-v3.1-unified.md §9.1）
# ============================================================
# 统一管线入口 POST /api/chapters/{id}/generate 的请求/响应模型
# 与 3.0 的 GenerateV3Request 并存（旧端点 deprecated 但保留行为）


class GenerateUnifiedRequest(BaseModel):
    """POST /api/chapters/{id}/generate 请求（统一引擎入口）。

    规格 §9.1：参数 tier: auto|climax|turn|progress|transition（默认 auto）。
    auto 时由 tier_classifier 自主决策（§2.2 宁低勿高）；其余值强制指定档位。

    与旧 /generate-v3 的关系：
    - 本端点是统一管线入口，自主完成定档 + 铺垫结构生长 + 三区写作 + 审校
    - 跳过 3.0 的三个人工闸门（通知式而非确认式，规格 §2.3 / §9.1）
    - tier=auto 时程序自主决策；强制档位时按档位参数表执行
    """

    tier: str = Field(
        TIER_AUTO,
        description="章节定档：auto(自动决策，默认) | climax | turn | progress | transition",
    )
    # 上下文与选项（沿用 3.0 闸门默认值）
    payload_count: int = Field(
        3,
        ge=1,
        le=5,
        description="高潮点候选数量（auto 档位时由 LLM 同次生成）",
    )
    enable_sketch_baseline: bool = Field(
        True,
        description="是否启用自由速写对照（§5，转折章以下档位自动关闭）",
    )
    enable_anchored_audit: bool = Field(
        True,
        description="是否启用 Layer 1 有锚审计（含高潮验收/泄底检查）",
    )
    enable_refinement: bool = Field(
        True,
        description="是否启用局部精修（漏埋补写/泄底降调/高潮重写）",
    )
    enable_inflight_regulation: bool = Field(
        True,
        description="是否启用飞行中调节（中途升档/高潮验收<7重写/压抑校准/并章建议）",
    )
    # 用户显式标注（规格 §2.2 依据 4，弱信号）
    user_tier_hint: Optional[str] = Field(
        None,
        description="用户预期档位提示（弱信号，仅 auto 时参考；强制档位则忽略）",
    )
    # 编辑后的章节卡字段（可选；不传则 AI 生成）
    edited_card_fields: Optional[Dict[str, Any]] = Field(
        None,
        description="用户编辑后的章节卡字段（可选，不传则 AI 生成）",
    )


class TierDecision(BaseModel):
    """定档决策结果（规格 §2.2 + §2.3）。

    由 tier_classifier 产出，作为 TIER_DECIDED SSE 事件的 payload。
    透明化呈现给用户：定档结果 + 理由 + 可一键改档。
    """

    tier: str = Field(..., description="最终档位：climax/turn/progress/transition")
    reason: str = Field(..., description="定档理由（如：高潮强度 7 分 + 卷末第二章）")
    # 决策依据（透明化）
    climax_score: Optional[int] = Field(
        None,
        ge=1,
        le=10,
        description="候选高潮强度自评（决策依据 1）",
    )
    chapter_position_signal: Optional[str] = Field(
        None,
        description="章节位置信号（决策依据 2，如：卷末倒数第二章）",
    )
    tension_level: Optional[int] = Field(
        None,
        description="章节卡 tension_level（决策依据 3）",
    )
    forced_by_user: bool = Field(
        False,
        description="是否用户强制指定（true 时 reason 为：用户强制指定）",
    )
    # 投资参数表（由 tier 决定，供下游 Phase 使用）
    max_depth: int = Field(..., description="铺垫结构生长深度上限")
    development_ratio: float = Field(..., description="铺陈段占比目标")


class ZoneAssignment(BaseModel):
    """三分区分配结果（规格 §6 zones 字段）。"""

    climax: List[str] = Field(
        default_factory=lambda: ["PAYLOAD"],
        description="高潮段节点 id（固定为 PAYLOAD）",
    )
    buildup: List[str] = Field(
        default_factory=list,
        description="蓄势段节点 id（distance_to_climax ≤ buildup_threshold）",
    )
    development: List[str] = Field(
        default_factory=list,
        description="铺陈段节点 id（distance_to_climax > buildup_threshold）",
    )


class SketchBaselineResult(BaseModel):
    """自由速写对照结论（规格 §5）。"""

    zone: str = Field(..., description="对照的区：buildup 或 development")
    sketch_text: str = Field("", description="无约束自由速写文本")
    # 对照诊断（规格 §5 表）
    diagnosis: str = Field(
        "consistent",
        description="诊断结论：consistent(轮廓一致) | premature_suspicion(疑似泄底) | over_suppressed(压抑过度=无聊)",
    )
    diagnosis_reason: str = Field("", description="诊断理由")
    action_taken: str = Field(
        "none",
        description="处置动作：none(通过) | tone_down(压低调子) | micro_twist(注入小波折)",
    )
    degraded: Optional[Dict[str, Any]] = Field(None, description="降级标记")


class InflightUpgradeEvent(BaseModel):
    """中途升档事件（规格 §8 表）。"""

    from_tier: str = Field(..., description="原档位")
    to_tier: str = Field(..., description="升档后档位")
    trigger: str = Field(..., description="触发原因：buildup_discovery | user_request")
    extra_nodes_added: int = Field(0, description="补生长的铺垫节点数")


class MergeSuggestion(BaseModel):
    """并章/删章建议（规格 §8 表，通知式）。"""

    suggestion_type: str = Field(..., description="merge(并章) | drop(删章)")
    reason: str = Field(..., description="建议理由")
    detail: str = Field("", description="详细说明")
