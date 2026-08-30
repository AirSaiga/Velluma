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
Canon 自动提取器（V4.0 新建）。

职责：
- 从已发布章节正文提取候选节点和边
- 默认进待确认队列（auto_commit=False）
- 作者确认后才写入 Canon

设计依据：docs/generation-v4.0-canon.md §3.2

业务场景：
- 章节发布后自动触发（hooks 在 chapter_publishing.py）
- routes/canon.py 的 POST /canon/extract 端点

使用方式：
    result = await extract_from_chapter(db, chapter_id, auto_commit=False)
    # result.extracted_nodes: List[dict]
    # result.committed: bool
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    CanonNode,
    NODE_TYPE_CHARACTER,
    NODE_TYPE_EVENT,
    NODE_TYPE_OBJECT,
    NODE_TYPE_PLACE,
    NODE_TYPE_HOOK,
    VISIBILITY_PUBLIC,
    EDGE_TYPE_CAUSES,
    EDGE_TYPE_BEFORE,
    EDGE_TYPE_HINTS,
    EDGE_TYPE_SETUPS,
)
from backend.repositories import (
    CanonRepository,
    ChapterRepository,
)
from backend.services.llm import call_llm_with_usage

logger = logging.getLogger(__name__)


# ============================================================
# 常量
# ============================================================

EXTRACT_MAX_TOKENS = 4096


# ============================================================
# Prompt 模板
# ============================================================

EXTRACT_SYSTEM = """你是叙事结构分析师。

任务：从一段小说正文中提取叙事知识图谱的候选节点和边。

# 节点类型
- character（角色）：有名有姓、有对话或显著动作的人物
- event（事件）：发生的事（如"兰星光球测试"、"老人察觉"）
- object（物件）：有特殊意义的物品（如"那枚焦痕"、"母亲遗物"）
- place（地点）：场景地点
- hook（伏笔）：作者埋下的、预期未来回收的伏笔

# 边类型
- causes（因果）：A 导致了 B
- before（时序）：A 在 B 之前
- hints（暗示）：A 隐晦暗示 B（弱伏笔）
- setups（强伏笔）：A 为 B 铺设
- callbacks（回收）：A 回收 B 的伏笔

# 提取规则
1. 只提取显著的节点（不要每个NPC都提取）
2. 节点 label 用简洁的中文（如"兰星"、"光球测试"）
3. canon_text 是该节点的事实陈述（10-50 字）
4. visibility 默认 public（已写出），但**如果是伏笔且故意没说透**，标 private
5. HOOK 节点的 metadata 要含 strength (1-10) 和 status="open"
6. 边要标注 strength (1-10)
7. 提取边时 source 和 target 用节点的 label（不是 id）

# 输出格式

严格 JSON：

```json
{
  "nodes": [
    {
      "type": "character",
      "label": "兰星",
      "canon_text": "平民出身的暗元素法师，隐藏弦月巅峰实力",
      "public_text": "星芒中级法师",
      "visibility": "public",
      "metadata": {}
    },
    {
      "type": "hook",
      "label": "针脚伏笔",
      "canon_text": "袖口三毫米歪斜的针脚暗示她曾剧烈震颤",
      "visibility": "private",
      "metadata": {"strength": 7, "status": "open", "bury_style": "implicit"}
    }
  ],
  "edges": [
    {
      "source_label": "针脚伏笔",
      "target_label": "兰星",
      "type": "hints",
      "strength": 7,
      "note": "针脚暗示兰星的真实实力"
    }
  ]
}
```"""

EXTRACT_USER_TEMPLATE = """# 章节信息
- 章节号：第 {chapter_number} 章
- 标题：{title}

# 章节正文

{body}

# 要求

提取本章的叙事节点和边。重点：
1. 不要漏掉伏笔（作者埋的、未来要回收的细节）
2. 区分 public（读者已经知道）和 private（作者没说透的伏笔）
3. 因果链和伏笔链是重点

返回严格 JSON。"""


# ============================================================
# 提取主入口
# ============================================================

