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
LLM 级审计 Prompt 模板（Phase 2 CP3.1c 新建）。

依据：
- 蓝图 §4.8.2 ConStory-Checker 式证据链审计
- 调研报告 §4.4 引用 ConStory-Bench 错误分布规律（中段错误密度最高）
- decisions §3.5 PlotLedger 匹配机制（伏笔维度）

四步流程（ConStory-Checker）：
1. 分类引导抽取：按 5 维度扫描矛盾易发片段
2. 两两配对判定：对每对潜在矛盾，判定一致/矛盾（降误报）
3. 证据链：对每个 finding，输出推理 + 原文引用 + 字符偏移
4. 标准化 JSON 报告：输出 QualityReport.findings 格式

输出契约（与 schemas/quality.py FindingItem 对齐）：
{
  "findings": [
    {
      "severity": "blocker|warning|info",
      "category": "timeline|characterization|worldview|fact|style",
      "quote": "原文引用（≤50字）",
      "offset": [start, end],
      "beat_id": int|null,
      "detail": "推理过程 + 矛盾说明",
      "suggestion": "修复建议"
    }
  ],
  "foreshadow_status": [
    {
      "ledger_id": "...",
      "status": "executed|skipped|modified",
      "evidence_quote": "原文引用（≤50字）",
      "note": "..."
    }
  ],
  "verdict": "pass|pass_with_fixes|fail"
}
"""

from typing import Any, Dict, List, Optional

# ============================================================
# System Prompt — 审计员角色设定
# ============================================================

AUDIT_SYSTEM_PROMPT = """你是资深小说连贯性审计员，专攻长篇小说的事后一致性校对。

【审计原则】
1. 证据驱动：每个发现（finding）必须附原文引用 + 字符偏移，不得臆断。
2. 两两配对判定：发现潜在矛盾后，必须对照原文另一处确认后才上报，杜绝误报。
3. 重点扫中段：章节中段（约 30%~70% 区间）是 ConStory-Bench 实测错误密度最高的区域，需加倍细致。
4. 只报真问题：风格偏好类问题不报；只报客观矛盾（时间线冲突、角色刻画前后不一致、世界观设定违反、事实细节硬伤）。

【五维扫描清单】
- timeline（时间线）：时序倒错、时间跨度矛盾、季节/昼夜不符
- characterization（角色刻画）：角色性格突变、能力越界、动机断裂、台词口吻不一
- worldview（世界观）：设定规则违反（如魔法体系、物理法则、社会规则）
- fact（事实细节）：物件状态前后不一致（位置/数量/形态）、人物在场状态矛盾
- style（叙事风格）：仅当出现明确的视角越界（如第一人称突然知道他人内心）才报，不报主观风格偏好

【伏笔维度（PlotLedger）】
对每个章节卡声明的 foreshadow_ops，必须给出执行状态判定：
- executed：伏笔在本章已按声明落地
- skipped：本章未触及该伏笔
- modified：本章触及但与声明方式不同
判定必须附 evidence_quote（原文引用），无 evidence 的不得标 executed/modified。

【严重性分级】
- blocker：客观矛盾且影响情节推进（如时间线倒错导致逻辑崩塌）
- warning：客观矛盾但可补救（如物件状态前后不一）
- info：潜在风险需人工确认（如角色口吻轻微偏移）

