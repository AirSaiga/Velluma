# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""stitch 产线的确定性闸门与后处理（纯函数，零 LLM/零 DB）。

从路由层（原 chapter_generation/adaptive.py）下沉：字数硬闸常量与截断、
缝合接缝归一族（复读剥离/尾缀复读/引号碰撞/桥接接缝/半角标点归一）、
返修环的确定性后处理（超字截断豁免/句级切除三豁免/带稿改写 prompt）。
对拍单测：services/adaptive/test_stitch_gates.py、validation/test_beat_rush_gate.py。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from backend.services.adaptive.paragraph_source import normalize_for_match


# ============================================================
# 细纲扩写字数硬闸门（对齐 bsadf/downgrade 的实测经验：软约束段均超写
# 近 2 倍。细纲的产品承诺是「生成字数不多、改起来轻」，必须硬保证。
# SSE 先生成后播放 → 压缩重试/截断对前端完全透明）
# ============================================================

OUTLINE_WC_HARD_RATIO = 1.6      # 超过 target×1.6 → 带压缩反馈重试一次
OUTLINE_WC_TRUNCATE_RATIO = 1.5  # 仍超 → 句界硬截断（截断上限必须 ≤ HARD）

# stitch/continue 字数闸（2026-08-28 扩面，08-29 改两级）：kimi-k2.6 实测对
# 「控制在 N 字以内」严重不服从（120 字目标产出 600-700 字、8-10 段，mimo
# 同病）——prompt 杠杆已尽，上代码闸。两级=先保头句界截到 ×1.5，截取稿
# 发回模型按目标压缩改写（首句豁免压缩，接缝两护见下）。
# 2026-09-03 线 E 再扩面：burst/open 同进此闸——两者 target=700 的承诺
# 同样是「约七百字」，kimi/mimo 的超产病在 700 目标下=1400+ 字快进剧情
# （冲章同族风险：burst 超产=走向卡一步写成三步，open 超产=开篇把第一章
# 节奏提前烧掉）。闸只抓严重超产（×1.6 才动），正常浮动不碰。
STITCH_WC_HARD_RATIO = 1.6
STITCH_WC_TRUNCATE_RATIO = 1.5

# 微镜头字数闸（第二冲程 2026-09-09）：stitch 且 target ≤ 60（前端单镜头
# 展开 target=50，区间 40-60）→ 超硬限**保头句界截断即止**，不走压缩改写
# ——压缩一次 = 一次完整 LLM 往返（实测 2-5s），对微镜头是杀鸡用牛刀；
# 61~80 字（×1.6 容差带）全盘接受 = 句子自然完结优先。返修环/快检照常
# （闸只省算力不降质）；target > 60 的 stitch（API 旧调用面）走原两级闸。
MICRO_STITCH_TARGET_MAX = 60


def _is_micro_lens(mode: str, target_chars: int) -> bool:
    """微镜头判定（纯函数）：stitch 模式且目标 ≤ MICRO_STITCH_TARGET_MAX。"""
    return mode == "stitch" and 0 < target_chars <= MICRO_STITCH_TARGET_MAX

# stitch LLM 预算下限（C2，P1-4）：deepseek 类推理模型即使传 REASONING_DISABLED
# 仍烧 ~800-1000 隐藏思考 tokens，1200 下限时正文余量太薄 → 「续写产出为空」；
# 抬到 2200 给隐藏推理留足死余量。纯上限放宽——非推理模型产出短于上限不多花。
STITCH_MAX_TOKENS_FLOOR = 2200


def _truncate_at_sentence(text: str, limit: int) -> str:
    """句界硬截断：在 limit 内找最后一个句末标点切断。

    复制自 bsadf/downgrade._truncate_at_sentence（无依赖纯函数，刻意不
    import bsadf——adaptive 链路不依赖步进流任何设施）。找不到句末标点
    （极端长句）退化为按字截断：字数硬闸门优先级高于单句完整性。
    """
    if len(text) <= limit:
        return text
    cut = max(text.rfind(p, 0, limit) for p in ("。", "！", "？", "…"))
    if cut > 0:
        return text[: cut + 1]
    return text[:limit]


