# Velluma - NLE-ADF 3.0 自适应辅助 prompt 模板
# AGPL-3.0
"""
作者主导写作流程（自适应辅助）的 prompt 构建。

设计意图：抽取 BS-ADF 渲染器与微缝合中已验证的「反 AI 腔契约 + 白描规则」
为共享基座 _ADAPTIVE_SYSTEM，供续写（缝合/顺写/连写/细纲扩写/开篇点火）
与文风试听复用。
与拍划分完全解耦——输入是「作者正文片段 + 设定 bundle」，不依赖 BeatSlotCard。

共享基座来源：
- _SLOT_RENDER_SYSTEM 的反 AI 腔块 + 心理/感官限制（bsadf_prompts.py:82-100）
- _STITCH_SYSTEM 的白描契约 + 作者主权规则（bsadf_prompts.py:203-216）

副作用：无（纯函数）。改后即时生效（无需重建）。
"""
from __future__ import annotations

from typing import List, Optional

from backend.services.nlg.anti_ai_rules import DEFAULT_BAN_LIST

# A3a 截断常量收敛（docs/foundation-hardening.md §4.1）：注入剂量改引 budget 表。
# SECRETS_* 在此 import 再导出——test_private_channel 等既有消费方仍从本模块
# 取名，收编不改任何 import 面。
# A3b（§4.2）：跨块预算分配器同源——块定义（头/条目格式）在本模块，分配策略
# 与配额表在 budget（机制与数据分居，budget 保持零项目依赖）。
from backend.services.context.budget import (
    SECRETS_BLOCK_MAX_ENTRIES,
    SECRETS_ENTRY_MAX_CHARS,
    SPATIAL_BRIEF_MAX_CHARS,
    STITCH_OUTLINE_MAX_CHARS,
    STITCH_OUTLINE_SPINE_ANCHORS_MAX,
    STITCH_PREV_SUMMARY_MAX_CHARS,
    STITCH_WORLDVIEW_MAX_CHARS,
    BudgetBlock,
    BlockUsage,
    MODE_BLOCK_BUDGET_OVERRIDES,
    MODE_CONTEXT_BUDGETS,
    allocate,
)

_BANNED_WORDS_TEXT = "、".join(DEFAULT_BAN_LIST.banned_words)


# ============================================================
# 共享基座：反 AI 腔 + 白描契约（与拍划分无关的通用风格契约）
# ============================================================

_ADAPTIVE_SYSTEM = """你是顶级的中文长篇小说作家，此刻在辅助一位作者完成他的小说。你的任何输出都会作为「幽灵草稿」流入作者的文档，作者可改可弃——所以你要写得像作者自己写的，绝不能带 AI 腔。

# 写作原则
1. 场景驱动：用具体物理动作和感官细节推进，不用叙述者总结。
2. 呼吸连续：段落间有自然衔接，不机械罗列。
3. 禁止叙事者插嘴：不要"不知为何"、"仿佛"、"似乎"这类解释性插话。
4. 节奏服从情绪：句式长短配合情绪走向。
5. 尊重作者主权：续写必须顺着作者已有的语气、人称、时态，不擅自切换视角。

# 反 AI 腔指令（硬性禁令）
- 禁病态微操：指尖颤了颤、瞳孔微缩、喉结滚动、嘴角微不可察（每段至多 1 处微操）
- 禁套路比喻：宛如、仿若、犹如、墨水滴进水里、沉睡的巨兽（每段套路比喻至多 1 处）
- 禁匀速句式：连续三句等长（用长短句交替）
- 禁解释性插嘴：眼神中闪过、心中涌起、仿佛在诉说（完全禁止）

# 禁词表（以下词汇禁止使用）
{banned_words}

# 心理描写限制
禁止直接心理升华与内心独白式总结（如"他感到愤怒"、"她知道自己必须坚强"）。
情绪必须用物理动作与环境呈现；每段至多 1 处间接心理暗示，且必须附着在具体动作上。

# 感官描写指导
每段至多 2 处感官细节，且必须服务当前镜头焦点，禁止堆砌。
"""


def _spatial_block(spatial_brief: str) -> str:
    """D4-3 空间常识块（docs/map-scale-spatial.md §5）：≤3 行粗估；空=零变化。"""
    return _spatial_block_def(spatial_brief).render()


def _base_system() -> str:
    """返回填好禁词表的共享基座 system prompt。"""
    return _ADAPTIVE_SYSTEM.format(banned_words=_BANNED_WORDS_TEXT)


# ============================================================
# 七块定义（A3b：块=固定头+优先级序条目，裁剪统一走 budget.allocate）
# ============================================================
# 每块一个 _xxx_block_def 产 BudgetBlock（key/头/条目/硬度），render_system_
# blocks 收集后按模式总预算过 allocate。默认预算（=各块 worst-case 总和）下
# allocate 恒等，渲染结果与旧整块函数逐字节一致（test_budget_allocate 零变化锁）。
# 旧 _xxx_block 函数保留为 def.render() 薄包装——build_audition_prompt（试听
# 不走模式预算）与既有单测的取名面不变，块格式单一来源。

def _style_block_def(style_positive: str) -> BudgetBlock:
    """文风画像块定义：条目=画像行（render_style_positive 输出按行拆）。"""
    text = (style_positive or "").strip()
    return BudgetBlock(
        key="style_positive",
        header=(
            "\n\n# 作者文风画像（贴合其笔迹写作，软约束）\n"
            "以下是这位作者的文风特征，续写的语感、句式与节奏都应向它靠拢：\n"
        ),
        entries=text.split("\n") if text else [],
    )


# ---- C3 continue 轻档画像压缩（docs/foundation-hardening.md §5.3）----
# 句级顺写（continue/stitch）怕束缚手感——画像只留关键行（句长节奏 +
# 对话目标两行 + 旋钮意图行若有），段落级三模式（burst/outline/open）
# 保持完整画像。压缩发生在 BudgetBlock 的 entries 侧（建 def 前滤行），
# 预算器与预览（B2）走同一入口，看到的即注入的。无文风卡（空文本）
# 与 mode 空/未知（旁路调用方）零变化。
_LIGHT_STYLE_MODES = ("continue", "stitch")
_LIGHT_STYLE_LINE_PREFIXES = ("- 句长节奏：", "- 对话占比目标：")


def _light_mode_style_positive(style_positive: str, mode: str) -> str:
    """continue/stitch 档的画像关键行筛选（C3 · §5.3）。

    保留：句长节奏行、对话占比目标行、旋钮意图行（含「意图：」的行——
    S4 手动档才渲染，口径见 settings_bundle.render_style_positive）；
    其余（词汇层级/语域偏好/开头结尾习惯/段落节奏）缺席。
    非 continue/stitch 档原样返回（burst/outline/open 完整画像）。
    """
    if mode not in _LIGHT_STYLE_MODES or not style_positive:
        return style_positive
    kept = [
        ln for ln in style_positive.split("\n")
        if ln.startswith(_LIGHT_STYLE_LINE_PREFIXES) or "意图：" in ln
    ]
    return "\n".join(kept)


