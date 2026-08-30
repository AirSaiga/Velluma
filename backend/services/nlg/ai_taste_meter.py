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
AI 味密度评估器 —— 纯算法层。

职责：
- 输入一段中文文本，输出 DensityReport（各维度命中数 + 归一化密度 + 综合分）
- 零 LLM 依赖、零 I/O、纯标准库（re/math/collections/dataclasses）
- 确定性：相同输入永远相同输出，便于单测

设计意图（对应 4 大反模式 + 段落级修辞模板）：
- 微操率  → 反模式 #1 病态微操
- 比喻频率 → 反模式 #2 套路比喻（含 metaphor_regexes + banned_words 里的意象）
- 句长变异系数 → 反模式 #3 匀速句式（CV 越低越机械）
- 后置修饰语频率 → 反模式 #3 的子项（"眼中带着一抹..."泛滥）
- 段落级加成（2026-07 新增，针对词语层检测漏掉的结构性 AI 腔）：
  · 单句段占比 → 鼓点式重锤短段滥用（"警报响了。""迟了。"每百字一次）
  · 否定反转句 → "不是X，是Y"张力模板（先否定预期再亮"真相"）
  · 三连排比   → 同前缀短句×3 连发的高潮模板（"穿透A。穿透B。穿透C。"）
  · 喻体复用   → 同一意象字在多个比喻中回收（巨兽/巨型生物/巨人）
- 综合分 = min(100, 词语层六维(满分100) + 段落级加成(满分25))，
  旧六维权重不变（避免回归），超 overall_trigger 则由 de_ai_washer 触发 LLM 洗涤

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
        paragraph_count: 叙述段数（按换行切分，排除引号开头的对白段）
        short_paragraph_count: 单句段数（≤15 字的独立叙述短段）
        short_paragraph_ratio: 单句段占比；叙述段数 <4 时为 0（样本不足不判）
        negation_twist_hits: 命中的"不是X，是Y"否定反转句列表
        negation_twist_density: 每 500 字否定反转句密度
        anaphora_hits: 命中的三连排比描述列表（如 "'穿透'开头×3"）
        anaphora_density: 每 500 字三连排比密度
        vehicle_reuse_hits: 命中的喻体复用描述列表（如 "'巨'出现于3个比喻"）
        vehicle_reuse_density: 每 500 字喻体复用密度
        overall_score: 综合分 0-100（词语层六维满分100 + 段落级加成满分25，
            截断到 100），越高越像 AI 腔
        triggered: 是否触发 LLM 洗涤（综合分超 overall_trigger，
            或 ≥2 个段落级维度超标 / 单句段占比超 2 倍上限的结构性触发）
        flagged_reasons: 触发的维度说明（人类可读，供审计/日志/wash prompt）
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
    paragraph_count: int = 0
    short_paragraph_count: int = 0
    short_paragraph_ratio: float = 0.0
    negation_twist_hits: List[str] = field(default_factory=list)
    negation_twist_density: float = 0.0
    anaphora_hits: List[str] = field(default_factory=list)
    anaphora_density: float = 0.0
    vehicle_reuse_hits: List[str] = field(default_factory=list)
    vehicle_reuse_density: float = 0.0
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

# ============================================================
# 段落级修辞模板检测（词语层检测漏掉的结构性 AI 腔）
# ============================================================

# 段落切分（按换行）
_PARA_SPLIT = re.compile(r"\n+")

# 单句段判定：≤15 字的独立短段（"警报响了。""迟了。""但血噬选中了他。"）
_SHORT_PARA_MAX_CHARS = 15
# 段落数不足此值不做段落节奏判断（单段文本无节奏可言）
_MIN_PARAGRAPHS_FOR_RATIO = 4

# "不是X，是Y"否定反转句：X≤20 字，X 与 Y 之间以标点/破折号断开
# 排除"是不是"（疑问/犹豫的合法用法）
_NEGATION_TWIST = re.compile(r"不是(?!是)[^。！？!?\n]{1,20}?[，。；;、…—-]是")

# 分句切分（排比检测用，比句子更细：逗号/破折号/冒号也算）
_CLAUSE_END = re.compile(r"[，。！？!?；;、…\n—：]")
# 排比前缀允许的最大分句长度（过长不太可能是模板排比）
_ANAPHORA_MAX_CLAUSE = 30
# 引导引号/括号（分句前缀归一化时剥掉）
_LEADING_QUOTES = "″\"“”‘’「『（(《"
# 对白段起始引号（对白行天然是短段，不计入"重锤短段"统计——防对话密集段误伤）
_DIALOGUE_OPENERS = set("″\"“‘「『'")

