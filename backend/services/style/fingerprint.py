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
文风指纹测量（文风模块重构 S1 测量层，docs/style-module-redesign.md §3-②/§7.3）。

职责：
- 输入一段中文文本，输出确定性指纹 dict（句长/对话占比/段落/标点/修辞密度/
  词汇丰富度/词级重复密度）
- 零 LLM 依赖、零 I/O；标准库（re/statistics）+ ai_taste_meter 复用
  + jieba 分词（懒加载，仅词汇/重复两族指标用，首调用建词典一次）
- 确定性：相同输入永远相同输出，便于单测与对账

「同一把尺子」原则（设计稿 §3-②）：
- 句长切分 / 字数口径 / 变异系数 / 对话字符统计的**规范实现**在本模块，
  审计侧（services/validation/code_auditors.py）从此处 import——
  作者样本与生成文本用同一套算法测量，这是「对账区」数值可比的前提。
- 对拍单测（test_fingerprint.py）锁定：同一文本在指纹侧与
  RhythmAuditor.sentence_len_cv / DialogueAuditor.dialogue_ratio 上同值。

指纹 dict 结构（JSONB/JSON 直存直传）：
- char_count / word_count                字数（word_count 与审计侧口径一致：去空白计长）
- sentence_count / sentence_len_mean / sentence_len_median / sentence_len_cv
- short_sentence_ratio                   ≤5 字碎句占比（句数 <10 不判，同 ai_taste_meter）
- sentence_len_histogram                 句长分布五桶（lte5/6_10/11_20/21_30/gt30），可视化用
- dialogue_ratio                          对话占比（引号内字符 / 全文字数，审计同口径）
- paragraph_count / paragraph_len_mean / short_paragraph_ratio（叙述段，排除对白段）
- punctuation                             破折号/省略号/叹号/问号 每千字频率
- rhetoric（light 模式省略）              比喻/微操/过渡词 每 500 字密度 + AI 味综合分
- lexical                                 词汇丰富度：token_count/ttr/mattr（MATTR 窗口
                                          100 词；<30 词不判 → None，同碎句率哲学）
- repetition                              词级 bigram 重复密度 + 频次 top5（<50 词不判；
                                          参考性指标——角色名等正当重复会抬高，不进门禁）