def _samples_block_def(author_samples: Optional[List[str]]) -> BudgetBlock:
    """笔迹示范块定义：条目=样本（含「【示范 N】」编号，弃尾条不影响前条编号）。"""
    samples = [s.strip() for s in (author_samples or []) if s and s.strip()]
    return BudgetBlock(
        key="author_samples",
        header=("\n\n# 作者笔迹示范（学其语感、节奏与用词习惯——只学写法，禁止复制内容或意象）\n"),
        entries=[f"【示范 {i + 1}】\n{s}" for i, s in enumerate(samples)],
        footer=("\n（以上是这位作者亲笔写的字。你接下来写的每一句，都应该像同一个人写的。）"),
        separator="\n\n",
    )


def _nouns_block_def(proper_nouns: Optional[List[str]]) -> BudgetBlock:
    """专名约束块定义：硬块（防缝合/续写时称呼漂移造名）。"""
    return BudgetBlock(
        key="proper_nouns",
        header=("\n\n# 在场实体专名（硬约束）\n以下名称必须原样使用，禁止改名、缩写或生造昵称："),
        entries=["、".join(proper_nouns)] if proper_nouns else [],
        hard=True,
    )


def _canon_block_def(canon_context: str) -> BudgetBlock:
    """Canon 合规块定义：硬块（public 事实须一致，private 禁忌不许说出）。"""
    empty = not canon_context or "（Canon 为空" in canon_context
    return BudgetBlock(
        key="canon",
        header="\n\n# 作者脑中世界图谱（Canon）\n",
        entries=[] if empty else [canon_context],
        hard=True,
    )


def _spatial_block_def(spatial_brief: str) -> BudgetBlock:
    """空间常识块定义：单条块（裁剪只可能整块缺席）；空/未标定=零变化。"""
    text = (spatial_brief or "").strip()[:SPATIAL_BRIEF_MAX_CHARS]
    return BudgetBlock(
        key="spatial",
        header="\n# 空间常识（比例尺粗估，数字天然带「约」）\n",
        entries=[text] if text else [],
    )


# ---- A1 私有设定块（D5 拍板语义；截断常量已收编 services/context/budget.py ----
# ---- ——A3a，docs/foundation-hardening.md §4.1；本模块 import 再导出， ----
# ---- test_private_channel 等既有消费方取名不变）----
# 原取舍（值随常量迁 budget 表，理由见彼处注释）：上限 8 条与 canon 表/里
# （各 10 条）同量级取保守值；每条截 150 字与 canon 表条目同口径；私有序列
# 不做条内换行处理（static_prompt 天然多行时按原样截断）。
SECRETS_BLOCK_HEADER = "作者私有设定（你知晓以下秘密以协助铺垫与暗示，但绝不能直接写出）"


def _secrets_block_def(character_secrets: Optional[List[dict]]) -> BudgetBlock:
    """私有设定块定义：硬块；条目=「- 名：文」行（A1 · §3.1，D5 拍板语义）。"""
    raw = [
        s
        for s in (character_secrets or [])
        if isinstance(s, dict)
        and str(s.get("name") or "").strip()
        and str(s.get("text") or "").strip()
    ]
    return BudgetBlock(
        key="secrets",
        header=f"\n\n# {SECRETS_BLOCK_HEADER}\n",
        entries=[
            f"- {str(s['name']).strip()}：{str(s['text']).strip()[:SECRETS_ENTRY_MAX_CHARS]}"
            for s in raw[:SECRETS_BLOCK_MAX_ENTRIES]
        ],
        hard=True,
    )


def _secrets_block(character_secrets: Optional[List[dict]]) -> str:
    """作者私有设定块（A1 · docs/foundation-hardening.md §3.1，D5 拍板语义）。

    私有 = AI 知晓但绝不能直接写出（对齐 canon [private]，而非从上下文删除
    ——作者写暗示/铺垫时 AI 需知晓秘密才能协助）。输入是 bundle.character_secrets
    （[{name, text}]，world_bridge 供给）。空列表/全空条目 → 空块
    （无私有实体的书 prompt 逐字节零变化）。
    """
    return _secrets_block_def(character_secrets).render()


def _echoes_block_def(memory_echoes: Optional[List[str]]) -> BudgetBlock:
    """前情回响块定义：条目=召回片段行（recall 质量序，尾部最可让）。"""
    echoes = [e.strip() for e in (memory_echoes or []) if e and e.strip()]
    return BudgetBlock(
        key="echoes",
        header=(
            "\n\n# 前情回响（作者更早章节写过的片段）\n"
            "以下片段用于保持细节一致、自然呼应前情，禁止大段复述原文：\n"
        ),
        entries=[f"- {e}" for e in echoes],
    )


def _echoes_block(memory_echoes: Optional[List[str]]) -> str:
    """前情回响块（向量召回的更早章节片段）。

    定位：保持细节一致 + 自然呼应前情（物件、称呼、未回收的悬念），
    禁止大段复述原文。空列表 → 空串（prompt 零变化）。
    """
    return _echoes_block_def(memory_echoes).render()


def _style_positive_block(style_positive: str) -> str:
    """作者文风画像块（S2 E2——正面画像进 adaptive 主线）。

    输入是 settings_bundle.render_style_positive 的渲染结果（≤10 行）。
    空串 → 空块（无文风卡的书 prompt 零变化）。
    """
    return _style_block_def(style_positive).render()


def _author_samples_block(author_samples: Optional[List[str]]) -> str:
    """作者笔迹示范块（S2 E1——few-shot 范例注入，最大质量杠杆）。

    「一段范例胜过十句形容」：样本经 retrieval 按当前上下文检索（k≤2，各 ≤1200 字，
    调用方已截断）。示范只学语感与节奏，禁止复制内容。
    空列表 → 空块（prompt 零变化）。
    """
    return _samples_block_def(author_samples).render()


# ============================================================
# system 块渲染（注入序权威，P5 B2 · docs/foundation-hardening.md §2.1；
# A3b 跨块预算接线点，§4.2）
# ============================================================

