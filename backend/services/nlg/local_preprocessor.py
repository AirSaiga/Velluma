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
本地预处理层（Local Preprocessor，Tier 2）—— 0 Token 的词性抽脂与硬断句。

职责：
- 在 LLM 段产出后、密度评估前，做一轮零成本的本地"抽脂"：
  1. 词性抽脂：用 jieba.posseg 识别连续堆叠的副词(d)/形容词(a)，只保留最后一个
  2. 逻辑连接词删除：删"然而/但是/不仅...反而"等 AI 爱用的因果衔接词
  3. 长句硬切断：超阈值的匀速长句，把逗号置换为句号，制造顿挫感

设计意图（区别于其他反 AI 味模块）：
- text_sanitizer：删"确定性无信息量"的黑名单词（微操短语/套路词），只做减法
- 本模块：按"词性结构"删冗余修饰（抽脂），并主动改句式结构（硬断句）——
  能处理 sanitizer 处理不了的"匀速句式/修饰语泛滥"问题，且 0 Token
- de_ai_washer / pruner.py：LLM 重写，成本高但能处理复杂腔调
- 三者串联：sanitizer(删黑名单) → 本模块(抽脂+断句) → meter 评估 → washer/pruner(LLM)

安全性约束：
- 双引号 ""/「」内的对话内容不抽脂（对话有角色语气，乱删会 OOC）
- jieba 首次加载 ~0.5s，用惰性单例，只在首次生成时触发，不阻塞启动
- 抽脂后若文本异常变空（极端误删），回退原文

