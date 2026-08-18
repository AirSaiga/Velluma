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
# [旧表冻结声明 2026-08-19] 本模块仍读 characters/assets 等旧表（roadmap P2.4 显式冻结）：
# 世界页（world_*）是唯一编辑源；此处旧表读取冻结不动，下次实质改造时换源 world。
# 新代码勿再新增旧表依赖。

"""
章节发布状态回写强化服务（Phase 2 CP3.3 新建）。

职责（蓝图 §4.10 + decisions §3.5）：
- 增量角色状态更新：不再逐角色重发全文，改为只发"涉及该角色的片段"（修 P0-5）
- 输出含 evidence_quote（SCORE 原则），无证据的状态变更不入库
- PlotLedger 激活：1 次 light LLM，输入 chapter_card.foreshadow_ops + 文本裁剪版，
  输出每个 op 的执行状态（executed/skipped/modified）+ evidence_quote
- 滚动摘要更新：1 次 light LLM，合并 Book.rolling_summary + 本章 summary

业务场景：
- 在 chapter_publishing.py 的 publish 流程中调用（CP3.3）
- 与既有 publish.py 并存：既有 update_character_states 保留向后兼容；
  本模块的 update_character_states_incremental 是 CP3.3 升级版

降级策略（蓝图 P5 失败不静默）：
- LLM 调用失败 → 降级返回 None/evidence 空，不阻断发布
- evidence 为空的状态变更不入库（SCORE 原则）
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.services.llm import call_llm
from backend.services.workflows.utils import clean_llm_output

logger = logging.getLogger(__name__)


# ============================================================
# 工具：角色相关片段裁剪（修 P0-5）
# ============================================================

def extract_character_relevant_segments(
    full_text: str,
    character_name: str,
    aliases: Optional[List[str]] = None,
    window_chars: int = 400,
    max_segments: int = 8,
) -> str:
    """从全文中裁剪涉及指定角色的片段（修 P0-5：不再逐角色重发全文）。

    算法：
    - 扫描 character_name + aliases 在全文中的所有出现位置
    - 每个出现位置取前后 window_chars/2 字符为窗口
    - 合并重叠窗口
    - 限制最多 max_segments 个片段，超出按出现顺序截断

    Args:
        full_text: 章节全文
        character_name: 角色名
        aliases: 角色别名列表（可选）
        window_chars: 单个片段的总字符数（前后各 window_chars/2）
        max_segments: 最多返回的片段数（防止超长角色戏份 prompt 膨胀）

    Returns:
        str: 拼接后的相关片段（用 "[...]" 分隔）；若无匹配返回空字符串
    """
    if not full_text or not character_name:
        return ""

    match_names = [character_name] + (aliases or [])
    match_names = [n for n in match_names if n and len(n) >= 1]

    if not match_names:
        return ""

    # 收集所有出现位置
    positions: List[int] = []
    for name in match_names:
        start = 0
        while True:
            idx = full_text.find(name, start)
            if idx < 0:
                break
            positions.append(idx)
            start = idx + 1

    if not positions:
        return ""

    positions.sort()

    # 转为窗口区间并合并重叠
    half = window_chars // 2
    intervals: List[tuple] = []
    for pos in positions:
        lo = max(0, pos - half)
        hi = min(len(full_text), pos + half)
        if intervals and lo <= intervals[-1][1]:
            # 与上一个重叠 → 合并
            intervals[-1] = (intervals[-1][0], hi)
        else:
            intervals.append((lo, hi))

    # 限制片段数（取前 max_segments 个，覆盖最早出现的戏份）
    intervals = intervals[:max_segments]

    # 提取并拼接
    segments: List[str] = []
    for lo, hi in intervals:
        segment = full_text[lo:hi].strip()
        if segment:
            segments.append(segment)

    return "\n[...]\n".join(segments)


# ============================================================
# 1. 增量角色状态更新（蓝图 §4.10 第 3 步）
# ============================================================

@dataclass
class CharacterStateUpdateV2:
    """CP3.3 增量角色状态更新结果。

    与既有 CharacterUpdateResult 区别：
    - 含 evidence_quote（SCORE 原则）：状态变更必须有原文证据
    - evidence_quote 为空 → 不入库（decisions §3.5 / 蓝图 §4.10 总纲）
    """

    character_id: str
    character_name: str
    old_state: str
    new_state: str
    evidence_quote: Optional[str] = None
    success: bool = True
    error_message: str = ""
    skipped: bool = False  # True 表示无相关片段，跳过更新


def build_incremental_character_update_prompt(
    *,
    character_name: str,
    static_prompt: str,
    old_dynamic_state: str,
    history_states: List[str],
    relevant_segments: str,
) -> tuple[str, str]:
    """构建增量角色状态更新 prompt（蓝图 §4.10）。

    输出契约（JSON）：
    {
      "new_dynamic_state": "更新后的状态描述（100-200 字）",
      "evidence_quote": "原文中支撑状态变更的引用（≤80字）"
    }

    evidence_quote 为空表示无证据 → 调用方应跳过入库。
    """
    history_str = "\n".join(history_states) if history_states else "暂无历史状态"

    system_prompt = """你是小说角色状态分析师。基于角色相关片段（而非全文），更新角色动态状态。