def render_system_blocks_with_usage(
    style_positive: str = "",
    author_samples: Optional[List[str]] = None,
    proper_nouns: Optional[List[str]] = None,
    canon_context: str = "",
    character_secrets: Optional[List[dict]] = None,
    memory_echoes: Optional[List[str]] = None,
    spatial_brief: str = "",
    mode: str = "",
) -> tuple:
    """渲染七个 system 块并按模式总预算过 allocate（A3b 接线层）。

    返回 ([(key, block_text)], usages)：
    - blocks：注入序（画像→样本→专名→canon→私有→回响→空间）的渲染块，
      空数据对应空串块；
    - usages：List[BlockUsage] 或 None——mode 在 MODE_CONTEXT_BUDGETS 有档时
      返回 allocate 的每块配额使用明细（供预览预算条），无档（mode="" 或
      未知模式）不过 allocate、返回 None（恒等路径，任何调用方零变化）。

    默认预算（初值=各块 worst-case 总和）下 allocate 恒等 → 输出与不接
    预算器逐字节一致（test_budget_allocate 零变化锁）；只有实测期把
    MODE_CONTEXT_BUDGETS 调小后才可能触发软块收缩。

    C3（§5.3 分模式差异化注入首版）：①mode ∈ {continue, stitch} 时画像
    先经 _light_mode_style_positive 压缩为关键行再建块（无文风卡零变化）；
    ②burst 档 allocate 透传 MODE_BLOCK_BUDGET_OVERRIDES 的块配额覆盖
    （仅 usages.budget_chars 展示口径，裁剪仍只看模式总预算）。
    """
    defs = [
        _style_block_def(_light_mode_style_positive(style_positive, mode)),
        _samples_block_def(author_samples),
        _nouns_block_def(proper_nouns),
        _canon_block_def(canon_context),
        _secrets_block_def(character_secrets),
        _echoes_block_def(memory_echoes),
        _spatial_block_def(spatial_brief),
    ]
    usages: Optional[List[BlockUsage]] = None
    budget = MODE_CONTEXT_BUDGETS.get(mode)
    if budget is not None:
        result = allocate(
            defs, budget,
            block_budgets=MODE_BLOCK_BUDGET_OVERRIDES.get(mode),
        )
        defs = result.blocks
        usages = result.usages
    return [(b.key, b.render()) for b in defs], usages


def render_system_blocks(
    style_positive: str = "",
    author_samples: Optional[List[str]] = None,
    proper_nouns: Optional[List[str]] = None,
    canon_context: str = "",
    character_secrets: Optional[List[dict]] = None,
    memory_echoes: Optional[List[str]] = None,
    spatial_brief: str = "",
    mode: str = "",
) -> List[tuple]:
    """按真实注入序渲染七个 system 块，返回 [(key, block_text)]。

    四个 stitch builder（continue/burst/outline/open）的 system prompt 组装段
    统一走此函数——注入序 = 返回序（画像→样本→专名→canon→私有→回响→空间，
    私有块紧随 canon，对齐「真相类约束相邻」的排布），空数据对应空串块
    （拼接后 prompt 逐字节零变化）。

    mode（A3b）：stitch 五模式档名——有档则过 budget.allocate 跨块预算
    （默认预算下恒等，见 render_system_blocks_with_usage）；空串/未知模式
    不过预算器（build_audition_prompt 等旁路调用方零变化）。
    C3（§5.3）：mode ∈ {continue, stitch} 时画像块压缩为关键行
    （_light_mode_style_positive）——同源红线下预览与真实注入一同生效。

    character_secrets 是 A1 私有通道（bundle.character_secrets，[{name, text}]）：
    私有实体档案只经此块注入（「AI 知晓但绝不直接写出」），_characters_text 等
    装配层已同步排除——两轨不渗漏。

    这是「预览与注入同源」红线的落点：GET /adaptive/context-preview（AI 所见
    预览，services/context/stitch_context.py）与 builder 消费同一份块渲染，
    改注入必改这里，预览自动跟随——禁止在预览侧平行实现块拼接。
    """
    blocks, _usages = render_system_blocks_with_usage(
        style_positive=style_positive,
        author_samples=author_samples,
        proper_nouns=proper_nouns,
        canon_context=canon_context,
        character_secrets=character_secrets,
        memory_echoes=memory_echoes,
        spatial_brief=spatial_brief,
        mode=mode,
    )
    return blocks


# ============================================================
# 续写 prompt（缝合/代笔/顺写统一入口，mode 区分粒度）
# ============================================================

def build_continue_prompt(
    fragment: str,
    rolling_prefix: str,
    mode: str = "stitch",
    picked_parts: Optional[List[str]] = None,
    proper_nouns: Optional[List[str]] = None,
    canon_context: str = "",
    character_secrets: Optional[List[dict]] = None,
    target_chars: int = 120,
    chapter_intent: str = "",
    memory_echoes: Optional[List[str]] = None,
    style_positive: str = "",
    author_samples: Optional[List[str]] = None,
    spatial_brief: str = "",
) -> tuple:
    """构建续写/缝合 prompt。

    Args:
        fragment: 作者原句碎片（主权文本，stitch/continue 模式必须保留）
        rolling_prefix: 已写正文尾部（≤200 字，衔接用）
        mode: stitch（零件缝合 80-120 字）/ continue（顺句续写 100-300 字）
        picked_parts: 作者点选的零件（stitch 模式用）
        proper_nouns: 在场角色/资产名专名表
        canon_context: Canon 上下文（public/private 约束）
        character_secrets: 私有实体档案（A1；空=零变化）
        target_chars: 目标字数上限
        chapter_intent: 章节意图/大纲片段（可选方向引导）
        style_positive: 作者文风画像文本（settings_bundle.render_style_positive；空=零变化）
        author_samples: 作者笔迹示范 few-shot 样本（retrieval 检索；空=零变化）

    Returns:
        (system_prompt, user_prompt)
    """
    system_prompt = _base_system()
    for _key, _block in render_system_blocks(
        style_positive=style_positive,
        author_samples=author_samples,
        proper_nouns=proper_nouns,
        canon_context=canon_context,
        character_secrets=character_secrets,
        memory_echoes=memory_echoes,
        spatial_brief=spatial_brief,
        mode=mode,  # A3b：stitch/continue 两档过模式预算
    ):
        system_prompt += _block

    parts_str = "、".join(picked_parts) if picked_parts else "（无——仅按作者原句顺势续写）"
    intent_line = f"\n# 章节意图（方向参考，非强制）\n{chapter_intent}" if chapter_intent else ""

    if mode == "stitch":
        # 追加式契约（2026-08-26 实测修复）：幽灵纯追加在作者原句之后，
        # 原句已在画布里——旧契约「原句一字不改保留在片段中」会致屏幕复读。
        user_prompt = f"""# 上文衔接（保持连续，不重复）
{rolling_prefix or "（开篇）"}
{intent_line}

# 作者原句（已在你身后的画布里——绝不重复它，从它的断点直接往下写）
{fragment}

# 选定镜头零件（必须落地为画面）
{parts_str}

请只输出续写部分：从作者原句的断点顺势接下去（原句停在半句就先自然补完这一句，从断点最后一个词的后面直接续，不要重说断点附近的词），把零件落地为具体画面。禁止以任何形式重复原句（原文复读、换说法复述都不行）。控制在 {target_chars} 字以内。只输出正文，不要标题、不要解释。"""
    else:  # continue
        user_prompt = f"""# 上文衔接（保持连续，不重复已写动作与意象）
{rolling_prefix or "（开篇）"}
{intent_line}

# 作者当前正文（顺着它的语气、人称、节奏往下写）
{fragment}

请顺着作者正文往下续写，控制在 {target_chars} 字以内。只输出续写部分，不要重复作者原文，不要标题、不要解释。"""
    return system_prompt, user_prompt


