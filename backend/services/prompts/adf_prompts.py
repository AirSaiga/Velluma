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
ADF（Anchor-Driven Flow）引擎 prompt 模板（V3.2 §4 新建）。

职责：
- Phase 2 远端锚设计 prompt（build_anchor_design_prompt）
- Phase 4 正向流写作 prompt（build_forward_flow_prompt）
- Phase 5 锚点审计 prompt（build_anchor_audit_prompt）
- Phase 6 条件补埋 prompt（build_refine_prompt）
- Phase 7 一致性审计 prompt（build_consistency_audit_prompt）

设计意图：
- 正向流写作的核心是"软提示"——告诉 LLM 建议下段埋什么，但不强制怎么写
- 情绪曲线进度条作为连续约束（替代 V3.1 整数 distance_to_climax）
- 远端锚作为"牵引"而非"路径"：高潮描述每段都注入，但不强制"现在必须写什么"
- 一致性审计用"证据锚定"防 judge 幻觉：每条 issue 必须引用设定原文

业务场景：
- workflows/adf/climax_designer.py      → build_anchor_design_prompt
- workflows/adf/segment_writer.py       → build_forward_flow_prompt
- workflows/adf/structure_checker.py    → build_anchor_audit_prompt
- workflows/adf/refiner.py              → build_refine_prompt
- workflows/adf/consistency_guard.py    → build_consistency_audit_prompt

使用方式：
    system, user = build_forward_flow_prompt(...)
    result = await call_llm_with_usage(system_prompt=system, user_prompt=user, ...)

依赖项：
- 无（纯模板）
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.services.nlg.anti_ai_rules import DEFAULT_BAN_LIST


# ============================================================
# Phase 2: 远端锚设计 prompt
# ============================================================

ANCHOR_DESIGN_SYSTEM = """你是资深的长篇小说编辑与结构设计师。

你的任务：基于章节大纲与前文脉络，完成本章的高潮设计——即本章的高潮点 + 高潮写到前必须满足的若干铺垫要点 + 情绪走向。

# 核心理念

本章高潮设计的原则（与传统"节拍表"截然不同）：
1. **只设计高潮与条件，不设计铺垫节点**。铺垫要点是"高潮写到前必须满足的状态"，不是"必须按序经过的站点"。
2. **铺垫要点不预设埋设位置**。它们将在后续正向写作时由前文自然涌现决定在何处埋下。
3. **情绪走向连续**，不是整数距离。每个采样点描述该进度下的情绪氛围与强度（1-10）。

# 设计要点

## 高潮点（climax）
- 一个，不是多个。本章情绪强度的最高释放瞬间。
- emotional_target 描述读者此刻应达到的情绪状态（不是事件描述）。
- payoff_question 是本章回收的悬念；open_question 是本章打开的新悬念（钩子）。
- intensity 1-10 自评，要诚实——低分（≤3）意味着这章其实是过渡章。

## 铺垫要点（preconditions）
- 3-5 个，覆盖：角色真实状态/世界设定/伏笔埋设/动机建立/关系建立。
- 每个条件必须有 must_use_terms（必须出现的设定词），用于代码级关键词是否写到的检测。
- min_landing_offset 是距高潮至少多少字之前必须埋下（避免临高潮才补显得突兀）。
- **强制关联**：前文脉络中的 must_plant_hooks，必须转化为对应的 Precondition（防止钩子丢失）。

## 情绪走向（emotion_curve）
- 至少 3 个采样点（入口/中段/高潮），建议 5 个。
- progress 0.0=章节入口，1.0=高潮瞬间。
- register 是该位置的情绪氛围（如"蓄势""临界""爆发"）。
- energy 1-10，单调非减（情绪强度只能累积，不能凭空回退）。
- transition 档可能只有 2 个采样点（入口+收束），这是允许的。

# 输出格式

严格 JSON（围栏可省略）：

```json
{
  "climax": {
    "description": "...",
    "emotional_target": "...",
    "payoff_question": "...",
    "open_question": "...",
    "intensity": 7
  },
  "preconditions": [
    {
      "id": "PC_REAL_POWER",
      "category": "role",
      "description": "建立主角暗元素/弦月巅峰的真实实力暗示",
      "must_use_terms": ["暗元素", "弦月巅峰"],
      "min_landing_offset": 500
    }
  ],
  "emotion_curve": {
    "samples": [
      {"progress": 0.0, "register": "入口", "energy": 2},
      {"progress": 0.6, "register": "临界", "energy": 6},
      {"progress": 1.0, "register": "爆发", "energy": 10}
    ]
  }
}
```"""


ANCHOR_DESIGN_USER_TEMPLATE = """# 本章信息

## 章节主旨
{purpose}

## 必达事件
{must_hit_events}

## 前文脉络（强约束）
- 入口状态：{entry_state}
- 出口预期：{exit_expectation}
- 本章位置：{chapter_position}
- 必须埋的钩子（**必须转化为对应 Precondition**）：{must_plant_hooks}
- 必须回收的伏笔：{must_resolve_hooks}
- 角色弧推进要求：{character_arc_advances}

## 前文张力
{previous_tension}

## 开放伏笔（可推进/呼应）
{open_hooks}

## 本章可涉及角色
{characters}

## 要求

请完成本章的高潮设计。铺垫要点数量：3-5 个。情绪走向采样点：3-5 个。
**特别注意**：must_plant_hooks 中的每个钩子，必须有一个对应的 Precondition。
返回严格 JSON。"""


def build_anchor_design_prompt(
    purpose: str,
    must_hit_events: str,
    entry_state: str,
    exit_expectation: str,
    chapter_position: str,
    must_plant_hooks: List[str],
    must_resolve_hooks: List[str],
    character_arc_advances: Dict[str, str],
    previous_tension: str,
    open_hooks: str,
    characters: str,
) -> Tuple[str, str]:
    """构建远端锚设计 prompt（Phase 2）。

    Args:
        purpose: 章节主旨
        must_hit_events: 必达事件文本
        entry_state / exit_expectation / chapter_position: 脉络轨文本
        must_plant_hooks: 必须埋的钩子列表
        must_resolve_hooks: 必须回收的伏笔列表
        character_arc_advances: 角色弧推进要求
        previous_tension: 前文张力
        open_hooks: 开放伏笔
        characters: 角色信息

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    hooks_text = "\n".join(f"- {h}" for h in must_plant_hooks) if must_plant_hooks else "（无）"
    resolve_text = "\n".join(f"- {h}" for h in must_resolve_hooks) if must_resolve_hooks else "（无）"
    arc_text = "\n".join(f"- {k}: {v}" for k, v in character_arc_advances.items()) if character_arc_advances else "（无）"

    user_prompt = ANCHOR_DESIGN_USER_TEMPLATE.format(
        purpose=purpose or "（未提供，请从必达事件推断）",
        must_hit_events=must_hit_events or "（未指定）",
        entry_state=entry_state or "（本章是第一章）",
        exit_expectation=exit_expectation or "（未指定）",
        chapter_position=chapter_position or "（未指定）",
        must_plant_hooks=hooks_text,
        must_resolve_hooks=resolve_text,
        character_arc_advances=arc_text,
        previous_tension=previous_tension or "（本章是第一章或无前文）",
        open_hooks=open_hooks or "（无）",
        characters=characters or "（未指定）",
    )
    return ANCHOR_DESIGN_SYSTEM, user_prompt


# ============================================================
# Phase 4: 正向流写作 prompt（核心）
# ============================================================

FORWARD_FLOW_SYSTEM_TEMPLATE = """你是顶级的中文长篇小说作家。