async def extract_from_chapter(
    db: AsyncSession,
    chapter_id: UUID,
    auto_commit: bool = False,
    llm_enabled: bool = True,
) -> Dict[str, Any]:
    """从章节正文提取候选节点和边。

    Args:
        db: 数据库会话
        chapter_id: 章节 ID
        auto_commit: True=直接进 Canon；False=进待确认队列
        llm_enabled: True=调 LLM 提取；False=只用启发式（很弱）

    Returns:
        {
            "extracted_nodes": List[dict],
            "extracted_edges": List[dict],
            "committed": bool,
            "message": str,
        }
    """
    chapter_repo = ChapterRepository(db)
    chapter = await chapter_repo.get_by_id(str(chapter_id))
    if not chapter:
        return {
            "extracted_nodes": [],
            "extracted_edges": [],
            "committed": False,
            "message": "章节不存在",
        }

    # 取正文（优先 content_text，其次 draft_text）
    body = (chapter.content_text or chapter.draft_text or "").strip()
    if not body or len(body) < 200:
        return {
            "extracted_nodes": [],
            "extracted_edges": [],
            "committed": False,
            "message": "章节正文过短或为空",
        }

    # 截断到 6000 字（避免 token 失控）
    body_truncated = body[:6000]

    # 调 LLM 提取
    extracted = {"nodes": [], "edges": []}
    if llm_enabled:
        try:
            extracted = await _llm_extract(chapter, body_truncated)
        except Exception as e:
            logger.warning(f"[Canon] LLM 提取失败，降级启发式: {e}")
            extracted = _heuristic_extract(chapter, body_truncated)
    else:
        extracted = _heuristic_extract(chapter, body_truncated)

    # 提交到 Canon 或待确认队列
    if auto_commit and extracted["nodes"]:
        committed_count = await _commit_to_canon(db, chapter, extracted)
        return {
            "extracted_nodes": extracted["nodes"],
            "extracted_edges": extracted["edges"],
            "committed": True,
            "message": f"已写入 Canon {committed_count['nodes']} 节点 + {committed_count['edges']} 边",
        }
    else:
        # 进待确认队列（暂用内存返回，前端可存 localStorage；后续可加 pending 表）
        return {
            "extracted_nodes": extracted["nodes"],
            "extracted_edges": extracted["edges"],
            "committed": False,
            "message": f"提取 {len(extracted['nodes'])} 节点 + {len(extracted['edges'])} 边，待作者确认",
        }


# ============================================================
# LLM 提取
# ============================================================

async def _llm_extract(chapter: Any, body: str) -> Dict[str, List[Dict[str, Any]]]:
    """调用 LLM 提取节点和边。"""
    chapter_number = getattr(chapter, "chapter_number", 1) or 1
    title = getattr(chapter, "chapter_name", "") or getattr(chapter, "title", "") or ""

    user_prompt = EXTRACT_USER_TEMPLATE.format(
        chapter_number=chapter_number,
        title=title,
        body=body,
    )

    result = await call_llm_with_usage(
        system_prompt=EXTRACT_SYSTEM,
        user_prompt=user_prompt,
        model_type="reasoning",
        temperature=0.2,
        max_tokens=EXTRACT_MAX_TOKENS,
        response_format={"type": "json_object"},
    )

    return _parse_extract_response(result.content)


