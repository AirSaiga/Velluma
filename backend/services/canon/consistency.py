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
Canon 一致性引擎（V4.0 新建）。

职责：
- Private 字段泄露检测（生成时 + 写作时）
- 事实矛盾检测（写作时实时）
- 悬空伏笔检测（写作新章时提醒）

设计依据：docs/generation-v4.0-canon.md §3

业务场景：
- routes/canon.py 的 POST /canon/check 端点
- 生成流水线的 Phase 5 审计增强
- 前端写作时的实时侧栏提醒

使用方式：
    issues, stats = await check_consistency(db, book_id, draft_text)
    # issues: List[ConsistencyIssue]
"""

import logging
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    CanonNode,
    CanonEdge,
    NODE_TYPE_HOOK,
    VISIBILITY_PRIVATE,
    VISIBILITY_PARTIAL,
)
from backend.repositories import CanonRepository
from backend.schemas.canon import ConsistencyIssue

logger = logging.getLogger(__name__)


# ============================================================
# 工具：从 canon_text 提取关键短语
# ============================================================

def _extract_key_phrases(text: str, max_phrases: int = 10) -> List[str]:
    """从 canon_text 提取关键短语（用于泄露检测）。

    简单策略：
    - 取 2-8 字的连续中英文短语
    - 过滤停用词和过短词
    """
    if not text:
        return []
    import re
    # 中英文短语
    phrases = re.findall(r'[\u4e00-\u9fa5]{2,8}|[A-Za-z]{3,15}', text)
    # 去重 + 过滤
    seen = set()
    result = []
    stop_words = {"这是", "这是指", "这个", "一个", "某种", "什么", "如果", "因为", "所以"}
    for p in phrases:
        if p in seen or p in stop_words or len(p) < 2:
            continue
        seen.add(p)
        result.append(p)
        if len(result) >= max_phrases:
            break
    return result


# ============================================================
# 一致性检查主入口
# ============================================================

async def check_consistency(
    db: AsyncSession,
    book_id: UUID,
    text: str,
    include_llm_check: bool = False,
) -> Tuple[List[ConsistencyIssue], dict]:
    """对一段文本做一致性检查（对照 Canon）。

    Args:
        db: 数据库会话
        book_id: 书籍 ID
        text: 待检查文本（章节正文或段落）
        include_llm_check: 是否调用 LLM 做语义级检查（默认 False，纯算法）

    Returns:
        tuple: (issues, stats)
            issues: List[ConsistencyIssue]
            stats: {"private_total": int, "hooks_open": int, ...}
    """
    repo = CanonRepository(db)
    issues: List[ConsistencyIssue] = []

    # ---- 检查 1: Private 字段泄露 ----
    try:
        private_nodes = await repo.nodes.find_private_nodes(book_id)
    except Exception as e:
        logger.warning(f"[Canon] 加载 private 节点失败: {e}")
        private_nodes = []

    private_leak_count = 0
    for node in private_nodes:
        # 提取 canon_text 的关键短语，看是否出现在 text 里
        phrases = _extract_key_phrases(node.canon_text)
        leaked = [p for p in phrases if p in text]
        if leaked:
            private_leak_count += 1
            issues.append(ConsistencyIssue(
                severity="error",
                kind="private_leak",
                node_id=str(node.id),
                node_label=node.label,
                detail=f"private 节点 [{node.label}] 的关键短语出现在文本中：{leaked[:3]}",
                evidence=leaked[0] if leaked else None,
                suggestions=[
                    f"删除对 '{leaked[0]}' 的直接提及",
                    f"改为间接暗示（用动作/反应代替直接说明）",
                    f"如果是有意暴露，请在节点 [{node.label}] 里更新 visibility 为 partial",
                ],
            ))

    # ---- 检查 2: 悬空伏笔（HOOK 节点 status=open 且超过 N 章未回收） ----
    try:
        hooks = await repo.nodes.find_hooks(book_id, only_open=True)
    except Exception as e:
        logger.warning(f"[Canon] 加载 HOOK 节点失败: {e}")
        hooks = []

    orphan_count = 0
    for hook in hooks:
        # 判断是否悬空过久
        appeared = hook.appeared_in or []
        if not appeared:
            continue
        last_appear = max(appeared)
        expected = hook.expected_reveal_chapter
        # 如果距上次出现 > 15 章 且预期揭示章节已过/未指定 → 悬空
        # 这里我们不知道当前是第几章，所以用 expected 判断
        if expected and expected < (last_appear + 5):
            # 还在预期范围内，跳过
            continue
        if not expected:
            # 没标预期揭示章节
            issues.append(ConsistencyIssue(
                severity="info",
                kind="orphan_hook",
                node_id=str(hook.id),
                node_label=hook.label,
                detail=f"伏笔 [{hook.label}] 未标注预期揭示章节",
                suggestions=[
                    f"在节点里标注 expected_reveal_chapter",
                    f"考虑在本章回收",
                ],
            ))
            orphan_count += 1

    # ---- 统计 ----
    stats = {
        "private_total": len(private_nodes),
        "private_leaked": private_leak_count,
        "hooks_open": len(hooks),
        "hooks_orphan": orphan_count,
        "issues_total": len(issues),
        "errors": sum(1 for i in issues if i.severity == "error"),
        "warnings": sum(1 for i in issues if i.severity == "warning"),
        "infos": sum(1 for i in issues if i.severity == "info"),
    }

    logger.info(
        f"[Canon] 一致性检查完成：{len(issues)} 个问题"
        f"（{stats['errors']} 错误 / {stats['warnings']} 警告 / {stats['infos']} 信息）"
    )
    return issues, stats


# ============================================================
# Prompt 注入用：构建 Canon 上下文
# ============================================================

async def build_canon_context_for_prompt(
    db: AsyncSession,
    book_id: UUID,
    chapter_number: Optional[int] = None,
) -> str:
    """为生成 prompt 构建 Canon 上下文段。

    分三层注入：
    1. private 真相（绝不许在正文写出，但作为隐藏动机）
    2. public 已建立事实（必须遵守）
    3. 悬空伏笔（本章可回收/累积）

    Returns:
        格式化的文本块，可直接拼到 prompt
    """
    repo = CanonRepository(db)
    parts: List[str] = []

    # 1. private 真相
    try:
        private_nodes = await repo.nodes.find_private_nodes(book_id)
    except Exception as e:
        logger.warning(f"[Canon] 加载 private 失败: {e}")
        private_nodes = []

    if private_nodes:
        parts.append("## 作者脑中的真相 [private] ★ 绝不许在正文直接写出")
        for n in private_nodes[:10]:
            line = f"- {n.label}：{n.canon_text[:150]}"
            if n.reveal_plan:
                line += f"（揭示计划：{n.reveal_plan[:80]}）"
            parts.append(line)
            # 关键：明确告诉 LLM 这是 private
            parts.append(f"  → 写作时可作为角色隐藏动机，但绝不能用对话/叙述/心理独白直接说出")

    # 2. public 已建立事实
    try:
        public_nodes = await repo.nodes.list_by_book(book_id, visibility="public", limit=15)
    except Exception as e:
        logger.warning(f"[Canon] 加载 public 失败: {e}")
        public_nodes = []

    public_facts = [n for n in public_nodes if n.type != "hook" and n.public_text]
    if public_facts:
        parts.append("\n## 必须遵守的已建立事实 [public]")
        for n in public_facts[:10]:
            parts.append(f"- {n.label}：{n.public_text[:120]}")

    # 3. 悬空伏笔
    try:
        open_hooks = await repo.nodes.find_hooks(book_id, only_open=True)
    except Exception as e:
        logger.warning(f"[Canon] 加载 hooks 失败: {e}")
        open_hooks = []

    if open_hooks:
        parts.append("\n## 活跃伏笔 [hook]（本章可推进/回收）")
        for h in open_hooks[:8]:
            meta = h.metadata_ or {}
            strength = meta.get("strength", "?")
            parts.append(f"- [{h.label}] 强度={strength}：{h.canon_text[:100]}")

    return "\n".join(parts) if parts else "（Canon 为空，无强约束）"