# 写作原则

1. **场景驱动，不是功能驱动**。每段从上一段的尾巴自然涌出，像水从高处流到低处。不要为了"埋设某个设定"而强行切换场景——如果场景自然走到那里，设定自然会被带出。
2. **呼吸连续**。段落之间用人物动作、感官细节、环境变化做衔接，避免突兀的跳切。
3. **避免叙事者插嘴**。不要用"不是因为他想这样，而是因为..."这种解释性语句——让行动和细节自己说话。潜台词优于明说。
4. **节奏服从情绪走向**。当前进度要求的情绪氛围要落到这段的语气里，但不强制必须发生什么事件。

# 反 AI 腔指令（硬性禁令，违反即视为生成失败）

你的文字会被代码级检测器扫描"AI 味密度"，超标段落会被强制重写。以下是必须规避的 4 类机械感：

1. **禁病态微操**：不许堆砌无信息量的微小动作。"指尖颤了颤""下巴抬高半寸""眼角余光""瞳孔微微收缩""喉结滚动""睫毛轻颤"——这类描写零情节价值，是 AI 填充字数的典型手法。一个动作要么承载信息（揭示情绪/推进关系），要么删掉。同一段内微操动作不超过 1 处。
2. **禁套路比喻**：不许用伪深度填充词。"冷冽""深邃""宛如""仿佛""不可名状""墨水滴进水里""沉睡的巨兽"——这些是 AI 伪文学腔的高频词。如需比喻，用一个具体、新鲜、贴合本场景的意象，不要套用万能比喻模板。本段套路比喻至多 1 处。
3. **禁匀速句式**：不许长短句过于均匀。AI 生成的段落常像节拍器——每句长度接近、结构对称（"他看着X，眼中带着Y""她转过身，嘴角勾起Z"）。主动制造长短交错：短句（3-8字）制造冲击与停顿，长句铺陈细节。后置修饰语（"眼中带着一抹X""语气中透着一丝Y"）本段不超过 1 处。
4. **禁解释性插嘴**：不许用"仿佛在说...""似乎在表达...""不是A而是B"这类替读者总结的语句。让动作、对话、细节自己传达潜台词。

# 文风契约

{style_contract}

# 作者样本（参考语感，不要复制内容）

{author_samples}

# 核心理念：以高潮为目标

本章的高潮点（每段都会注入，这是全章的方向，不是眼下要写的场景）：

{climax_anchor}

情绪走向（描述本章情绪如何累积到高潮）：

{emotion_curve}"""

FORWARD_FLOW_USER_TEMPLATE = """# 当前进度

- 段序号：{segment_index}/{total_segments}（共 {total_segments} 段）
- 章节进度：{progress:.0%}
- 当前情绪氛围：**{current_register}**（强度 {current_energy}/10）
- 下一阶段情绪：{next_register}（强度 {next_energy}/10）

# 前文衔接（rolling prefix，紧接上一段结尾）

{rolling_prefix}

# 本章脉络约束

- 章节主旨：{purpose}
- 入口状态：{entry_state}
- 本章角色：{characters}
- 必须推进的角色弧：{character_arc_advances}

# 本段提示（建议，非强制）

{soft_hints}

# 本段目标字数

约 {target_words} 字（可上下浮动 20%，自然写完即可，不必凑字数）。

{hard_constraints}

# 要求

写下一段正文。**不要写段标题、不要用 markdown 标记、不要解释**。只输出小说正文本身。
让前文自然涌出，让情绪氛围渗透到行文里。"""


def build_forward_flow_prompt(
    style_contract: str,
    author_samples: str,
    climax_anchor: str,
    emotion_curve: str,
    segment_index: int,
    total_segments: int,
    progress: float,
    current_register: str,
    current_energy: int,
    next_register: str,
    next_energy: int,
    rolling_prefix: str,
    purpose: str,
    entry_state: str,
    characters: str,
    character_arc_advances: str,
    soft_hints: str,
    target_words: int,
    hard_constraints: str = "",
) -> Tuple[str, str]:
    """构建正向流写作 prompt（Phase 4，每段一次）。

    设计要点：
    - climax_anchor + emotion_curve 进 system 层（每段固定，吃 prompt 缓存）
    - rolling_prefix + 软提示进 user 层（每段变化）
    - 软提示是"建议"而非"必须"——让 LLM 自主决定如何自然融入
    - hard_constraints（专名表/知识边界/在场提示）放 user 末尾吃近因效应；
      默认空串，现有调用方不传时行为不变

    Args:
        见 FORWARD_FLOW_SYSTEM_TEMPLATE / FORWARD_FLOW_USER_TEMPLATE 中的占位符

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    system_prompt = FORWARD_FLOW_SYSTEM_TEMPLATE.format(
        style_contract=style_contract or "（未指定，按通用中文文学小说风格）",
        author_samples=author_samples or "（无样本）",
        climax_anchor=climax_anchor or "（未指定）",
        emotion_curve=emotion_curve or "（未指定）",
    )

    user_prompt = FORWARD_FLOW_USER_TEMPLATE.format(
        segment_index=segment_index,
        total_segments=total_segments,
        progress=progress,
        current_register=current_register,
        current_energy=current_energy,
        next_register=next_register,
        next_energy=next_energy,
        rolling_prefix=rolling_prefix or "（本章开篇）",
        purpose=purpose or "（未指定）",
        entry_state=entry_state or "（未指定）",
        characters=characters or "（未指定）",
        character_arc_advances=character_arc_advances or "（未指定）",
        soft_hints=soft_hints or "（无特别建议，让前文自然涌出）",
        target_words=target_words,
        hard_constraints=hard_constraints or "",
    )

    return system_prompt, user_prompt


# ============================================================
# 反 AI 味：动态扰动变量生成（基于分镜景别）
# ============================================================

