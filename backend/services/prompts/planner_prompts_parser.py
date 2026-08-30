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
规划提示词解析器 - 解析 Planner Agent 的输出。

职责：
- 解析 LLM 返回的规划结果
- 处理 JSON 和 Markdown 代码块格式
- 提取结构化数据

业务场景：
- 解析章节规划输出
- 提取节拍列表和元数据

主要功能：
- JSON 解析（处理各种格式）
- 提取节拍列表
- 提取工作流层级

依赖项：
- json: JSON 解析
- re: 正则表达式处理

使用方式：
    beats, tier = parse_planner_full_result(raw_result, outline, word_count)
"""

import json
import re


LOW_TENSION_RED_LINES = ["禁止发生任何武力冲突或战斗升级", "避免正面冲突"]


def parse_planner_full_result(
    planner_result_raw: str,
    chapter_outline: str,
    word_count: int,
) -> tuple:
    text = (planner_result_raw or "").strip()
    candidates = [text] if text else []
    fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    candidates.extend(block.strip() for block in fenced_blocks if block and block.strip())
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.append(text[first_brace : last_brace + 1].strip())
    parsed_obj = None
    for candidate in candidates:
        try:
            parsed_obj = json.loads(candidate)
            break
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

    workflow_tier = "TIER_2_STANDARD"
    if isinstance(parsed_obj, dict):
        tier = parsed_obj.get("workflow_tier")
        if tier in ["TIER_1_FAST", "TIER_2_STANDARD", "TIER_3_FORTRESS"]:
            workflow_tier = tier

    chapter_narrative_anchor = ""
    if isinstance(parsed_obj, dict):
        chapter_narrative_anchor = str(parsed_obj.get("chapter_narrative_anchor", "")).strip()

    beats = []
    if isinstance(parsed_obj, dict) and isinstance(parsed_obj.get("beats"), list):
        for idx, beat in enumerate(parsed_obj["beats"], start=1):
            if not isinstance(beat, dict):
                continue
            summary = str(beat.get("summary") or "").strip()
            if not summary:
                continue
            position = beat.get("position")
            if not isinstance(position, int) or position <= 0:
                position = idx
            target_words = beat.get("target_words")
            if not isinstance(target_words, int) or target_words <= 0:
                target_words = max(200, word_count // max(1, len(parsed_obj["beats"])))
            word_count_target = beat.get("word_count_target")
            if not isinstance(word_count_target, int) or word_count_target <= 0:
                word_count_target = target_words
            beat_id = str(beat.get("beat_id") or f"beat-{position}").strip() or f"beat-{position}"
            location = str(beat.get("location") or "").strip() or None
            pov_character = str(beat.get("pov_character") or "").strip() or None
            pov_mode = str(beat.get("pov_mode") or "single").strip()
            if pov_mode not in ["single", "ensemble", "omniscient"]:
                pov_mode = "single"
            pov_characters_raw = beat.get("pov_characters")
            if isinstance(pov_characters_raw, list):
                pov_characters = [str(c).strip() for c in pov_characters_raw if str(c).strip()]
            else:
                pov_characters = []
            if pov_mode == "ensemble" and not pov_character and pov_characters:
                pov_character = pov_characters[0]
            pov_perception_state = str(beat.get("pov_perception_state") or "正常").strip() or "正常"
            pov_aperture = str(beat.get("pov_aperture") or "subjective_observation").strip()
            if pov_aperture not in ["internal_only", "subjective_observation", "systemic_sense"]:
                pov_aperture = "subjective_observation"
            persistent_state_anchors = []
            raw_anchors = beat.get("persistent_state_anchors")
            if isinstance(raw_anchors, list):
                for anchor in raw_anchors:
                    if isinstance(anchor, dict):
                        anchor_type = str(anchor.get("anchor_type") or "").strip()
                        description = str(anchor.get("description") or "").strip()
                        involved_chars = anchor.get("involved_characters", [])
                        if isinstance(involved_chars, list):
                            involved_characters = [str(c).strip() for c in involved_chars if str(c).strip()]
                        else:
                            involved_characters = []
                        if anchor_type and description:
                            persistent_state_anchors.append({
                                "anchor_type": anchor_type,
                                "description": description,
                                "involved_characters": involved_characters
                            })
            action_summary = str(beat.get("action_summary") or "").strip() or summary
            worldbuilding_instruction = str(beat.get("worldbuilding_instruction") or "").strip() or None
            entry_state = str(beat.get("entry_state") or "").strip()
            if not entry_state:
                entry_state = f"承接上文并切入：{summary[:40]}"
            exit_state = str(beat.get("exit_state") or "").strip()
            if not exit_state:
                exit_state = f"停在本节拍收束点：{action_summary[:40]}"
            raw_hook_ids = beat.get("hook_ids")
            raw_red_lines = beat.get("red_lines")
            hook_ids = [str(item).strip() for item in raw_hook_ids if str(item).strip()] if isinstance(raw_hook_ids, list) else []
            red_lines = [str(item).strip() for item in raw_red_lines if str(item).strip()] if isinstance(raw_red_lines, list) else []
            if not red_lines:
                red_lines = ["不得越过本节拍 exit_state 指向的剧情停点"]

            pacing_type = str(beat.get("pacing_type") or "Medium").strip()
            if pacing_type not in ["Fast", "Medium", "Slow"]:
                pacing_type = "Medium"

            weight = beat.get("weight")
            if not isinstance(weight, int):
                weight = 3
            else:
                weight = max(1, min(5, weight))

            beats.append(
                {
                    "position": position,
                    "beat_id": beat_id,
                    "summary": summary,
                    "location": location,
                    "pov_character": pov_character,
                    "pov_mode": pov_mode,
                    "pov_characters": pov_characters,
                    "pov_perception_state": pov_perception_state,
                    "pov_aperture": pov_aperture,
                    "persistent_state_anchors": persistent_state_anchors,
                    "action_summary": action_summary,
                    "worldbuilding_instruction": worldbuilding_instruction,
                    "entry_state": entry_state or None,
                    "exit_state": exit_state or None,
                    "red_lines": red_lines,
                    "word_count_target": word_count_target,
                    "target_words": word_count_target,
                    "hook_ids": hook_ids,
                    "pacing_type": pacing_type,
                    "weight": weight,
                    "workflow_tier": workflow_tier,
                }
            )
    if not beats:
        fallback_summary = (chapter_outline or "").strip() or "按章节大纲推进剧情并完成关键冲突。"
        beats = [
            {
                "position": 1,
                "beat_id": "beat-1",
                "summary": fallback_summary,
                "location": None,
                "pov_character": None,
                "pov_perception_state": "正常",
                "pov_aperture": "subjective_observation",
                "persistent_state_anchors": [],
                "action_summary": fallback_summary,
                "worldbuilding_instruction": None,
                "entry_state": "承接上文并切入本节拍",
                "exit_state": "停在本节拍收束点，不推进后续事件",
                "red_lines": ["不得越过本节拍 exit_state 指向的剧情停点"],
                "word_count_target": word_count,
                "target_words": word_count,
                "hook_ids": [],
                "pacing_type": "Medium",
                "weight": 3,
                "workflow_tier": workflow_tier,
            }
        ]
    beats.sort(key=lambda item: item["position"])
    return beats, chapter_narrative_anchor


def _split_single_beat_fallback(beat: dict, chapter_outline: str, word_count: int) -> list:
    """
    当 Planner 只返回 1 个 beat 时的兜底拆分逻辑。

    策略：
    - 目标字数 >= 1500 时拆成 2-4 个 beats
    - 优先尝试按大纲中的换行/段落拆分 summary
    - 无法拆分时按字数平均分配
    """
    target_count = max(2, min(4, round(word_count / 600)))
    base_summary = str(beat.get("summary") or chapter_outline or "").strip()
    
    # 尝试按大纲的自然段落拆分
    outline_parts = [p.strip() for p in base_summary.split("\n") if p.strip()]
    if len(outline_parts) >= target_count:
        parts = outline_parts[:target_count]
    else:
        # 按字数平均拆分 summary（简单句末切分）
        sentences = [s.strip() for s in base_summary.replace("。", ".").replace("！", "!").replace("？", "?").split(".") if s.strip()]
        if len(sentences) >= target_count:
            chunk_size = max(1, len(sentences) // target_count)
            parts = []
            for i in range(target_count):
                start = i * chunk_size
                end = len(sentences) if i == target_count - 1 else (i + 1) * chunk_size
                parts.append("。".join(sentences[start:end]) + "。")
        else:
            parts = [base_summary] * target_count
    
    split_word = max(200, word_count // target_count)
    result = []
    for i, part in enumerate(parts, start=1):
        b = dict(beat)
        b["position"] = i
        b["beat_id"] = f"beat-{i}"
        b["summary"] = part.strip()
        b["action_summary"] = part.strip()
        b["word_count_target"] = split_word
        b["target_words"] = split_word
        # 第一个 beat 保持原 entry_state，后续用简化承接
        if i > 1:
            b["entry_state"] = f"承接上一节拍：{part.strip()[:40]}"
        # 最后一个 beat 保持原 exit_state，中间用简化收束
        if i < len(parts):
            b["exit_state"] = f"停在本节拍收束点：{part.strip()[:40]}"
        result.append(b)
    return result


def parse_planner_result(
    planner_result_raw: str,
    chapter_outline: str,
    word_count: int,
) -> list:
    beats, _ = parse_planner_full_result(planner_result_raw, chapter_outline, word_count)
    
    # 兜底：如果只有 1 个 beat 但字数/要求明显应该多 beat，自动拆分
    if len(beats) == 1 and word_count >= 1200:
        beats = _split_single_beat_fallback(beats[0], chapter_outline, word_count)
    
    return beats
