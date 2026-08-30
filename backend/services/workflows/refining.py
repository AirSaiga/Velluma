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
精修阶段工作流 - 基于审阅意见重写章节。

职责：
- 根据审阅报告中的 revision_plan 重写章节
- 修复审阅中发现的问题
- 保持章节整体结构和风格一致

业务场景：
- 章节生成的精修阶段（可选）
- 审阅发现质量问题后的修复
- 迭代优化的最后一轮

主要功能：
- 精准修改（基于 revision_plan）
- 保持风格一致性
- 字数控制

依赖项：
- backend.services.prompts: Refine Prompt 模板
- backend.services.llm: LLM 调用接口

使用方式：
    refined_text = await refine_draft(chapter, book, current_draft, revision_plan, ...)
"""

from typing import Any, Optional

from backend.services.prompts import build_refine_agent_prompt
from backend.services.llm import call_llm, call_llm_with_usage
from backend.services.workflows.utils import clean_llm_output
from backend.models import Chapter, Book, Character, CharacterRelationship
from backend.services.utils.prompt_logger import PromptLogger


async def refine_draft(
    chapter: Chapter,
    book: Book,
    entities: list[Any],
    relationships: list[CharacterRelationship],
    current_draft: str,
    revision_plan: str,
    word_count: int,
    recorder: Optional[Any] = None,
) -> str:
    """根据审阅意见精修章节初稿。

    Args:
        chapter: 章节实体
        book: 书籍实体
        entities: 章节关联的角色实体列表
        relationships: 角色关系列表
        current_draft: 当前草稿文本
        revision_plan: 审阅意见/修改计划
        word_count: 目标字数
        recorder: 可选的 RunRecorder 实例（Phase 0 观测层）

    Returns:
        str: 精修后的正文
    """
    system_prompt, user_prompt = build_refine_agent_prompt(
        chapter, book, entities, relationships, current_draft, revision_plan, word_count
    )

    # T1 观测层 + T2 creative 槽
    if recorder is not None:
        async with recorder.record_call(stage="refining.chapter", model_slot="creative") as ctx:
            llm_result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.7,
                max_tokens=10000,
                model_type="creative",
            )
            ctx.set_result(llm_result)
        refined_text = llm_result.content
    else:
        refined_text = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.7,
            max_tokens=10000,
            model_type="creative",
        )

    return clean_llm_output(refined_text)


async def refine_single_beat(
    beat: dict,
    original_chunk: str,
    revision_guide: str,
    issue_descriptions: list[str],
    chapter: Chapter,
    book: Book,
    previous_tail: str = "",
    beat_id: str = None,
    all_issues: list[dict] = None,
    prompt_logger: Optional[PromptLogger] = None,
    recorder: Optional[Any] = None,
    evidence_findings: Optional[list[dict]] = None,
    max_iterations: int = 2,
) -> str:
    """对单个 Beat 进行精准局部重写。

    基于 Review Agent 给出的审查驳回原因和修改计划，对指定 Beat 的草稿
    进行针对性精修。通过强调驳回原因和具体问题，确保 LLM 严格遵循修改指令。

    【Bug 1 修复 - 精准制导打点精修】
    实现算法：I_k = { i ∈ I | k ∈ i.target_beat_ids }
    只将 target_beat_ids 包含当前 beat_id 的 issues 传入该 beat 的精修。

    【CP3.2 改造 - 证据驱动精修】（蓝图 §4.9）
    新增 evidence_findings 参数：来自 QualityReport.findings 的结构化证据，
    每个 finding 含 quote / detail / suggestion / offset / severity。
    精修 prompt 注入"原文引用：{quote}；问题：{detail}；建议：{suggestion}"。
    ≤ max_iterations 轮收敛，未解决 → degraded 标记（蓝图 P10 原则）。

    Args:
        beat: Beat 信息字典，应包含 summary、pov_character、entry_state、
              exit_state、red_lines 等字段
        original_chunk: 待修改的原始草稿文本
        revision_guide: Review Agent 给出的全局修改计划
        issue_descriptions: 针对该 beat 的具体问题描述列表（兼容性保留）
        chapter: 章节实体
        book: 书籍实体
        previous_tail: 前一 Beat 的尾巴文本，用于保持语气衔接
        beat_id: 当前 Beat 的唯一标识（用于精准匹配 issues）
        all_issues: Review Agent 返回的所有 issues 列表，包含 target_beat_ids
        evidence_findings: CP3.2 证据驱动；QualityReport.findings 中
                          target_beat_ids 包含当前 beat 的项（结构化证据）
        max_iterations: CP3.2 收敛轮数上限（默认 2，蓝图 §4.9）

    Returns:
        str: 精修后的正文
    """
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"

    # =======================================================================
    # Bug 1 修复：精准制导打点精修 - 只传入与当前 beat 相关的 issues
    # 算法：I_k = { i ∈ I | k ∈ i.target_beat_ids }
    # =======================================================================
    targeted_issues = []

    if all_issues and isinstance(all_issues, list):
        # 从 beat 中提取 beat_id
        current_beat_id = beat_id or beat.get("beat_id") or beat.get("id")
        if current_beat_id:
            for issue in all_issues:
                if isinstance(issue, dict):
                    target_beat_ids = issue.get("target_beat_ids", [])
                    # 如果 issue 没有指定 target_beat_ids，或包含当前 beat_id，则适用
                    if not target_beat_ids or current_beat_id in target_beat_ids:
                        targeted_issues.append(issue.get("description", ""))

    # 合并传入的 issue_descriptions（兼容性处理）
    if issue_descriptions:
        targeted_issues.extend([desc for desc in issue_descriptions if desc])

    # 去重
    targeted_issues = list(dict.fromkeys(targeted_issues))

    # 构建问题描述列表
    issues_text = ""
    if targeted_issues:
        issues_list = "\n".join(f"- {desc}" for desc in targeted_issues if desc)
        issues_text = f"""