def _truncate_keep_tail(text: str, limit: int) -> str:
    """保尾截断（P1-1，A3）：末段完整保留，超字从前往后按句界删节到 ≤ limit。

    outline 模式的价值重心在末段——双端锚定的「后端缝合」全靠末段引向
    after_text，现有尾截砍掉的恰是承接段，等于砍掉整次扩写的意义；与旧
    引擎「末段（结局段）豁免截断」护栏思想对齐。仅 outline 字数硬闸使用，
    其他模式维持尾截口径不变。

    退化路径（防死循环）：全文单段（末段即全文）或末段自身 ≥ limit 时，
    已没有「删前保尾」的操作空间，回落现有尾截 _truncate_at_sentence。
    入参契约：text 已 strip（路由侧字数闸前的统一清洗）。
    """
    if len(text) <= limit:
        return text
    # 段落切分保留分隔符形态：[段, 分隔, 段, 分隔, 末段]
    parts = re.split(r"(\n+)", text)
    if len(parts) < 3 or not parts[-1]:
        return _truncate_at_sentence(text, limit)
    sep, tail = parts[-2], parts[-1]
    if len(tail) + len(sep) >= limit:
        # 末段自身超限：保不住，回落尾截
        return _truncate_at_sentence(text, limit)
    head = "".join(parts[:-2])
    head_limit = limit - len(tail) - len(sep)
    if len(head) <= head_limit:
        return text
    # 从前往后找最早能装进 head_limit 的句界：head[:p] 整句让位（删最少句数
    # 优先）；找不到（前段末句是超长单句）则整个前段让位、只留末段
    for i, ch in enumerate(head):
        if ch in ("。", "！", "？", "…") and len(head) - (i + 1) <= head_limit:
            return head[i + 1:] + sep + tail
    return tail

# ============================================================
# 碎片拼回判定规范化（P1-2，A4）
# ============================================================
# 模型常在「已把作者碎片复述进产出」时换了同类标点/夹了空白（「他握紧刀。」
# →「他握紧刀 !」）——裸子串 `fragment in text` 会误判「不含」，把作者原句
# 再拼回句首造成开头重复。判定口径：抹全部空白（normalize_for_match，与
# 组件侧同一把尺子）+ 标点折叠为等价类；字符内容（语义）变了仍判不含。
_PUNCT_FOLD = str.maketrans({
    # 句末等价类：句/叹/问/省略（全半角）视为同一种「一句终了」
    "。": ".", "．": ".", ".": ".",
    "！": ".", "!": ".", "？": ".", "?": ".", "…": ".",
    # 停顿等价类：逗/顿/分号
    "，": ",", ",": ",", "、": ",", "；": ",", ";": ",",
    # 冒号
    "：": ":", ":": ":",
    # 引号/括号
    "“": "\"", "”": "\"", "\"": "\"",
    "‘": "'", "’": "'", "'": "'", "「": "'", "」": "'", "『": "'", "』": "'",
    "（": "(", "(": "(", "）": ")", ")": ")",
    # 破折号
    "—": "-", "－": "-", "―": "-", "-": "-",
})


def _contains_fragment(text: str, fragment: str) -> bool:
    """stitch 碎片复述判定（规范化）：抹空白 + 标点折叠等价类后的子串命中。

    只容纳「模型已复述碎片」的形态微差（标点/空白变体）；字符内容变了
    （加字/换词，如「他握紧刀」→「他握紧了刀」）仍判不含。
    """
    key = normalize_for_match(fragment).translate(_PUNCT_FOLD)
    if not key:
        return True  # 空碎片按已含处理（路由层已有 fragment 真值门，防御位）
    return key in normalize_for_match(text).translate(_PUNCT_FOLD)