业务场景：
- segment_writer 段后处理：measure_ai_taste 之前调用，让评估更准 + 减轻下游 LLM 洗涤负担
"""

import logging
import re
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# 长句硬切断阈值（字符数）。中文小说单句 >24 字易显匀速冗长。
DEFAULT_MAX_SENTENCE_LEN = 24

# 因果/逻辑连接词清单（保守，只删 AI 高频且语义可省的）。
# 用 jieba 分词边界匹配，避免子串误删（如"但是"不会误伤"但"作为助词的用法）。
_CONNECTIVES = frozenset({
    "然而", "但是", "不仅", "反而", "之所以", "是因为",
    "与此同时", "与此同期", "随后就", "紧接着",
})

# jieba 词性标记（POS）中代表"修饰类"的标记
# d=副词, df=区别词(属性词), a=形容词, ad=副形词, an=名形词,
# z=状态词（如"默默地/静静地/缓缓的"，形容性成分，AI 堆砌重灾区）
_ADVERBIAL_FLAGS = frozenset({"d", "df"})
_ADJECTIVE_FLAGS = frozenset({"a", "ad", "an", "z"})

# 双引号对话边界（保护对话不被抽脂）
# 中文弯引号 "" 、直角引号 「」『』、英文直引号 "
_DIALOGUE_OPEN = "\u201c\u300c\u300e\""  # "、「、『、"
_DIALOGUE_CLOSE = "\u201d\u300d\u300f"   # "、」、』


# ============================================================
# jieba 惰性初始化（模块级单例）
# ============================================================

_jieba_initialized = False
_pseg = None


def _ensure_jieba_ready() -> None:
    """惰性初始化 jieba。首次调用加载词库（~0.5s），后续直接返回。"""
    global _jieba_initialized, _pseg
    if _jieba_initialized:
        return
    try:
        import jieba
        import jieba.posseg as pseg
        jieba.initialize()
        _pseg = pseg
        _jieba_initialized = True
        logger.info("[LocalPreprocessor] jieba 词库已加载")
    except ImportError:
        logger.warning(
            "[LocalPreprocessor] jieba 未安装，本地预处理层降级为仅硬断句（跳过抽脂）。"
            "请运行 pip install jieba"
        )
        _jieba_initialized = True  # 标记已尝试，避免反复报错


# ============================================================
# 对话保护：把文本切成"对话段"和"叙述段"，只对叙述段抽脂
# ============================================================


def _split_dialogue(text: str) -> List[Tuple[str, bool]]:
    """把文本切成片段列表，标记每段是否为对话（True=对话，不抽脂）。

    用栈式扫描成对引号，引号内=对话，引号外=叙述。

    Returns:
        list of (片段文本, 是否对话)
    """
    if not text:
        return []
    fragments: List[Tuple[str, bool]] = []
    current = []
    in_dialogue = False
    for ch in text:
        current.append(ch)
        if not in_dialogue and ch in _DIALOGUE_OPEN:
            # 收尾当前叙述段
            if len(current) > 1:
                fragments.append(("".join(current[:-1]), False))
            current = [ch]
            in_dialogue = True
        elif in_dialogue and ch in _DIALOGUE_CLOSE:
            fragments.append(("".join(current), True))
            current = []
            in_dialogue = False
    # 收尾残留
    tail = "".join(current)
    if tail:
        fragments.append((tail, in_dialogue))
    return fragments


# ============================================================
# Tier 2a：词性抽脂（删连续堆叠的副词/形容词 + 删连接词）
# ============================================================


def _strip_connectives(words) -> List[Tuple[str, str]]:
    """删除因果连接词。返回过滤后的 (word, flag) 列表。

    用分词边界匹配，比子串匹配安全（不会误伤词内子串）。
    """
    return [(w, f) for (w, f) in words if w not in _CONNECTIVES]


def _strip_adverb_fat(words) -> List[Tuple[str, str]]:
    """词性抽脂：连续 2 个以上副词/形容词，只保留最后一个。

    只处理相邻的同类修饰词堆叠（如"缓缓地默默地"→"默默地"），
    不跨动词、不跨名词。保留所有非修饰词。
    """
    if not words:
        return words
    result: List[Tuple[str, str]] = []
    i = 0
    n = len(words)
    while i < n:
        word, flag = words[i]
        # 判断是否为修饰类词
        is_mod = flag in _ADVERBIAL_FLAGS or flag in _ADJECTIVE_FLAGS
        if not is_mod:
            result.append((word, flag))
            i += 1
            continue
        # 收集连续的修饰类词（中间允许穿插结构助词/标点）
        # 助词 flag：u=助词, ud/uv/ul/uj/uz=结构助词（的/地/得/了 等）
        # 标点 flag：w=标点, ws/x=其他符号
        run = [(word, flag)]
        j = i + 1
        while j < n:
            w2, f2 = words[j]
            # 跳过结构助词/标点（可穿透，不算入"连续修饰"判定）
            if f2 in ("u", "ud", "uv", "ul", "uj", "uz", "w", "ws", "x"):
                run.append((w2, f2))
                j += 1
                continue
            is_mod2 = f2 in _ADVERBIAL_FLAGS or f2 in _ADJECTIVE_FLAGS
            if is_mod2:
                run.append((w2, f2))
                j += 1
            else:
                break
        # run 里修饰类词数量
        mod_count = sum(
            1 for (_, f) in run if f in _ADVERBIAL_FLAGS or f in _ADJECTIVE_FLAGS
        )
        if mod_count >= 2:
            # 抽脂：只保留最后一个修饰词。
            # 删除前导修饰词时，把它紧随的结构助词（的/地/得）一并删掉，
            # 避免残留孤立的"地"（如"缓缓地默默地"→删"缓缓地"留"默默地"）。
            last_mod_idx = None
            for k in range(len(run) - 1, -1, -1):
                f = run[k][1]
                if f in _ADVERBIAL_FLAGS or f in _ADJECTIVE_FLAGS:
                    last_mod_idx = k
                    break
            if last_mod_idx is not None:
                kept = []
                skip_following_particle = False
                for k in range(len(run)):
                    f = run[k][1]
                    is_m = f in _ADVERBIAL_FLAGS or f in _ADJECTIVE_FLAGS
                    if is_m and k < last_mod_idx:
                        # 删掉前导修饰词，并标记删除其尾随结构助词
                        skip_following_particle = True
                        continue
                    if skip_following_particle and f in ("u", "ud", "uv", "ul"):
                        # 这是被删修饰词的尾随"的/地/得"，一并删除
                        skip_following_particle = False
                        continue
                    skip_following_particle = False
                    kept.append(run[k])
                result.extend(kept)
            else:
                result.extend(run)
        else:
            result.extend(run)
        i = j
    return result


def _strip_adverb_fat_safe(text: str) -> str:
    """对单段叙述文本做词性抽脂 + 删连接词。

    Returns:
        抽脂后的文本
    """
    _ensure_jieba_ready()
    if _pseg is None:
        return text  # jieba 不可用，降级跳过
    try:
        words = [(w.word, w.flag) for w in _pseg.lcut(text)]
    except Exception as e:
        logger.warning(f"[LocalPreprocessor] jieba 分词失败，跳过抽脂: {e}")
        return text
    # 先删连接词，再抽脂
    words = _strip_connectives(words)
    words = _strip_adverb_fat(words)
    return "".join(w for (w, _) in words)


# ============================================================
# Tier 2b：长句硬切断（制造顿挫感）
# ============================================================

# 句末标点（用于切分句子）
_SENTENCE_END = re.compile(r"[。！？!?…]")


def _break_long_sentence(sentence: str, delim: str, max_len: int) -> str:
    """对单个超长句做硬切断。

    若句子超过 max_len 且含逗号，把第一个逗号置换为句号。
    只切一次（避免把句子切得太碎）。
    """
    if len(sentence) <= max_len or "，" not in sentence:
        return sentence + delim
    # 把第一个逗号换成句号，后半句保留原 delim
    idx = sentence.find("，")
    first = sentence[:idx]
    rest = sentence[idx + 1:]
    # first 自带句号收束，rest 后接原 delim
    return f"{first}。{rest}{delim}"


def _break_long_sentences(text: str, max_len: int = DEFAULT_MAX_SENTENCE_LEN) -> str:
    """对整段文本做长句硬切断。"""
    if not text:
        return text
    # 用句末标点切分（保留分隔符）
    parts = _SENTENCE_END.split(text)
    delims = _SENTENCE_END.findall(text)
    # parts[i] + delims[i] 组成一个完整句（delims 可能为空=末尾无标点）
    out = []
    for i, sent in enumerate(parts):
        delim = delims[i] if i < len(delims) else ""
        if delim:
            out.append(_break_long_sentence(sent, delim, max_len))
        else:
            # 末尾无标点的残留片段，原样保留
            out.append(sent)
    return "".join(out)


# ============================================================
# 主入口
# ============================================================


class LocalPreprocessor:
    """本地预处理层（Tier 2）：0 Token 的词性抽脂 + 硬断句。

    用法：
        processor = LocalPreprocessor()
        clean = processor.preprocess_segment(raw_segment_text, genre="xianxia")
    """

    def __init__(self, max_sentence_len: int = DEFAULT_MAX_SENTENCE_LEN):
        self.max_sentence_len = max_sentence_len

    def preprocess_segment(
        self,
        text: str,
        genre: Optional[str] = None,
    ) -> str:
        """对单段正文做本地预处理（抽脂 + 硬断句）。

        Args:
            text: 单段正文（通常为 LLM raw 产出）
            genre: 题材（预留，目前未用于白名单；None 走通用）

        Returns:
            预处理后的正文。若处理异常或结果变空，回退原文。
        """
        if not text or not text.strip():
            return text

        original = text
        try:
            # 1. 对话保护：切分对话段/叙述段，只对叙述段抽脂
            fragments = _split_dialogue(text)
            processed_parts = []
            for frag_text, is_dialogue in fragments:
                if is_dialogue or not frag_text:
                    processed_parts.append(frag_text)
                else:
                    # 2. 叙述段：抽脂 + 删连接词
                    stripped = _strip_adverb_fat_safe(frag_text)
                    # 3. 硬断句（对话段不切断，保持对话完整）
                    stripped = _break_long_sentences(stripped, self.max_sentence_len)
                    processed_parts.append(stripped)
            result = "".join(processed_parts)
        except Exception as e:
            logger.warning(f"[LocalPreprocessor] 预处理异常，回退原文: {e}")
            return original

        # 安全兜底：抽脂后异常变空（极端误删），回退原文
        if not result or not result.strip():
            logger.warning("[LocalPreprocessor] 预处理后文本变空，回退原文")
            return original

        # 安全兜底：若删减幅度过大（<50% 原文），可能误伤，回退
        if len(result) < len(original) * 0.5:
            logger.warning(
                f"[LocalPreprocessor] 预处理后文本过短（{len(result)}/{len(original)}），"
                f"疑似误伤，回退原文"
            )
            return original

        return result


# ============================================================
# 模块级单例 + 便捷函数（供 segment_writer 一行接入）
# ============================================================

_default_processor: Optional[LocalPreprocessor] = None


def _get_default_processor() -> LocalPreprocessor:
    global _default_processor
    if _default_processor is None:
        _default_processor = LocalPreprocessor()
    return _default_processor


def preprocess_segment(text: str, genre: Optional[str] = None) -> str:
    """便捷入口：用默认单例对单段正文做本地预处理。

    Args:
        text: 单段正文
        genre: 题材（预留）

    Returns:
        预处理后的正文
    """
    return _get_default_processor().preprocess_segment(text, genre=genre)
