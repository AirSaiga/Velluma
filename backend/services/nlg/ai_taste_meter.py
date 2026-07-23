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
AI 味密度评估器 —— 纯算法层。

职责：
- 输入一段中文文本，输出 DensityReport（各维度命中数 + 归一化密度 + 综合分）
- 零 LLM 依赖、零 I/O、纯标准库（re/math/collections/dataclasses）
- 确定性：相同输入永远相同输出，便于单测

设计意图（对应 4 大反模式）：
- 微操率  → 反模式 #1 病态微操
- 比喻频率 → 反模式 #2 套路比喻（含 metaphor_regexes + banned_words 里的意象）
- 句长变异系数 → 反模式 #3 匀速句式（CV 越低越机械）
- 后置修饰语频率 → 反模式 #3 的子项（"眼中带着一抹..."泛滥）
- 综合分加权汇总，超 overall_trigger 则由 de_ai_washer 触发 LLM 洗涤

归一化基准：每 500 字。中文小说单段 400~820 字，归一化后阈值跨段可比。

业务场景：
- segment_writer 每段 LLM 返回后调用，决定走 sanitizer 还是 washer
- structure_checker 第 5 维度读取综合分作为文风质量评分
"""

import re
import statistics
from dataclasses import dataclass, field
from typing import List, Tuple

from backend.services.nlg.anti_ai_rules import (
    AntiAIBanList,
    DensityThresholds,
    DEFAULT_BAN_LIST,
    DEFAULT_THRESHOLDS,
)

# 归一化基准字数
_NORM_BASE = 500.0


@dataclass
class DensityReport:
    """单段文本的 AI 味密度报告。

    Attributes:
        char_count: 文本字符数（用于归一化分母）
        micro_action_hits: 命中的微操短语列表（具体命中串）
        micro_action_density: 每 500 字微操密度
        metaphor_hits: 命中的套路比喻列表
        metaphor_density: 每 500 字比喻密度
        trailing_modifier_hits: 命中的后置修饰语列表
        trailing_modifier_density: 每 500 字后置修饰语密度
        transition_hits: 命中的逻辑过渡词列表
        transition_density: 每 500 字逻辑过渡词密度
        zhi_phrase_hits: 命中的"的"字短语堆叠列表
        zhi_phrase_density: 每 500 字"的"字短语堆叠密度
        sentence_count: 句子数（按中文句末标点切分）
        sentence_length_cv: 句长变异系数（stddev/mean）；文本过短时为 None
        overall_score: 综合分 0-100（加权汇总），越高越像 AI 腔
        triggered: 是否超过 overall_trigger 阈值（触发 LLM 洗涤的硬开关）
        flagged_reasons: 触发的维度说明（人类可读，供审计/日志）
    """

    char_count: int = 0
    micro_action_hits: List[str] = field(default_factory=list)
    micro_action_density: float = 0.0
    metaphor_hits: List[str] = field(default_factory=list)
    metaphor_density: float = 0.0
    trailing_modifier_hits: List[str] = field(default_factory=list)
    trailing_modifier_density: float = 0.0
    transition_hits: List[str] = field(default_factory=list)
    transition_density: float = 0.0
    zhi_phrase_hits: List[str] = field(default_factory=list)
    zhi_phrase_density: float = 0.0
    sentence_count: int = 0
    sentence_length_cv: float = 0.0
    overall_score: float = 0.0
    triggered: bool = False
    flagged_reasons: List[str] = field(default_factory=list)


# 预编译正则（模块级，避免每次调用重编译）
def _compile_all(patterns: Tuple[str, ...]) -> List[re.Pattern]:
    return [re.compile(p) for p in patterns]


_MICRO_ACTION_PATTERNS = _compile_all(DEFAULT_BAN_LIST.banned_regexes)
_METAPHOR_PATTERNS = _compile_all(DEFAULT_BAN_LIST.metaphor_regexes)
_TRAILING_PATTERNS = _compile_all(DEFAULT_BAN_LIST.trailing_modifier_regexes)
_TRANSITION_PATTERNS = _compile_all(DEFAULT_BAN_LIST.transition_word_regexes)
_ZHI_PHRASE_PATTERNS = _compile_all(DEFAULT_BAN_LIST.zhi_phrase_regexes)

# 中文句末标点（用于句长统计）
_SENTENCE_END = re.compile(r"[。！？!?…]")


def _count_hits(text: str, patterns: List[re.Pattern]) -> List[str]:
    """统计所有 pattern 在 text 中的命中（返回命中串列表，含重复）。"""
    hits: List[str] = []
    for pat in patterns:
        hits.extend(m.group(0) for m in pat.finditer(text))
    return hits


def _count_substring_hits(text: str, words: Tuple[str, ...]) -> List[str]:
    """统计词表（普通子串）命中，返回命中词列表（按出现次数重复）。"""
    hits: List[str] = []
    for w in words:
        if not w:
            continue
        cnt = text.count(w)
        hits.extend([w] * cnt)
    return hits


def _normalize(count: int, char_count: int) -> float:
    """归一化到每 500 字密度。文本过短（<50字）按 50 字计，避免密度爆炸。"""
    denom = max(50, char_count)
    return count * (_NORM_BASE / denom)


def _sentence_length_cv(text: str) -> Tuple[int, float]:
    """计算句长变异系数。

    按中文句末标点（。！？…）切分，统计每句字符数的变异系数。
    CV = stddev/mean。句数 <3 时返回 0（样本不足，不判匀速）。

    Returns:
        tuple: (句子数, 变异系数)
    """
    # 用句末标点切分，保留非空片段
    parts = _SENTENCE_END.split(text)
    lengths = [len(p.strip()) for p in parts if p.strip()]
    lengths = [l for l in lengths if l > 0]
    if len(lengths) < 3:
        return len(lengths), 0.0
    mean = statistics.mean(lengths)
    if mean == 0:
        return len(lengths), 0.0
    stdev = statistics.pstdev(lengths)
    return len(lengths), stdev / mean


def _score_micro_action(density: float, threshold: float) -> float:
    """微操密度 → 0-25 分。超阈值即满档，线性映射。"""
    if threshold <= 0:
        return 25.0 if density > 0 else 0.0
    ratio = density / threshold
    return min(25.0, ratio * 25.0)


def _score_metaphor(density: float, threshold: float) -> float:
    """比喻密度 → 0-20 分。"""
    if threshold <= 0:
        return 20.0 if density > 0 else 0.0
    ratio = density / threshold
    return min(20.0, ratio * 20.0)


def _score_trailing(density: float, threshold: float) -> float:
    """后置修饰语密度 → 0-15 分。"""
    if threshold <= 0:
        return 15.0 if density > 0 else 0.0
    ratio = density / threshold
    return min(15.0, ratio * 15.0)


def _score_transition(density: float, threshold: float) -> float:
    """逻辑过渡词密度 → 0-10 分。
    AI 行文典型：用"然而/随后/与此同时"硬拼动作因果链。
    """
    if threshold <= 0:
        return 10.0 if density > 0 else 0.0
    ratio = density / threshold
    return min(10.0, ratio * 10.0)


def _score_zhi_phrase(density: float, threshold: float) -> float:
    """的-短语堆叠密度 → 0-10 分。
    AI 堆砌修饰典型：同句连续多个"……的……的……的"。
    """
    if threshold <= 0:
        return 10.0 if density > 0 else 0.0
    ratio = density / threshold
    return min(10.0, ratio * 10.0)


def _score_rhythm(cv: float, cv_min: float) -> float:
    """句长变异系数 → 0-20 分。CV 越低（越匀速）分越高。
    cv >= cv_min → 0 分（节奏正常）；cv < cv_min → 线性升到 20 分。
    cv=0（样本不足）返回 0，不冤枉短文本。
    """
    if cv <= 0:
        return 0.0
    if cv >= cv_min:
        return 0.0
    # cv 在 (0, cv_min) 区间线性映射到 (20, 0)
    return 20.0 * (1.0 - cv / cv_min)


def measure_ai_taste(
    text: str,
    ban_list: AntiAIBanList = DEFAULT_BAN_LIST,
    thresholds: DensityThresholds = DEFAULT_THRESHOLDS,
) -> DensityReport:
    """评估一段文本的 AI 味密度。

    纯算法、确定性、零外部依赖。相同输入恒定输出。

    Args:
        text: 待评估文本（通常为单段 LLM 生成正文）
        ban_list: 禁令清单（默认 DEFAULT_BAN_LIST）
        thresholds: 密度阈值（默认 DEFAULT_THRESHOLDS）

    Returns:
        DensityReport：含各维度命中、密度、综合分、是否触发洗涤

    使用方式：
        report = measure_ai_taste(segment_text)
        if report.triggered:
            await wash_segment_if_too_ai(segment_text, report)
        else:
            sanitized = sanitize_segment(segment_text)
    """
    if not text or not text.strip():
        return DensityReport()

    char_count = len(text)

    # 维度 1：微操（词表子串 + 句式正则）
    micro_hits = _count_substring_hits(text, ban_list.banned_micro_actions)
    micro_hits += _count_hits(text, _MICRO_ACTION_PATTERNS)
    micro_density = _normalize(len(micro_hits), char_count)

    # 维度 2：套路比喻（正则 + banned_words 里的意象词）
    metaphor_hits = _count_hits(text, _METAPHOR_PATTERNS)
    metaphor_hits += _count_substring_hits(text, ban_list.banned_words)
    metaphor_density = _normalize(len(metaphor_hits), char_count)

    # 维度 3：后置修饰语
    trailing_hits = _count_hits(text, _TRAILING_PATTERNS)
    trailing_density = _normalize(len(trailing_hits), char_count)

    # 维度 4：逻辑过渡词（AI 行文最典型：然而/随后/与此同时 硬拼因果链）
    transition_hits = _count_hits(text, _TRANSITION_PATTERNS)
    transition_density = _normalize(len(transition_hits), char_count)

    # 维度 5：的-短语堆叠（AI 堆砌修饰：同句连续多个"……的……的"）
    zhi_hits = _count_hits(text, _ZHI_PHRASE_PATTERNS)
    zhi_density = _normalize(len(zhi_hits), char_count)

    # 维度 6：句长变异系数
    sent_count, cv = _sentence_length_cv(text)

    # 综合分（加权：微操25 + 比喻20 + 后置15 + 转折词10 + 的-短语10 + 节奏20 = 100）
    overall = (
        _score_micro_action(micro_density, thresholds.micro_action_per_500)
        + _score_metaphor(metaphor_density, thresholds.metaphor_per_500)
        + _score_trailing(trailing_density, thresholds.trailing_modifier_per_500)
        + _score_transition(transition_density, thresholds.transition_per_500)
        + _score_zhi_phrase(zhi_density, thresholds.zhi_phrase_per_500)
        + _score_rhythm(cv, thresholds.sentence_length_cv_min)
    )

    flagged: List[str] = []
    if micro_density > thresholds.micro_action_per_500:
        flagged.append(f"微操密度 {micro_density:.1f}/{thresholds.micro_action_per_500}")
    if metaphor_density > thresholds.metaphor_per_500:
        flagged.append(f"比喻密度 {metaphor_density:.1f}/{thresholds.metaphor_per_500}")
    if trailing_density > thresholds.trailing_modifier_per_500:
        flagged.append(f"后置修饰 {trailing_density:.1f}/{thresholds.trailing_modifier_per_500}")
    if transition_density > thresholds.transition_per_500:
        flagged.append(f"逻辑过渡词 {transition_density:.1f}/{thresholds.transition_per_500}")
    if zhi_density > thresholds.zhi_phrase_per_500:
        flagged.append(f"的-短语堆叠 {zhi_density:.1f}/{thresholds.zhi_phrase_per_500}")
    if 0 < cv < thresholds.sentence_length_cv_min:
        flagged.append(f"句式匀速 CV={cv:.2f}<{thresholds.sentence_length_cv_min}")

    return DensityReport(
        char_count=char_count,
        micro_action_hits=micro_hits,
        micro_action_density=round(micro_density, 2),
        metaphor_hits=metaphor_hits,
        metaphor_density=round(metaphor_density, 2),
        trailing_modifier_hits=trailing_hits,
        trailing_modifier_density=round(trailing_density, 2),
        transition_hits=transition_hits,
        transition_density=round(transition_density, 2),
        zhi_phrase_hits=zhi_hits,
        zhi_phrase_density=round(zhi_density, 2),
        sentence_count=sent_count,
        sentence_length_cv=round(cv, 3),
        overall_score=round(overall, 1),
        triggered=overall >= thresholds.overall_trigger,
        flagged_reasons=flagged,
    )