【SCORE 原则】状态变更必须有原文证据：
- 必须从"角色相关片段"中摘录 evidence_quote（≤80字），证明状态变更的依据
- 若片段中无明确支撑状态变更的原文，evidence_quote 返回空字符串
- 严禁基于推断/脑补生成 evidence_quote

【更新规则】
1. 保留关键身份信息（年龄、家族、核心能力、职业）
2. 整合本片段中发生的重大事件、心理变化、人际关系进展
3. 保持角色性格一致性
4. 字数 100-200 字，精炼不流水账

【输出契约】严格 JSON（无 Markdown 标记）：
{
  "new_dynamic_state": "更新后的状态描述",
  "evidence_quote": "原文引用（≤80字），无证据时为空字符串"
}"""

    user_prompt = f"""请更新角色动态状态：

【角色信息】
角色名：{character_name}
角色设定：{static_prompt or "暂无设定"}

【当前动态状态】
{old_dynamic_state}

【历史动态状态】
{history_str}

【角色相关片段】（已从全文裁剪，仅含该角色出现的段落）
{relevant_segments}

请输出 JSON。"""

    return system_prompt, user_prompt


async def update_character_states_incremental(
    character_list: List[Any],
    chapter: Any,
    character_repository: Any,
    chapter_text: Optional[str] = None,
) -> List[CharacterStateUpdateV2]:
    """CP3.3 增量角色状态更新（蓝图 §4.10 第 3 步，修 P0-5）。

    与既有 update_character_states 区别：
    - 输入改为"涉及该角色的片段"（裁剪），不再逐角色重发全文
    - 输出含 evidence_quote，无证据的状态变更不入库
    - 无相关片段的角色直接 skip（不浪费 LLM 调用）

    Args:
        character_list: 角色列表
        chapter: 章节对象
        character_repository: CharacterRepository 实例
        chapter_text: 可选的章节正文（默认从 chapter.content_text/draft_text 读）

    Returns:
        List[CharacterStateUpdateV2]
    """
    import json

    text = chapter_text
    if text is None:
        text = (getattr(chapter, "content_text", None) or getattr(chapter, "draft_text", None) or "")

    results: List[CharacterStateUpdateV2] = []

    for character in character_list:
        if not character:
            continue

        char_id = str(character.id)
        char_name = character.name
        old_state = character.dynamic_state or "暂无动态状态"

        # 裁剪角色相关片段
        aliases = getattr(character, "aliases", None) or []
        relevant = extract_character_relevant_segments(text, char_name, aliases)

        if not relevant:
            # 无相关片段 → 跳过（不浪费 LLM 调用）
            results.append(CharacterStateUpdateV2(
                character_id=char_id,
                character_name=char_name,
                old_state=old_state,
                new_state=old_state,
                evidence_quote=None,
                success=True,
                skipped=True,
            ))
            logger.debug(f"[PublishV2] 角色 {char_name} 本章无相关片段，跳过状态更新")
            continue

        # 历史 state（最多 3 条）
        history_states: List[str] = []
        hist = getattr(character, "dynamic_state_history", None) or []
        for item in hist[-3:]:
            if isinstance(item, dict):
                state = item.get("state", "")
                updated_at = item.get("updated_at", "")
                if state:
                    history_states.append(f"- {updated_at}: {state}")

        system_prompt, user_prompt = build_incremental_character_update_prompt(
            character_name=char_name,
            static_prompt=getattr(character, "static_prompt", "") or "",
            old_dynamic_state=old_state,
            history_states=history_states,
            relevant_segments=relevant,
        )

        try:
            response = await call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="light",
                temperature=0.3,
                response_format={"type": "json_object"},
                max_tokens=600,
            )
            parsed = json.loads(clean_llm_output(response))
            new_state = (parsed.get("new_dynamic_state") or "").strip()
            evidence = (parsed.get("evidence_quote") or "").strip()

            if not new_state:
                results.append(CharacterStateUpdateV2(
                    character_id=char_id, character_name=char_name,
                    old_state=old_state, new_state=old_state,
                    evidence_quote=None, success=False,
                    error_message="empty_new_state",
                ))
                continue

            # SCORE 原则：无证据不入库
            if not evidence:
                logger.info(
                    f"[PublishV2] 角色 {char_name} 状态变更无 evidence_quote，跳过入库"
                )
                results.append(CharacterStateUpdateV2(
                    character_id=char_id, character_name=char_name,
                    old_state=old_state, new_state=old_state,
                    evidence_quote=None, success=True, skipped=True,
                ))
                continue

            # 入库
            character.dynamic_state = new_state
            history = getattr(character, "dynamic_state_history", None) or []
            from datetime import datetime, timezone
            history.append({
                "state": new_state,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "evidence_quote": evidence,
            })
            if len(history) > 10:
                history = history[-10:]
            character.dynamic_state_history = history
            await character_repository.commit_and_refresh(character)

            results.append(CharacterStateUpdateV2(
                character_id=char_id, character_name=char_name,
                old_state=old_state, new_state=new_state,
                evidence_quote=evidence, success=True,
            ))

        except Exception as e:
            logger.warning(
                f"[PublishV2] 角色 {char_name} 增量状态更新失败，降级跳过: "
                f"{type(e).__name__}: {e}"
            )
            results.append(CharacterStateUpdateV2(
                character_id=char_id, character_name=char_name,
                old_state=old_state, new_state=old_state,
                evidence_quote=None, success=False,
                error_message=f"{type(e).__name__}: {str(e)[:200]}",
            ))

    return results


# ============================================================
# 2. PlotLedger 激活（蓝图 §4.10 第 4 步 + decisions §3.5）
# ============================================================

@dataclass
class ForeshadowOpStatus:
    """单个伏笔操作的执行状态判定结果。"""

    ledger_id: str
    action: Optional[str]   # 声明的 action（plant/advance/close/drop）
    status: str             # executed / skipped / modified
    evidence_quote: Optional[str]
    note: Optional[str]


def _prefilter_foreshadow_segments(
    full_text: str,
    foreshadow_ops: List[Dict[str, Any]],
    window_chars: int = 300,
) -> str:
    """关键词预筛：对 foreshadow_ops 的 note 提取关键词，从全文中裁剪相关段落。

    decisions §3.5：输入"章节文本裁剪版（仅含涉及伏笔的段落，由代码级关键词预筛）"。
    """
    if not full_text or not foreshadow_ops:
        return ""

    # 收集所有关键词（从 note 中提取 ≥2 字的中文/英文片段）
    keywords: set = set()
    for op in foreshadow_ops:
        if not isinstance(op, dict):
            continue
        note = op.get("note") or ""
        if note:
            # 提取 ≥2 字的连续中文/英文/数字片段
            for kw in re.findall(r"[\u4e00-\u9fa5A-Za-z]{2,}", note):
                keywords.add(kw)

    if not keywords:
        return ""

    # 找关键词位置 → 窗口 → 合并
    positions: List[int] = []
    for kw in keywords:
        start = 0
        while True:
            idx = full_text.find(kw, start)
            if idx < 0:
                break
            positions.append(idx)
            start = idx + 1

    if not positions:
        return ""

    positions.sort()
    half = window_chars // 2
    intervals: List[tuple] = []
    for pos in positions:
        lo = max(0, pos - half)
        hi = min(len(full_text), pos + half)
        if intervals and lo <= intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], hi)
        else:
            intervals.append((lo, hi))

    segments = [full_text[lo:hi].strip() for lo, hi in intervals if full_text[lo:hi].strip()]
    return "\n[...]\n".join(segments[:10])  # 最多 10 段


def build_plotledger_activation_prompt(
    *,
    foreshadow_ops: List[Dict[str, Any]],
    relevant_text: str,
) -> tuple[str, str]:
    """构建 PlotLedger 激活 prompt（decisions §3.5）。"""
    ops_lines = []
    for i, op in enumerate(foreshadow_ops):
        if not isinstance(op, dict):
            continue
        ops_lines.append(
            f"  [{i}] ledger_id={op.get('ledger_id', '?')} "
            f"action={op.get('action', '?')} note={op.get('note', '')}"
        )
    ops_block = "\n".join(ops_lines)

    system_prompt = """你是小说伏笔执行状态判定员。基于章节文本片段，判定每个伏笔操作（foreshadow_op）的实际执行情况。

