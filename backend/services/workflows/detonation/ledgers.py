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
伏笔自动落账器（V3.0 Slice B 新建，V3.1 统一引擎更新）。

职责（设计文档 §5 Phase 9 + D5 伏笔即产物 + 3.1 §6 PlotLedger 来源）：
从铺垫结构图节点自动落账到 PlotLedger，零额外 LLM 调用。

业务流程（D5）：
- 树中 sets_up 指向未来章节高潮点的节点（Phase 2 生成时标记 future_payoff）
  → 自动写入 PlotLedger（status=open, action=plant, meta.planted_in_text=证据）
- 本章兑现的旧伏笔 → status=closed

V3.1（规格 §6）：登记来源标记从 "detonation_chain" 升级为 "setup_graph_auto"，
含 planted_in_text 证据。旧 ledgers 的 source 值不回填（数据无损约束）。

这是 PlotLedger 的"开账"路径（与 publish_v2.activate_plot_ledgers 的"闭账"对称）。

业务场景：
- workflow.execute 在生成完成后调用
- 每个带 future_payoff 标记的节点 → 一条 PlotLedger 记录

设计要点：
- 零 LLM 调用（证据来自 graph_auditor 的 planted_in_text 回填，或正文 substring 匹配）
- 幂等：同节点重复落账不重复插入（按 ledger_key 去重）
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def plant_ledgers_from_chain(
    db: AsyncSession,
    chain_id: UUID,
    book_id: UUID,
    chapter_id: UUID,
    nodes: List[Dict[str, Any]],
    full_text: str,
    chapter_number: Optional[int] = None,
) -> Dict[str, Any]:
    """从爆发链节点自动落账伏笔（开账）。

    Args:
        db: AsyncSession
        chain_id: 爆发链 id（写入 meta 供溯源）
        book_id: 书籍 id
        chapter_id: 章节 id
        nodes: SetupNode 列表
        full_text: 完整正文（substring 匹配证据用）
        chapter_number: 章节序号（写入 created_at_chapter）

    Returns:
        dict: {"planted": [{ledger_key, content, evidence}], "skipped": int, "degraded": Optional}
    """
    from backend.models import PlotLedger, generate_uuid
    from sqlalchemy import select

    planted: List[Dict[str, Any]] = []
    skipped = 0

    # 筛选带 future_payoff 标记的节点（跨章伏笔）
    future_nodes = [
        n for n in nodes
        if isinstance(n, dict) and n.get("future_payoff")
    ]

    if not future_nodes:
        # fallback：把所有 plant 类型节点也作为伏笔候选（更激进的落账策略）
        future_nodes = [
            n for n in nodes
            if isinstance(n, dict)
            and n.get("type") == "plant"
            and n.get("satisfied_by_existing") is None  # 排除已被前章事实满足的
        ]

    for node in future_nodes:
        node_id = str(node.get("id", ""))
        content = str(node.get("content", "")).strip()
        if not content:
            skipped += 1
            continue

        # ledger_key：按 chain_id + node_id 唯一（幂等）
        ledger_key = f"detonation_{chain_id}_{node_id}"

        # 检查是否已存在（幂等）
        existing_stmt = select(PlotLedger).where(
            PlotLedger.book_id == book_id,
            PlotLedger.ledger_key == ledger_key,
        )
        existing_result = await db.execute(existing_stmt)
        if existing_result.scalars().first():
            skipped += 1
            continue

        # 证据：优先用 graph_auditor 回填的 planted_in_text，否则 substring 匹配
        evidence = None
        planted_in = node.get("planted_in_text")
        if isinstance(planted_in, dict) and planted_in.get("quote"):
            evidence = planted_in["quote"]
        else:
            # 简化：取节点 content 的前 30 字在正文中查找
            probe = content[:30]
            offset = full_text.find(probe)
            if offset >= 0:
                evidence = full_text[offset:offset + 60]

        # future_payoff 信息（指向哪一章/哪个 payload）
        future_payoff = node.get("future_payoff") or {}

        try:
            ledger = PlotLedger(
                id=generate_uuid(),
                book_id=book_id,
                chapter_id=chapter_id,
                ledger_key=ledger_key,
                hook_id=f"h_{node_id[:8]}" if node_id else None,
                entry_type="foreshadow",
                content=content,
                status="open",
                created_at_chapter=chapter_number,
                meta={
                    # V3.1（规格 §6）：来源标记升级为 setup_graph_auto（含 planted_in_text 证据）
                    # 旧 ledgers 保留 "detonation_chain" 值，不回填
                    "source": "setup_graph_auto",
                    "chain_id": str(chain_id),
                    "node_id": node_id,
                    "node_type": node.get("type"),
                    "node_assignment": node.get("assignment"),
                    "planted_in_text": evidence,
                    "future_payoff": future_payoff,
                    "restraint_note": node.get("restraint_note"),
                },
            )
            db.add(ledger)
            planted.append({
                "ledger_key": ledger_key,
                "content": content[:80],
                "evidence": evidence[:80] if evidence else None,
            })
        except Exception as e:
            logger.warning(f"[Ledgers] 落账失败 node={node_id}: {e}")
            skipped += 1

    if planted:
        try:
            await db.flush()
            logger.info(f"[Ledgers] 自动落账 {len(planted)} 条伏笔（跳过 {skipped}）")
        except Exception as e:
            logger.warning(f"[Ledgers] flush 失败: {e}")
            return {
                "planted": [],
                "skipped": skipped,
                "degraded": {"reason": "flush_exception", "action": "skip_all", "detail": str(e)[:200]},
            }

    return {
        "planted": planted,
        "skipped": skipped,
        "degraded": None if planted or skipped == 0 else {"reason": "no_candidates", "action": "noop"},
    }


def count_auto_plant_rate(
    nodes: List[Dict[str, Any]],
    planted_count: int,
) -> float:
    """计算自动落账率（设计文档 §9 验收指标：≥90%）。

    落账率 = 已落账节点数 / 应落账节点数
    应落账 = future_payoff 节点 或 plant 类型节点（排除 satisfied_by_existing）
    """
    candidates = [
        n for n in nodes
        if isinstance(n, dict)
        and (n.get("future_payoff") or n.get("type") == "plant")
        and n.get("satisfied_by_existing") is None
    ]
    if not candidates:
        return 1.0  # 无应落账节点，视为 100%
    return planted_count / len(candidates)
