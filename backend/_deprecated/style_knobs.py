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
意图旋钮档位定义（文风模块重构 S4，docs/style-module-redesign.md §3-⑤）。

职责：四个意图维度的五档定义（档位 → 展示名 + prompt 意图行），
后端渲染（render_style_positive）与前端 UI 标签共用同一套语义。

设计边界（诚实原则）：
- 旋钮是**意图微调层**，叠在画像/样本之上——缺键（自动档）= 不注入该维度，
  交给正面画像与 few-shot 样本（不假装能从语料"测出"文白/冷热）。
- 能测量的两个维度（节奏/对话）前端另有实测锚点做偏差提示，但后端注入
  仍是纯意图行（测量→提示在 UI 层，注入→模板行在渲染层，两层解耦）。
- 对话旋钮不在此表：它直接落 StyleCard.dialogue_ratio_target（有真实
  消费方 DialogueAuditor/ADF 契约），档位映射在前端完成。
"""

from typing import Dict, List, Tuple

# knob_key → (维度名, [(tier, 档名, prompt 意图行), ...] tier 1-5)
KNOB_DEFS: Dict[str, Tuple[str, List[Tuple[int, str, str]]]] = {
    "rhythm": (
        "句长节奏",
        [
            (1, "极快", "短句为主（常 ≤10 字），少用长句，节奏急促"),
            (2, "偏快", "以短句为主，长句只作点缀"),
            (3, "适中", "长短句均衡交替"),
            (4, "偏慢", "以中长句为主，偶尔用短句收束"),
            (5, "极慢", "长句绵延为主，少用短句，节奏舒缓"),
        ],
    ),
    "register": (
        "文白",
        [
            (1, "极白", "口语化、生活化用词，像说话一样写"),
            (2, "偏白", "平白晓畅，少用书面语"),
            (3, "适中", "白话为主，偶带书面色彩"),
            (4, "偏文", "书面语为主，用词讲究"),
            (5, "极文", "雅正书面语，可带文言色彩"),
        ],
    ),
    "density": (
        "浓淡",
        [
            (1, "极淡", "白描为主，几乎不用比喻与修辞"),
            (2, "偏淡", "少修辞，偶一比喻即可"),
            (3, "适中", "修辞适度，意象点到即止"),
            (4, "偏浓", "意象绵密，修辞是常态"),
            (5, "极浓", "修辞繁密，追求语言的质感与光晕"),
        ],
    ),
    "warmth": (
        "冷热",
        [
            (1, "极冷", "克制、零度写作，情绪绝不外露"),
            (2, "偏冷", "情感内敛，多用动作暗示"),
            (3, "适中", "情感自然流露，不煽情"),
            (4, "偏热", "情感外露，笔触带温度"),
            (5, "极热", "情感浓烈，抒情直接"),
        ],
    ),
}

# 语料实测句均字数 → 节奏档参考锚（供前端偏差提示；无语料时无锚）
SENTENCE_MEAN_TO_RHYTHM_TIER = [
    (12, 1),   # 句均 ≤12 字 → 快
    (16, 2),
    (22, 3),
    (30, 4),
    (float("inf"), 5),
]


def render_knob_lines(style_knobs: Dict) -> List[str]:
    """把 style_knobs 渲染为 prompt 意图行（自动档/非法档静默跳过）。

    Returns:
        行列表（如 "句长节奏意图：偏快——以短句为主，长句只作点缀"）；
        空字典/全自动档 → 空列表（prompt 零变化）。
    """
    if not isinstance(style_knobs, dict) or not style_knobs:
        return []
    lines: List[str] = []
    for key, (dim_name, tiers) in KNOB_DEFS.items():
        raw = style_knobs.get(key)
        try:
            tier = int(raw)
        except (TypeError, ValueError):
            continue
        for t, label, prompt_line in tiers:
            if t == tier:
                lines.append(f"{dim_name}意图：{label}——{prompt_line}")
                break
    return lines