【SCORE 原则】无原文证据的判定不得标 executed/modified：
- executed：本章已按声明落地该伏笔 → 必须附 evidence_quote（原文能找到的引用）
- modified：本章触及该伏笔但与声明方式不同 → 必须附 evidence_quote
- skipped：本章未触及该伏笔（evidence_quote 可空）

【输出契约】严格 JSON：
{
  "statuses": [
    {
      "ledger_id": "...",
      "status": "executed|skipped|modified",
      "evidence_quote": "原文引用（≤80字）",
      "note": "判定说明"
    }
  ]
}"""

    user_prompt = f"""请判定以下伏笔操作的执行状态：

【伏笔操作声明】
{ops_block}

【章节相关片段】（已预筛，仅含可能涉及伏笔的段落）
{relevant_text}

请输出 JSON。每个 foreshadow_op 必须在 statuses 中对应一项。"""

    return system_prompt, user_prompt


async def activate_plot_ledgers(
    foreshadow_ops: List[Dict[str, Any]],
    chapter_text: str,
    plot_ledger_repository: Any,
    chapter_id: Any,
    chapter_number: Optional[int] = None,
) -> List[ForeshadowOpStatus]:
    """CP3.3 PlotLedger 激活（decisions §3.5）。

    流程：
    1. 关键词预筛章节文本（裁剪）
    2. 1 次 light LLM 判定每个 op 的 status + evidence_quote
    3. 无 evidence 的 executed/modified 降级为 skipped
    4. 按 status 更新 PlotLedger（executed → closed；skipped → 保留 open；modified → 保留 open + meta）

    Args:
        foreshadow_ops: chapter_card.foreshadow_ops
        chapter_text: 章节正文
        plot_ledger_repository: PlotLedgerRepository 实例
        chapter_id: 当前章节 ID（用于 resolved_in_chapter_id）
        chapter_number: 当前章节序号（用于日志）

    Returns:
        List[ForeshadowOpStatus]
    """
    import json

    if not foreshadow_ops:
        return []

    relevant_text = _prefilter_foreshadow_segments(chapter_text, foreshadow_ops)
    if not relevant_text:
        # 无相关段落 → 全部 skipped
        return [
            ForeshadowOpStatus(
                ledger_id=str(op.get("ledger_id", "")),
                action=op.get("action"),
                status="skipped",
                evidence_quote=None,
                note="no_relevant_text_after_prefilter",
            )
            for op in foreshadow_ops if isinstance(op, dict)
        ]

    system_prompt, user_prompt = build_plotledger_activation_prompt(
        foreshadow_ops=foreshadow_ops,
        relevant_text=relevant_text,
    )

    try:
        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_type="light",
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=1500,
        )
        parsed = json.loads(clean_llm_output(response))
        raw_statuses = parsed.get("statuses") or []
    except Exception as e:
        logger.warning(
            f"[PublishV2] PlotLedger 激定 LLM 调用失败，全部降级 skipped: "
            f"{type(e).__name__}: {e}"
        )
        return [
            ForeshadowOpStatus(
                ledger_id=str(op.get("ledger_id", "")),
                action=op.get("action"),
                status="skipped",
                evidence_quote=None,
                note=f"llm_failed: {type(e).__name__}",
            )
            for op in foreshadow_ops if isinstance(op, dict)
        ]

    # 规范化 + evidence 约束 + DB 更新
    valid_statuses = {"executed", "skipped", "modified"}
    statuses: List[ForeshadowOpStatus] = []

    for raw in raw_statuses:
        if not isinstance(raw, dict):
            continue
        ledger_id = str(raw.get("ledger_id") or "")
        if not ledger_id:
            continue
        status = raw.get("status", "skipped")
        if status not in valid_statuses:
            status = "skipped"
        evidence = (raw.get("evidence_quote") or "").strip()
        # SCORE 约束：executed/modified 必须有 evidence，否则降级 skipped
        if status in ("executed", "modified") and not evidence:
            status = "skipped"

        statuses.append(ForeshadowOpStatus(
            ledger_id=ledger_id,
            action=None,  # 由调用方按 ledger_id 查 op 填充
            status=status,
            evidence_quote=evidence[:200] if evidence else None,
            note=(raw.get("note") or "")[:300] or None,
        ))

    # 按 ledger_id 建 op 索引，补 action
    op_map = {str(op.get("ledger_id", "")): op for op in foreshadow_ops if isinstance(op, dict)}
    for st in statuses:
        op = op_map.get(st.ledger_id)
        if op:
            st.action = op.get("action")

    # DB 更新：executed → closed（resolved_in_chapter_id）；modified → meta；skipped 不动
    try:
        from backend.models import PlotLedgerStatus
        for st in statuses:
            # 按 ledger_id 查记录
            # PlotLedgerRepository 没有按 ledger_id 单查的方法，用 find_one
            from backend.models import PlotLedger
            record = await plot_ledger_repository.find_one(
                conditions=[PlotLedger.ledger_key == st.ledger_id],
            )
            if not record:
                continue
            if st.status == "executed":
                record.status = PlotLedgerStatus.CLOSED.value
                record.resolved_in_chapter_id = chapter_id
                meta = dict(record.meta or {})
                meta["cp33_evidence_quote"] = st.evidence_quote
                meta["cp33_note"] = st.note
                record.meta = meta
            elif st.status == "modified":
                meta = dict(record.meta or {})
                meta["cp33_status"] = "modified"
                meta["cp33_evidence_quote"] = st.evidence_quote
                meta["cp33_note"] = st.note
                record.meta = meta
            # skipped: 不修改
        await plot_ledger_repository.commit()
        logger.info(
            f"[PublishV2] PlotLedger 激活完成: executed={sum(1 for s in statuses if s.status=='executed')}, "
            f"modified={sum(1 for s in statuses if s.status=='modified')}, "
            f"skipped={sum(1 for s in statuses if s.status=='skipped')}"
        )
    except Exception as e:
        logger.warning(f"[PublishV2] PlotLedger DB 更新失败（不影响返回）: {type(e).__name__}: {e}")

    return statuses


# ============================================================
# 3. 滚动摘要更新（蓝图 §4.10 第 2 步）
# ============================================================

async def update_rolling_summary(
    book_repository: Any,
    book_id: Any,
    chapter_summary: str,
    chapter_number: Optional[int] = None,
) -> Optional[str]:
    """CP3.3 滚动摘要更新（蓝图 §4.10 第 2 步）。

    流程：
    - 读 Book.rolling_summary（旧）
    - 1 次 light LLM 合并压缩：旧摘要 + 本章摘要 → 新滚动摘要
    - 写回 Book.rolling_summary

    滚动摘要供下一章 ContextEngine P1 使用（CP2.3a 已加字段）。

    Args:
        book_repository: BookRepository 实例
        book_id: 书籍 ID
        chapter_summary: 本章摘要
        chapter_number: 本章序号（用于日志）

    Returns:
        新的 rolling_summary，或 None（失败时）
    """
    import json

    book = await book_repository.get_by_id(book_id)
    if not book:
        logger.warning(f"[PublishV2] 滚动摘要更新失败：书籍 {book_id} 不存在")
        return None

    old_rolling = getattr(book, "rolling_summary", None) or ""

    # 若本章无摘要，跳过
    if not chapter_summary or not chapter_summary.strip():
        logger.debug(f"[PublishV2] 本章 {chapter_number} 无摘要，跳过滚动摘要更新")
        return old_rolling or None

    system_prompt = """你是小说章节摘要合并器。将"已有滚动摘要"与"本章摘要"合并为新的滚动摘要。