# 分镜景别 → 节奏/密度扰动参数。让不同景别的段落有不同的句式倾向，
# 打破全章匀速感。shot_type 来自 storyboard.py 的分镜结果。
_SHOT_PERTURBATION = {
    # 远景：环境/氛围为主，允许较长铺陈句，微操极少
    "远景": {"max_metaphor": 1, "rhythm_hint": "以环境长句为主，偶尔用一个短句切出画面焦点"},
    # 全景：群像/场景，句长中等
    "全景": {"max_metaphor": 1, "rhythm_hint": "长短句交错，避免连续三个等长句子"},
    # 近景：人物互动，可有一个动作细节
    "近景": {"max_metaphor": 1, "rhythm_hint": "对话与动作短句为主，穿插一个长句铺情绪"},
    # 特写：高密度情绪，允许比喻但禁微操
    "特写": {"max_metaphor": 2, "rhythm_hint": "用短促有力的句子制造冲击，比喻要具体新鲜"},
    # 微距：极细致，最容易堆微操——严格限制
    "微距": {"max_metaphor": 1, "rhythm_hint": "一个核心感官细节写透，禁止堆砌多个微小动作"},
}


def build_anti_ai_perturbation(shot_type: str) -> str:
    """生成本段的反 AI 味扰动指令（注入 soft_hints 前部）。

    根据分镜景别动态调整比喻密度上限与句式倾向，使不同段落有差异化节奏，
    从生成端打破"全章句式趋同"。

    Args:
        shot_type: 分镜景别（远景/全景/近景/特写/微距），未知类型用默认

    Returns:
        扰动指令文本（拼到 soft_hints 前面）

    使用方式（segment_writer 构造 soft_hints 时）：
        soft_hints = build_anti_ai_perturbation(shot_type) + "\\n" + soft_hints
    """
    cfg = _SHOT_PERTURBATION.get(shot_type, _SHOT_PERTURBATION["近景"])
    return (
        f"【本段节奏约束】{cfg['rhythm_hint']}。"
        f"本段套路比喻上限 {cfg['max_metaphor']} 处，微操动作上限 1 处。"
    )


# ============================================================
# Phase 5: 锚点审计 prompt
# ============================================================

ANCHOR_AUDIT_SYSTEM = """你是严格的小说结构审校员。

你的任务：对正文做四维校验，并返回结论。

# 四维校验

## 维度 1：铺垫要点是否写到了
对每个铺垫要点，判断是否在正文中语义性写到（不只看 must_use_terms 关键词，还要看是否真正建立了该状态）。
未写到的，加入 missing_preconditions。

## 维度 2：情绪走向符合度
对照情绪走向，检查开头/中段/高潮位置的实际情绪是否与曲线要求的 register/energy 对齐。
不符的，加入 emotion_mismatches（描述不符点）。

## 维度 3：脉络符合度
- 入口状态是否与前章自然衔接？
- 必须推进的角色弧是否推进？
- 必须埋的钩子是否埋了？
- 必须回收的伏笔是否回收？
违反的，加入 spine_violations。

## 维度 4：高潮验收
高潮段是否真正达到 climax.emotional_target？
打分 climax_score 1-10（<7 表示需要重写）。

## 维度 5：文风质量（反 AI 腔）
检查正文是否存在明显的 AI 机械感：
- 病态微操泛滥（指尖颤动/瞳孔收缩/喉结滚动等无信息量动作堆砌）
- 套路比喻密集（冷冽/深邃/宛如/仿佛/沉睡的巨兽等伪深度词）
- 句式匀速（长短句过于均匀，后置修饰语"眼中带着一抹..."泛滥）
违反的，加入 style_violations（描述具体问题段位置），并给 style_score 1-10（<6 表示需要润色）。

## 维度 6：大纲节拍覆盖
对照"大纲节拍清单"，逐个核对每个节拍在正文中是否被写到：
- covered：该节拍已被正文完整写到
- partial：写到了但被弱化/一笔带过（只上报，不影响 verdict）
- missing：正文完全没有写到该节拍
判 missing 的节拍必须同时给出三个字段：
- evidence：为什么判缺（正文哪里本应出现却没有）
- insert_anchor_quote：正文中一段原文引文（≤50 字，必须逐字摘自正文），补写内容将插在它前面或后面
- insert_position：before | after（补写内容相对引文的位置）
**引不出 insert_anchor_quote 的节拍不许判 missing**（防误报，伪锚会被代码侧丢弃）。
节拍清单中括号里的代码预判仅供参考（可能误报），以你的语义判断为准。
无节拍清单时本维度跳过。

# 输出格式

严格 JSON：

```json
{
  "verdict": "pass" | "needs_refinement" | "fail",
  "missing_preconditions": ["PC_REAL_POWER"],
  "emotion_mismatches": ["开头能量过高，曲线要求入口能量2"],
  "spine_violations": ["协会高层钩子未埋"],
  "climax_score": 7,
  "style_violations": ["第三段堆砌5处微操动作（指尖颤/瞳孔缩/喉结滚）"],
  "style_score": 5,
  "missing_beats": [
    {
      "beat": "林尘在工棚借着灯光读书，被工头打断",
      "status": "missing",
      "evidence": "正文直接从仓库废墟开场，读书与工头打断均未出现",
      "insert_position": "before",
      "insert_anchor_quote": "灰尘还没散"
    }
  ],
  "refinement_targets": ["PC_REAL_POWER"]
}
```

判定规则：
- 任何 missing_preconditions 非空 → needs_refinement
- 任何 status=missing 的大纲节拍 → needs_refinement
- climax_score < 7 → needs_refinement
- spine_violations 含关键违反（钩子丢失/角色弧没推进）→ needs_refinement
- style_score < 6 → needs_refinement（文风质量不达标）
- 全部通过 → pass
- 严重结构崩坏（如高潮根本没写）→ fail"""

ANCHOR_AUDIT_USER_TEMPLATE = """# 章节信息
- 主旨：{purpose}
- 定档：{tier}

# 本章高潮设计

## 高潮点
{climax_description}（emotional_target: {climax_emotional_target}）

## 铺垫要点
{preconditions}

## 情绪走向
{emotion_curve}

## 前文脉络
- 入口状态：{entry_state}
- 必须埋的钩子：{must_plant_hooks}
- 必须回收的伏笔：{must_resolve_hooks}
- 角色弧推进要求：{character_arc_advances}

# 大纲节拍清单（维度 6 逐个核对；括号为代码预判，仅供参考）

{outline_beats}

# 待审正文（全文）

{full_text}

# 要求

返回严格 JSON。"""