# 比喻标记：像（排除好像/想像/图像等）、仿佛、宛如、犹如、好似(乎除外)、如同、如(今/果/何/此/同除外)
_SIMILE_MARKER = re.compile(
    r"(?<![好图影画相头想声])像|好似(?!乎)|仿佛|宛如|犹如|如同|如(?!今|果|何|此|同|下|上|意)"
)
# 喻体截取：标记后 ≤12 字（到标点为止）
_SIMILE_VEHICLE = re.compile(r"[^，。！？!?；;、\n]{1,12}")
# 喻体前的数量/模糊前缀（归一化时剥掉）
_VEHICLE_PREFIXES = ("什么", "某种", "一个", "一只", "一条", "一道", "一群", "个")
# 喻体复用统计时忽略的功能字（避免"的/个/一"类字误报）
_VEHICLE_STOPCHARS = set("的么什某了和与在般样似同个种只条道群把被让使着过是有没不一二两半千万")


def _short_paragraph_stats(text: str) -> Tuple[int, int, float]:
    """统计单句段占比（仅统计叙述段，排除引号开头的对白段）。

    对白行天然是独立短段（"你走了？""走了。"），不是重锤模板；
    分子分母都不计入，避免对话密集段误伤。

    Returns:
        tuple: (单句段数, 叙述段总数, 占比)。叙述段数 <4 时占比返回 0。
    """
    paras = [p.strip() for p in _PARA_SPLIT.split(text) if p.strip()]
    narrative = [p for p in paras if p[0] not in _DIALOGUE_OPENERS]
    total = len(narrative)
    if total < _MIN_PARAGRAPHS_FOR_RATIO:
        return 0, total, 0.0
    short = sum(1 for p in narrative if len(p) <= _SHORT_PARA_MAX_CHARS)
    return short, total, short / total


def _negation_twist_hits(text: str) -> List[str]:
    """命中所有"不是X，是Y"否定反转句，返回命中串列表。"""
    return [m.group(0) for m in _NEGATION_TWIST.finditer(text)]


def _anaphora_hits(text: str) -> List[str]:
    """检测三连排比：同一段内 ≥3 个分句共享同一前缀（2 字前缀，或单字"是"）。

    AI 高潮模板："穿透弹幕。穿透爆炸。穿透一切阻拦。""是X。是Y。是Z。"
    按段检测（排比通常集中在同一段），返回人类可读的命中描述列表。
    """
    hits: List[str] = []
    for para in _PARA_SPLIT.split(text):
        clauses = [
            c.strip().lstrip(_LEADING_QUOTES)
            for c in _CLAUSE_END.split(para)
        ]
        clauses = [c for c in clauses if 2 <= len(c) <= _ANAPHORA_MAX_CLAUSE]
        if len(clauses) < 3:
            continue
        groups: dict = {}
        for c in clauses:
            key2 = c[:2]
            groups.setdefault(key2, 0)
            groups[key2] += 1
            # 单字"是"开头的分句（"是X。是Y。是Z。"）2 字前缀各不相同，单独归组
            if c.startswith("是"):
                groups.setdefault("是*", 0)
                groups["是*"] += 1
        for key, n in groups.items():
            if n >= 3:
                label = key.rstrip("*")
                hits.append(f"'{label}'开头×{n}")
    return hits


def _vehicle_reuse_hits(text: str) -> List[str]:
    """检测喻体复用：同一内容字出现在 ≥2 个不同比喻的喻体中。

    AI"比喻义务化"的副产品：全段回收同一意象（巨兽/巨型生物/巨人 → "巨"）。
    返回人类可读的命中描述列表（每个复用字 1 条）。
    """
    vehicles: List[str] = []
    for m in _SIMILE_MARKER.finditer(text):
        vm = _SIMILE_VEHICLE.match(text, m.end())
        if not vm:
            continue
        v = vm.group(0)
        for prefix in _VEHICLE_PREFIXES:
            if v.startswith(prefix):
                v = v[len(prefix):]
                break
        v = v[:6].strip()
        if v:
            vehicles.append(v)
    if len(vehicles) < 2:
        return []
    # 统计每个内容字出现在多少个不同喻体中
    char_in_vehicles: dict = {}
    for v in vehicles:
        for ch in set(v) - _VEHICLE_STOPCHARS:
            char_in_vehicles.setdefault(ch, set()).add(v)
    return [
        f"'{ch}'出现于{len(vs)}个比喻"
        for ch, vs in char_in_vehicles.items()
        if len(vs) >= 2
    ]


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


def short_sentence_ratio(text: str) -> Tuple[int, int, float]:
    """碎句率：≤5 字碎句占全部句子的比例（碎句化检测，与"匀速句式"对称的反模式）。

    业务场景：PRUNE 剪枝后护栏——早期 prune prompt 要求"长句切碎+极短句连发"，
    实测整章 ≤5 字碎句占比达 41%（机枪句），比匀速句式更糟。
    健康中文小说该比例通常 <10%。

    Returns:
        tuple: (碎句数, 句子总数, 碎句率)。句数 <10 时返回 0（样本不足不判）。
    """
    if not text:
        return 0, 0, 0.0
    parts = [p.strip() for p in _SENTENCE_END.split(text) if p.strip()]
    total = len(parts)
    if total < 10:
        return 0, total, 0.0
    short = sum(1 for p in parts if len(p) <= 5)
    return short, total, short / total


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


