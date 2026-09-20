# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
from backend.services.world.field_layers import (
    LEVEL_PARTIAL,
    FieldLayerEntry,
    iter_field_layers,
)

# A3a 截断常量收敛（docs/reports/foundation-hardening.md §4.1）：canon 段剂量改引 budget 表
from backend.services.context.budget import (
    CANON_HOOK_LEDGER_FETCH_LIMIT,
    CANON_HOOK_MAX_ENTRIES,
    CANON_HOOK_TEXT_MAX_CHARS,
    CANON_PRIVATE_MAX_ENTRIES,
    CANON_PRIVATE_TEXT_MAX_CHARS,
    CANON_PUBLIC_FETCH_LIMIT,
    CANON_PUBLIC_MAX_ENTRIES,
    CANON_PUBLIC_TEXT_MAX_CHARS,
    CANON_REVEAL_PLAN_MAX_CHARS,
)

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
# 字段级真相分层（2026-09-03）：实体档案字段作为虚拟真相条目
# ============================================================

async def _collect_field_layer_entries(
    db: AsyncSession, book_id: UUID
) -> List[Tuple[str, FieldLayerEntry]]:
    """扫描本书实体的 field_layers，产出 [(实体名, 分层条目)]。

    字段内容本身即「里」——不建真相节点副本，真相层消费链直接读字段分层
    （派生感知取代物料迁移）。整人 private 实体跳过：全档案已在 secrets
    通道，再进 [private] 段是重复注入。无分层的书返回空列表（零行为变化）。
    """
    try:
        from backend.repositories.world_repository import WorldRepository

        entities = await WorldRepository(db).entities.list_by_book(book_id)
    except Exception as e:
        logger.warning(f"[Canon] 加载实体字段分层失败: {e}")
        return []
    out: List[Tuple[str, FieldLayerEntry]] = []
    for ent in entities:
        if getattr(ent, "visibility", "public") == "private":
            continue
        for entry in iter_field_layers(ent):
            out.append(((ent.name or ""), entry))
    return out


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

    # 字段级真相分层（2026-09-03）：分层字段全文参与同一泄密判据；
    # partial 字段的抽取集 = 全文短语 − 表文本短语（表里共有的词读者已知，不算泄密）
    field_entries = await _collect_field_layer_entries(db, book_id)
    for ent_name, entry in field_entries:
        phrases = _extract_key_phrases(entry.full_text)
        if entry.level == LEVEL_PARTIAL and entry.public_text:
            known = set(_extract_key_phrases(entry.public_text))
            phrases = [p for p in phrases if p not in known]
        leaked = [p for p in phrases if p in text]
        if leaked:
            label = f"{ent_name}·{entry.label}"
            private_leak_count += 1
            issues.append(ConsistencyIssue(
                severity="error",
                kind="private_leak",
                node_id=None,
                node_label=label,
                detail=f"分层字段 [{label}] 的关键短语出现在文本中：{leaked[:3]}",
                evidence=leaked[0] if leaked else None,
                suggestions=[
                    f"删除对 '{leaked[0]}' 的直接提及",
                    f"改为间接暗示（用动作/反应代替直接说明）",
                    f"如果是有意暴露，请在该字段的分层里把「表」补全或改回公开",
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
        "private_total": len(private_nodes) + len(field_entries),
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

    C2 换源（docs/reports/canon-world-fusion.md §6，格式冻结 K3）：
    - 段1/2 的 label：ref 挂接节点由世界对象推演（实体/地点改名后词表跟随，
      根治名字漂移→泄密漏检）；无 ref 保持原 label。
    - 段3 [hook]：装配源切到 plot_ledgers（open + 有真相面文本，取前 8）；
      未迁移书的存量 canon hook 节点（无 ref_id）继续兜底，按 label 去重。

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

    # C2：ref 节点 label 由世界对象推演（一次批量解析，失败静默回退原 label）
    world_names = await _resolve_world_labels(db, book_id, private_nodes)

    # 字段级真相分层（2026-09-03）：分层字段以虚拟条目并入同一 [private] 段，
    # 标签「实体名·字段名」；partial 追加「读者目前只知」（表）——段外档案只露表。
    field_entries = await _collect_field_layer_entries(db, book_id)

    if private_nodes or field_entries:
        parts.append("## 作者脑中的真相 [private] ★ 绝不许在正文直接写出")
        for n in private_nodes[:CANON_PRIVATE_MAX_ENTRIES]:
            label = world_names.get(str(n.ref_id), n.label) if n.ref_id else n.label
            line = f"- {label}：{n.canon_text[:CANON_PRIVATE_TEXT_MAX_CHARS]}"
            if n.reveal_plan:
                line += f"（揭示计划：{n.reveal_plan[:CANON_REVEAL_PLAN_MAX_CHARS]}）"
            parts.append(line)
            # 关键：明确告诉 LLM 这是 private
            parts.append(f"  → 写作时可作为角色隐藏动机，但绝不能用对话/叙述/心理独白直接说出")
        for ent_name, entry in field_entries:
            line = f"- {ent_name}·{entry.label}：{entry.full_text[:CANON_PRIVATE_TEXT_MAX_CHARS]}"
            if entry.level == LEVEL_PARTIAL and entry.public_text:
                line += f"（读者目前只知：{entry.public_text[:CANON_PRIVATE_TEXT_MAX_CHARS]}）"
            parts.append(line)
            parts.append(f"  → 写作时可作为角色隐藏动机，但绝不能用对话/叙述/心理独白直接说出")

    # 2. public 已建立事实
    try:
        public_nodes = await repo.nodes.list_by_book(book_id, visibility="public", limit=CANON_PUBLIC_FETCH_LIMIT)
    except Exception as e:
        logger.warning(f"[Canon] 加载 public 失败: {e}")
        public_nodes = []

    public_facts = [n for n in public_nodes if n.type != "hook" and n.public_text]
    if public_facts:
        world_names_pub = await _resolve_world_labels(db, book_id, public_facts)
        parts.append("\n## 必须遵守的已建立事实 [public]")
        for n in public_facts[:CANON_PUBLIC_MAX_ENTRIES]:
            label = world_names_pub.get(str(n.ref_id), n.label) if n.ref_id else n.label
            parts.append(f"- {label}：{n.public_text[:CANON_PUBLIC_TEXT_MAX_CHARS]}")

    # 3. 悬空伏笔（C2 换源：plot_ledgers 优先；未迁移书的存量 canon hook 兜底）
    hook_lines: List[str] = []
    try:
        from sqlalchemy import select as _select
        from backend.models import PlotLedger as _PlotLedger

        result = await db.execute(
            _select(_PlotLedger)
            .where(
                _PlotLedger.book_id == book_id,
                _PlotLedger.status == "open",
            )
            .limit(CANON_HOOK_LEDGER_FETCH_LIMIT)
        )
        ledgers = [
            l for l in result.scalars().all()
            if (l.canon_text or "").strip() or (l.public_text or "").strip()
        ][:CANON_HOOK_MAX_ENTRIES]
        for l in ledgers:
            strength = (l.meta or {}).get("strength", "?")
            hook_lines.append(f"- [{l.ledger_key}] 强度={strength}：{(l.canon_text or l.public_text or '')[:CANON_HOOK_TEXT_MAX_CHARS]}")
    except Exception as e:
        logger.warning(f"[Canon] 加载伏笔账本失败: {e}")

    covered_labels = {f"[{l.split(']')[0][1:]}]" for l in hook_lines if l.startswith("- [")}
    try:
        open_hooks = await repo.nodes.find_hooks(book_id, only_open=True)
    except Exception as e:
        logger.warning(f"[Canon] 加载 hooks 失败: {e}")
        open_hooks = []
    for h in open_hooks[:CANON_HOOK_MAX_ENTRIES]:
        if h.ref_id is not None:
            continue  # 已迁移并入账本（ledger 线已在上面），不重复
        if f"[{h.label}]" in covered_labels:
            continue
        meta = h.metadata_ or {}
        strength = meta.get("strength", "?")
        hook_lines.append(f"- [{h.label}] 强度={strength}：{h.canon_text[:CANON_HOOK_TEXT_MAX_CHARS]}")

    if hook_lines:
        parts.append("\n## 活跃伏笔 [hook]（本章可推进/回收）")
        parts.extend(hook_lines[:CANON_HOOK_MAX_ENTRIES])

    return "\n".join(parts) if parts else "（Canon 为空，无强约束）"


async def _resolve_world_labels(db: AsyncSession, book_id: UUID, nodes) -> dict:
    """C2：批量解析 ref 节点的世界侧真名（entity/location → name）。

    返回 {str(ref_id): name}；任何失败返回空 dict（调用方回退 node.label）。
    """
    ref_ids = {n.ref_id for n in nodes if getattr(n, "ref_id", None) is not None}
    if not ref_ids:
        return {}
    out: dict = {}
    try:
        from backend.repositories.world_repository import WorldRepository

        repo = WorldRepository(db)
        for ent in await repo.entities.list_by_book(book_id):
            if ent.id in ref_ids:
                out[str(ent.id)] = ent.name
        for loc in await repo.locations.list_by_book(book_id):
            if loc.id in ref_ids:
                out[str(loc.id)] = loc.name
    except Exception as e:
        logger.debug(f"[Canon] 世界名解析失败（回退 node.label）: {e}")
    return out
