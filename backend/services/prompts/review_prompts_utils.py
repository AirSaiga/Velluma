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
审阅提示词工具模块 - 审阅相关的工具函数。

职责：
- 提供审阅提示词的辅助函数
- 边界信息渲染
- 问题类型标准化
- 审阅结果解析

业务场景：
- 审阅提示词构建的辅助函数
- 审阅结果后处理

主要功能：
- 边界信息渲染
- 问题类型标准化
- 审阅结果解析

依赖项：
- backend.models: 数据模型
"""

import json
import re

from backend.models import Chapter


def render_boundary_brief(chapter: Chapter) -> str:
    beats = getattr(chapter, "story_beats", None)
    if not isinstance(beats, list) or not beats:
        return "暂无节拍边界数据，请结合章节大纲谨慎判定越界与配速风险。"
    ordered_beats = sorted(beats, key=lambda beat: getattr(beat, "position", 0) or 0)
    lines = []
    for idx, beat in enumerate(ordered_beats, start=1):
        summary = str(getattr(beat, "summary", "") or "").strip() or f"Beat {idx}"
        entry_state = str(getattr(beat, "entry_state", "") or "").strip() or "未提供"
        exit_state = str(getattr(beat, "exit_state", "") or "").strip() or "未提供"
        red_lines = getattr(beat, "red_lines", None)
        if isinstance(red_lines, list):
            red_line_items = [str(item).strip() for item in red_lines if str(item).strip()]
        else:
            red_line_items = []
        red_line_text = "；".join(red_line_items) if red_line_items else "无"
        lines.append(
            f"{idx}. {summary}\n"
            f"   - entry_state: {entry_state}\n"
            f"   - exit_state: {exit_state}\n"
            f"   - red_lines: {red_line_text}"
        )
    return "\n".join(lines)


def normalize_issue_type(raw_type, description: str) -> str:
    issue_type = str(raw_type or "").strip()
    normalized = issue_type.upper()
    description_text = str(description or "")
    lowered_issue_type = issue_type.lower()
    lowered_description = description_text.lower()
    if (
        normalized == "PACING_OVERFLOW"
        or "PACING_OVERFLOW" in normalized
        or "越界" in issue_type
        or "越过" in issue_type
        or "超速" in issue_type
        or "收束" in issue_type
        or "exit_state" in issue_type.lower()
        or "red_line" in issue_type.lower()
        or "越界" in description_text
        or "越过" in description_text
        or "超速" in description_text
        or "收束" in description_text
        or "exit_state" in description_text.lower()
        or "red_line" in description_text.lower()
    ):
        return "PACING_OVERFLOW"
    if (
        "完整性" in issue_type
        or "段落" in issue_type
        or "删段" in issue_type
        or "删减" in issue_type
        or "压缩" in issue_type
        or "integrity" in lowered_issue_type
        or "paragraph" in lowered_issue_type
        or "完整性" in description_text
        or "段落" in description_text
        or "删段" in description_text
        or "删减" in description_text
        or "压缩" in description_text
        or "integrity" in lowered_description
        or "paragraph" in lowered_description
    ):
        return "完整性缺失"
    if "OOC" in normalized:
        return "OOC"
    if "剧情遗漏" in issue_type or "PLOT MISSING" in normalized or "MISSING" in normalized:
        return "剧情遗漏"
    if "逻辑" in issue_type or "LOGIC" in normalized or "FLAW" in normalized:
        return "逻辑硬伤"
    return "逻辑硬伤"


def build_default_revision_plan(has_pacing_overflow: bool) -> str:
    if has_pacing_overflow:
        return "请先回退到越界前的收束节点，删除触发 red_lines 的情节，放慢叙事节奏并悬停在对应 exit_state，再补齐必要动机后输出完整正文。"
    return "请按章节大纲与角色设定修复逻辑问题，保留原文关键段落结构，避免大幅删段，并返回完整正文。"


def parse_review_result(review_result_raw: str):
    text = (review_result_raw or "").strip()
    if not text:
        return {
            "pass": False,
            "issues": [{"type": "审查异常", "severity": "high", "description": "Review Agent 返回为空，无法完成质检。", "target_beat_ids": []}],
            "revision_plan": "请基于章节大纲重新审查，并仅输出合法 JSON。",
            "target_beat_ids": [],
        }, "Empty response from Review Agent"
    candidates = [text]
    fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    candidates.extend(block.strip() for block in fenced_blocks if block and block.strip())
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.append(text[first_brace : last_brace + 1].strip())
    parsed_obj = None
    parse_error = None
    for candidate in candidates:
        try:
            parsed_obj = json.loads(candidate)
            break
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            parse_error = str(e)
    if not isinstance(parsed_obj, dict):
        return {
            "pass": False,
            "issues": [{"type": "审查异常", "severity": "high", "description": "Review Agent 返回内容无法解析为合法 JSON。", "target_beat_ids": []}],
            "revision_plan": "请严格按约定 JSON 结构输出审查结论，不要附加解释文本。",
            "target_beat_ids": [],
        }, parse_error or "Review JSON parse failed"
    raw_issues = parsed_obj.get("issues")
    normalized_issues = []
    all_target_beat_ids = set()
    if isinstance(raw_issues, list):
        for issue in raw_issues:
            if isinstance(issue, dict):
                description = str(issue.get("description") or "").strip()
                issue_type = normalize_issue_type(issue.get("type"), description)
                severity = str(issue.get("severity") or "").strip().lower()
                if severity not in {"high", "medium", "low"}:
                    severity = "medium"
                target_beat_ids = issue.get("target_beat_ids")
                if isinstance(target_beat_ids, list):
                    for bid in target_beat_ids:
                        if isinstance(bid, str) and bid.strip():
                            all_target_beat_ids.add(bid.strip())
                normalized_issues.append(
                    {
                        "type": issue_type,
                        "severity": severity,
                        "description": description or "未提供问题描述",
                        "target_beat_ids": target_beat_ids if isinstance(target_beat_ids, list) else [],
                    }
                )
            elif isinstance(issue, str) and issue.strip():
                description = issue.strip()
                normalized_issues.append(
                    {
                        "type": normalize_issue_type("", description),
                        "severity": "medium",
                        "description": description,
                        "target_beat_ids": [],
                    }
                )
    revision_plan = parsed_obj.get("revision_plan")
    has_pacing_overflow = any(issue.get("type") == "PACING_OVERFLOW" for issue in normalized_issues)
    if not isinstance(revision_plan, str) or not revision_plan.strip():
        revision_plan = build_default_revision_plan(has_pacing_overflow)
    elif has_pacing_overflow:
        lowered_revision_plan = revision_plan.lower()
        if (
            "回退" not in revision_plan
            and "exit_state" not in lowered_revision_plan
            and "悬停" not in revision_plan
            and "收束" not in revision_plan
        ):
            revision_plan = (
                f"{revision_plan.rstrip()}\n"
                "补充要求：请先回退越界剧情，放慢推进并悬停在对应 exit_state，确保不触发 red_lines。"
            )
    result = {
        "pass": bool(parsed_obj.get("pass", False)),
        "issues": normalized_issues,
        "revision_plan": revision_plan,
        "target_beat_ids": list(all_target_beat_ids)
    }
    return result, None