def _strip_fragment_prefix(text: str, fragment: str) -> str:
    """剥离模型复读的原句前缀（追加式幽灵契约，2026-08-26 实测修复）。

    幽灵是纯追加插入（光标后落文档），作者原句已在画布里——模型若把原句
    再吐回来（含标点/空白变体），屏幕上会出现「原句 + 幽灵复读原句 + 续写」
    的重复。此处把复读前缀剥掉，只留纯续写；语义变体（换词/加字）不是复读，
    不剥（旧拼回判定的等价类口径，_contains_fragment 同款规范化）。
    """
    frag = (fragment or "").strip()
    if not frag:
        return text
    if text.startswith(frag):
        stripped = text[len(frag):].lstrip()
        return stripped or text
    key = normalize_for_match(frag).translate(_PUNCT_FOLD)
    if not key:
        return text
    acc: list = []
    for i, ch in enumerate(text):
        n = normalize_for_match(ch).translate(_PUNCT_FOLD)
        if not n:
            continue
        acc.append(n)
        joined = "".join(acc)
        if joined == key:
            stripped = text[i + 1:].lstrip()   # 等价复读完整复现原句 → 剥到此处
            return stripped or text
        if len(joined) > len(key):
            break                            # 内容已偏离原句 → 不是复读
    return _strip_fragment_tail_repeat(text, frag, key)


def _strip_fragment_tail_repeat(text: str, frag: str, key: str) -> str:
    """半句断点的尾缀复读剥离（2026-08-29 接缝断裂事故）。

    作者停在半句（『…在这个世道，这句』）时，模型常从断点悬空处重启整句
    （『在这个世道，这句话连垫桌脚都嫌薄。…』）——复读的是原句**尾缀**而
    非整句，整句匹配剥不到，上屏成『…在这个世道，这句在这个世道，这句…』
    重复。判据：断点非句末（悬空半句）且产出以原句尾缀（≥2 个规范化字符）
    开头 → 剥掉该尾缀，画布半句与续写拼合恰成完整句。断点已在句末时不开
    此闸——句末后的同词开头是新句复用词汇，不是复读（『…他握紧刀。』+
    『他握紧刀把门闩上。』各是各的句子）。
    """
    if not text or not frag or len(key) < 2:
        return text
    # 断点在句末 → 尾缀同词是新句，不是复读
    if frag[-1] in ("。", "！", "？", "…", ".", "!", "?"):
        return text
    # 规范化坐标系下做尾缀匹配（等价类口径同整句匹配）；命中后映射回原文切割点
    norm_pairs = [(i, normalize_for_match(ch).translate(_PUNCT_FOLD))
                  for i, ch in enumerate(text)]
    norm_pairs = [(i, n) for i, n in norm_pairs if n]
    if not norm_pairs:
        return text
    norm_text = "".join(n for _, n in norm_pairs)
    for k in range(min(len(key), len(norm_text)), 1, -1):   # 最长尾缀优先
        if norm_text.startswith(key[-k:]):
            cut = norm_pairs[k - 1][0] + 1
            stripped = text[cut:].lstrip()
            # 切割点后紧跟的标点**保留**（『他握紧』+『。他退后半步。』拼合成
            # 「他握紧。他退后半步。」是自然句；剥掉反而腰斩拼合）；剥空=全文
            # 纯复读，留原文走后续空产出处理，不在剥离层吞掉幽灵
            return stripped or text
    return text


_OPEN_QUOTES = ("“", "「", "『", "\"")


def _strip_colliding_open_quote(text: str, fragment: str) -> str:
    """双开引号碰撞剥除（2026-09-11 排毒批）。

    作者断点就是一个悬空开引号（打了「“」还没写字）而幽灵自带完整对白又以
    开引号起 → 上屏成「““快吃吧……”」。剥掉幽灵头部的开引号，画布的
    “与幽灵的对白正文恰拼成一句完整引文。只看断点**最后一个非空白字符**：
    作者段落中段已闭合的成对引号不在此列（那是合法的新对白起点）。全角/
    半角开引号都认（半角直引号随后由标点归一统一转全角）。
    """
    if not text:
        return text
    frag = (fragment or "").rstrip()
    if not frag or frag[-1] not in _OPEN_QUOTES:
        return text
    t = text.lstrip()
    if t[:1] in _OPEN_QUOTES:
        return t[1:]
    return text