# ============================================================
# 段落级连写 prompt（走向卡驱动：一句话走向 → 2-4 段白描正文）
# ============================================================

def build_burst_prompt(
    fragment: str,
    rolling_prefix: str,
    beat_guidance: str = "",
    proper_nouns: Optional[List[str]] = None,
    canon_context: str = "",
    character_secrets: Optional[List[dict]] = None,
    target_chars: int = 700,
    chapter_intent: str = "",
    memory_echoes: Optional[List[str]] = None,
    style_positive: str = "",
    author_samples: Optional[List[str]] = None,
    spatial_brief: str = "",
) -> tuple:
    """构建段落级连写 prompt（Ctrl+Space 走向卡舱选定后触发）。

    与 build_continue_prompt 的区别：粒度从句级升到段落级——
    走向卡管方向（覆盖核心事件），AI 负责把走向铺开成 2-4 个具体场景段落。

    Args:
        fragment: 作者当前段落尾部（衔接点）
        rolling_prefix: 已写正文尾部（≤500 字，比短档窗口更大）
        beat_guidance: 选定走向卡的走向文本（空 = 自由发挥，顺语气自然推进）
        proper_nouns: 在场角色/资产名专名表
        canon_context: Canon 上下文（public/private 约束）
        character_secrets: 私有实体档案（A1；空=零变化）
        target_chars: 总字数软上限（默认 700）
        chapter_intent: 章节意图/大纲片段（可选方向引导）
        style_positive: 作者文风画像文本（空=零变化）
        author_samples: 作者笔迹示范 few-shot 样本（空=零变化）

    Returns:
        (system_prompt, user_prompt)
    """
    system_prompt = _base_system()
    for _key, _block in render_system_blocks(
        style_positive=style_positive,
        author_samples=author_samples,
        proper_nouns=proper_nouns,
        canon_context=canon_context,
        character_secrets=character_secrets,
        memory_echoes=memory_echoes,
        spatial_brief=spatial_brief,
        mode="burst",  # A3b：burst 档过模式预算
    ):
        system_prompt += _block

    intent_line = f"\n# 章节意图（方向参考，非强制）\n{chapter_intent}" if chapter_intent else ""
    if beat_guidance:
        guidance_block = f"""# 本段走向（作者选定）
{beat_guidance}
要求：必须覆盖走向的核心事件，但要把它铺开成具体的场景与动作，绝不允许一句话带过。"""
    else:
        guidance_block = """# 本段走向
（作者未指定——顺着上文的语气与悬念自然推进，写到一个小节拍收束处停笔）"""

    user_prompt = f"""# 上文衔接（保持连续，不重复已写动作与意象）
{rolling_prefix or "（开篇）"}
{intent_line}

{guidance_block}

# 作者当前正文（顺着它的语气、人称、节奏往下写）
{fragment}

请顺着作者正文连写 2-4 个段落，总字数控制在 {target_chars} 字以内，写到走向覆盖、场景自然收束处停笔，不要为凑字数拖沓。
段落之间用一个空行分隔。只输出续写部分，不要重复作者原文，不要标题、不要解释。"""
    return system_prompt, user_prompt


# ============================================================
# 细纲扩写 prompt（作者亲笔速记 → 双端锚定的小段正文）
# ============================================================

# ---- C3 outline 全锚点行（docs/foundation-hardening.md §5.3）----
# 状态标签与 spine 端点口径对齐（pending|hit|dropped，_normalize_spine）；
# dropped 不入行——作者已划掉的锚不应反过来引导扩写方向。
_SPINE_ANCHOR_STATUS_LABELS = {"pending": "待兑现", "hit": "已兑现"}


def _format_spine_anchor_line(spine_anchors: Optional[List[dict]]) -> str:
    """spine 锚点列表 → user prompt 意图区的全锚点行（C3 · §5.3）。

    格式「# 本章锚点：A（待兑现）；B（已兑现）…」（≤STITCH_OUTLINE_SPINE_
    ANCHORS_MAX 个，分号分隔；dropped 与空文本不入行，未知 status 按
    待兑现）。输入是路由侧从 chapter.spine 抽出的 [{text, status}]；
    无有效锚点 → 空串（无 spine 书 prompt 逐字节零变化）。
    """
    parts: List[str] = []
    for a in (spine_anchors or []):
        if not isinstance(a, dict):
            continue
        text = str(a.get("text") or "").strip()
        status = str(a.get("status") or "").strip()
        if not text or status == "dropped":
            continue
        label = _SPINE_ANCHOR_STATUS_LABELS.get(status, "待兑现")
        parts.append(f"{text}（{label}）")
        if len(parts) >= STITCH_OUTLINE_SPINE_ANCHORS_MAX:
            break
    return f"# 本章锚点：{'；'.join(parts)}" if parts else ""


