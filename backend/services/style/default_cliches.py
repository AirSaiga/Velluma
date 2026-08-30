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
内置默认禁词种子数据（Phase 1 CP2.1c）。

职责：首次启动时若 SystemCliche 表为空，从本模块种子化。

依据：
- 原 validators.py:35-46 的 10 条硬编码
- 调研报告 §4.3 中英文禁词清单（avoid-ai-writing + 中文网文社区共识）
- 蓝图 §4.4 禁词表

分类规则：
- category=cliche：AI 腔陈词滥调（最常见的"模型默认分布"产物）
- category=house_voice：模型机构腔（RLHF 单一 house voice）
- category=transition：万能过渡词
- severity=blocker：硬阻断 fail-fast（高频且无替代价值的）
- severity=warning：软警告（命中即记日志但不阻断）
"""

from typing import Any, Dict, List


# ============================================================
# 中文禁词（category=cliche，severity=blocker 优先）
# ============================================================

ZH_CLICHE_BLOCKER: List[Dict[str, Any]] = [
    # 原 validators.py 的 10 条（高频网文腔，无替代价值）
    {"pattern": "眼底闪过一丝", "alternative": "用具体动作或微表情描写"},
    {"pattern": "嘴角勾起一抹", "alternative": "直接写笑容或表情"},
    {"pattern": "不禁倒吸一口凉气", "alternative": "用角色的生理反应或动作"},
    {"pattern": "倒吸一口凉气", "alternative": "用角色的生理反应或动作"},
    {"pattern": "勾起一抹冷笑", "alternative": "直接写冷笑或讥讽语气"},
    {"pattern": "深邃的眼眸", "alternative": "用具体眼神或目光描写"},
    {"pattern": "不可名状的", "alternative": "具体描述为何难以形容"},
    {"pattern": "宛如实质般的", "alternative": "用具体比喻"},
    {"pattern": "难以言喻的", "alternative": "具体描述这种感觉"},
]

ZH_CLICHE_WARNING: List[Dict[str, Any]] = [
    # 扩充：中文网文社区共识禁词（调研报告 §4.3 来源 24-25）
    {"pattern": "命运的齿轮", "alternative": "直接描述事件因果"},
    {"pattern": "时间的长河", "alternative": "用具体时间或场景"},
    {"pattern": "宿命般", "alternative": "用角色主观感受"},
    {"pattern": "仿佛能穿透", "alternative": "用具体目光效果"},
    {"pattern": "时间仿佛静止", "alternative": "用具体的环境或动作静止"},
    {"pattern": "心如刀绞", "alternative": "用具体的生理或动作反应"},
    {"pattern": "心如止水", "alternative": "用具体的神态描写"},
    {"pattern": "怒火中烧", "alternative": "用具体的愤怒表现"},
    {"pattern": "不动声色地", "alternative": "直接描述动作"},
    {"pattern": "若有所思", "alternative": "用具体的思考表现"},
    {"pattern": "意味深长", "alternative": "直接写出意味"},
    {"pattern": "不可思议地", "alternative": "用具体描述"},
    {"pattern": "总而言之", "alternative": "省略或用具体过渡"},
]


# ============================================================
# 中文句式（category=house_voice）
# ============================================================

ZH_HOUSE_VOICE_WARNING: List[Dict[str, Any]] = [
    # 调研报告 §4.3：段末升华、空洞强化词
    {"pattern": "不是.*而是", "is_regex": True, "alternative": "直接陈述事实，避免对比修辞"},
    {"pattern": "这不仅是.*更是", "is_regex": True, "alternative": "分句陈述"},
    {"pattern": "仿佛在诉说着", "alternative": "直接描述其状态"},
    {"pattern": "似乎在暗示着", "alternative": "直接写出暗示内容"},
    {"pattern": "预示着", "alternative": "直接描述事件"},
]


# ============================================================
# 英文禁词（CP2.1c 预留，CP3 文风体系深化时启用）
# ============================================================

EN_CLICHE_WARNING: List[Dict[str, Any]] = [
    # 调研报告 §4.3 来源 22（avoid-ai-writing）
    {"pattern": "delve", "language": "en", "alternative": "explore / examine"},
    {"pattern": "tapestry", "language": "en", "alternative": "用具体比喻"},
    {"pattern": "realm", "language": "en", "alternative": "area / field / domain"},
    {"pattern": "testament to", "language": "en", "alternative": "直接陈述因果"},
    {"pattern": "leverage", "language": "en", "alternative": "use / exploit"},
    {"pattern": "pivotal", "language": "en", "alternative": "crucial / key"},
    {"pattern": "underscore", "language": "en", "alternative": "highlight / emphasize"},
    {"pattern": "meticulous", "language": "en", "alternative": "careful / precise"},
]


# ============================================================
# 统一种子入口
# ============================================================

def get_all_seed_cliches() -> List[Dict[str, Any]]:
    """返回全部种子禁词（供 SystemClicheRepository.seed_if_empty 使用）。

    每项是可直接 SystemCliche(**item) 的 dict。
    自动补充默认字段（language=zh, category, severity）。
    """
    seeds: List[Dict[str, Any]] = []
    for item in ZH_CLICHE_BLOCKER:
        seeds.append({
            "language": "zh", "category": "cliche", "severity": "blocker",
            "is_regex": False, "enabled": True,
            **item,
        })
    for item in ZH_CLICHE_WARNING:
        seeds.append({
            "language": "zh", "category": "cliche", "severity": "warning",
            "is_regex": False, "enabled": True,
            **item,
        })
    for item in ZH_HOUSE_VOICE_WARNING:
        seeds.append({
            "language": "zh", "category": "house_voice", "severity": "warning",
            "is_regex": False, "enabled": True,
            **item,
        })
    for item in EN_CLICHE_WARNING:
        seeds.append({
            "language": "en", "category": "cliche", "severity": "warning",
            "is_regex": False, "enabled": True,
            **item,
        })
    return seeds