【合并原则】
1. 保持时序：先旧事件，后新事件
2. 压缩冗余：相同信息只保留一次
3. 保留关键转折、角色状态变化、伏笔进展
4. 字数控制：不超过 600 字（避免后续章节 ContextEngine 注入过长）

【输出契约】严格 JSON：
{
  "rolling_summary": "合并后的滚动摘要（≤600字）"
}"""

    user_prompt = f"""请合并滚动摘要：

【已有滚动摘要】
{old_rolling or "（首章，暂无历史摘要）"}

【本章（第{chapter_number or '?'}章）摘要】
{chapter_summary}

请输出 JSON。"""

    try:
        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_type="light",
            temperature=0.2,
            response_format={"type": "json_object"},
            max_tokens=1000,
        )
        parsed = json.loads(clean_llm_output(response))
        new_rolling = (parsed.get("rolling_summary") or "").strip()
        if not new_rolling:
            logger.warning("[PublishV2] 滚动摘要合并返回空，保留旧摘要")
            return old_rolling or None

        book.rolling_summary = new_rolling
        await book_repository.commit_and_refresh(book)
        logger.info(
            f"[PublishV2] 滚动摘要更新成功: 章节={chapter_number}, "
            f"长度={len(new_rolling)}"
        )
        return new_rolling

    except Exception as e:
        logger.warning(
            f"[PublishV2] 滚动摘要更新失败，降级保留旧摘要: "
            f"{type(e).__name__}: {e}"
        )
        return old_rolling or None
