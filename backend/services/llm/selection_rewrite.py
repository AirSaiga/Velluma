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
选区级改写 Prompt 分派器（Phase 3 CP4.1 新建，蓝图 §4.9）。

职责：按 mode（rewrite/describe/expand/compress/tone_shift）分派 system prompt，
对应 Sudowrite Rewrite/Describe/Expand 式交互。

业务场景：
- routes/chapter_optimization.py 的 POST /optimize_selection 调用
- services/llm/client.py 的 optimize_selection_with_llm 读取 mode → 选 prompt
- 前端 RichTextEditor 选区菜单的 5 种模式按钮触发

设计原则：
- 5 种模式各有独立 system prompt，明确该模式的边界（做什么 / 不做什么）
- tone_shift 模式额外注入 tone 参数（如"冷峻"/"诙谐"）
- user_instruction 始终作为附加指令（mode 是大方向，user_instruction 是细节补充）
"""

from typing import Optional


# ============================================================
# 合法 mode 取值
# ============================================================

VALID_MODES = ("rewrite", "describe", "expand", "compress", "tone_shift")


# ============================================================
# 各 mode 的 system prompt
# ============================================================
# 设计依据（蓝图 §4.9 + Sudowrite 交互范式）：
# - rewrite：保持原意，换表达（去 AI 味，增人味）
# - describe：扩充感官细节（视/听/嗅/触/味），不推进情节
# - expand：在原意基础上增加细节/心理/对白（可推进情节）
# - compress：压缩冗余，保留关键信息，目标字数 -40%
# - tone_shift：按 tone 调整语气（不改情节，只改语气）


_MODE_SYSTEM_PROMPTS = {
    "rewrite": """你是一位资深小说编辑，擅长把 AI 味浓重的段落改写成有"人味"的文字。

【任务】改写用户选中的文本：保持原意不变，换一种更自然、更有个性的表达方式。

【改写要点】
1. 保留原文的核心信息（动作、对白、情节节点）
2. 消除 AI 默认腔调（升华句、万能过渡词、等长句堆叠、过度排比）
3. 增加 POV 角色的私人偏见、思维噪音、口语化呼吸感
4. 句长主动打散：短句、反问、单字段落与长句交错
5. 允许不完美：真实的思绪是跳跃的、口语化的

【边界】
- 不推进情节（不添加新事件）
- 不改变角色性格
- 不添加原文没有的感官细节（那是 describe 模式的任务）
""",

    "describe": """你是一位擅长感官描写的小说编辑。

【任务】为用户选中的文本扩充感官细节，让场景更"可感"。

【描写要点】
1. 五感交织：视觉（光影/色彩）、听觉（声音/寂静）、嗅觉（气味）、触觉（温度/质感）、味觉（若有）
2. 细节锚定：用具体的物件、动作、微表情替代抽象描述
3. POV 视角：所有感官必须通过 POV 角色的感知呈现，不得全知
4. 节制：每个感官通道 1-2 处即可，避免堆砌

【边界】
- 不推进情节（不添加新动作/新事件）
- 不改变原有对白内容
- 扩写幅度控制在原文的 1.5-2 倍
""",

    "expand": """你是一位擅长扩展情节的小说编辑。

【任务】在用户选中的文本基础上扩写：增加细节、角色心理、对白，让场景更饱满。

【扩写要点】
1. 心理活动：补充 POV 角色的内心独白、回忆、联想
2. 对白延展：在合适处补充角色对话（保持口吻一致）
3. 动作细化：把概括性动作拆解为连续的具体动作
4. 环境互动：角色与环境的互动（触碰物件、观察环境）

【边界】
- 可以推进情节（与 describe 的关键区别）
- 但不得偏离章节大纲与角色设定
- 扩写幅度控制在原文的 2-3 倍
""",

    "compress": """你是一位擅长精简文字的小说编辑。

【任务】压缩用户选中的文本：去除冗余，保留关键信息，让表达更凝练。

【压缩要点】
1. 删除重复信息（同一意思的多次表达只留一次）
2. 删除空话套话（"他心里想着"、"她不禁感到"等可省略的心理标签）
3. 合并相近动作（"他走过去，停下来，看着她" → "他驻足看她"）
4. 保留：情节节点、关键对白、角色状态变化

【边界】
- 目标字数：原文的 60%（即压缩约 40%）
- 不得删除任何情节信息（只删冗余，不删内容）
- 不得改变原意
""",

    "tone_shift": """你是一位擅长调整语气的小说编辑。

【任务】调整用户选中文本的语气，使其符合指定的 tone（语气风格），但不改变情节内容。

【换气要点】
1. 词汇选择：按 tone 替换语气词（如"冷峻"→ 短句、硬词；"诙谐"→ 反讽、俏皮）
2. 句式调整：语气影响句长（冷峻偏短、抒情偏长）
3. 节奏控制：语气影响节奏（紧张→短促、舒缓→悠长）
4. POV 一致：保持 POV 角色的核心性格，只调整语气外壳

【边界】
- 不改变情节（事件、动作、对白的核心内容不变）
- 不改变角色性格底色（只调整表达语气）
- 字数与原文相近（±20%）
""",
}


# ============================================================
# 公共尾部规则（所有 mode 共享）
# ============================================================

_COMMON_TAIL = """
【输出规则】
1. 直接输出改写后的文本，不要任何解释、前言、后续
2. 必须输出完整结果，严禁截断或省略
3. 保持与【前文】【后文】的衔接自然
4. 若【用户附加指令】与上述 mode 规则冲突，以 mode 规则为准（mode 是大方向）"""


# ============================================================
# 出口：构建完整 system prompt
# ============================================================

def build_selection_rewrite_system_prompt(
    mode: str = "rewrite",
    tone: Optional[str] = None,
) -> str:
    """按 mode + tone 构建 system prompt（蓝图 §4.9）。

    Args:
        mode: rewrite / describe / expand / compress / tone_shift
        tone: 仅 mode=tone_shift 时生效，目标语气（如 冷峻 / 诙谐 / 抒情）

    Returns:
        str: 完整 system prompt
    """
    # 兜底：非法 mode 用 rewrite
    if mode not in VALID_MODES:
        mode = "rewrite"

    base = _MODE_SYSTEM_PROMPTS[mode]

    # tone_shift 模式注入 tone 指令
    if mode == "tone_shift":
        tone_str = tone.strip() if tone and tone.strip() else "自然"
        base = base + f"\n\n【目标语气】本次改写的目标语气为：「{tone_str}」。所有词汇选择、句式、节奏都应服务于这个语气。"

    return base + _COMMON_TAIL


def build_selection_rewrite_user_prompt(
    *,
    selected_text: str,
    context_before: str,
    context_after: str,
    outline: str,
    user_instruction: str,
    style_context: str = "",
) -> str:
    """构建 user prompt（所有 mode 共用同一结构）。

    user_instruction 作为"附加指令"附加在末尾（mode 是大方向，user_instruction 是细节）。
    style_context（S2 E5）：文风约束块（画像/避免用词/笔迹示范，由路由层拼装）；
    空串 → 不注入该块，prompt 与旧版逐字节一致。
    """
    style_block = ""
    if style_context and style_context.strip():
        style_block = f"""
【文风约束（改写后的文字要像同一个人写的）】
{style_context.strip()}

"""
    return f"""
【章节大纲】
{outline}

【前文】
{context_before}

【选中文本】
{selected_text}

【后文】
{context_after}
{style_block}【用户附加指令】
{user_instruction or "（无附加指令，严格按 mode 规则执行）"}

请提供【选中文本】的改写版本：
"""