def build_outline_expand_prompt(
    outline_note: str,
    rolling_prefix: str,
    after_text: str = "",
    proper_nouns: Optional[List[str]] = None,
    canon_context: str = "",
    character_secrets: Optional[List[dict]] = None,
    target_chars: int = 400,
    chapter_intent: str = "",
    memory_echoes: Optional[List[str]] = None,
    style_positive: str = "",
    author_samples: Optional[List[str]] = None,
    spatial_brief: str = "",
    serves_anchor: str = "",
    spine_anchors: Optional[List[dict]] = None,
) -> tuple:
    """构建细纲扩写 prompt（胶囊节点「落笔扩写」触发）。

    与 burst 的区别：意图来自作者亲笔速记（非 AI 菜单挑选），且速记可能处于
    章节中间——扩写必须双端缝合：开头承接上文结尾，结尾引向下文开头。
    after_text 为空（章末/回补段后无正文）时退化为单端锚定，写到自然收束处停笔。

    双端锚定语义引自 adf_prompts.build_beat_patch_prompt（Phase 6.5 补写），
    铺开指令引自 build_burst_prompt 的走向覆盖措辞。

    Args:
        outline_note: 作者的细纲速记（本段必须完整兑现的核心事件）
        rolling_prefix: 细纲之前的已写正文尾部（≤500 字）
        after_text: 细纲之后的已写正文开头（≤300 字，可空）
        proper_nouns: 在场角色/资产名专名表
        canon_context: Canon 上下文（public/private 约束）
        character_secrets: 私有实体档案（A1；空=零变化）
        target_chars: 目标字数上限（默认 400）
        chapter_intent: 章节意图/大纲片段（可选方向引导）
        memory_echoes: 向量召回的前情片段
        style_positive: 作者文风画像文本（空=零变化）
        author_samples: 作者笔迹示范 few-shot 样本（空=零变化）
        serves_anchor: 胶囊挂的谋篇锚点文本（P1.4 M3 三锚定：双端缝合+锚点意图；空=零变化）
        spine_anchors: 本章 spine 全锚点列表（C3 · §5.3，[{text, status}]，
            路由从 chapter.spine 抽取；None/空 → 锚点行缺席=零变化。
            胶囊不只看到自己挂的单锚，还有全章谋篇盘面）

    Returns:
        (system_prompt, user_prompt)
    """
    system_prompt = _base_system()
    for _key, _block in render_system_blocks(
        style_positive=style_positive,
        author_samples=author_samples,
        proper_nouns=proper_nouns,
        canon_context=canon_context,
        character_secrets=character_secrets,
        memory_echoes=memory_echoes,
        spatial_brief=spatial_brief,
        mode="outline",  # A3b：outline 档过模式预算
    ):
        system_prompt += _block

    intent_line = f"\n# 章节意图（方向参考，非强制）\n{chapter_intent}" if chapter_intent else ""
    # C3（§5.3）：全锚点行先于单锚——一般→具体（先给全章谋篇盘面，再点出
    # 本段服务的锚点）；无 spine → 行缺席，prompt 逐字节不变
    anchors_line = _format_spine_anchor_line(spine_anchors)
    if anchors_line:
        intent_line += f"\n{anchors_line}"
    if serves_anchor:
        intent_line += f"\n# 本段服务的谋篇锚点（作者定的方向，扩写要朝它去）\n{serves_anchor}"
    if after_text:
        after_block = f"""# 下文正文（你的结尾要自然引向它的开头）
{after_text}
要求：结尾只做铺垫过渡，绝不重复、改写或提前写出下文的内容。"""
        closing_line = "写完细纲覆盖的内容、衔接好上下文后立即停笔，不要顺势写下文。"
    else:
        after_block = ""
        closing_line = "写到细纲内容自然收束处停笔，不要顺势往下写。"

    user_prompt = f"""# 上文正文（你的开头要自然承接它的结尾，不重复已写动作与意象）
{rolling_prefix or "（开篇）"}
{intent_line}

# 细纲速记（作者亲笔，本段必须完整兑现的核心事件）
{outline_note}
要求：把速记铺开成具体的场景与动作，绝不允许一句话带过；速记里的字数说明（如「约300字」）是给你的预算提示，不要写进正文。

{after_block}
# 任务
请把细纲速记扩写成正文，总字数控制在 {target_chars} 字以内。只输出扩写的正文——不要复述细纲原文，不要标题、不要解释。{closing_line}"""
    return system_prompt, user_prompt


# ============================================================
# 试听 prompt（文风页试衣间，S3——真实注入管线的可感知出口）
# ============================================================

def build_audition_prompt(
    text: str,
    style_positive: str = "",
    author_samples: Optional[List[str]] = None,
    target_chars: int = 400,
) -> tuple:
    """构建试听改写 prompt（与 stitch-ghost 同一套基座与文风块）。

    试衣间的承诺是「所见即所得」：作者在文风页调的配置，改写效果与
    写作台续写走完全相同的注入路径（_base_system + 文风画像块 + 笔迹示范块），
    差异只在 user prompt 的任务描述（改写既有段落而非续写）。

    Args:
        text: 待改写的段落（作者粘贴或默认测试段）
        style_positive: 文风画像文本（草稿配置或已存卡渲染）
        author_samples: 笔迹示范样本（A/B 基线版传 None/[]）
        target_chars: 目标字数（约等于原段长度，由调用方给）

    Returns:
        (system_prompt, user_prompt)
    """
    system_prompt = _base_system()
    system_prompt += _style_positive_block(style_positive)
    system_prompt += _author_samples_block(author_samples)

    user_prompt = f"""# 待改写的段落
{text}

# 任务
请把上面这段文字**改写成这位作者的笔迹**：情节、信息、人物动作一个都不变，
只换声音——句式节奏、用词习惯、语气按上文画像与示范对齐。
长度与原文相近（{target_chars} 字左右）。只输出改写后的正文，不要解释。"""
    return system_prompt, user_prompt


# ============================================================
# 点火 prompt（冷启动：空章 + 大纲 → 开篇 2-5 段，破纸引子）
# ============================================================

def build_opening_prompt(
    outline_text: str,
    previous_summary: str = "",
    worldview_text: str = "",
    proper_nouns: Optional[List[str]] = None,
    canon_context: str = "",
    character_secrets: Optional[List[dict]] = None,
    target_chars: int = 700,
    memory_echoes: Optional[List[str]] = None,
    style_positive: str = "",
    author_samples: Optional[List[str]] = None,
    spatial_brief: str = "",
) -> tuple:
    """构建开篇点火 prompt（空章冷启动：大纲是唯一燃料）。

    定位"破纸引子"而非"成品章"：把作者从空白页捞出来，给出一个可改可续的起点。
    与 burst 的区别：无任何已写正文，大纲从"方向参考"升级为主输入。

    Args:
        outline_text: 本章大纲（全文截 800，主燃料）
        previous_summary: 上一章结尾/摘要（截 300，衔接用，可空）
        worldview_text: 世界观（截 200，定基调，可空）
        proper_nouns: 在场角色/资产名专名表
        canon_context: Canon 上下文（public/private 约束）
        character_secrets: 私有实体档案（A1；空=零变化）
        target_chars: 总字数软上限（默认 700）
        style_positive: 作者文风画像文本（空=零变化）
        author_samples: 作者笔迹示范 few-shot 样本（空=零变化）

    Returns:
        (system_prompt, user_prompt)
    """
    system_prompt = _base_system()
    for _key, _block in render_system_blocks(
        style_positive=style_positive,
        author_samples=author_samples,
        proper_nouns=proper_nouns,
        canon_context=canon_context,
        character_secrets=character_secrets,
        memory_echoes=memory_echoes,
        spatial_brief=spatial_brief,
        mode="open",  # A3b：open 档过模式预算
    ):
        system_prompt += _block

    prev_line = f"\n# 上一章结尾（新章开头要与其自然衔接）\n{previous_summary[:STITCH_PREV_SUMMARY_MAX_CHARS]}" if previous_summary else ""
    worldview_line = f"\n# 世界观基调\n{worldview_text[:STITCH_WORLDVIEW_MAX_CHARS]}" if worldview_text else ""

    user_prompt = f"""# 本章大纲（这是唯一的创作依据，开头必须服务于它的第一段进展）
{(outline_text or "")[:STITCH_OUTLINE_MAX_CHARS] or "（无大纲）"}
{prev_line}{worldview_line}

# 任务
作者面对空白页，请你为本章写开篇 2-5 个段落，总字数控制在 {target_chars} 字以内。
- 从一个具体的场景、动作或对话切入，把读者直接扔进现场——禁止"多年以后/这是一个/话说"这类概述式开场
- 只写"引子"：推进到大纲的第一个小进展、留出悬念就停笔，不要试图写完整章
- 段落之间用一个空行分隔
- 只输出正文，不要标题、不要章节号、不要解释。"""
    return system_prompt, user_prompt