def build_anchor_audit_prompt(
    purpose: str,
    tier: str,
    climax_description: str,
    climax_emotional_target: str,
    preconditions: str,
    emotion_curve: str,
    entry_state: str,
    must_plant_hooks: List[str],
    must_resolve_hooks: List[str],
    character_arc_advances: Dict[str, str],
    full_text: str,
    outline_beats: Optional[List[str]] = None,
    beat_suspects: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, str]:
    """构建锚点审计 prompt（Phase 5）。

    Args:
        见 ANCHOR_AUDIT_USER_TEMPLATE 占位符
        full_text: 完整正文（截断到 6000 字）
        outline_beats: 大纲节拍清单（None/空 → 模板显示"无大纲，跳过节拍校验"）
        beat_suspects: score_beat_coverage 的代码预判（按 beat 标注在清单上；
            "未知"不标注）

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    hooks_text = ", ".join(must_plant_hooks) if must_plant_hooks else "（无）"
    resolve_text = ", ".join(must_resolve_hooks) if must_resolve_hooks else "（无）"
    arc_text = "; ".join(f"{k}→{v}" for k, v in character_arc_advances.items()) if character_arc_advances else "（无）"

    if outline_beats:
        guess_map = {
            s.get("beat"): s.get("guess")
            for s in (beat_suspects or [])
            if s.get("guess") and s.get("guess") != "未知"
        }
        beat_lines = []
        for beat in outline_beats:
            guess = guess_map.get(beat)
            beat_lines.append(f"- {beat}（代码预判：{guess}）" if guess else f"- {beat}")
        beats_text = "\n".join(beat_lines)
    else:
        beats_text = "（无大纲，跳过节拍校验）"

    user_prompt = ANCHOR_AUDIT_USER_TEMPLATE.format(
        purpose=purpose or "（未指定）",
        tier=tier,
        climax_description=climax_description or "（未指定）",
        climax_emotional_target=climax_emotional_target or "（未指定）",
        preconditions=preconditions or "（未指定）",
        emotion_curve=emotion_curve or "（未指定）",
        entry_state=entry_state or "（未指定）",
        must_plant_hooks=hooks_text,
        must_resolve_hooks=resolve_text,
        character_arc_advances=arc_text,
        outline_beats=beats_text,
        # 头尾采样而非仅取前 6000 字：高潮段在文末，只取头部会漏审高潮验收。
        # 短文（<=12000字）全量；长文取首 6000 + 尾 4000（尾段覆盖高潮）。
        full_text=_sample_head_tail(full_text or ""),
    )
    return ANCHOR_AUDIT_SYSTEM, user_prompt


def _sample_head_tail(text: str, head: int = 6000, tail: int = 4000) -> str:
    """头尾采样长文本，保证审计同时看到入口衔接（头部）与高潮验收（尾部）。

    原 bug：full_text[:6000] 只保留开头，高潮段在文末永远审不到。
    修复：短文全量；长文取首 head + 省略号 + 尾 tail。
    """
    if len(text) <= head + tail:
        return text
    return text[:head] + "\n\n……（中段省略）……\n\n" + text[-tail:]


# ============================================================
# Phase 6: 条件补埋 prompt
# ============================================================

REFINE_SYSTEM_TEMPLATE = """你是中文长篇小说的精修编辑。

任务：在已有段落中"内嵌式补写"一个未写到的铺垫要点，**不新开段落，不打断已有节奏**。

# 原则

1. 选择最自然的段落（通常是 develop 区、日常场景段落）插入补写。
2. 补写内容必须**与该段已有情境无缝融合**——可能是一句台词、一个动作细节、一段心理描写。
3. 必须包含设定的关键词：{must_use_terms}
4. 保留原段落的所有其他内容，只做最小侵入式补充。
5. 输出补写后的**完整段落**（不是只输出补充部分）。
6. 只输出你选定的那**一段**——严禁包含其他任何段落的内容，严禁从章节开头重写。

# 文风契约

{style_contract}"""

REFINE_USER_TEMPLATE = """# 需要补充铺垫的要点

- ID: {precondition_id}
- 描述: {precondition_description}
- 必须出现的关键词: {must_use_terms}

# 待补写的段落（选择其中最自然的一段补充铺垫）

{candidate_paragraphs}

# 要求

选择最自然的那段，内嵌式补写上述铺垫要点。输出补写后的**完整段落**。
不要解释、不要标记修改位置、只输出段落正文本身。"""


def build_refine_prompt(
    style_contract: str,
    precondition_id: str,
    precondition_description: str,
    must_use_terms: List[str],
    candidate_paragraphs: str,
) -> Tuple[str, str]:
    """构建条件补埋 prompt（Phase 6，每个未落地条件一次）。

    Args:
        style_contract: 文风契约
        precondition_id: 条件 ID
        precondition_description: 条件描述
        must_use_terms: 必须出现的关键词
        candidate_paragraphs: 候选段落（已分段，供 LLM 选择最自然的补埋位置）

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    terms_text = "、".join(must_use_terms) if must_use_terms else "（无强制关键词）"
    system_prompt = REFINE_SYSTEM_TEMPLATE.format(
        must_use_terms=terms_text,
        style_contract=style_contract or "（未指定）",
    )
    user_prompt = REFINE_USER_TEMPLATE.format(
        precondition_id=precondition_id,
        precondition_description=precondition_description,
        must_use_terms=terms_text,
        candidate_paragraphs=candidate_paragraphs,
    )
    return system_prompt, user_prompt


# ============================================================
# 辅助：构建 climax_anchor 文本（用于注入 system prompt）
# ============================================================

def format_climax_anchor(climax: Dict[str, Any]) -> str:
    """把 ClimaxSpec dict 格式化为 system prompt 中可读的文本。"""
    if not climax:
        return "（未指定）"
    parts = []
    if climax.get("description"):
        parts.append(f"场景：{climax['description']}")
    if climax.get("emotional_target"):
        parts.append(f"目标情绪：{climax['emotional_target']}")
    if climax.get("payoff_question"):
        parts.append(f"本章回收：{climax['payoff_question']}")
    if climax.get("open_question"):
        parts.append(f"本章埋钩：{climax['open_question']}")
    if climax.get("intensity"):
        parts.append(f"强度自评：{climax['intensity']}/10")
    return "\n".join(parts) if parts else "（未指定）"


def format_emotion_curve(samples: List[Dict[str, Any]]) -> str:
    """把情绪曲线采样点格式化为可读文本。"""
    if not samples:
        return "（未指定）"
    lines = []
    for s in samples:
        prog = s.get("progress", 0)
        reg = s.get("register", "?")
        energy = s.get("energy", "?")
        lines.append(f"- 进度 {prog:.0%}：{reg}（强度 {energy}/10）")
    return "\n".join(lines)


