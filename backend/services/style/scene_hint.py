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
写作场景判定（P5 C2 · 样本场景匹配，docs/reports/foundation-hardening.md §5.2）。

职责：对当前写作上下文（stitch 装配处传 rolling_prefix 尾 300 字）判出
场景档位，供 retrieve_author_samples 对同型样本做检索加成——「作者正写
对话时，few-shot 示范优先给对话样本」。

v2（判定器扩档）：dialogue / action / lyrical / general 四档。suspense 本轮
不做（自动判定永不产出 suspense；但显式传参通路接受 suspense——它是样本
侧合法词表成员，作者/前端显式指定时直接透传）。判定口径与文风页/审计侧
同源（「同一把尺子」原则），四路信号全部出自同一次 compute_text_fingerprint
(light) 调用（对话占比/句长族/质感密度）+ 一个动作动词正则：

  1. 对白占比（v1 原样，行为不变）：dialogue_ratio > 0.35 → dialogue；
  2. 动作动词密度（hits/千字）：动作戏的动词风暴（冲/砸/扑/掐/…）；
  3. 节奏信号（短句率 / 句长 CV）：动作戏短促（节奏独立佐证，双信号才判
     ——防动词密集的争吵对白误入 action，而那类窗已被 dialogue 档截走）；
  4. 质感（描写性词汇）密度（texture_per_1k）：抒情段的比喻/感官词密度。

保守优先原则：信号不强时一律回落 general——宁可漏判不可错判（错判会注入
错类型样本，比不注入更糟）。三档非 general 判定全部要求双条件与（主信号
+ 佐证），且档间互斥（dialogue 最先判走，action 与 lyrical 的密度信号
方向相反天然分流）。

零变化契约：空文本/统计失败一律回落 "general"；对文本的 dialogue 判定
行为与 v1 逐一致（dialogue 分支代码未动，有测试锁定）。

v3（fragment 优先两段式）：stitch 断点处作者正在写的 fragment 是最强的
「现在时」信号，但 v1/v2 通路只判 rolling_prefix 尾窗，fragment 被静默
丢弃——《弦上灰》实测（logs/style_ab/repro_scene_hint.py，材料
material_v2.json）action 断点的 fragment 是纯动作戏（动词密度 71.4/千字，
远超强信号豁免线 25），而尾窗是机库描写，拼接后被稀释到 15.4 → 误判
general。两段式判定（detect_scene_hint）：

  1. fragment 非空时先单独判 fragment——只有「强信号非 general」才直接
     采信（口径见 _fragment_strong_scene：dialogue 用现有对白占比线，
     action 用既有动词风暴豁免线 25/千字而非普线 18——短窗分母小、噪声
     大，采信门槛必须高于普线；lyrical 本轮不开放：质感词表是封闭口径，
     短句里一两个质感词就能把密度顶过线，误判风险高于收益，宁可回落）；
  2. fragment 无强信号（含判出 general）→ 回落「rolling_prefix 尾部窗 +
     fragment」拼接判定（现状通路的语义扩展——dialogue 断点实测 fragment
     仅 13 字无引号判 general，正是靠拼接窗口里的对白尾巴才判回 dialogue，
     证明「仅 fragment」单一路径不可行）；
  3. fragment 为空 → 与 v2 逐字节一致（纯尾窗判定，零变化契约）。