"""

import re
import statistics
from typing import Dict, List, Optional

from backend.services.nlg.ai_taste_meter import measure_ai_taste

# ============================================================
# 规范原语（审计侧与文风侧共用的"同一把尺子"）
# ============================================================
# 以下四个函数的语义与 code_auditors.py 历史实现逐字节对齐
# （对拍单测锁定）；改动它们 = 同时改变审计指标口径，须跑对拍后再动。

_SENTENCE_SPLIT = re.compile(r"[。！？!?\n]")
_SENTENCE_MIN_CHARS = 2  # 过滤 ≤2 字碎片（标点连写/空白，与审计侧一致）

# 对话引号对（中文优先 + 英文双引号），与 DialogueAuditor 历史口径一致
# （\u201c=\u201c \u201d=\u201d，用转义写死防编辑器引号归一化弄反）
_DIALOGUE_QUOTE_PAIRS = (
    ("\u201c", "\u201d"),
    ("\u300c", "\u300d"),
    ("\u300e", "\u300f"),
    ("\"", "\""),
)


def split_sentences(text: str) -> List[str]:
    """按中英文句末标点切句，过滤 ≤2 字碎片（审计侧 RhythmAuditor 同口径）。"""
    if not text:
        return []
    parts = _SENTENCE_SPLIT.split(text)
    return [s.strip() for s in parts if len(s.strip()) > _SENTENCE_MIN_CHARS]


def count_words(text: str) -> int:
    """字数（去所有空白后计长；与审计侧 _count_words / drafting 口径一致）。"""
    if not text:
        return 0
    return len(re.sub(r"\s+", "", text))


def coefficient_of_variation(values: List[float]) -> float:
    """变异系数 CV = stddev / mean（总体标准差）。空列表/均值 0 返回 0。"""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return (variance ** 0.5) / mean


def count_dialogue_chars(text: str) -> int:
    """统计被成对引号包裹的字符数（含引号本身；DialogueAuditor 同口径）。"""
    if not text:
        return 0
    total = 0
    for open_q, close_q in _DIALOGUE_QUOTE_PAIRS:
        in_quote = False
        for ch in text:
            if not in_quote and ch == open_q:
                in_quote = True
                total += 1
            elif in_quote and ch == close_q:
                in_quote = False
                total += 1
            elif in_quote:
                total += 1
    return total


# ============================================================
# 指纹内部统计（不进审计侧，仅指纹用）
# ============================================================

_PARAGRAPH_SPLIT = re.compile(r"\n+")
_SHORT_SENTENCE_MAX_CHARS = 5    # 碎句判定（同 ai_taste_meter.short_sentence_ratio）
_SHORT_SENTENCE_MIN_COUNT = 10   # 句数不足不判碎句率（同上）
_SHORT_PARAGRAPH_MAX_CHARS = 15  # 重锤短段判定（同 ai_taste_meter）
_MIN_PARAGRAPHS_FOR_RATIO = 4    # 段数不足不判短段占比（同上）
# 对白段起始引号：对白行天然是短段，不计入叙述段统计（防对话密集误伤）
_DIALOGUE_OPENERS = frozenset("″“\"\"‘「『'")


def _sentence_stats(sentences: List[str]) -> Dict[str, float]:
    """句长族指标：均值/中位数/CV/碎句率/五桶直方图。"""
    lengths = [len(s) for s in sentences]
    count = len(lengths)
    if count == 0:
        return {
            "sentence_count": 0,
            "sentence_len_mean": 0.0,
            "sentence_len_median": 0.0,
            "sentence_len_cv": 0.0,
            "short_sentence_ratio": 0.0,
            "sentence_len_histogram": _empty_histogram(),
        }
    short_count = sum(1 for l in lengths if l <= _SHORT_SENTENCE_MAX_CHARS)
    return {
        "sentence_count": count,
        "sentence_len_mean": round(statistics.mean(lengths), 1),
        "sentence_len_median": round(statistics.median(lengths), 1),
        "sentence_len_cv": round(coefficient_of_variation([float(l) for l in lengths]), 3),
        "short_sentence_ratio": round(short_count / count, 3) if count >= _SHORT_SENTENCE_MIN_COUNT else 0.0,
        "sentence_len_histogram": _histogram(lengths),
    }


def _histogram(lengths: List[int]) -> Dict[str, int]:
    buckets = _empty_histogram()
    for l in lengths:
        if l <= 5:
            buckets["lte5"] += 1
        elif l <= 10:
            buckets["6_10"] += 1
        elif l <= 20:
            buckets["11_20"] += 1
        elif l <= 30:
            buckets["21_30"] += 1
        else:
            buckets["gt30"] += 1
    return buckets


def _empty_histogram() -> Dict[str, int]:
    return {"lte5": 0, "6_10": 0, "11_20": 0, "21_30": 0, "gt30": 0}


def _paragraph_stats(text: str) -> Dict[str, float]:
    """段落族指标（仅叙述段：排除引号开头的对白段）。"""
    paras = [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if p.strip()]
    narrative = [p for p in paras if p and p[0] not in _DIALOGUE_OPENERS]
    count = len(narrative)
    if count == 0:
        return {
            "paragraph_count": 0,
            "paragraph_len_mean": 0.0,
            "short_paragraph_ratio": 0.0,
        }
    lengths = [len(p) for p in narrative]
    short = sum(1 for l in lengths if l <= _SHORT_PARAGRAPH_MAX_CHARS)
    return {
        "paragraph_count": count,
        "paragraph_len_mean": round(statistics.mean(lengths), 1),
        "short_paragraph_ratio": round(short / count, 3) if count >= _MIN_PARAGRAPHS_FOR_RATIO else 0.0,
    }


def _punctuation_stats(text: str, word_count: int) -> Dict[str, float]:
    """标点习惯：破折号/省略号/叹号/问号每千字频率（去空白字数为分母）。"""
    denom = max(1, word_count)
    per_1k = lambda n: round(n / denom * 1000, 2)  # noqa: E731
    return {
        "dash_per_1k": per_1k(text.count("—")),
        "ellipsis_per_1k": per_1k(text.count("…")),
        "exclaim_per_1k": per_1k(text.count("！") + text.count("!")),
        "question_per_1k": per_1k(text.count("？") + text.count("?")),
    }


def _rhetoric_stats(text: str) -> Dict[str, float]:
    """修辞密度：复用 ai_taste_meter（纯算法、确定性），每 500 字归一。"""
    report = measure_ai_taste(text)
    return {
        "metaphor_per_500": report.metaphor_density,
        "micro_action_per_500": report.micro_action_density,
        "transition_per_500": report.transition_density,
        "ai_taste_score": report.overall_score,
    }


# ============================================================
# 词汇丰富度与重复密度（NLP 扩展：jieba 分词 + 纯算法统计）
# ============================================================

_TOKEN_KEEP = re.compile(r"[\w一-鿿]+")  # 去纯标点/空白/符号（含 CJK 区间）
_LEX_MIN_TOKENS = 30    # token 不足不判丰富度（同碎句率「句数<10 不判」哲学）
_MATTR_WINDOW = 100     # MATTR 移动窗口（词数）
_REP_MIN_TOKENS = 50    # token 不足不判重复密度
_REP_BIGRAM_MIN_FREQ = 3  # bigram 频次达此值计为「重复」
_REP_TOP_K = 5          # 重复 bigram 取前 K


def _tokenize(text: str) -> List[str]:
    """jieba 分词 + 过滤纯标点/空白/符号。

    jieba 在函数内懒 import：首调用建缓存词典约数百毫秒（一次性），
    模块顶层 import 会拖慢启动与测试首载，勿上提。
    """
    import jieba

    return [tok for tok in jieba.lcut(text) if _TOKEN_KEEP.fullmatch(tok)]


def _mattr(tokens: List[str], window: int) -> float:
    """移动平均 TTR（MATTR，Covington & McFall 1982）：步长 1 逐窗 TTR 取均值。

    滑窗计数增量维护（O(n)）而非逐窗重建 set（O(n·window)）——
    语料聚合指纹可达数万 token，逐窗重建在长语料上不可承受。
    """
    n_windows = len(tokens) - window + 1
    counts: Dict[str, int] = {}
    for tok in tokens[:window]:
        counts[tok] = counts.get(tok, 0) + 1
    distinct_sum = len(counts)
    for i in range(1, n_windows):
        # 移出左端 tokens[i-1]，移入右端 tokens[i+window-1]
        left = tokens[i - 1]
        counts[left] -= 1
        if counts[left] == 0:
            del counts[left]
        right = tokens[i + window - 1]
        counts[right] = counts.get(right, 0) + 1
        distinct_sum += len(counts)
    return distinct_sum / n_windows / window


def _lexical_stats(tokens: List[str]) -> Dict:
    """词汇丰富度：TTR（类型/令牌比）+ MATTR（长度不敏感的移动平均 TTR）。"""
    n = len(tokens)
    if n < _LEX_MIN_TOKENS:
        return {"token_count": n, "ttr": None, "mattr": None}
    ttr = round(len(set(tokens)) / n, 3)
    mattr = ttr if n < _MATTR_WINDOW else round(_mattr(tokens, _MATTR_WINDOW), 3)
    return {"token_count": n, "ttr": ttr, "mattr": mattr}


def _repetition_stats(tokens: List[str]) -> Dict:
    """词级 bigram 重复密度。

    ⚠ 参考性指标：角色名/固定搭配等正当重复会自然抬高该值，
    只用于呈现与漂移轻提示，不进任何门禁（判断权在作者）。
    """
    n = len(tokens)
    if n < _REP_MIN_TOKENS:
        return {"bigram_repeat_ratio": None, "repeated_bigrams_top": []}
    bigram_counts: Dict[str, int] = {}
    for i in range(n - 1):
        key = tokens[i] + tokens[i + 1]
        bigram_counts[key] = bigram_counts.get(key, 0) + 1
    total = n - 1
    repeated_total = sum(c for c in bigram_counts.values() if c >= _REP_BIGRAM_MIN_FREQ)
    # 频次降序 + 字符串升序 tiebreak（保确定性）
    top = sorted(
        ((bg, c) for bg, c in bigram_counts.items() if c >= _REP_BIGRAM_MIN_FREQ),
        key=lambda kv: (-kv[1], kv[0]),
    )[:_REP_TOP_K]
    return {
        "bigram_repeat_ratio": round(repeated_total / total, 3),
        "repeated_bigrams_top": [[bg, c] for bg, c in top],
    }


# ============================================================
# 出口：单文本指纹 + 语料聚合
# ============================================================

def compute_text_fingerprint(text: str, *, light: bool = False) -> Dict:
    """计算一段文本的文风指纹。

    Args:
        text: 待测量文本（作者样本 / 语料拼接 / 章节正文）
        light: 轻量模式——跳过修辞密度（ai_taste 十组正则较重），
               章节指纹批量计算时用；样本/语料始终全量。

    Returns:
        指纹 dict（结构见模块头注释；空文本返回全零指纹不抛错）
    """
    if not text or not text.strip():
        fp = {
            "char_count": 0,
            "word_count": 0,
            **_sentence_stats([]),
            "dialogue_ratio": 0.0,
            **_paragraph_stats(""),
            "punctuation": _punctuation_stats("", 0),
            "rhetoric": None,
            # 空文本同构返回（token_count=0、其余 None/[]，消费方零判空分支）
            "lexical": _lexical_stats([]),
            "repetition": _repetition_stats([]),
        }
        return fp

    word_count = count_words(text)
    sentences = split_sentences(text)
    tokens = _tokenize(text)  # 词汇/重复两族共用，只分词一次
    fingerprint: Dict = {
        "char_count": len(text),
        "word_count": word_count,
        **_sentence_stats(sentences),
        "dialogue_ratio": round(count_dialogue_chars(text) / max(1, word_count), 3),
        **_paragraph_stats(text),
        "punctuation": _punctuation_stats(text, word_count),
        "rhetoric": None if light else _rhetoric_stats(text),
        # light 模式也算——jieba 单遍 + 纯算法统计，代价可承受
        "lexical": _lexical_stats(tokens),
        "repetition": _repetition_stats(tokens),
    }
    return fingerprint


def aggregate_corpus(contents: List[str], *, max_chars: Optional[int] = None) -> Dict:
    """语料聚合指纹：拼接全部样本后整体测量。

    拼接后整体算（而非逐条平均）——句长 CV 等分布族指标只有在大样本上
    才有意义，逐条平均会把"样本内节奏"与"样本间差异"混掉。

    Args:
        contents: 样本原文列表（空串自动跳过）
        max_chars: 拼接上限（防极端大语料拖慢请求；截断保留完整样本条，
                   从最新往前取——list_by_book 返回即新→旧）
    """
    valid = [c for c in contents if c and c.strip()]
    if max_chars is not None:
        kept: List[str] = []
        total = 0
        for c in valid:
            if total + len(c) > max_chars:
                continue
            kept.append(c)
            total += len(c)
        valid = kept
    if not valid:
        return compute_text_fingerprint("")
    return compute_text_fingerprint("\n\n".join(valid), light=False)


# ============================================================
# 台账化与漂移（完整落地批，设计稿 §5/§6.4）
# ============================================================

def count_negative_hits(texts: List[str], words: List[str]) -> Dict[str, int]:
    """负面清单台账化：统计各禁词在文本集（近 N 章正文）中的命中次数。

    纯子串计数（与 ClichéAuditor 的字面词口径一致；正则型系统禁词不在此列——
    台账只管作者自己的负面清单条目）。命中为零的词也返回 0（反向提醒可能不需要）。
    """
    joined = "\n".join(t for t in texts if t)
    return {w: joined.count(w) for w in words if w}


def compute_style_drift_hint(
    text: str,
    dialogue_target: Optional[float],
    cv_lo: float,
    cv_hi: float,
) -> Optional[str]:
    """写作中心跳漂移轻提示（纯 code，设计稿 §5）。

    对当前章正文尾部测同把尺子指标，显著偏离目标/健康带时返回一句人话；
    判断权留给作者（只呈现事实）。文本过短（<400 字）或无显著偏离 → None。
    """
    if not text or len(text) < 400:
        return None
    fp = compute_text_fingerprint(text, light=True)
    notes: List[str] = []

    if dialogue_target is not None:
        lo = max(0.0, dialogue_target - 0.2)
        hi = min(1.0, dialogue_target + 0.2)
        ratio = fp["dialogue_ratio"]
        if ratio < lo:
            notes.append(f"对话占比 {ratio * 100:.0f}% 低于目标（{(lo + hi) / 2 * 100:.0f}% 附近）")
        elif ratio > hi:
            notes.append(f"对话占比 {ratio * 100:.0f}% 高于目标区间")
    cv = fp["sentence_len_cv"]
    if cv > 0 and cv < cv_lo:
        notes.append(f"句长起伏 {cv:.2f} 偏匀速（AI 腔征兆，健康 ≥{cv_lo}）")
    # 用词重复度（NLP 扩展）：阈值常量懒 import——validation 包 __init__ 直引
    # code_auditors（其又 import 本模块），模块顶层 import 会成环，勿上提
    from backend.services.validation.thresholds import NGRAM_REPEAT_RATIO_HI

    rep_ratio = fp["repetition"]["bigram_repeat_ratio"]
    if rep_ratio is not None and rep_ratio >= NGRAM_REPEAT_RATIO_HI:
        notes.append("用词重复度偏高（疑似套路化表达）")

    if not notes:
        return None
    return "文风漂移：" + "；".join(notes[:2]) + "——回头看一眼？（详见文风页对账）"