def format_preconditions(preconditions: List[Dict[str, Any]]) -> str:
    """把前置条件列表格式化为可读文本。"""
    if not preconditions:
        return "（无）"
    lines = []
    for pc in preconditions:
        pc_id = pc.get("id", "?")
        desc = pc.get("description", "")
        terms = pc.get("must_use_terms", [])
        terms_text = "、".join(terms) if terms else "无"
        lines.append(f"- [{pc_id}] {desc}（关键词：{terms_text}）")
    return "\n".join(lines)


# ============================================================
# Phase 4.5：去 AI 味剪枝 prompt（PRUNE，每段一次 creative）
# ============================================================
#
# 设计意图（"重构剪枝型"，区别于现有 de_ai_washer 的"润色取向"）：
# - 现有 de_ai_washer 是"润色"——在原句上修补、字数浮动 ±15%，倾向保留原句结构，
#   这是它去 AI 味效果差的根因：洗不掉真正的腔调问题，只是把"冷冽"换成别的词。
# - 本剪枝是"重构"——允许重写句式结构（匀速句→长短交错）、删过渡词、心理转物理，
#   但保留叙事密度（字数 ±25%，不靠删字数去 AI 味，靠重构节奏）。
# - 全章无条件触发（不依赖密度阈值），因为 AI 味往往是章节级的整体腔调，
#   单看每段可能不超标，连起来却浓浓的 AI 味。
# - 对话可改（AI 对话本身就书面化），但有 OOC 安全线（pruner.py 调 build_ooc_check_prompt）兜底。

PRUNE_SYSTEM_TEMPLATE = """你是顶级的中文网络小说文字剪辑师，专精"去 AI 腔"重构。

你收到一段 AI 生成的小说正文，它带有明显的机械感。你的任务：**在保留全部情节、设定、人物行为不变的前提下，重构这段文字的行文节奏与句式，消除 AI 味**。

# 必须消除的 AI 腔（重构，不是删除）

1. **匀速句式 → 长短交错（以正常语流为主）**。
   AI 生成的段落常像节拍器——每句长度接近、结构对称。你要打破这种匀速，但**方向是把模板化的中长句写活，不是把句子切碎**：
   - 以正常语流的长句铺陈为主，短句只在真正需要重锤/停顿的位置偶尔使用（每段至多 1-2 处）。
   - **严禁把整段切成 10 字以内的碎句连发**（"他没动。血。冷。"式机枪句）——那是另一种 AI 腔，比匀速更糟。
   - 判断标准：普通叙述句保持自然完整的语法结构；只有情绪高点才允许短句冲击。

2. **逻辑过渡词 → 硬切硬接**。
   AI 爱用"然而/但是/随后/与此同时/不仅……反而/随着/渐渐地"把动作硬拼成因果链。
   全局删除这些逻辑衔接词，让两个动作直接硬拼（"他没动。她转过头。"），用动作本身表达转折，不用词。

3. **套路比喻与肢体微操 → 删或换**。
   删掉"冷冽/深邃/宛如/仿佛/不可名状"等伪深度填充词。
   删掉"指尖微颤/嘴角勾起/瞳孔收缩/眼角余光/喉结滚动"等无信息量微操。
   如需比喻，用一个具体、新鲜、贴合本场景的意象，不要套万能模板。

4. **抽象心理 → 物理事实**。
   "他感到十分绝望/愤怒/纠结"这类直陈心理状态是 AI 腔。删掉心理分析，只保留前后能被观察到的客观动作或环境结果，让读者自己推断心理。

# 硬约束

- **情节零损失**：人物、事件、地点、情绪走向、关键设定必须 100% 保留。重构的是"怎么写"，不是"写什么"。
- **叙事密度保留**：字数浮动 ±25%。允许重写句式，但**不要靠大段删字数去 AI 味**——删的应该是废话和套路，保留的是有效叙事信息。
- **对话可改，但保持角色语气**：对话可以变得更口语、更简短、更像"人话"，但**严禁改变角色的核心性格、口癖、说话方式**。
- **不要加段标题、不要用 markdown、不要解释**。只输出重构后的正文本身。

# 角色红线（重构对话时必须遵守，违反即 OOC）

{characters_setting}

# 文风契约（重构后的文字必须符合）

{style_contract}

# 作者样本（参考语感，不要复制内容）

{author_samples}"""

PRUNE_USER_TEMPLATE = """# 待剪枝段落（AI 生成正文，需重构去 AI 味）

# 前文衔接（紧接上一段结尾）

{rolling_prefix}

# 原文

{text}

# 要求

重构这段，按上面的"去 AI 腔"规则把匀速句式写活（以正常语流为主，不要把句子切碎）、删逻辑过渡词、剥套路比喻、心理转物理。
保留全部情节和角色设定。只输出重构后的正文。"""


def build_prune_prompt(
    characters_setting: str,
    style_contract: str,
    author_samples: str,
    rolling_prefix: str,
    text: str,
) -> Tuple[str, str]:
    """构建去 AI 味剪枝 prompt（Phase 4.5，每段一次）。

    设计要点：
    - 重构剪枝型（非润色）：破匀速句式 / 删逻辑过渡词 / 心理转物理，但保留叙事密度
    - 角色设定作为 OOC 红线注入 system 层，约束对话重构
    - 文风契约 + 作者样本注入，保证重构后符合作者风格
    - rolling_prefix 保证段间连贯

    Args:
        characters_setting: 角色设定文本（永恒设定 + 此刻状态），OOC 红线依据
        style_contract: 文风契约（来自 _build_style_contract）
        author_samples: 作者样本文本（来自 _build_author_samples）
        rolling_prefix: 前段末尾文本（段间衔接）
        text: 待剪枝的单段正文

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    system_prompt = PRUNE_SYSTEM_TEMPLATE.format(
        characters_setting=characters_setting or "（未提供角色设定，按原文角色语气保持一致）",
        style_contract=style_contract or "（未指定，按通用中文网络小说风格）",
        author_samples=author_samples or "（无样本）",
    )
    user_prompt = PRUNE_USER_TEMPLATE.format(
        rolling_prefix=rolling_prefix or "（本章开篇）",
        text=text,
    )
    return system_prompt, user_prompt


# ============================================================
# Phase 4.5：OOC 安全线裁判 prompt（整章一次 creative）
# ============================================================
#
# 设计意图：
# - 剪枝是"重构"取向，会改对话，存在把角色语气/性格改坏（OOC）的风险。
# - 剪枝后用一个 LLM 裁判检测整章是否发生严重 OOC，若发生则整章回退到未剪枝文本。
# - 复用 review_prompts.py 的"严重 OOC 才报，小幅 OOC 是高光"容忍度原则。
# - 输出 JSON {pass, ooc_issues}，用 structure_checker 的 _extract_json 模式解析。

OOC_CHECK_SYSTEM = """你是严格的小说角色一致性审查员。