优先级链不变：显式 scene_type 传参 > fragment 强信号 > 拼接判定 >
general 兜底（保守优先原则：任何一路信号不强都回落）。
"""

import re
from typing import Optional

from backend.services.style.fingerprint import compute_text_fingerprint

# ============================================================
# 档位常量与判定口径
# ============================================================

SCENE_DIALOGUE = "dialogue"   # 对话场景（对话占比超阈值）
SCENE_ACTION = "action"       # 动作场景（动词密度 + 短促节奏双信号）
SCENE_LYRICAL = "lyrical"     # 抒情场景（质感密度高 + 动作/对话双低）
SCENE_GENERAL = "general"     # 一般场景（默认档，含一切兜底情形）

# 显式传参通路接受的合法词表 = 样本侧合法词表（backend/schemas/style.py
# scene_type 枚举）。自动判定只产四档（无 suspense）；显式值经
# resolve_scene_type 校验后可直接透传给检索层。
VALID_SCENE_TYPES = frozenset({"dialogue", "action", "lyrical", "suspense", "general"})

# 对话占比阈值（严格大于才判 dialogue）：0.35 ≈ 尾 300 字里超过三分之一
# 是引号内文字——设计稿 §5.2 拍板值，勿随手调（改判定 = 改加成触发面）
DIALOGUE_RATIO_THRESHOLD = 0.35

# 判定窗口：stitch 装配处取 rolling_prefix 尾 300 字（此刻正在写的段落，
# 不是整章——场景是「现在时」信号）。装配方切片，本模块只判给定文本。
SCENE_HINT_TAIL_CHARS = 300

# ---- 动作信号 ----
# 动作动词字符类（词表出处：logs/style_ab/pick_material_v2.py ACTION_RE，
# 文风双跑实验 v1/v2 已在《弦上灰》全 17 章窗上人工核过命中面）。
_ACTION_VERB_RE = re.compile(r"[冲砸撞炸闪躲逃扑射劈碎裂爆吼叫嘶吼奔逃跌撞窜滚掐扼拖拽坠杀斩削掠腾撕扯踹跺掷扔甩捅刺爬追][^，。！？\n]{0,6}")
# 动作动词密度阈值（hits/千字）：《弦上灰》回测中动作窗（仓库破门/钻管
# 逃亡/夺机戏）密度普遍 25~60，普通叙述窗多在 10 以下——取 18 卡在两类
# 分布的空隙里（保守偏高：宁可漏判）。
ACTION_DENSITY_PER_1K = 18.0
# 强信号豁免线：动词风暴密度 ≥35/千字时不再要求节奏佐证——回测中管道
# 坍塌窗（hits 5~8/约 200 字）句长不极端短但仍确凿是动作戏，双信号门槛
# 会漏判；此密度下误判风险已足够低。
ACTION_STRONG_DENSITY_PER_1K = 25.0
# 节奏佐证（满足其一即可）：短句率 ≥0.25 或句长 CV ≥0.45——动作戏短促
# 破折；双信号防「动词密集但节奏平缓」的叙述误入。
ACTION_SHORT_RATIO = 0.25
ACTION_CV = 0.45

# ---- 抒情信号 ----
# 质感（描写性词汇）密度阈值（texture_per_1k，fingerprint 同一把尺子）：
# 回测中抒情窗（《弦上灰》樱花余波/沉降电梯/农场晨光）密度普遍 33~46，
# 普通窗中位 20 上下——取 33（保守偏高）。
LYRICAL_TEXTURE_PER_1K = 33.0
# 抒情要求动作密度低（< 12/千字，远低于 action 阈值）且对白占比很低
# （≤0.12——回测中高质感但夹对白/追逐的窗据此被拦在 general）——动起来
# 或说起来的段不是静观沉思的段。
LYRICAL_MAX_ACTION_PER_1K = 12.0
LYRICAL_MAX_DIALOGUE_RATIO = 0.12


def resolve_scene_type(
    explicit: Optional[str],
    text: Optional[str],
    fragment: str = "",
) -> str:
    """显式 scene_type 优先，非法/缺失回落自动判定（v3 两段式）。

    Args:
        explicit: 请求体显式携带的场景类型（None/空/非法 → 自动判定）
        text: 自动判定用的尾窗文本（调用方负责取尾窗）
        fragment: 作者原句碎片（空=纯尾窗判定，v2 行为逐字节不变）

    Returns:
        样本侧合法的场景类型串
    """
    if explicit and explicit in VALID_SCENE_TYPES:
        return explicit
    return detect_scene_hint(text, fragment)


def detect_scene_type(text: Optional[str]) -> str:
    """判定给定文本的场景档位（v2 四档：dialogue / action / lyrical / general）。

    纯算法、零 I/O：单次 compute_text_fingerprint(light) 出对话占比/句长族/
    质感密度，动作动词另跑一个正则。任何异常/空文本 → "general"（宁稳勿炸
    ——判定失败绝不能阻塞样本检索）。

    判定序：dialogue（v1 行为不变）→ action → lyrical → general 兜底。

    Args:
        text: 待判定文本（调用方负责取尾窗，如 rolling_prefix[-300:]）

    Returns:
        "dialogue" | "action" | "lyrical" | "general"
    """
    if not text or not text.strip():
        return SCENE_GENERAL
    try:
        fp = compute_text_fingerprint(text, light=True)
        ratio = fp.get("dialogue_ratio") or 0.0
        # dialogue 分支：v1 原样，零变化（有 test_scene_hint 锁定）
        if ratio > DIALOGUE_RATIO_THRESHOLD:
            return SCENE_DIALOGUE

        word_count = max(1, fp.get("word_count") or 0)
        action_density = len(_ACTION_VERB_RE.findall(text)) * 1000.0 / word_count
        if action_density >= ACTION_DENSITY_PER_1K:
            if action_density >= ACTION_STRONG_DENSITY_PER_1K:
                return SCENE_ACTION  # 动词风暴：豁免节奏佐证
            short_ratio = fp.get("short_sentence_ratio") or 0.0
            cv = fp.get("sentence_len_cv") or 0.0
            if short_ratio >= ACTION_SHORT_RATIO or cv >= ACTION_CV:
                return SCENE_ACTION

        texture = fp.get("texture") or {}
        texture_per_1k = texture.get("texture_per_1k") or 0.0
        if (
            texture_per_1k >= LYRICAL_TEXTURE_PER_1K
            and action_density < LYRICAL_MAX_ACTION_PER_1K
            and ratio <= LYRICAL_MAX_DIALOGUE_RATIO
        ):
            return SCENE_LYRICAL

        return SCENE_GENERAL
    except Exception:  # noqa: BLE001 —— 统计失败兜底 general，不向上抛
        return SCENE_GENERAL


# ============================================================
# v3 · fragment 优先两段式判定（stitch 断点场景判定修复）
# ============================================================

def _fragment_strong_scene(fragment: str) -> Optional[str]:
    """fragment 单独判定的「强信号」口径（v3 两段式第一段）。

    只有显著强于普线的信号才允许 fragment 单独定档——短窗（几十字）分母
    小、单句噪声大，普线（如 action 18/千字）在短窗上误判面过大。两路
    开放、一路关闭：

    - dialogue：现有对白占比线（> 0.35）原样复用。占比是字符级比值而非
      千字密度，不受窗长稀释，短窗上依然可靠（引号要么在要么不在）。
    - action：动词风暴豁免线（≥ 25/千字，ACTION_STRONG_DENSITY_PER_1K）
      而非普线 18——豁免线本来就是「密度高到无需节奏佐证」的档位，拿它
      兼做 fragment 采信线语义自洽；且不要求节奏佐证（fragment 常是半句，
      句长统计无意义）。
    - lyrical：本轮不开放。质感词表是封闭口径（LYRICAL_TEXTURE_PER_1K
      按千字密度计），短句里一两个质感词即可把密度顶过 33/千字线（《弦上
      灰》lyrical 断点三种输入全判 general 的同因），fragment 单独判 lyrical
      的误判风险高于收益——回落拼接判定（长窗稀释后仍过线才采信）。

    Returns:
        "dialogue" | "action" | None（None=无强信号，回落两段式第二段）
    """
    if not fragment or not fragment.strip():
        return None
    try:
        fp = compute_text_fingerprint(fragment, light=True)
        ratio = fp.get("dialogue_ratio") or 0.0
        if ratio > DIALOGUE_RATIO_THRESHOLD:
            return SCENE_DIALOGUE
        word_count = max(1, fp.get("word_count") or 0)
        action_density = len(_ACTION_VERB_RE.findall(fragment)) * 1000.0 / word_count
        if action_density >= ACTION_STRONG_DENSITY_PER_1K:
            return SCENE_ACTION
        return None
    except Exception:  # noqa: BLE001 —— 统计失败=无强信号，回落拼接判定
        return None


def detect_scene_hint(tail_text: Optional[str], fragment: str = "") -> str:
    """两段式场景判定（v3，stitch 装配处新入口）。

    判定序（保守优先：任何一路信号不强都回落，最终兜底 general）：
      1. fragment 非空且单独判出强信号非 general 档 → 直接采信
         （_fragment_strong_scene 口径）；
      2. 否则「tail_text + fragment」拼接判定（现状通路的语义扩展：
         v2 通路只判尾窗，此处把 fragment 拼上去——断点处的动作碎片不再
         被描写性尾巴稀释；dialogue 断点实测靠拼接窗里的对白尾巴判回
         dialogue，单靠 fragment 不可行）；
      3. fragment 为空 → detect_scene_type(tail_text)，与 v2 逐字节一致。

    Args:
        tail_text: rolling_prefix 尾窗文本（调用方负责取尾窗，如
            rolling_prefix[-300:]）
        fragment: 作者原句碎片（空=纯尾窗判定，行为零变化）

    Returns:
        "dialogue" | "action" | "lyrical" | "general"
    """
    frag = (fragment or "").strip()
    if not frag:
        return detect_scene_type(tail_text)
    strong = _fragment_strong_scene(frag)
    if strong:
        return strong
    return detect_scene_type((tail_text or "") + frag)