# ============================================================
# 意图反推 prompt（层 2：从已写正文推断本章意图）
# ============================================================

_INTENT_INFERENCE_SYSTEM = """你是资深小说编辑。根据作者已写的正文和（可选）大纲，推断这一章的叙事意图。

你要输出：
- arc：本章的核心弧线（一句话，如"林尘发现真相并决定反抗"）
- emotion_curve：情绪走向（3-5 个阶段，每阶段 {phase, emotion, energy 1-10}）
- setup_points：本章应铺陈的要点（2-4 个，作者未来写作可呼应）
- deviations：如果你注意到正文走向与章节卡（must_hit_events/foreshadow_ops）有偏差，列出（每条一句话）；无偏差则空数组

扎根作者已写的正文（这是事实），参考设定养料（角色/世界观/前文摘要）。不要编造没写过的剧情。
只输出 JSON，不要解释。"""


def build_intent_inference_prompt(
    written_text: str,
    outline_text: str,
    nutrients: dict,
    soft_constraints: dict,
) -> tuple:
    """构建意图反推 prompt。

    Args:
        written_text: 作者已写的正文（层 1 拼接）
        outline_text: 章节大纲（可为空——此时纯从正文反推）
        nutrients: 设定养料（SettingsBundle.nutrients()）
        soft_constraints: 软约束（SettingsBundle.soft_constraints()，含 must_hit_events）

    Returns:
        (system_prompt, user_prompt)
    """
    user_prompt = f"""# 章节大纲
{outline_text or "（作者未提供大纲，请从正文反推）"}

# 作者已写正文
{written_text[:2000]}

# 设定养料
角色：{nutrients.get('characters', '（无）')}
世界观：{nutrients.get('worldview_text', '（无）')[:200]}
前文摘要：{nutrients.get('previous_summary', '（无）')[:200]}

# 章节卡参考（软约束，作者可偏离，偏离要标注）
必达事件：{soft_constraints.get('must_hit_events', '（无）')}
伏笔操作：{soft_constraints.get('foreshadow_ops', '（无）')}

推断本章意图。输出 JSON：
{{"arc": "...", "emotion_curve": [{{"phase": "开端", "emotion": "紧张", "energy": 6}}], "setup_points": ["..."], "deviations": ["..."]}}"""
    return _INTENT_INFERENCE_SYSTEM, user_prompt


# ============================================================
# 未来推测 prompt（层 3：基于层1+2 推测接下来的画面）
# ============================================================

_FUTURE_PROJECTION_SYSTEM = """你是小说叙事参谋。基于作者已写的事实（层 1）和本章意图（层 2），推测接下来 2-3 个可能写的"画面方向"。

每个方向是一个具体的、物理的、可立刻动笔的镜头提案（不是剧情总结）：
- event：这个画面在发生什么（一句话，有动作）
- anchors：画面里的物理焦点（1-2 个，如"渗血的绷带""熄灭的油灯"）
- emotion：这个画面的情绪基调（一个词）

扎根已写正文（衔接连贯），参考角色此刻状态（dynamic_state）和在场资产。不要编造与已建立事实矛盾的剧情。
只输出 JSON，不要解释。"""


def build_future_projection_prompt(
    written_text: str,
    intent: dict,
    nutrients: dict,
    soft_constraints: dict,
    spine_anchors: Optional[List[dict]] = None,
    encounters: Optional[List[str]] = None,
) -> tuple:
    """构建未来推测 prompt。

    Args:
        written_text: 层 1 正文尾部（最近写的，≤500 字）
        intent: 层 2 意图（ChapterIntent.to_dict()）
        nutrients: 设定养料
        soft_constraints: 软约束
        spine_anchors: 章级软脉络的 pending 锚点（P1.4 M2：[{id,text}]，空=不注入零变化）
        encounters: 地图相遇机会行（W5 桥：此刻同地角色组，如「甲与乙（北岸要塞）」；
            空=不注入零变化）

    Returns:
        (system_prompt, user_prompt)
    """
    # 谋篇锚点块（P1.4 M2 走向卡挂脉络）：服务于某锚点的推测带 serves_anchor；
    # 无脉络/无 pending 锚点时两个插入点全空 → prompt 与旧版逐字节一致
    spine_block = ""
    serve_note = ""
    if spine_anchors:
        anchor_lines = "\n".join(f"- {a['id']}: {a['text']}" for a in spine_anchors[:5])
        spine_block = f"""
# 本章谋篇锚点（作者定的方向，推测优先朝这些锚点去；没有合适的就别硬挂）
{anchor_lines}
"""
        serve_note = (
            '\n若某推测服务于上面某个谋篇锚点，给它加 "serves_anchor": "锚点id"'
            "（不属于任何锚点则省略该字段）。"
        )
    # 相遇机会块（W5 桥：世界沙盘喂走向卡——地理事实作走向素材，不是指令）
    encounter_block = ""
    if encounters:
        encounter_block = f"""
# 地图上的相遇机会（此刻同地的角色组——地理事实，可自然用作走向素材）
{chr(10).join('- ' + e for e in encounters[:3])}
"""
        serve_note += (
            '\n若某推测正是让某组相遇发生/错开，给它加 "from_encounter": true。'
        )
    user_prompt = f"""# 本章意图
弧线：{intent.get('arc', '（未推断）')}
情绪走向：{intent.get('emotion_curve', [])}
铺陈要点：{intent.get('setup_points', [])}
{spine_block}{encounter_block}
# 作者最近写的正文（衔接此处继续）
{written_text[-500:]}

# 角色此刻状态（软约束）
{soft_constraints.get('character_dynamics', '（无）')}

# 在场资产状态
{soft_constraints.get('asset_states', '（无）')}

# 可呼应的伏笔
{soft_constraints.get('open_hooks', '（无）')[:200]}

推测接下来的 2-3 个画面方向。输出 JSON：
{{"projections": [{{"event": "老烟用残手砸灭油灯", "anchors": ["渗血的绷带", "熄灭的灯"], "emotion": "压抑"}}]}}{serve_note}"""
    return _FUTURE_PROJECTION_SYSTEM, user_prompt


