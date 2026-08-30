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
反 AI 味规则集 —— 纯数据契约层。

职责：
- 定义禁令词表、禁令正则、密度阈值，全部为 frozen dataclass / 不可变常量
- 零依赖、零 I/O、零副作用——供 ai_taste_meter / text_sanitizer / de_ai_washer 只读引用
- 符合规范2：强类型 Dataclass，严禁散乱字典或硬编码魔数

设计意图：
- 黑名单分两类语义：
  · banned_micro_actions：无信息量的微小动作（确定性删除安全）
  · banned_words：伪深度套路填充词（确定性删除安全）
  · banned_regexes：复杂句式模式（裁剪时只删明确的；"像...一样"类只在密度算法统计）
- 阈值用"每 500 字"归一化，跨不同字数段落可比
- 改词表/阈值 = 改代码 + 单测验证，不暴露运行时配置面

业务场景：
- ai_taste_meter.measure_ai_taste() 读取阈值计算密度
- text_sanitizer.sanitize_segment() 读取黑名单做正则裁剪
- adf_prompts.py 读取黑名单生成反 AI 腔 prompt 指令区块
"""

from dataclasses import dataclass, field


# ============================================================
# 禁令数据契约
# ============================================================

@dataclass(frozen=True)
class AntiAIBanList:
    """反 AI 味禁令清单（不可变）。

    所有字段为 tuple（不可变），保证实例创建后不被篡改。

    Attributes:
        banned_micro_actions: 无信息量的病态微操短语。
            这类短语删掉不影响情节，确定性删除安全。
            对应反模式 #1：病态微操 (Micro-Action Overkill)。
        banned_words: 伪深度套路填充词。
            这类词高频出现在 AI 生成的"伪文学"腔调里，确定性删除安全。
            对应反模式 #2：伪深度套路比喻 (Pseudodepth Metaphor Tropes)。
        banned_regexes: 复杂句式禁令正则（编译为 pattern，匹配后整处删除）。
            仅放确定性无信息量的句式（嘴角上扬/瞳孔收缩等微操句式）。
            警示：句式正则误伤风险高于词表，新加规则需人工抽样验证。
        metaphor_regexes: 套路比喻正则（仅用于密度统计，不进确定性裁剪）。
            "像...一样"等可能是合法比喻，只在 ai_taste_meter 统计频率，
            超阈值交 LLM 洗涤而非无脑删。
    """

    # 1. 病态微操短语（无信息量的小动作，确定性删除）
    banned_micro_actions: tuple = (
        "指尖颤了颤", "指尖微颤", "指尖轻轻一颤", "指尖微微发抖",
        "下巴抬高半寸", "下巴微微扬起",
        "眼角余光", "眼角微微抽动",
        "瞳孔微微收缩", "瞳孔骤然收缩",
        "嘴角微不可察地", "嘴角不可察觉地",
        "喉结上下滚动", "喉结微微滚动",
        "睫毛轻颤", "睫毛微微颤动",
        "呼吸微微一窒", "呼吸不由得一窒",
        "手指无意识地蜷缩", "指节微微泛白",
    )

    # 2. 伪深度套路词（填充词，确定性删除）
    banned_words: tuple = (
        # 伪深度形容词
        "冷冽", "深邃", "极深", "幽深",
        # 套路比喻引导词
        "宛如", "仿若", "犹如", "宛若",
        # 模糊化表述（AI 爱用来假装有深度）
        "不可名状", "难以言喻", "无法言说", "言语无法形容",
        # 套路意象
        "墨水滴进水里", "沉睡的巨兽", "深渊般的",
    )

    # 3. 复杂句式禁令正则（确定性删除——仅放明确无信息量的微操句式）
    banned_regexes: tuple = (
        r"嘴角[^\n，。]{0,6}?(上扬|勾起|抽动|上挑)",
        r"指尖[^\n，。]{0,4}?(颤|抖)",
        r"瞳孔[^\n，。]{0,4}?(收缩|放大|骤缩)",
        r"眼[中底]闪过一抹[^\n，。]{0,8}?(冷意|寒光|笑意|精光)",
        r"眼底[^\n，。]{0,4}?掠过[^\n，。]{0,8}?(冷|寒|笑)",
        r"唇角[^\n，。]{0,4}?(上扬|勾起|抿出)",
    )

    # 4. 套路比喻正则（仅统计密度，不进确定性裁剪——避免误伤合法比喻）
    metaphor_regexes: tuple = (
        r"像[^\n，。]{1,15}?一样",
        r"仿佛[^\n，。]{1,15}?(似的|一般)",
        r"如同[^\n，。]{1,15}?(一般|似的)",
    )

    # 5. 后置修饰语泛滥正则（"眼中带着一抹..."类，仅统计密度）
    trailing_modifier_regexes: tuple = (
        r"眼[中底]带着[^\n，。]{1,10}?(抹|丝|缕)",
        r"语气中带着[^\n，。]{1,10}?(抹|丝|缕)",
        r"神色间带着[^\n，。]{1,10}?(抹|丝|缕)",
    )

    # 6. 逻辑过渡词正则（仅统计密度，不进确定性裁剪——这类词可能是合法用法）
    # AI 行文最典型的特征：用逻辑衔接词把动作硬拼成"因为/所以/然而/随后"的因果链，
    # 破坏网文应有的硬切硬接节奏。
    transition_word_regexes: tuple = (
        r"然而",
        r"但是",
        r"随后",
        r"与此同时",
        r"不仅[^\n，。]{0,10}?(反而|而且|还)",
        r"随着[^\n，。]{1,8}?(，|的)",
        r"渐渐地",
        r"逐渐地",
        r"于是",
        r"因此",
        r"紧接着",
    )

    # 7. "的"字短语堆叠正则（仅统计密度）
    # AI 堆砌修饰的典型：同一短句内连续出现两个以上"……的……的……的"结构。
    zhi_phrase_regexes: tuple = (
        r"[^\n，。]{1,10}?的[^\n，。]{1,10}?的[^\n，。]{1,10}?的",
    )


@dataclass(frozen=True)
class DensityThresholds:
    """AI 味密度阈值（不可变）。

    所有阈值按"每 500 字"归一化，使不同字数段落的评分可比。
    超过阈值不代表直接删，而是触发对应的处理（裁剪/洗涤）。

    Attributes:
        micro_action_per_500: 每 500 字微操短语数上限。超出由 sanitizer 删。
        metaphor_per_500: 每 500 字套路比喻数上限。超出计入综合分。
        trailing_modifier_per_500: 每 500 字后置修饰语数上限。超出计入综合分。
        transition_per_500: 每 500 字逻辑过渡词数上限。超出计入综合分。
            AI 行文最典型的特征：用"然而/随后/与此同时"把动作硬拼成因果链。
        zhi_phrase_per_500: 每 500 字"的"字短语堆叠数上限。超出计入综合分。
            AI 堆砌修饰的典型：同一短句连续多个"……的……的"。
        sentence_length_cv_min: 句长变异系数下限。低于此值=句式过于匀速。
            CV = stddev/mean；中文小说正文 CV 通常 0.5~0.8，AI 腔常 <0.35。
        short_paragraph_ratio_max: 单句段（≤15 字的独立短段）占比上限。
            AI 腔典型：每百余字敲一个"警报响了。""迟了。"式重锤短段，
            实测超标文本占比可达 36%；人声写作重锤段极少，通常 <15%。
            段落数 <4 时不判（单段文本无段落节奏可言）。
        negation_twist_per_500: 每 500 字"不是X，是Y"否定反转句上限。
            AI 制造张力的头号模板：先否定读者预期再亮出"真相"，
            高频使用张力递减（实测超标文本 11 次/5080 字）。
        anaphora_per_500: 每 500 字三连排比上限。
            AI 高潮模板：同前缀短句×3 连发（"穿透A。穿透B。穿透C。"
            "是X。是Y。是Z。"）。按段内分句的同前缀分组检测。
        vehicle_reuse_per_500: 每 500 字喻体复用上限。
            AI"比喻义务化"的副产品：同一意象字（如"巨"）反复出现在
            多个比喻的喻体中（巨兽/巨型生物/巨人）。按内容字在
            ≥2 个不同喻体中复现计 1 次命中。
        overall_trigger: 综合分（0-100）触发阈值。超过则触发 LLM 洗涤 Pass。
            已从 55 放宽到 40：原阈值过死导致段内洗涤几乎从不触发，
            这是"去 AI 味效果差"的根因之一。
        wash_max_segments_per_chapter: 单章最多洗涤多少段（防成本失控）。
            已从 3 提到 8：原值只允许洗 3 段，4-6 段的章剩余段落只能正则轻裁。
    """

    micro_action_per_500: float = 2.0
    metaphor_per_500: float = 1.5
    trailing_modifier_per_500: float = 2.0
    transition_per_500: float = 1.5
    zhi_phrase_per_500: float = 1.5
    sentence_length_cv_min: float = 0.35
    short_paragraph_ratio_max: float = 0.25
    negation_twist_per_500: float = 1.0
    anaphora_per_500: float = 0.5
    vehicle_reuse_per_500: float = 1.0
    short_sentence_ratio_max: float = 0.25  # ≤5字碎句占比上限（PRUNE 剪枝后护栏用）
    overall_trigger: float = 40.0
    wash_max_segments_per_chapter: int = 8


# ============================================================
# 默认实例（全模块共享，规范2要求不可变常量）
# ============================================================

DEFAULT_BAN_LIST: AntiAIBanList = AntiAIBanList()
DEFAULT_THRESHOLDS: DensityThresholds = DensityThresholds()