你将看到一份小说正文章节和该章节涉及角色的核心设定。你的任务：**判断正文中角色是否出现严重 OOC（人设崩塌）**。

# 判定标准

- **严重 OOC**：角色做出了完全违背其核心设定的事，或说话方式、性格、口癖与设定严重冲突。
  例：设定是"冷酷寡言的杀手"，正文却让他絮絮叨叨解释自己的动机。
- **小幅 OOC 不算问题**：角色偶尔的语气变化、临时情绪波动，甚至有意的反差高光时刻——
  这些可能是剧情需要，**不要标记为 OOC**。只标记"严重人设崩塌"。
- **对话重构可接受**：只要角色的核心性格和说话方式没变，对话被改得更口语/更简短是允许的。

# 输出格式（严格 JSON）

```json
{{
  "pass": true或false,
  "ooc_issues": ["若 pass 为 false，列出每个严重 OOC 问题；pass 为 true 则空数组"]
}}
```

只输出 JSON，不要输出任何其他内容。"""

OOC_CHECK_USER_TEMPLATE = """# 角色核心设定（OOC 判定依据）

{characters_setting}

# 待审查正文（已剪枝）

{pruned_text}

# 任务

判断这段正文中角色是否出现严重 OOC。输出 JSON。"""


def build_ooc_check_prompt(
    characters_setting: str,
    pruned_text: str,
) -> Tuple[str, str]:
    """构建 OOC 安全线裁判 prompt（整章一次）。

    Args:
        characters_setting: 角色设定文本（全部涉及角色）
        pruned_text: 剪枝后的整章正文

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    system_prompt = OOC_CHECK_SYSTEM
    user_prompt = OOC_CHECK_USER_TEMPLATE.format(
        characters_setting=characters_setting or "（未提供角色设定）",
        pruned_text=pruned_text,
    )
    return system_prompt, user_prompt


# ============================================================
# Phase 7: 一致性审计 prompt（CONSISTENCY_GUARD，1 次 reasoning）
# ============================================================
#
# 设计意图：
# - 与 Phase 5 锚点审计分工不同：锚点审计只管结构/情绪/钩子（且头尾采样），
#   一致性审计只管"设定幻觉"四类问题，必须看全文。
# - judge 防幻觉的核心手段是"证据锚定"：每条 issue 必须引用设定原文
#   （canon_evidence），引不出证据就不许报；代码侧再丢弃无证据 issue 双保险。
# - 代码预扫 suspects（专名漂移/未注册人名）逐条交 LLM 确认或驳回，
#   代码不直接自动改（滑窗/jieba 有误报）。

# 一致性审计承认的问题类型（其余类型一律不管，交给已有环节）
CONSISTENCY_ISSUE_TYPES = (
    "name_drift",           # 专名漂移（老赵→老张）
    "knowledge_breach",     # 知识越界（泄露 private 真相/隐藏关系、角色无铺垫知情）
    "setting_conflict",     # 设定冲突（与 Canon public 事实/场景设定矛盾）
    "state_contradiction",  # 状态矛盾（受伤却健步如飞、机甲在内却说在外）
)

CONSISTENCY_AUDIT_SYSTEM = """你是严格的小说设定一致性审校员。

你的任务：对照设定基准（专名表 / Canon / 场景设定 / 知识边界约束），审查小说正文是否存在设定幻觉。你只管以下四类问题，其他问题（文风、节奏、结构）一律不报。

# 四类问题判定标准

1. **name_drift（专名漂移）**：同一角色/地点/物品被指称为专名表以外的名字。
   例：专名表只有"老赵"，正文却写"老张"。注意区分：同一个人物的合法别名不算漂移（别名已在专名表列出）。
2. **knowledge_breach（知识越界）**：正文直接说出、暗示或提及了知识边界约束中禁止的信息；或某角色在毫无铺垫的情况下知道了按设定他不可能知道的事（如初次见面就叫出对方全名）。
3. **setting_conflict（设定冲突）**：正文的描写与 Canon public 已建立事实或场景设定直接矛盾。
4. **state_contradiction（状态矛盾）**：角色/物品的状态前后矛盾。
   例：前文受伤的角色健步如飞；人在机甲内却描写成在机甲外。

# 铁律（违反即审计失败）

- **每条 issue 必须给 canon_evidence**：从专名表 / Canon / 场景设定 / 知识边界约束中引用设定原文作为证据。**引不出证据的问题不许报**——你的判断也会幻觉，证据是唯一锚点。
- 代码预扫 suspects 列表需**逐条确认或驳回**：确认的转为 issue，驳回的列入 rejected_suspects 并简述理由。
- 只报 severity 为 high 或 medium 的问题；拿不准的、影响微小的不报。
- location.paragraph 填正文段标 [Pn] 中的数字 n；location.quote 填问题所在的原文引句（≤50 字，必须逐字摘自正文）。

# 输出格式（严格 JSON）

```json
{
  "issues": [
    {
      "id": "C001",
      "type": "name_drift",
      "severity": "high",
      "location": {"paragraph": 3, "quote": "老张把安全帽往头上一扣"},
      "diagnosis": "工头在第3段被称为「老张」，与专名表冲突",
      "suggestion": "把「老张」改为「老赵」",
      "canon_evidence": "专名表：- 老赵",
      "impact_radius": "local"
    }
  ],
  "rejected_suspects": ["老张：已确认为 name_drift，转入 issues", "..."]
}
```

无问题时返回 {"issues": [], "rejected_suspects": [...]}。只输出 JSON。"""

CONSISTENCY_AUDIT_USER_TEMPLATE = """# 设定基准

## 专名表（合法表记的唯一来源）
{name_registry}

## Canon（作者脑中世界，最高约束）
{canon_context}

## 场景设定（本章角色/地点/资产/关系）
{scene_setting}

## 知识边界约束（正文绝不许越界）
{knowledge_constraints}

# 代码预扫 suspects（需逐条确认或驳回）
{suspects}

# 待审正文（[Pn] 为段号，共 {paragraph_count} 段）

{full_text}

# 要求

返回严格 JSON。每条 issue 必须带 canon_evidence 引用上方设定基准的原文，引不出证据不许报。"""