# ============================================================
# 挂件生发 prompt（层 3 → 3-4 个镜头特写挂件）
# ============================================================

_DOCK_GENERATOR_SYSTEM = """你是一个物理镜头碎片生成器。基于作者当前段落、本章推测方向和设定养料，生成 3-4 个具体的镜头特写挂件。

每个挂件是一个 8-14 字的【微型镜头】，作者扫一眼就能在脑中想象出那个画面，并立刻判断"要不要顺着写"。

【结构铁律 —— 每个碎片必须有"主语 + 具体动作/状态"】
- action 类：[谁] + [具体动词] + [对象/方向] → "林尘攥紧扳手摸向灯塔基座"
- scene 类：[具体物件/环境] + [可视感官细节] → "礁石滩泛着暗红的金属锈光"
- line 类：[完整台词原文] +（可选说话人）→ "别在退潮时回头。阿晚的声音"
- 必须扎根设定但生发新画面：角色动作符合其性格设定，但要是作者还没写过的具体动作

【5 个叙事方向 —— 每个碎片必须服务其中一个】
- 主线：朝本章核心事件/弧线推进【一小步】（角色发现了线索、做出决定、遭遇关键转折）
- 伏笔：埋下隐患或铺垫（物件异常、不经意的细节、暗藏的线索）
- 刻画：深化角色形象或性格（符合人设的具体行为、习惯动作、技能展示）
- 环境：场景的物理质感（光影、声音、气味、空间细节）
- 关系：角色间的暗流张力（对话、肢体语言、眼神、未说出口的话）

【就近铁律 —— 碎片是"下一屏"的画面，不是章末预告】
- 文流第一：碎片必须与作者当前段落的最后一句**直接衔接**——作者下一句就能顺着接上写，中间不需要任何过渡句
- 大纲节拍是几步之外的目的地，不是碎片内容：只给通往节拍的路上的第一步（过渡、铺垫、临近的动作），绝不直接呈现节拍本身的场面——**节拍里写着的对白（如某人的呵斥/问话）绝对禁止直接当碎片**，那是作者写到跟前才该写的
- 禁止跳到本章后段的高潮/转折/结局场面——核心事件等作者写到跟前再提，绝不提前搬上来
- 主线方向 = 朝目的地推进的下一小步，不是把节拍事件直接搬上来
- 没有大纲节拍可用时，也只许在当前文流上就近生发

【场景锚定 —— 碎片长在作者此刻的场景里】
- 道具不凭空发明：碎片里的物件/地点必须已出现在当前段落、设定养料或就近节拍里——伏笔类尤其如此，「物件异常」用已有物件的异常，不得为埋伏笔造新道具
- 不复述已写：碎片必须是还没落笔的画面——作者已写的画面（刚引用的原文、刚描写过的物件）换个说法再端上来，等于没给选项
- 空间不瞬移：碎片发生在当前段落的同一场景/时刻，或通向下一拍的过渡画面（抵达、开门、天亮）；就近节拍若在别的场景，给「过渡到那一拍」的第一步，不给那一拍的进行中
- 保底本场景：3-4 个碎片中至少 2 个发生在当前段落的同一场景内——作者不换景就能直接落笔

【反例 —— 这些是"太笼统"，禁止产出】
× "传送带突然停转"（停转了然后呢？没有"谁"做什么）
× "环境变得压抑"（抽象形容词，不可视）
× "阿晚说过一些话"（什么话？没有内容）
× "林尘感到不安"（心理描写，违反铁律）
× "气氛紧张起来"（纯氛围概括，不可操作）

【正例 —— 这些是"具体可操作"，要产出这样的】
✓ "林尘攥紧扳手摸向灯塔基座"（主语+动作+对象，能展开成行为段）
✓ "礁石滩泛着暗红的金属锈光"（物件+视觉感官，能展开成环境段）
✓ "别在退潮时回头。阿晚的声音"（完整台词，能展开成对话/回忆段）
✓ "一只手从灯塔窗洞里伸出来"（物件+动作+位置，制造悬念）

铁律：
1. 禁心理描写（"心中一紧"/"感到不安"）、禁比喻（"宛如"）、禁抽象形容词（"压抑"/"紧张"/"压抑"）
2. 禁词表（以下词汇禁止）：{banned_words}
3. 角色动作必须符合其永恒设定（static_prompt），不许 OOC
4. 多样性：不要全是 action 或全是 line，混搭让作者有不同方向
5. 每个碎片必须标注 direction（从 主线/伏笔/刻画/环境/关系 里选），按方向权重分布生成

【自检 —— 输出前对每个碎片问】
- 作者扫一眼能想象出画面吗？（不能 → 太笼统，重写）
- 有明确的"谁"或"什么物件"吗？（没有 → 补主语）
- 动作/状态是具体的可视细节吗？（是抽象形容词 → 换成物理动作/感官）
- direction 标了吗？和画面匹配吗？

只输出 JSON，不要解释。"""