针对本段的具体问题：
{issues_list}
"""

    # =======================================================================
    # CP3.2：证据驱动精修 - 注入 QualityReport.findings 结构化证据（蓝图 §4.9）
    # =======================================================================
    evidence_text = ""
    if evidence_findings:
        evidence_lines = []
        for ev in evidence_findings:
            if not isinstance(ev, dict):
                continue
            quote = (ev.get("quote") or "").strip()
            detail = (ev.get("detail") or "").strip()
            suggestion = (ev.get("suggestion") or "").strip()
            severity = ev.get("severity", "warning")
            category = ev.get("category", "")
            if not detail:
                continue  # 无 detail 的证据无价值
            line_parts = [f"[{severity}|{category}]"]
            if quote:
                line_parts.append(f"原文引用：{quote}")
            line_parts.append(f"问题：{detail}")
            if suggestion:
                line_parts.append(f"建议：{suggestion}")
            evidence_lines.append("；".join(line_parts))
        if evidence_lines:
            evidence_block = "\n".join(f"- {ln}" for ln in evidence_lines)
            evidence_text = f"""
【证据驱动精修 - 来自双层审计 QualityReport.findings】
以下每条证据都附原文引用与修复建议，请逐条对照修复：
{evidence_block}
"""

    # 构建 system_prompt - 强调审查驳回原因与修改指令
    system_prompt = f"""{global_sys_prompt}

你是一个精修编辑。你之前的草稿被编辑驳回，请根据以下修改指令重新生成本段内容。

【审查驳回原因与修改指令】
你之前的草稿被编辑驳回。原因及修改计划如下：
{revision_guide}
{issues_text}{evidence_text}
请严格遵守上述修改计划，重新生成本段的内容。保持原有的优秀动作描写，但必须彻底根除上面指出的问题！

## 你的任务
根据修改指令重写片段，保持原有风格和情节连贯性，同时彻底修复指出的所有问题。
直接输出修改后的正文，不要包含任何解释、标题或元信息。"""

    # 提取 beat 信息
    beat_summary = beat.get("summary", "")
    pov_character = beat.get("pov_character", "")
    entry_state = beat.get("entry_state", "")
    exit_state = beat.get("exit_state", "")
    red_lines = beat.get("red_lines", [])

    # 构建红线说明
    red_lines_text = ""
    if red_lines:
        if isinstance(red_lines, list):
            red_lines_text = f"\n【红线（禁止触碰）】\n" + "\n".join(f"- {rl}" for rl in red_lines)
        elif isinstance(red_lines, str):
            red_lines_text = f"\n【红线（禁止触碰）】\n{red_lines}"

    # 构建前文衔接说明
    tail_text = ""
    if previous_tail:
        tail_text = f"""
【前文衔接参考】
以下是前一段的末尾文本，请确保语气和节奏自然衔接：
---
{previous_tail[-500:]}
---
"""

    # 构建 user_prompt
    user_prompt = f"""请重写以下片段：

【剧情摘要】
{beat_summary}

【视角人物】
{pov_character if pov_character else "未指定"}