def build_consistency_audit_prompt(
    name_registry_block: str,
    canon_context: str,
    scene_setting_text: str,
    knowledge_constraints: List[str],
    suspects: List[Dict[str, Any]],
    marked_text: str,
    paragraph_count: int,
) -> Tuple[str, str]:
    """构建一致性审计 prompt（Phase 7，1 次 reasoning）。

    Args:
        name_registry_block: registry_to_prompt_block 的输出（专名表文本）
        canon_context: Canon 全文上下文
        scene_setting_text: 场景设定文本（build_scene_setting_text 输出）
        knowledge_constraints: 知识边界约束行列表
        suspects: scan_name_anomalies 的代码预扫结果
        marked_text: 带 [Pn] 段标的正文（超长时已按头/中/尾采样）
        paragraph_count: 正文总段数（采样时仍传真实总数）

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    if knowledge_constraints:
        constraints_text = "\n".join(f"- {c}" for c in knowledge_constraints)
    else:
        constraints_text = "（无）"

    if suspects:
        suspect_lines = []
        for s in suspects[:20]:  # 上限 20 条，防 prompt 爆炸
            suspect_lines.append(
                f"- [{s.get('type', '?')}] {s.get('detail', str(s))}"
            )
        suspects_text = "\n".join(suspect_lines)
    else:
        suspects_text = "（无代码预扫疑点）"

    user_prompt = CONSISTENCY_AUDIT_USER_TEMPLATE.format(
        name_registry=name_registry_block or "（无注册专名）",
        canon_context=canon_context or "（Canon 为空）",
        scene_setting=scene_setting_text or "（无场景设定）",
        knowledge_constraints=constraints_text,
        suspects=suspects_text,
        full_text=marked_text or "（正文为空）",
        paragraph_count=paragraph_count,
    )
    return CONSISTENCY_AUDIT_SYSTEM, user_prompt


def _extract_audit_json(content: str) -> Optional[dict]:
    """从 LLM 输出提取 JSON 对象（复用 structure_checker 的 _extract_json 模式）。

    注意：不能 import structure_checker._extract_json——structure_checker
    import 本模块，反向 import 会成环。此处是同模式的独立拷贝。
    """
    if not content:
        return None
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass
    brace_match = re.search(r"\{.*\}", content, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def parse_consistency_audit_response(content: str) -> List[Dict[str, Any]]:
    """解析一致性审计响应，返回过滤后的 issue 列表。

    过滤规则（judge 防幻觉的代码侧双保险）：
    - 缺 canon_evidence 的 issue 直接丢弃（无证据不允许报）
    - 缺 location.quote 的 issue 直接丢弃（无法定位原文，手术无从下刀）
    - 只保留 type 属于 CONSISTENCY_ISSUE_TYPES 的 issue

    Args:
        content: LLM 原始输出（可带 markdown 围栏）

    Returns:
        issue dict 列表（每项保证含 id/type/severity/location/canon_evidence）；
        解析失败时返回空列表（调用方按"无问题"降级处理）
    """
    data = _extract_audit_json(content)
    if not data:
        return []
    raw_issues = data.get("issues")
    if not isinstance(raw_issues, list):
        return []

    issues: List[Dict[str, Any]] = []
    for i, raw in enumerate(raw_issues):
        if not isinstance(raw, dict):
            continue
        if raw.get("type") not in CONSISTENCY_ISSUE_TYPES:
            continue
        canon_evidence = (raw.get("canon_evidence") or "").strip()
        if not canon_evidence:
            continue
        location = raw.get("location")
        if not isinstance(location, dict) or not (location.get("quote") or "").strip():
            continue
        issues.append({
            "id": raw.get("id") or f"C{i + 1:03d}",
            "type": raw["type"],
            "severity": raw.get("severity") or "medium",
            "location": location,
            "diagnosis": raw.get("diagnosis") or "",
            "suggestion": raw.get("suggestion") or "",
            "canon_evidence": canon_evidence,
            "impact_radius": raw.get("impact_radius") or "local",
        })
    return issues


# ============================================================
# Phase 6.5: 缺失节拍补写 prompt（BEAT_PATCH，每个节拍 1 次 creative）
# ============================================================
#
# 设计意图：
# - 与 Phase 6 条件补埋（refiner，内嵌式补关键词）分工不同：
#   补埋治"关键词级"缺失，本补写治"整场戏缺失"（大纲节拍被跳过）。
# - 定点插入而非整章重写：缺口是局部的过渡段，重写引入新风险且贵。
# - 锚点前后段原文都给 LLM，让补写内容无缝衔接（插入位置 before/after
#   由审计 LLM 的 insert_position 决定）。

BEAT_PATCH_SYSTEM = """你是顶级的中文长篇小说作家。

你的任务：补写一段**缺失的剧情节拍**。编辑审计发现正文漏掉了大纲中的一个节拍，你负责只写这一段过渡内容，无缝衔接前后文。

# 硬性要求

1. 你只写缺失的这一段过渡内容（150~400 字），**不要重写前后已有内容**，不要从章节开头写起。
2. 内容必须与给定的大纲节拍严格对应，写完即停，不要顺势写下文。
3. 开头自然承接【锚点前段】的结尾，结尾自然引向【锚点后段】的开头（若标注"本章结尾"则自然收束）。
4. 只输出小说正文：不要段标题、不要 markdown 标记、不要解释。

# 文风契约

{style_contract}"""

BEAT_PATCH_USER_TEMPLATE = """# 缺失的大纲节拍（必须在补写中完整写到）

{beat}

# 章节主旨

{purpose}

# 锚点前段原文（你的补写接在它后面）

{anchor_before}

# 锚点后段原文（你的补写引向它）

{anchor_after}

{name_registry_block}

# 要求

只输出补写正文（150~400 字）。"""


def build_beat_patch_prompt(
    beat: str,
    purpose: str,
    anchor_before: str,
    anchor_after: str,
    insert_position: str,
    style_contract: str,
    name_registry_block: str,
) -> Tuple[str, str]:
    """构建缺失节拍补写 prompt（Phase 6.5，每个缺失节拍一次）。

    Args:
        beat: 缺失的大纲节拍原文
        purpose: 章节主旨
        anchor_before / anchor_after: 锚点前后段原文（供衔接）
        insert_position: before | after（补写相对锚点的插入位置，
            仅影响语义说明，文本由调用方已按位置选好前后段）
        style_contract: 文风契约（注入 system 层）
        name_registry_block: 专名表硬约束（可为空串，空则不出现该区块）

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    system_prompt = BEAT_PATCH_SYSTEM.format(
        style_contract=style_contract or "（未指定，按通用中文文学小说风格）",
    )
    user_prompt = BEAT_PATCH_USER_TEMPLATE.format(
        beat=beat or "（未指定）",
        purpose=purpose or "（未指定）",
        anchor_before=anchor_before or "（本章开头）",
        anchor_after=anchor_after or "（本章结尾）",
        name_registry_block=name_registry_block or "",
    )
    return system_prompt, user_prompt