def build_dock_generator_prompt(
    recent_text: str,
    projections: list,
    nutrients: dict,
    hard_constraints: dict,
    direction_weights: dict = None,
    reader_expectations: list = None,
    memory_echoes: list = None,
    spine_intent: str = "",
    outline_nearby: list = None,
) -> tuple:
    """构建挂件生发 prompt。

    Args:
        recent_text: 作者当前段落（≤300 字）
        projections: 层 3 推测（SegmentProjection.to_dict() 列表）
        nutrients: 设定养料（角色物理特征/资产/地点）
        hard_constraints: 硬约束（banned_words / character_statics / canon_private_labels）
        direction_weights: 5 叙事方向权重（{"主线":0.4,...}），碎片按此分布生成并自标 direction
        reader_expectations: 读者期待（[{type, description, tension}]，最多取前 2 条进块；
            呼应期待的碎片须标 from_expectation，呼应=侧面暗示，绝不直接揭晓）
        spine_intent: 章级谋篇意图一句话（P1.4 M2；空=不注入。8-14 字零件吃
            画像的同款克制——只给方向不给展开）

    Returns:
        (system_prompt, user_prompt)
    """
    banned = "、".join(hard_constraints.get("banned_words", [])[:30])
    system_prompt = _DOCK_GENERATOR_SYSTEM.format(banned_words=banned or "（无）")

    # 推测方向摘要
    proj_lines = []
    for p in (projections or [])[:3]:
        beats = p.get("possible_beats", []) if isinstance(p, dict) else []
        for b in beats[:2]:
            proj_lines.append(f"- {b.get('event', '')}（焦点：{b.get('anchors', [])}）")
    proj_text = "\n".join(proj_lines) if proj_lines else "（无推测，基于当前段落自由生发）"

    # 角色永恒设定（防 OOC）
    statics = hard_constraints.get("character_statics", {})
    static_lines = [f"- {k}：{v[:80]}" for k, v in statics.items() if k and v][:5]

    # 方向权重块（碎片按此分布生成；防剧透——只给权重数字，不给剧情细节）
    if direction_weights:
        dw_lines = []
        for d, w in sorted(direction_weights.items(), key=lambda x: -x[1]):
            pct = int(w * 100)
            if pct > 0:
                dw_lines.append(f"{d} {pct}%")
        dw_text = "｜".join(dw_lines) if dw_lines else "（均匀分布）"
        dw_block = f"""
# 叙事方向权重（碎片请按此分布生成，高权重方向至少占 1 个）
{dw_text}
每个碎片必须标注 direction（只能从 主线/伏笔/刻画/环境/关系 里选）。
"""
    else:
        dw_block = ""

    # 读者期待块（账本为空则整块省略——不用账本的作者 prompt 零变化）
    exp_lines = []
    for e in (reader_expectations or [])[:2]:
        if not isinstance(e, dict):
            continue
        desc = (e.get("description") or "")[:40]
        tension = e.get("tension") or 5
        if desc:
            exp_lines.append(f"- （张力{tension}/10）{desc}")
    exp_block = ""
    if exp_lines:
        exp_block = f"""
# 读者期待（读者正在等的事；最多用 1 个碎片【侧面】呼应——暗示/推进，绝不直接揭晓；呼应的碎片须加 "from_expectation": true）
{chr(10).join(exp_lines)}
"""

    # 前情回响块（向量召回的更早章节片段——「伏笔呼应」类零件的素材源）
    echo_lines = [e.strip() for e in (memory_echoes or []) if e and e.strip()]
    echo_block = ""
    if echo_lines:
        echo_block = f"""
# 前情回响（更早章节的片段——可用作呼应素材，让零件呼应前情细节/物件/悬念）
{chr(10).join('- ' + e for e in echo_lines[:2])}
"""

    # 章级谋篇意图一行（P1.4 M2；空=零变化。克制：只给方向不给展开）
    spine_line = f"\n# 本章意图（方向参考）\n{spine_intent}" if spine_intent else ""

    # 大纲就近节拍（2026-08-25 就近铁律配套；空=零变化）——作者自己的大纲、
    # 接下来 1-2 拍原文。2026-08-26 定位修正：节拍是**目的地**不是碎片内容
    # （实测：碎片直接呈现节拍对白，与作者笔下位置隔着数步，割裂感重）。
    nearby_block = ""
    if outline_nearby:
        nearby_lines = "\n".join(f"- {b}" for b in outline_nearby[:2])
        nearby_block = f"""
# 作者大纲·就近节拍（几步之外的目的地——剧情正朝那里去；碎片只给通往它的第一步，不是节拍本身的画面）
{nearby_lines}
"""

    user_prompt = f"""# 作者当前段落
{recent_text[:300]}
{spine_line}{nearby_block}
# 接下来的画面方向（参考，可偏离）
{proj_text}
{dw_block}{exp_block}{echo_block}
# 设定养料（角色物理特征/资产/地点，自由用作画面素材）
角色：{nutrients.get('characters', '（无）')}
资产：{nutrients.get('assets', '（无）')}
地点：{nutrients.get('locations', '（无）')}

# 角色永恒设定（动作必须符合，不许 OOC）
{chr(10).join(static_lines) if static_lines else '（无）'}

# Canon private 禁忌（以下内容绝不能在挂件里出现）
{hard_constraints.get('canon_private_labels', [])[:5] or '（无）'}

生成 3-4 个镜头特写挂件（每个 8-14 字，主语+具体动作/状态，作者能一眼想象出画面）。
若某个碎片呼应了"读者期待"，给它加 "from_expectation": true（至多 1 个）。输出 JSON：
{{"parts": [{{"type": "action", "text": "林尘攥紧扳手摸向灯塔基座", "direction": "主线"}}, {{"type": "scene", "text": "礁石滩泛着暗红的金属锈光", "direction": "环境"}}, {{"type": "line", "text": "别在退潮时回头。阿晚的声音", "direction": "关系"}}]}}"""
    return system_prompt, user_prompt


# ============================================================
# 章级谋篇建议 prompt（软脉络 suggest：一句话意图 + ≤5 锚点，docs/chapter-planning-spine.md §3.1）
# ============================================================

def build_spine_suggest_prompt(
    outline_text: str = "",
    open_hooks: str = "",
    canon_context: str = "",
    worldview_text: str = "",
    prev_pending_anchors: Optional[List[str]] = None,
    previous_summary: str = "",
) -> tuple:
    """构建章级谋篇建议 prompt（1×creative，产出**不落库**——D-4 预填红线）。

    度优先（设计稿第一原则）：建议产出刻意轻——意图一句话 + 3-5 个锚点短语，
    绝不是大纲。锚点是「本章不能少的那几步」，不是情节展开。
    """
    system_prompt = (
        "你是长篇小说的谋篇助手。基于本章大纲与世界状态，提炼一句本章意图"
        "（本章要去哪）和 3-5 个关键锚点（哪几步不能少）。极度克制：意图不超过"
        "30 字；每个锚点是 2-12 字的短语（动宾结构，如「发现假信」「压住不表」），"
        "不是句子。绝不产出情节展开或段落大纲。只输出 JSON。"
    )
    parts = []
    if outline_text.strip():
        parts.append(f"# 本章大纲（作者写的，最重要依据）\n{outline_text[:800]}")
    if previous_summary.strip():
        parts.append(f"# 上一章结尾态势\n{previous_summary[:300]}")
    if open_hooks.strip():
        parts.append(f"# 开放伏笔（可考虑兑现）\n{open_hooks[:300]}")
    if prev_pending_anchors:
        parts.append("# 上一章未兑现锚点（作者上章想写没写到的，可顺延）\n" + "、".join(prev_pending_anchors[:5]))
    if worldview_text.strip():
        parts.append(f"# 世界观基调\n{worldview_text[:300]}")
    if canon_context.strip():
        parts.append(f"# Canon 约束\n{canon_context[:400]}")
    if not parts:
        parts.append("（无大纲无前情——依据通用叙事常识给保守建议）")
    user_prompt = "\n\n".join(parts) + '\n\n输出 JSON：\n{"intent": "甲发现那封信是伪造的", "anchors": ["发现假信", "压住不表", "乙的异常反应"]}'
    return system_prompt, user_prompt
