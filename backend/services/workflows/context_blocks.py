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
起草 Prompt 上下文增强段渲染器（Phase 0 T4 过渡方案）。

职责：
- 修复调研报告病灶 4：上下文加载层取到了但起草 prompt 没消费的断链
- 把角色卡、伏笔、世界快照、金句、文风黑名单渲染为可注入的 prompt 片段

业务场景：
- _build_fast_path_prompt / _build_standard_path_prompt 调用本模块渲染增强段
- 在 Phase 1 上下文引擎（Context Engine）落地前作为过渡方案

预算控制（避免 prompt 爆炸，参考调研报告 §5.1 重新分配原则）：
- 角色卡：按 importance_level 降序，最多 5 个，每个 static_prompt 截 200 字
- 伏笔：仅 status=open 的，最多 5 条
- 金句（作者样本）：最多 2 段，每段截 200 字
- 文风黑名单：直接列禁词，最多 10 条
- 世界快照：末 600 字（1.0 Sketch 用的量）
"""

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# 预算常量
MAX_CHARACTERS = 5
MAX_CHARACTER_STATIC_LEN = 200
MAX_OPEN_HOOKS = 5
MAX_GOLDEN_SNIPPETS = 2
MAX_GOLDEN_SNIPPET_LEN = 200
MAX_SNAPSHOT_LEN = 600


def render_character_cards_block(entities: Optional[List[Any]]) -> str:
    """渲染角色卡块。

    Args:
        entities: ChapterEntity 列表（每个含 .character 关联）

    Returns:
        渲染后的 prompt 片段；无数据时返回空串
    """
    if not entities:
        return ""

    # 过滤出有 character 关联的实体，按角色重要性排序
    valid = []
    for ent in entities:
        char = getattr(ent, "character", None)
        if char is None:
            continue
        valid.append(char)

    if not valid:
        return ""

    # 按 importance_level 降序，取前 N 个
    valid.sort(key=lambda c: getattr(c, "importance_level", 1) or 1, reverse=True)
    valid = valid[:MAX_CHARACTERS]

    lines = ["【角色设定】（请严格遵循以下角色设定，不得违背）"]
    for char in valid:
        name = getattr(char, "name", "未命名") or "未命名"
        static = getattr(char, "static_prompt", None) or ""
        dynamic = getattr(char, "dynamic_state", None) or ""
        current = getattr(char, "current_state", None) or ""

        if len(static) > MAX_CHARACTER_STATIC_LEN:
            static = static[:MAX_CHARACTER_STATIC_LEN] + "…"

        line = f"- {name}：{static}"
        # 动态状态优先于历史快照（current_state 是从世界快照提取的此刻状态）
        if current:
            line += f"【此刻状态：{current[:100]}】"
        elif dynamic:
            line += f"【当前状态：{dynamic[:100]}】"
        lines.append(line)

    return "\n".join(lines) + "\n"


def render_open_hooks_block(open_hooks: Optional[List[dict]]) -> str:
    """渲染开放伏笔块。

    Args:
        open_hooks: PlotLedger 字典列表（应含 content / hook_id 字段）

    Returns:
        渲染后的 prompt 片段；无数据时返回空串
    """
    if not open_hooks:
        return ""

    # 仅取 status=open 的（PlotLedger 字段）
    open_only = []
    for h in open_hooks:
        if isinstance(h, dict):
            status = h.get("status", "open")
            if status == "open":
                open_only.append(h)
        else:
            # ORM 对象
            status = getattr(h, "status", "open")
            if status == "open" or status.value == "open" if hasattr(status, "value") else status == "open":
                open_only.append(h)

    if not open_only:
        return ""

    open_only = open_only[:MAX_OPEN_HOOKS]

    lines = ["【开放伏笔】（本章可呼应/推进以下伏笔，但不得矛盾）"]
    for h in open_only:
        if isinstance(h, dict):
            content = h.get("content", "") or ""
            hook_id = h.get("hook_id", "") or ""
        else:
            content = getattr(h, "content", "") or ""
            hook_id = getattr(h, "hook_id", "") or ""
        prefix = f"[{hook_id}] " if hook_id else ""
        lines.append(f"- {prefix}{content[:120]}")

    return "\n".join(lines) + "\n"


def render_golden_snippets_block(golden_snippets: Optional[list]) -> str:
    """渲染金句（作者样本）块。

    Args:
        golden_snippets: 字符串列表或 dict 列表（来自 book.golden_snippets）

    Returns:
        渲染后的 prompt 片段；无数据时返回空串
    """
    if not golden_snippets:
        return ""

    snippets_text = []
    for s in golden_snippets[:MAX_GOLDEN_SNIPPETS]:
        if isinstance(s, str):
            text = s
        elif isinstance(s, dict):
            text = s.get("content") or s.get("text") or ""
        else:
            text = str(s)
        if not text:
            continue
        if len(text) > MAX_GOLDEN_SNIPPET_LEN:
            text = text[:MAX_GOLDEN_SNIPPET_LEN] + "…"
        snippets_text.append(text)

    if not snippets_text:
        return ""

    lines = ["【作者样本】（请模仿以下片段的句长节奏、词汇层级、叙事语气）"]
    for i, text in enumerate(snippets_text, 1):
        lines.append(f"样本{i}：{text}")

    return "\n".join(lines) + "\n"


def render_world_snapshot_block(previous_world_snapshot: Optional[Any]) -> str:
    """渲染前章世界快照块。

    Args:
        previous_world_snapshot: 快照对象（dict 或 ORM，含末段文本）

    Returns:
        渲染后的 prompt 片段；无数据时返回空串
    """
    if not previous_world_snapshot:
        return ""

    # 快照可能是 dict 或 ORM 对象，提取文本
    if isinstance(previous_world_snapshot, dict):
        text = (
            previous_world_snapshot.get("summary")
            or previous_world_snapshot.get("text")
            or previous_world_snapshot.get("content")
            or ""
        )
    else:
        text = (
            getattr(previous_world_snapshot, "summary", None)
            or getattr(previous_world_snapshot, "text", None)
            or getattr(previous_world_snapshot, "content", None)
            or str(previous_world_snapshot)
        )

    if not text or not isinstance(text, str):
        return ""

    # 截取末段
    if len(text) > MAX_SNAPSHOT_LEN:
        text = "…" + text[-MAX_SNAPSHOT_LEN:]

    return f"【前章世界状态】（本章必须延续以下状态，不得矛盾）\n{text}\n"


def render_author_intent_block(author_intent: Optional[str]) -> str:
    """渲染作者意图块（T7 配套）。

    Args:
        author_intent: 作者意图文本

    Returns:
        渲染后的 prompt 片段；无数据时返回空串
    """
    if not author_intent or not isinstance(author_intent, str):
        return ""
    intent = author_intent.strip()
    if not intent:
        return ""
    if len(intent) > 300:
        intent = intent[:300] + "…"
    return f"【作者意图】（高优先级指令）\n{intent}\n"