def _score_scaled(density: float, threshold: float, cap: float) -> float:
    """通用密度计分：密度/阈值 线性映射到 0-cap。"""
    if threshold <= 0:
        return cap if density > 0 else 0.0
    return min(cap, density / threshold * cap)


def _score_short_paragraph(ratio: float, max_ratio: float) -> float:
    """单句段占比 → 0-10 分。占比 ≤ max_ratio 不扣分；
    超出后线性升分，占比达 2 倍上限时满档。"""
    if max_ratio <= 0:
        return 10.0 if ratio > 0 else 0.0
    if ratio <= max_ratio:
        return 0.0
    return min(10.0, (ratio / max_ratio - 1.0) * 10.0)


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

    # 维度 7：单句段占比（鼓点式重锤短段滥用）
    short_count, para_count, short_ratio = _short_paragraph_stats(text)

    # 维度 8："不是X，是Y"否定反转句
    neg_hits = _negation_twist_hits(text)
    neg_density = _normalize(len(neg_hits), char_count)

    # 维度 9：三连排比（同前缀分句×3）
    ana_hits = _anaphora_hits(text)
    ana_density = _normalize(len(ana_hits), char_count)

    # 维度 10：喻体复用（同一意象字出现在多个比喻中）
    veh_hits = _vehicle_reuse_hits(text)
    veh_density = _normalize(len(veh_hits), char_count)

    # 综合分：词语层六维（满分 100，权重不变）+ 段落级加成（满分 25），截断到 100
    word_level = (
        _score_micro_action(micro_density, thresholds.micro_action_per_500)
        + _score_metaphor(metaphor_density, thresholds.metaphor_per_500)
        + _score_trailing(trailing_density, thresholds.trailing_modifier_per_500)
        + _score_transition(transition_density, thresholds.transition_per_500)
        + _score_zhi_phrase(zhi_density, thresholds.zhi_phrase_per_500)
        + _score_rhythm(cv, thresholds.sentence_length_cv_min)
    )
    paragraph_bonus = (
        _score_short_paragraph(short_ratio, thresholds.short_paragraph_ratio_max)
        + _score_scaled(neg_density, thresholds.negation_twist_per_500, 6.0)
        + _score_scaled(ana_density, thresholds.anaphora_per_500, 5.0)
        + _score_scaled(veh_density, thresholds.vehicle_reuse_per_500, 4.0)
    )
    overall = min(100.0, word_level + paragraph_bonus)

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
    if short_ratio > thresholds.short_paragraph_ratio_max:
        flagged.append(
            f"单句段占比 {short_ratio:.0%}（{short_count}/{para_count} 段≤{_SHORT_PARA_MAX_CHARS}字，"
            f"上限 {thresholds.short_paragraph_ratio_max:.0%}）"
            f"——重锤短段滥用，合并进上下文，只保留极少数真正的重锤"
        )
    if neg_density > thresholds.negation_twist_per_500:
        flagged.append(
            f"否定反转句 {neg_density:.1f}/500字（上限 {thresholds.negation_twist_per_500}）"
            f"：{neg_hits[0][:30]} ——删掉先否定再肯定的绕路，直接陈述"
        )
    if ana_density > thresholds.anaphora_per_500:
        flagged.append(
            f"三连排比 {ana_density:.1f}/500字（上限 {thresholds.anaphora_per_500}）"
            f"：{'、'.join(ana_hits[:3])} ——至多保留一处，其余拆散改写"
        )
    if veh_density > thresholds.vehicle_reuse_per_500:
        flagged.append(
            f"喻体复用 {veh_density:.1f}/500字（上限 {thresholds.vehicle_reuse_per_500}）"
            f"：{'、'.join(veh_hits[:3])} ——同一意象只用一次，其余换新鲜意象或删掉"
        )

    # 结构模板触发：段落级维度是强 AI 签名，但加成上限（25 分）够不到洗涤阈值。
    # 规则：≥2 个段落级维度超标，或单句段占比超 2 倍上限 → 直接触发洗涤。
    structural_fired = sum([
        short_ratio > thresholds.short_paragraph_ratio_max,
        neg_density > thresholds.negation_twist_per_500,
        ana_density > thresholds.anaphora_per_500,
        veh_density > thresholds.vehicle_reuse_per_500,
    ])
    structural_override = (
        structural_fired >= 2
        or short_ratio > 2 * thresholds.short_paragraph_ratio_max
    )
    if structural_override:
        flagged.append(f"结构模板多重命中（{structural_fired}/4 维度），直接触发洗涤")

    triggered = overall >= thresholds.overall_trigger or structural_override

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
        paragraph_count=para_count,
        short_paragraph_count=short_count,
        short_paragraph_ratio=round(short_ratio, 3),
        negation_twist_hits=neg_hits,
        negation_twist_density=round(neg_density, 2),
        anaphora_hits=ana_hits,
        anaphora_density=round(ana_density, 2),
        vehicle_reuse_hits=veh_hits,
        vehicle_reuse_density=round(veh_density, 2),
        overall_score=round(overall, 1),
        triggered=triggered,
        flagged_reasons=flagged,
    )
