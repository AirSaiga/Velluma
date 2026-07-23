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
爆发链（Detonation Chain）工作流包（V3.0 新建）。

包结构（设计文档 §2.1）：
- types.py:           dataclass（FuseSegment / DetonationResult / GrowResult / PayloadWriteResult）
- graph_auditor.py:   Layer 0 图校验（零 token 纯算法）
- chain_grower.py:    铺垫树生长（逆向递归，1-2 次 reasoning）
- payload_writer.py:  高潮点双候选写作（复用 fortress_candidate）
- fuse_writer.py:     铺垫写作（距离指令，串行 Rolling Prefix 链）
- assembler.py:       轻量组装（阅读序拼接 + 接缝打磨）
- workflow.py:        DetonationWorkflow 主类（编排上述模块）

与 DualTrackWorkflow 的关系：
- 完全独立类，零代码交叉
- 共享层（ContextEngine / RunRecorder / 文风体系 / 模型槽位路由）通过参数注入
- 入口端点 /generate-v3 调用本包；/generate-chapter 仍走 DualTrackWorkflow

使用示例：
    from backend.services.workflows.detonation import DetonationWorkflow

    workflow = DetonationWorkflow(
        chain=chain_dict, chapter=chapter, chapter_card=cc,
        entities=entities, style_card=sc, recorder=recorder,
    )
    result = await workflow.execute(progress_callback=cb)
"""

from backend.services.workflows.detonation.types import (
    FuseSegment,
    DetonationResult,
    GrowResult,
    PayloadWriteResult,
)
from backend.services.workflows.detonation.graph_auditor import (
    audit_chain_graph,
    build_retry_feedback,
    DEFAULT_TEXTURE_BUDGET_RATIO,
)
from backend.services.workflows.detonation.chain_grower import (
    grow_detonation_chain,
    extract_established_facts,
)
from backend.services.workflows.detonation.payload_writer import (
    write_payload_dual_candidates,
)
from backend.services.workflows.detonation.fuse_writer import (
    write_fuse_segments,
)
from backend.services.workflows.detonation.assembler import (
    assemble_chapter,
)
from backend.services.workflows.detonation.workflow import (
    DetonationWorkflow,
)
from backend.services.workflows.detonation.anchored_auditor import (
    run_anchored_audit,
    derive_refinement_targets,
    DETONATION_SCORE_THRESHOLD,
)
from backend.services.workflows.detonation.refiner import (
    refine_full,
    refine_broken_nodes,
    refine_premature_segments,
)
from backend.services.workflows.detonation.ledgers import (
    plant_ledgers_from_chain,
    count_auto_plant_rate,
)
# V3.1 统一引擎新增模块
from backend.services.workflows.detonation.tier_classifier import (
    classify_tier,
    classify_from_user_forced,
    assign_zones,
)
from backend.services.workflows.detonation.sketch_baseline import (
    run_sketch_baseline,
    DIAGNOSIS_CONSISTENT,
    DIAGNOSIS_PREMATURE_SUSPICION,
    DIAGNOSIS_OVER_SUPPRESSED,
    ACTION_NONE,
    ACTION_TONE_DOWN,
    ACTION_MICRO_TWIST,
)

__all__ = [
    # 类型
    "FuseSegment",
    "DetonationResult",
    "GrowResult",
    "PayloadWriteResult",
    # 图校验
    "audit_chain_graph",
    "build_retry_feedback",
    "DEFAULT_TEXTURE_BUDGET_RATIO",
    # 树生长
    "grow_detonation_chain",
    "extract_established_facts",
    # 高潮点写作
    "write_payload_dual_candidates",
    # 铺垫写作
    "write_fuse_segments",
    # 组装
    "assemble_chapter",
    # 有锚审计（Slice B）
    "run_anchored_audit",
    "derive_refinement_targets",
    "DETONATION_SCORE_THRESHOLD",
    # 精修（Slice B）
    "refine_full",
    "refine_broken_nodes",
    "refine_premature_segments",
    # 伏笔落账（Slice B）
    "plant_ledgers_from_chain",
    "count_auto_plant_rate",
    # V3.1 统一引擎
    "classify_tier",
    "classify_from_user_forced",
    "assign_zones",
    "run_sketch_baseline",
    "DIAGNOSIS_CONSISTENT",
    "DIAGNOSIS_PREMATURE_SUSPICION",
    "DIAGNOSIS_OVER_SUPPRESSED",
    "ACTION_NONE",
    "ACTION_TONE_DOWN",
    "ACTION_MICRO_TWIST",
    # 主类
    "DetonationWorkflow",
]