【输出契约】严格 JSON，不得包含任何注释或 Markdown 代码块标记。
"""


# ============================================================
# User Prompt 构造器
# ============================================================

def build_audit_user_prompt(
    chapter_text: str,
    *,
    chapter_card: Optional[Dict[str, Any]] = None,
    characters: Optional[List[Dict[str, Any]]] = None,
    prev_chapter_summary: Optional[str] = None,
    code_audit_findings: Optional[List[Dict[str, Any]]] = None,
    beats: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """构造 LLM 审计的 user prompt。

    Args:
        chapter_text: 本章正文（全文）
        chapter_card: 章节卡（含 must_hit_events / foreshadow_ops / continuity / involved_characters）
        characters: 本章涉及角色（含 name / aliases / static_prompt / dynamic_state）
        prev_chapter_summary: 上一章摘要（用于衔接校验）
        code_audit_findings: CP3.1b 代码级审计的命中片段（重点复查提示）
        beats: 节拍列表（含 position / participants / red_lines / word_count_target）

    Returns:
        str: 拼接好的 user prompt
    """
    sections: List[str] = []

    # 段 1：本章正文（带字符偏移刻度，便于 LLM 输出 offset）
    sections.append("【本章正文】（字符偏移以本段从 0 起计）")
    sections.append(chapter_text)
    sections.append("")

    # 段 2：上一章摘要（衔接校验输入）
    if prev_chapter_summary:
        sections.append("【上一章摘要】（用于首段衔接校验）")
        sections.append(prev_chapter_summary[:800])  # 截断防 prompt 膨胀
        sections.append("")

    # 段 3：章节卡（must_hit_events / continuity / foreshadow_ops）
    if chapter_card:
        sections.append("【章节卡】")
        if chapter_card.get("purpose"):
            sections.append(f"- 主旨：{chapter_card['purpose']}")
        if chapter_card.get("must_hit_events"):
            events_str = "; ".join(
                e.get("event", str(e)) if isinstance(e, dict) else str(e)
                for e in chapter_card["must_hit_events"]
            )
            sections.append(f"- 必达事件：{events_str}")
        if chapter_card.get("continuity"):
            cont = chapter_card["continuity"]
            cont_str = (
                f"from_chapter={cont.get('from_chapter')}, "
                f"time_gap={cont.get('time_gap')}, "
                f"location={cont.get('location')}"
            )
            sections.append(f"- 衔接：{cont_str}")
        if chapter_card.get("foreshadow_ops"):
            sections.append("- 伏笔操作（PlotLedger 维度必须逐条判定）：")
            for i, op in enumerate(chapter_card["foreshadow_ops"]):
                if isinstance(op, dict):
                    sections.append(
                        f"  [{i}] ledger_id={op.get('ledger_id','?')} "
                        f"action={op.get('action','?')} note={op.get('note','')}"
                    )
        sections.append("")

    # 段 4：涉及角色（角色刻画校验输入）
    if characters:
        sections.append("【涉及角色】（用于角色刻画一致性校验）")
        for char in characters[:15]:  # 截断防 prompt 膨胀
            if isinstance(char, dict):
                name = char.get("name", "?")
                aliases = char.get("aliases", [])
                static = (char.get("static_prompt") or "")[:200]
                aliases_str = "/".join(aliases) if aliases else "无"
                sections.append(f"- {name}（别名：{aliases_str}）：{static}")
        sections.append("")

    # 段 5：节拍框架（在场一致性 + 必达事件辅助校验）
    if beats:
        sections.append("【节拍框架】（用于在场一致性 + 必达事件校验）")
        for beat in beats:
            if isinstance(beat, dict):
                pos = beat.get("position", "?")
                participants = beat.get("participants", []) or []
                participants_str = ", ".join(
                    (p if isinstance(p, str) else (p.get("name", "?") if isinstance(p, dict) else str(p)))
                    for p in participants
                ) or "未声明"
                summary = (beat.get("summary") or beat.get("action_summary") or "")[:120]
                sections.append(f"  Beat {pos}：在场=[{participants_str}]；摘要={summary}")
        sections.append("")

    # 段 6：代码级审计命中提示（重点复查）
    if code_audit_findings:
        sections.append("【代码级审计命中提示】（请重点复查以下区域，确认是否为真问题）")
        for f in code_audit_findings[:8]:  # 只取前 8 条防膨胀
            if isinstance(f, dict):
                quote = f.get("quote") or ""
                detail = f.get("detail", "")
                sections.append(f"  - [{f.get('category','?')}] {quote} — {detail}")
        sections.append("")

    # 段 7：中段重点扫描指令（ConStory-Bench）
    mid_start = len(chapter_text) // 3
    mid_end = (len(chapter_text) * 2) // 3
    sections.append(
        f"【重点扫描区】本章中段约字符 [{mid_start}, {mid_end}] 是 ConStory-Bench "
        f"实测错误密度最高的区域，请对该区间加倍细致地执行五维扫描。"
    )
    sections.append("")

    # 段 8：输出格式指令
    sections.append(_OUTPUT_FORMAT_INSTRUCTION)

    return "\n".join(sections)


# ============================================================
# 输出格式指令
# ============================================================

_OUTPUT_FORMAT_INSTRUCTION = """【输出格式】严格 JSON（不要 Markdown 代码块标记，不要注释）：

{
  "findings": [
    {
      "severity": "blocker|warning|info",
      "category": "timeline|characterization|worldview|fact|style",
      "quote": "原文引用（≤50字，必须能在正文中找到）",
      "offset": [起始字符偏移, 结束字符偏移],
      "beat_id": 关联节拍序号或null,
      "detail": "推理过程 + 矛盾点说明（必须解释为何是问题）",
      "suggestion": "具体修复建议"
    }
  ],
  "foreshadow_status": [
    {
      "ledger_id": "章节卡声明的伏笔 ID",
      "status": "executed|skipped|modified",
      "evidence_quote": "原文引用（≤50字，executed/modified 必填，skipped 可空）",
      "note": "判定说明"
    }
  ],
  "verdict": "pass|pass_with_fixes|fail"
}

判定规则：
- verdict=pass：findings 为空且无 blocker 级问题
- verdict=pass_with_fixes：存在 warning/info 级问题，可补救
- verdict=fail：存在 blocker 级问题，需重写或大改

伏笔维度（若章节卡有 foreshadow_ops 则必填 foreshadow_status，否则返回空数组）：
- 每条 foreshadow_op 必须在 foreshadow_status 中对应一项
- executed/modified 必须附 evidence_quote（原文能找到的引用）
- 无 evidence 的不得标 executed/modified（应标 skipped）
"""


# ============================================================
# 响应解析辅助
# ============================================================

# 合法取值集合（用于解析时校验）
VALID_SEVERITIES = {"blocker", "warning", "info"}
VALID_CATEGORIES = {"timeline", "characterization", "worldview", "fact", "style"}
VALID_VERDICTS = {"pass", "pass_with_fixes", "fail", "unaudited"}
VALID_FORESHADOW_STATUS = {"executed", "skipped", "modified"}
