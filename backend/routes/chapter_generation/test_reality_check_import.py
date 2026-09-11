# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""完稿链 B5 现实校验的符号在位守卫。

事故背景（2026-09-04 审计）：finish 端点调用 build_knowledge_view 但 import 区
漏导，NameError 被 except 吞掉——B5 现实校验自上线起静默死亡。本测试锁死
「路由模块命名空间必须能解析该符号」，再脱落即红。
"""
import backend.routes.chapter_generation.adaptive.settle_finish as adaptive_mod


def test_finish_reality_check_symbols_imported():
    # finish 端点现实校验段直接裸调该符号（无模块前缀）
    assert hasattr(adaptive_mod, "build_knowledge_view")


def test_finish_reality_check_deferred_import_resolves():
    # 延迟导入路径本身必须可解析（权威符号存在于 knowledge_plane / reality_check）
    from backend.services.context.knowledge_plane import build_knowledge_view  # noqa: F401
    from backend.services.world.reality_check import run_reality_check  # noqa: F401
