"""
正文生成模块 (Drafting Prose) - 三种并发策略的 Prose Draft 生成。

职责：
- 提供起草阶段的正文生成功能
- 支持串行、并行，半并行三种并发策略
- 管理动态状态和微审阅

模块结构：
- micro_reviewer.py: 微观审阅模块
- state_manager.py: 状态管理模块

使用方式：
    from backend.services.workflows.drafting_prose_modules import (
        micro_review_assertion,
        update_dynamic_state,
        build_initial_relational_state,
    )

迁移说明 (2026-04-11)：
- 从 drafting_prose 目录重命名为 drafting_prose_modules 以避免循环导入
- 微审阅功能已移至 micro_reviewer.py
- 状态管理功能已移至 state_manager.py
"""

# 从原文件导出生成函数（保持向后兼容）
from backend.services.workflows.drafting_prose import (
    _generate_prose_serial_v25,
    _generate_prose_parallel_v25,
    _generate_prose_semi_parallel_v25,
    _generate_single_beat_serial,
    _generate_single_beat_parallel,
    _generate_single_beat_cascade,
    _init_serial_context,
    _init_cascade_context,
    _update_context_serial,
    _update_cascade_context,
    _adjust_after_failure,
    _execute_generation_with_retry,
    _finalize_parallel_result,
    _extract_character_prompts_for_beat,
    _build_initial_relational_state,
    _merge_relational_delta,
)

# 导出微审阅模块
from backend.services.workflows.drafting_prose_modules.micro_reviewer import (
    micro_review_assertion,
    infer_fail_categories,
    quick_qc,
    # 向后兼容别名
    _micro_review_assertion,
    _infer_fail_categories,
    _quick_qc,
)

# 导出状态管理模块
from backend.services.workflows.drafting_prose_modules.state_manager import (
    update_dynamic_state,
    update_emotional_state,
    build_initial_relational_state,
    merge_relational_delta,
    extract_fallback_summary,
    get_target_words,
    # 向后兼容别名
    _update_dynamic_state,
    _update_emotional_state,
)

__all__ = [
    # 原文件生成函数
    "_generate_prose_serial_v25",
    "_generate_prose_parallel_v25",
    "_generate_prose_semi_parallel_v25",
    "_generate_single_beat_serial",
    "_generate_single_beat_parallel",
    "_generate_single_beat_cascade",
    "_init_serial_context",
    "_init_cascade_context",
    "_update_context_serial",
    "_update_cascade_context",
    "_adjust_after_failure",
    "_execute_generation_with_retry",
    "_finalize_parallel_result",
    "_extract_character_prompts_for_beat",
    "_build_initial_relational_state",
    "_merge_relational_delta",
    # 微审阅
    "micro_review_assertion",
    "infer_fail_categories",
    "quick_qc",
    "_micro_review_assertion",
    "_infer_fail_categories",
    "_quick_qc",
    # 状态管理
    "update_dynamic_state",
    "update_emotional_state",
    "build_initial_relational_state",
    "merge_relational_delta",
    "extract_fallback_summary",
    "get_target_words",
    "_update_dynamic_state",
    "_update_emotional_state",
]
