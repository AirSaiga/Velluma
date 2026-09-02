# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 分节 prompt 编译器（约束治理一期 · 剂量治理的通用设施）
"""
按谓词激活的 prompt 分节拼装——「约束剂量」治理的数据驱动机制。

设计意图（导师方案 Q3）：中档模型对 prompt 约束的服从率随条数稀释，且与
本次上下文无关的条款是纯噪声。每节声明 when 谓词，渲染时只求值存活的节——
多数调用下规则面显著收窄，且每节都与本次调用的上下文现实相关。

**这是通用设施，dock 只是第一个租户**（2026-09-02 一期；五模式共享基座的
编译器化挂账）。禁止为单个 prompt 手写条件字符串拼接——那会让二期变成重写。

纯函数、零依赖（谓词由调用方注入）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class PromptSection:
    """一个 prompt 分节：text 原样拼装；when(ctx) 为 False 时整节缺席。

    when 为 None = 恒在场。ctx 是本次调用的上下文特征 dict（如
    {"has_nearby": True, "has_echo_material": False}），谓词只读它。
    """

    key: str
    text: str
    when: Optional[Callable[[Dict[str, Any]], bool]] = None


def render_sections(sections: List[PromptSection], ctx: Dict[str, Any]) -> str:
    """按序拼装存活的分节（谓词异常视为 False——缺素材整节缺席，不阻塞）。"""
    out: List[str] = []
    for s in sections:
        if s.when is None:
            out.append(s.text)
            continue
        try:
            if s.when(ctx):
                out.append(s.text)
        except Exception:
            pass
    return "".join(out)
