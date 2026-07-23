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
爆发链工作流类型定义（V3.0 新建）。

职责：定义 detonation/ 包内各模块共享的 dataclass 与结果类型。

设计说明：
- 使用 dataclass 而非 ORM，保持工作流层与持久化解耦
- 与 schemas/detonation.py 的 Pydantic 模型字段对齐，但这里是工作流内部类型
- 所有字段均可空（降级路径友好）
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FuseSegment:
    """铺垫段（一段朝爆炸写的成文）。

    一个铺垫段对应 reading_order 中的一个 SetupNode（PAYLOAD 除外）。
    """

    node_id: str
    text: str
    word_count: int = 0
    # 写作时的 prompt 历史（调试用）
    prompts: Dict[str, str] = field(default_factory=dict)


@dataclass
class DetonationResult:
    """爆发链工作流完整结果（对应 SSE 流的最终产物）。

    由 workflow.DetonationWorkflow.execute() 返回，供 stream_handler 持久化与 SSE 推送。
    """

    # 组装后的完整正文（铺垫段 + 爆发段，按 reading_order）
    final_text: str = ""
    # 各铺垫段成文（供观测/调试/精修定位）
    fuse_segments: List[FuseSegment] = field(default_factory=list)
    # 爆发段成文（来自 payload.text，已人审冻结）
    payload_text: str = ""
    # Layer 0 图校验结论（零 token）
    graph_audit: Dict[str, Any] = field(default_factory=dict)
    # Layer 1 有锚审计结论（Slice B）
    anchored_audit: Optional[Dict[str, Any]] = None
    # 统计信息（供观测层）
    stats: Dict[str, Any] = field(default_factory=dict)
    # 降级事件列表（失败不静默）
    degraded: List[Dict[str, Any]] = field(default_factory=list)
    # 调试信息（prompt 历史、各阶段耗时等）
    debug_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GrowResult:
    """铺垫树生长结果（chain_grower 产出）。"""

    nodes: List[Dict[str, Any]] = field(default_factory=list)
    reading_order: List[str] = field(default_factory=list)
    # Layer 0 代码级校验结论（生长后立即跑）
    validation: Dict[str, Any] = field(default_factory=dict)
    degraded: Optional[Dict[str, Any]] = None
    prompts: Dict[str, str] = field(default_factory=dict)


@dataclass
class PayloadWriteResult:
    """高潮点双候选写作结果（payload_writer 产出）。"""

    candidates: List[str] = field(default_factory=list)
    scores: Dict[str, Any] = field(default_factory=dict)
    winner_label: Optional[str] = None
    winner_text: Optional[str] = None
    degraded: Optional[Dict[str, Any]] = None
    prompts: Dict[str, Any] = field(default_factory=dict)