def detect_dangling_quote_collision(text: str, fragment: str) -> bool:
    """悬空开引号 × 动作前缀碰撞影子检（2026-09-13，Z+X 路线·只落台账）。

    作者断点停在未闭合的开引号上（打了「“」话没说完），模型没接住续话
    义务、另起动作子句（幽灵首字非引号）——拼合上屏成
    「“林尘笑了笑，“今晚做啥好吃的？”」双开引号。既有
    _strip_colliding_open_quote 只救幽灵首字符是开引号的形态，此形态字面
    穿透。纯检测不修文：修文须触碰画布字符或重排幽灵子句，均违反「幽灵
    纯追加 + 作者文本不可触碰」红线——影子攒语料定频率后再定执法路线。

    判据（三条件同时成立）：
    - 断点最后一个非空白字符是开引号；
    - 幽灵首字符非开引号（那是既有剥除函数的领地，不重复记账）；
    - 幽灵内部自带引号对（模型另起炉灶的直接证据）。
    """
    frag = (fragment or "").rstrip()
    if not frag or frag[-1] not in _OPEN_QUOTES:
        return False
    t = (text or "").lstrip()
    if not t or t[:1] in _OPEN_QUOTES:
        return False
    return any(q in t for q in _OPEN_QUOTES)


def _normalize_bridge_seam(text: str, suffix: str) -> str:
    """桥接尾部接缝归一（2026-09-09 FIM 红队 R1：prompt 管不住的确定性下沉）。

    幽灵末尾与后文首句的接缝两防线：
    ①尾悬停顿标点（，、；：——）收成句号——幽灵与后文首句各成其句，
      杜绝「……饭香扑鼻，」+「明姐端来脸盆」的粘连跑句；
    ②幽灵末尾与后文开头等价重叠（模型把后文首句复读进了过渡）→ 剥掉重叠段
      （等价类口径与复读剥离同款；剥后无句读则补句号）。
    """
    t = (text or "").rstrip()
    if not t:
        return text
    if t[-1] in ("，", "、", "；", "：", ",", ";", ":", "—"):
        t = t[:-1] + "。"
    suf = (suffix or "").strip()
    if suf:
        key = normalize_for_match(suf).translate(_PUNCT_FOLD)
        for k in range(min(len(key), 24), 3, -1):   # 最长重叠优先，≤24 字（整句复读也接得住）
            if normalize_for_match(t[-k:]).translate(_PUNCT_FOLD) == key[:k]:
                t = t[:-k].rstrip()
                break
        if t and t[-1] not in ("。", "！", "？", "…", "”", "」", ".", "!", "?"):
            t += "。"
    return t


_HALF_DOTS_RE = re.compile(r"\.{3,}")


def _normalize_ghost_punctuation(text: str) -> str:
    """幽灵半角标点归一（2026-09-09 编辑器「对不齐」，呈现平面末站）。

    中文正文的等宽网格被半角字符打破——半角省略号 "..." 只占约 1.5 字宽
    （全角 "……" 占 2 字宽），含它的行右边缘参差、行内后续字整体错半格。
    归一规则（确定性替换，零语义变化）：
    ① 三连及以上半角点 → "……"；
    ② 直引号 " 按出现序配对转 “”（中文对白引号恒成对，孤引号任何
       归属都是模型笔误，交替赋值不劣于原样）。
    ⚠ 作者手打的存量半角标点**不经过此函数**（画布主权，AI 只管自己的
    产出侧防增量）；调用点在所有闸门（接缝/返修/洗层/终检）之后——
    上游对后文锚的重叠比对必须看到模型的原始字符。
    """
    if not text:
        return text
    text = _HALF_DOTS_RE.sub("……", text)
    if '"' in text:
        out: list[str] = []
        open_quote = True
        for ch in text:
            if ch == '"':
                out.append("\u201c" if open_quote else "\u201d")
                open_quote = not open_quote
            else:
                out.append(ch)
        text = "".join(out)
    return text


