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

设计意图：
- 正向流写作的核心是"软提示"——告诉 LLM 建议下段埋什么，但不强制怎么写
- 情绪曲线进度条作为连续约束（替代 V3.1 整数 distance_to_climax）
- 远端锚作为"牵引"而非"路径"：高潮描述每段都注入，但不强制"现在必须写什么"

业务场景：
- workflows/adf/climax_designer.py      → build_anchor_design_prompt
- workflows/adf/segment_writer.py       → build_forward_flow_prompt
- workflows/adf/structure_checker.py    → build_anchor_audit_prompt
- workflows/adf/refiner.py              → build_refine_prompt

使用方式：
    system, user = build_forward_flow_prompt(...)
    result = await call_llm_with_usage(system_prompt=system, user_prompt=user, ...)

依赖项：
- 无（纯模板）
"""

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

约 {target_words} 字（上限 {target_words} 字，不许超出——超出会被截断导致正文不完整）。

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
) -> Tuple[str, str]:
    """构建正向流写作 prompt（Phase 4，每段一次）。

    设计要点：
    - climax_anchor + emotion_curve 进 system 层（每段固定，吃 prompt 缓存）
    - rolling_prefix + 软提示进 user 层（每段变化）
    - 软提示是"建议"而非"必须"——让 LLM 自主决定如何自然融入

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
  "refinement_targets": ["PC_REAL_POWER"]
}
```

判定规则：
- 任何 missing_preconditions 非空 → needs_refinement
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
) -> Tuple[str, str]:
    """构建锚点审计 prompt（Phase 5）。

    Args:
        见 ANCHOR_AUDIT_USER_TEMPLATE 占位符
        full_text: 完整正文（截断到 6000 字）

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    hooks_text = ", ".join(must_plant_hooks) if must_plant_hooks else "（无）"
    resolve_text = ", ".join(must_resolve_hooks) if must_resolve_hooks else "（无）"
    arc_text = "; ".join(f"{k}→{v}" for k, v in character_arc_advances.items()) if character_arc_advances else "（无）"

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

1. **匀速句式 → 长短交错**。
   AI 生成的段落常像节拍器——每句长度接近、结构对称。你必须在段落里制造陡峭的顿挫感：
   - 把超过 12-15 字的长句切断成短句，用句号收束。
   - 允许连续出现 2-4 字的极短句（"他没动。""血。""冷。"），紧接着一个含多个动词的短连句。
   - 长句铺陈细节，短句制造冲击与停顿。长短交错，不要匀速。

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

重构这段，按上面的"去 AI 腔"规则制造长短交错的陡峭节奏、删逻辑过渡词、剥套路比喻、心理转物理。
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