def _parse_extract_response(content: str) -> Dict[str, List[Dict[str, Any]]]:
    """解析 LLM 提取响应。"""
    if not content:
        return {"nodes": [], "edges": []}
    try:
        # 尝试直接解析
        data = json.loads(content)
    except json.JSONDecodeError:
        # 尝试从 ```json 围栏提取
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if fence_match:
            try:
                data = json.loads(fence_match.group(1))
            except json.JSONDecodeError:
                return {"nodes": [], "edges": []}
        else:
            brace_match = re.search(r"\{.*\}", content, re.DOTALL)
            if brace_match:
                try:
                    data = json.loads(brace_match.group(0))
                except json.JSONDecodeError:
                    return {"nodes": [], "edges": []}
            else:
                return {"nodes": [], "edges": []}

    nodes = data.get("nodes") or []
    edges = data.get("edges") or []
    # 字段标准化
    norm_nodes = []
    for n in nodes:
        if not isinstance(n, dict) or not n.get("label"):
            continue
        norm_nodes.append({
            "type": str(n.get("type", "event")),
            "label": str(n["label"])[:200],
            "canon_text": str(n.get("canon_text", "")),
            "public_text": str(n.get("public_text", "")),
            "visibility": str(n.get("visibility", "public")),
            "metadata": n.get("metadata", {}) or {},
            "source": "auto_extracted",
            "confidence": "tentative",
        })
    norm_edges = []
    for e in edges:
        if not isinstance(e, dict):
            continue
        src = e.get("source_label") or e.get("source")
        tgt = e.get("target_label") or e.get("target")
        if not src or not tgt:
            continue
        norm_edges.append({
            "source_label": str(src),
            "target_label": str(tgt),
            "type": str(e.get("type", "hints")),
            "strength": int(e.get("strength", 5)),
            "note": str(e.get("note", "")),
            "metadata": e.get("metadata", {}) or {},
        })

    return {"nodes": norm_nodes, "edges": norm_edges}


# ============================================================
# 启发式提取（降级，很弱）
# ============================================================

def _heuristic_extract(chapter: Any, body: str) -> Dict[str, List[Dict[str, Any]]]:
    """启发式提取（无 LLM，只做角色名提取）。"""
    nodes = []
    # 从 ChapterEntity 已经绑定的角色作为 character 节点
    # （完整提取需 LLM；这里只是降级）
    chapter_number = getattr(chapter, "chapter_number", 1) or 1
    nodes.append({
        "type": "event",
        "label": f"第{chapter_number}章事件",
        "canon_text": (getattr(chapter, "outline_text", "") or "")[:200],
        "public_text": "",
        "visibility": "public",
        "metadata": {"chapter_number": chapter_number},
        "source": "auto_extracted",
        "confidence": "tentative",
    })
    return {"nodes": nodes, "edges": []}


# ============================================================
# 提交到 Canon
# ============================================================

async def _commit_to_canon(
    db: AsyncSession,
    chapter: Any,
    extracted: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, int]:
    """把提取的节点/边写入 Canon。"""
    repo = CanonRepository(db)
    book_id = chapter.book_id
    chapter_number = getattr(chapter, "chapter_number", 1) or 1

    # 先创建所有节点，记录 label → id 映射
    label_to_id: Dict[str, UUID] = {}
    for n in extracted["nodes"]:
        try:
            node = await repo.create_node_if_not_exists(
                book_id=book_id,
                label=n["label"],
                node_type=n["type"],
                canon_text=n.get("canon_text", ""),
                public_text=n.get("public_text", ""),
                visibility=n.get("visibility", "public"),
                source=n.get("source", "auto_extracted"),
                confidence=n.get("confidence", "tentative"),
                metadata=n.get("metadata", {}),
            )
            label_to_id[n["label"]] = node.id
        except Exception as e:
            logger.warning(f"[Canon] 节点 [{n.get('label')}] 创建失败: {e}")

    # 创建边
    edge_count = 0
    for e in extracted["edges"]:
        src_label = e.get("source_label")
        tgt_label = e.get("target_label")
        src_id = label_to_id.get(src_label)
        tgt_id = label_to_id.get(tgt_label)
        if not src_id or not tgt_id:
            continue
        try:
            await repo.upsert_edge(
                book_id=book_id,
                source_id=src_id,
                target_id=tgt_id,
                edge_type=e["type"],
                strength=e.get("strength", 5),
                note=e.get("note", ""),
                established_in=[chapter_number],
                metadata=e.get("metadata", {}),
            )
            edge_count += 1
        except Exception as ex:
            logger.warning(f"[Canon] 边 [{src_label}->{tgt_label}] 创建失败: {ex}")

    return {"nodes": len(label_to_id), "edges": edge_count}