def _bridge_actor_steal(text: str, suffix: str, known_names) -> Optional[str]:
    """桥接抢场影子检（2026-09-09 抢场事故，shadow 只落台账不拦截）。

    实测事故：幽灵「明姐迎上来，手里还攥着块湿抹布」vs 后文首句「明姐端过来
    准备好的脸盆」——同一叙事槽位（明姐的迎接反应）换道具演了两遍，字面
    n-gram 零重合拦不住（改写式撞车）。判据：幽灵**末句**与后文**首句**共享
    同一登场者名 → 幽灵把后文的登场反应提前演了。shadow 攒语料，转正后可
    走返修环（带主角一侧铁律重新生成）。
    """
    if not text or not suffix:
        return None
    # 首拍边界：引文句（「……。”明姐端来……」）的句末标点在引号**内**——
    # 直接切会把台词后的归属动作（登场者所在）丢出首拍。跳过紧跟闭引号的
    # 句末标点，切到引号外的第一个自由句读
    cut = -1
    for i, ch in enumerate(suffix):
        if ch in ("。", "！", "？", "…"):
            nxt = suffix[i + 1] if i + 1 < len(suffix) else ""
            if nxt in ("”", "」", "』", '"'):
                i += 1  # 连同闭引号一起跨过，继续找自由句读
                continue
            cut = i
            break
    first = suffix[: cut + 1] if cut >= 0 else suffix
    # 幽灵末句：按句末标点切分取最后一个非空句
    import re as _re
    sents = [x for x in _re.split(r"[。！？…]", text) if x.strip()]
    g_last = sents[-1] if sents else text
    for name in (known_names or []):
        name = str(name).strip()
        if len(name) >= 2 and name in first and name in g_last:
            return name
    return None


def _split_first_sentence(text: str) -> tuple:
    """首句切分：到第一个句末标点（含标点）为止，返回 (首句, 其余)。

    句末标点取 _truncate_at_sentence 同族；找不到（极端长句/对白未闭合）
    返回 ("", text)——调用方退整稿路径。
    """
    for i, ch in enumerate(text):
        if ch in ("。", "！", "？", "…"):
            return text[: i + 1], text[i + 1:]
    return "", text


# ============================================================
# 缝合返修环路由侧辅助（约束治理二期，2026-09-02；环本体在
# services/validation/repair_loop.py——本区只承载 stitch 专属的确定性后处理、
# 句级切除豁免纪律与返修 prompt 组装）
# ============================================================

def _postprocess_repair_draft(text: str, mode: str, fragment: str, target_chars: int) -> str:
    """返修稿的确定性后处理（与主生成同一套判据，但**零 LLM**——单次 stitch
    creative 调用 3 次封顶：初生成 + 可能已有的压缩重试 + 返修改写；返修稿
    不再触发压缩改写，超字走纯截断）。

    - stitch：复读剥离（返修模型同样可能把作者原句吐回来）；
    - stitch/continue 超硬限：首句锚定 + 保头句界截（豁免口径同主路径）；
    - outline 超硬限：保尾截断（末段承接段豁免）。
    """
    if mode == "stitch" and fragment:
        text = _strip_fragment_prefix(text, fragment)
    if target_chars > 0:
        if mode in ("stitch", "continue"):
            hard = int(target_chars * STITCH_WC_HARD_RATIO)
            if len(text) > hard:
                anchor, body = _split_first_sentence(text)
                if not anchor or len(anchor) > int(target_chars * 0.6):
                    anchor, body = "", text
                text = anchor + _truncate_at_sentence(
                    body, max(int(target_chars * STITCH_WC_TRUNCATE_RATIO) - len(anchor), 40),
                )
        elif mode == "outline":
            hard = int(target_chars * OUTLINE_WC_HARD_RATIO)
            if len(text) > hard:
                text = _truncate_keep_tail(text, int(target_chars * OUTLINE_WC_TRUNCATE_RATIO))
    return text


# 句级切分（切除用）：句子单元（含句末标点）与换行单元分列，重建时保结构
_EXCISE_UNITS_RE = re.compile(r"[^。！？…\n]+[。！？…]?|\n+")