【入场状态】
{entry_state if entry_state else "未指定"}

【退场状态】
{exit_state if exit_state else "未指定"}
{red_lines_text}
{tail_text}
【待修改的原始草稿】
---
{original_chunk}
---

请直接输出修改后的正文，不要包含任何解释或标记。"""

    if prompt_logger:
        beat_label = f"FUSION_REFINE_BEAT_{beat_id or beat.get('beat_id', 'unknown')}"
        prompt_logger.log_prompts(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.7,
            max_tokens=6000,
            prompt_label=beat_label,
        )

    # 单次 LLM 调用封装（供多轮收敛复用）
    async def _call_refine(sys_p: str, usr_p: str, stage_suffix: str = "") -> str:
        stage = f"refining.beat.{beat_id or beat.get('beat_id', 'unknown')}{stage_suffix}"
        if recorder is not None:
            async with recorder.record_call(stage=stage, model_slot="creative") as ctx:
                llm_result = await call_llm_with_usage(
                    system_prompt=sys_p,
                    user_prompt=usr_p,
                    temperature=0.7,
                    max_tokens=6000,
                    model_type="creative",
                )
                ctx.set_result(llm_result)
            return llm_result.content
        return await call_llm(
            system_prompt=sys_p,
            user_prompt=usr_p,
            temperature=0.7,
            max_tokens=6000,
            model_type="creative",
        )

    # 第 1 轮精修
    refined_text = await _call_refine(system_prompt, user_prompt)
    refined_text = clean_llm_output(refined_text)

    # =======================================================================
    # CP3.2 收敛：若存在 blocker 级证据且 max_iterations >= 2，跑第 2 轮加强修复
    # 蓝图 §4.9：≤2 轮收敛，未解决 → degraded（由调用方 stream_handler 标记）
    # =======================================================================
    has_blocker_evidence = bool(evidence_findings) and any(
        isinstance(ev, dict) and ev.get("severity") == "blocker"
        for ev in evidence_findings
    )
    if (
        has_blocker_evidence
        and max_iterations >= 2
        and refined_text.strip()
    ):
        # 第 2 轮：基于第 1 轮产出加强修复，重申 blocker 证据
        blocker_lines = []
        for ev in (evidence_findings or []):
            if isinstance(ev, dict) and ev.get("severity") == "blocker":
                quote = (ev.get("quote") or "").strip()
                detail = (ev.get("detail") or "").strip()
                suggestion = (ev.get("suggestion") or "").strip()
                if not detail:
                    continue
                parts = []
                if quote:
                    parts.append(f"原文引用：{quote}")
                parts.append(f"问题：{detail}")
                if suggestion:
                    parts.append(f"建议：{suggestion}")
                blocker_lines.append("- " + "；".join(parts))
        blocker_block = "\n".join(blocker_lines) if blocker_lines else ""

        second_system = f"""{system_prompt}

## 第 2 轮加强修复（blocker 级证据未在第 1 轮完全解决）
以下 blocker 级证据必须在本次重写中彻底根除：
{blocker_block}

请基于第 1 轮的产出再次重写，确保 blocker 问题完全消失。"""
        second_user = f"""请基于第 1 轮的产出再次重写：

【第 1 轮产出（待二次修复）】
---
{refined_text}
---

请直接输出二次修复后的正文，彻底根除上述 blocker 证据。"""

        if prompt_logger:
            prompt_logger.log_prompts(
                system_prompt=second_system,
                user_prompt=second_user,
                temperature=0.7,
                max_tokens=6000,
                prompt_label=f"FUSION_REFINE_BEAT_{beat_id or beat.get('beat_id', 'unknown')}_ITER2",
            )

        try:
            second_text = await _call_refine(second_system, second_user, stage_suffix=".iter2")
            second_text = clean_llm_output(second_text)
            if second_text.strip():
                refined_text = second_text
        except Exception as e:
            # 第 2 轮失败 → 保留第 1 轮产出（降级，不阻断）
            import logging
            logging.getLogger(__name__).warning(
                f"[Refine] beat {beat_id} 第 2 轮收敛失败，保留第 1 轮产出: "
                f"{type(e).__name__}: {e}"
            )
            if recorder is not None:
                recorder.record_degraded(
                    stage=f"refining.beat.{beat_id or beat.get('beat_id', 'unknown')}.iter2",
                    reason="convergence_iter2_exception",
                    action="kept_iter1_output",
                    model_slot="creative",
                    detail=f"{type(e).__name__}: {str(e)[:200]}",
                )

    return refined_text