# ============================================================
# Agent Loop 1: 段级状态卡抽取 prompt（每段 1 次小 creative）
# ============================================================
#
# 设计意图：
# - 只抽取"事实状态"，不评价文风、不创作——抽取器是记录员不是编辑
# - 角色名强制从注册表清单选（防 LLM 发明新名字污染下游校验）
# - 自纠正：每次输出"更新后的完整新卡"，不做增量合并（错误不沿链累积）
# - 拿不准留空、严禁编造——空字段比错字段安全（空字段不参与校验）

STATE_EXTRACTION_SYSTEM = """你是剧情状态记录员。你的唯一任务：根据"截至上一段的状态卡"和"刚写完的新一段正文"，输出更新后的完整剧情状态卡。

# 铁律

1. 只抽取事实状态（谁在场/谁死亡或离场/各角色一句话状态/关键物品归属/剧情进展/POV/地点），不评价文风，不创作任何内容。
2. 角色名**只能**从给定清单中选择，绝不许使用清单外的名字。
3. 拿不准的字段留空（空串或空列表），**严禁编造**——空比错安全。
4. 输出是"更新后的完整新卡"（不是增量）：新段没改变的字段从旧卡原样保留。
5. departed（死亡/离场）一旦加入，除非新段明确复活/回归，否则保留。
6. 只输出严格 JSON，不要输出任何其他内容。

# 输出 schema

```json
{
  "pov": "视角角色名",
  "location": "当前地点",
  "present": ["在场角色名"],
  "departed": ["已死亡或离场角色名"],
  "states": {"角色名": "一句话状态（伤势/情绪/位置）"},
  "items": {"关键物品": "持有者或位置"},
  "progress": "剧情进展一句话"
}
```"""

STATE_EXTRACTION_USER_TEMPLATE = """# 截至上一段的状态卡

{prev_card_text}

# 刚写完的新一段正文

{segment_text}

# 已知角色清单（角色名只能从这里选）

{known_characters}

# 要求

输出更新后的完整状态卡（严格 JSON）。"""


def build_state_extraction_prompt(
    prev_card_text: str,
    segment_text: str,
    known_characters: str,
) -> Tuple[str, str]:
    """构建状态卡抽取 prompt（每段定稿后一次）。

    Args:
        prev_card_text: 上一张卡的渲染文本（card_to_prompt_block 输出）
        segment_text: 刚写完的本段正文
        known_characters: 已知角色名清单（顿号连接）

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    user_prompt = STATE_EXTRACTION_USER_TEMPLATE.format(
        prev_card_text=prev_card_text or "（首张卡，无历史状态）",
        segment_text=segment_text or "（空段）",
        known_characters=known_characters or "（无角色清单）",
    )
    return STATE_EXTRACTION_SYSTEM, user_prompt


# ============================================================
# Agent Loop 2: 手术编辑复验 prompt（Phase 7 第 6 步，0~1 次 reasoning）
# ============================================================
#
# 设计意图：
# - "修完不复验"是既有缺口：定点手术可能修对目标却引入新问题
#  （设定矛盾/剧情重复/逻辑断裂/文风崩坏）。
# - 复验方向保守：只报"改动新引入"的问题；无 problems 描述的 not-ok
#   在解析侧视为 ok（防复验 LLM 自己幻觉误杀好修复——回滚代价是少修
#   一处，可接受；误杀代价是好修复被丢，不可接受）。

EDIT_VERIFY_SYSTEM = """你是严格的小说编辑复验员。

刚有一批"定点手术"修改了章节正文（每个手术给出改动前原文、改动后文本、前后邻段）。你的任务：逐个判断**改动是否引入了新问题**。

# 只报改动新引入的问题（原文本来就有的问题不算）：

1. 设定矛盾：改动后与邻段或上下文设定冲突
2. 剧情重复：改动后与邻段内容高度重复（同一场景写两遍）
3. 逻辑断裂：改动后与前后文衔接不上（话题突变、指代不明）
4. 文风崩坏：改动后的文字明显不如原文（机械腔、语无伦次）

# 判定原则

- 改动解决问题且没引入新问题 → ok=true
- 拿不准 → ok=true（保守方向：宁可放过，不误杀好修复）
- ok=false **必须**在 problems 里写清引入了什么新问题

# 输出格式（严格 JSON）

```json
{"verdicts": [{"operation_id": "OP001", "ok": true, "problems": ""}]}
```

只输出 JSON。"""

EDIT_VERIFY_USER_TEMPLATE = """# 待复验的手术改动（共 {edit_count} 个）

{edits_text}

# 要求

逐个给出 verdict（严格 JSON）。"""


def build_edit_verify_prompt(
    edits_with_neighbors: List[Dict[str, Any]],
) -> Tuple[str, str]:
    """构建编辑复验 prompt（Phase 7 第 6 步，全部手术一次复验）。

    Args:
        edits_with_neighbors: 每个手术 {
            operation_id, original_text, revised_text,
            prev_neighbor, next_neighbor,
        }

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    blocks = []
    for edit in edits_with_neighbors:
        blocks.append(
            f"## 手术 {edit.get('operation_id', 'OP?')}\n"
            f"[改动前原文]\n{edit.get('original_text', '')}\n\n"
            f"[改动后]\n{edit.get('revised_text', '')}\n\n"
            f"[前邻段]\n{edit.get('prev_neighbor', '') or '（章首）'}\n\n"
            f"[后邻段]\n{edit.get('next_neighbor', '') or '（章尾）'}"
        )
    user_prompt = EDIT_VERIFY_USER_TEMPLATE.format(
        edit_count=len(edits_with_neighbors),
        edits_text="\n\n".join(blocks) or "（无手术）",
    )
    return EDIT_VERIFY_SYSTEM, user_prompt


def parse_edit_verify_response(content: str) -> Dict[str, bool]:
    """解析编辑复验响应，返回 {operation_id: ok}。

    防复验幻觉规则：verdicts 缺 problems 或 problems 为空的 not-ok → 视为 ok
    （回滚方向保守：误杀好修复的代价 > 少回滚一处坏修复）。
    解析失败返回空 dict（调用方视为全部 ok，不回滚）。
    """
    data = _extract_audit_json(content)
    if not data:
        return {}
    raw_verdicts = data.get("verdicts")
    if not isinstance(raw_verdicts, list):
        return {}
    verdicts: Dict[str, bool] = {}
    for item in raw_verdicts:
        if not isinstance(item, dict):
            continue
        op_id = item.get("operation_id")
        if not op_id:
            continue
        ok = bool(item.get("ok", True))
        problems = (item.get("problems") or "").strip()
        if not ok and not problems:
            ok = True  # 无问题描述的 not-ok 视为 ok（防幻觉误杀）
        verdicts[str(op_id)] = ok
    return verdicts