def _excise_violating_sentences(
    text: str,
    violations: List[Dict],
    *,
    mode: str,
    target_chars: int,
) -> Optional[str]:
    """句级切除兜底：删掉含违规 span 的句子，重建文本。失败返 None。

    切除三豁免（导师裁决 2026-09-02）：
    1. stitch/continue/burst 的首句（衔接锚句）不可切——切了作者的半句
       永远悬空（2026-08-29 接缝事故同族防线）；
    2. outline 的末段（引向 after_text 的承接段）不可切；
    3. 切除后剩余 < max(target×0.6, 80 字) 不可切——保不了基本体量宁可拒稿。
    另：beat_rush 整类不授权切除（2026-09-03 拍板「excise 不授权」——抢拍是
    方向性错误，删句对整稿伤害大于改写；改写失败宁可拒稿走熔断/逃生舱）；
    切除只动内部句；切除产物仍须过返修环的零违规验收（调用方职责）。
    """
    if not text or not violations:
        return None
    spans: List[str] = []
    for w in violations:
        # beat_rush 不进切除兜底（对齐 ghost_guard「rewrite-only」声明）：
        # 改写失败后本函数对其返回「无可切」→ 返修环走拒稿，绝不删句
        if str(w.get("kind") or "") == "beat_rush":
            continue
        span = str(w.get("span_text") or "").strip()
        if not span:
            continue
        # cliche 类复合 span（「、」连接）逐词匹配；其余整 span 匹配
        spans.extend(s for s in re.split(r"[、]", span) if s)
    if not spans:
        return None

    units = _EXCISE_UNITS_RE.findall(text)
    if not units:
        return None
    # 句子单元的索引（换行单元不参与豁免/切除判定）
    sent_idx = [i for i, u in enumerate(units) if u.strip(" \t\n")]
    if not sent_idx:
        return None
    first_sent = sent_idx[0]
    # outline 末段保护：最后一个非空句子单元起的连续尾部
    tail_sent = sent_idx[-1] if mode == "outline" else -1

    protected = {first_sent} if mode in ("stitch", "continue", "burst", "open") else set()
    if mode == "outline":
        protected.add(tail_sent)

    drop: set = set()
    for i in sent_idx:
        if i in protected:
            # 违规落在豁免句上 → 切除兜底整体失败（拒稿或降级由返修环裁决）
            if any(s in units[i] for s in spans):
                return None
            continue
        if any(s in units[i] for s in spans):
            drop.add(i)
    if not drop:
        return None

    kept = [u for i, u in enumerate(units) if i not in drop]
    rebuilt = "".join(kept)
    rebuilt = re.sub(r"\n{3,}", "\n\n", rebuilt).strip("\n")
    # 切除把段落掏空了（全文/整段被删）→ 失败
    if not rebuilt.strip():
        return None
    floor = max(int(target_chars * 0.6), 80) if target_chars > 0 else 80
    if len(rebuilt) < floor:
        return None
    return rebuilt


_VIOLATION_REPAIR_LINES = {
    "canon_leak": "「{span}」是作者设定中读者不该看到的真相，绝不能直接写出——改为侧面暗示或删去相关表述",
    "secret_leak": "「{span}」出自私密设定，绝不能直接写出——改为行为/神态暗示或删去",
    "out_of_scene": "「{span}」此刻不在场，不得让它登场行动——删改相关动作，换在场的人/物承接",
    "location_jump": "「{span}」不在当前场景，不得写抵达那里——改为当前场景内的动作",
    "dead_speak": "「{span}」已死亡，不得让它开口或行动（除非明确写成回忆/转述）",
    "beat_rush": "这段直接写出了大纲里几步之后的节拍场面（命中「{span}」）——那一拍留给后面；改写为通往它路上的画面，不写节拍事件本身",
}


def _build_violation_repair_prompt(
    *,
    mode: str,
    fragment: str,
    target_chars: int,
    violations: List[Dict],
    draft: str,
) -> str:
    """返修环的带稿改写 prompt：违规清单是硬事实（代码闸检出，非模型自评），
    指令收敛为「只修这些问题，其余保持不变」——改写面越小，弱模型越不容易
    修一个砸三个。"""
    lines: List[str] = []
    for w in violations:
        kind = str(w.get("kind") or "")
        span = str(w.get("span_text") or "")
        tpl = _VIOLATION_REPAIR_LINES.get(kind)
        lines.append("- " + (tpl.format(span=span) if tpl else (w.get("message") or span or kind)))
    frag_ctx = (
        f"作者正文停在：『…{fragment[-40:]}』（草稿正是在补它/接它，开头衔接必须保留）\n"
        if fragment else ""
    )
    wc = f"改写后控制在 {target_chars} 字以内；" if target_chars > 0 else ""
    return (
        f"{frag_ctx}下面这段续写草稿存在必须修复的硬伤：\n"
        + "\n".join(lines)
        + f"\n\n请改写整段草稿：只修复上述问题，保持衔接、剧情方向与文风不变；{wc}"
        f"只输出改写后的续写正文，不要解释。\n\n--- 草稿 ---\n{draft}"
    )
