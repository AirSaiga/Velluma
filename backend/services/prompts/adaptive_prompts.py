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
    BudgetBlock,
    BlockUsage,
    MODE_BLOCK_BUDGET_OVERRIDES,
    MODE_CONTEXT_BUDGETS,
    allocate,
)

# prompt 侧禁词扩展（2026-08-27 文学诊断轮）：只进生成 prompt 的禁词表，
# 不进 DEFAULT_BAN_LIST——sanitizer 对禁词做确定性子串删除，「回味」「顿了顿」
# 这类词删除会打穿句子（「脑子里却还在回味那行字」→「脑子里却还在那行字」）。
# 词表按消费方分层：代码删除层保持人工筛选最小集，prompt 禁令层可放宽。
_PROMPT_ONLY_BANNED = ("一抹", "氤氲", "指腹", "眸子", "眸光", "回味", "顿了顿")
_BANNED_WORDS_TEXT = "、".join(DEFAULT_BAN_LIST.banned_words + _PROMPT_ONLY_BANNED)


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

# 细节功能（好细节的尺子）
每个细节必须改变点什么：回答上文悬着的问题、与场内另一物发生关系、或携带人物的过去（「边缘已经起了毛」一个词就写出他反复重读）。三项皆不沾的静态贴图（手部小动作、材质、光线）每段至多 1 个；可写可不写的细节，不写。限额不是配额，不必用满。
"""
# 2026-08-27 诊断轮：本节换血替换旧「感官描写指导」（每段至多 2 处感官细节）——
# 该指令只考核细节的具体性不考核功能性，中档模型把它解析成「插入特写道具=推进」，
# 限额被当配额用满，催生手部特写/材质/光线三类静态贴图库存。


# ---- 句级续写三律（2026-08-27 文学诊断轮）----
# 实测幽灵草稿的三类结构性 AI 腔，词表打不中（好句坏句共享词汇），须指令级：
# ①回说式填充/三通道冗余：字面复读已禁，模型改道语义层——用「回味/想起」
#   复述刚消费过的信息，或手/物/心三个感官通道重演同一状态；
# ②断点徘徊：作者停在半个判断上，模型接住却不敢担纲（「显得有些」式软化），
#   补完后还回头对它做文章；
# ③外部打断收尾：「吼声突然炸开」式结束——段尾是中档模型注意力最弱、
#   对约束服从最差的位置。
# 措辞以正面任务式为主（「只写新东西」「停在动作上」）：中档模型对任务指令的
# 服从度高于负面禁令，禁令堆叠只会催生新套路与判断稀释（导师诊断结论）。
_RULE_NEW_INFO = "- 只写新东西：每一句都要推进——新动作、新事实、时间或处境的变化。作者已写的每一句读者都读过了，不得再提：不复述、不「回味/想起/还在想」、不换一个感官通道重演刚才的状态；凡是回答「刚才怎样」的句子删掉，只回答「接下来发生什么」。"
_RULE_BREAKPOINT = "- 作者正文停在半句或半个判断上：第一句用最少的字把它补完，补完立即向前走，不再回头对它做文章。"
_RULE_ENDING = "- 最后一句停在人物自己正在做的事上（一个动作、一句话头、一个没想完的具体念头），不用突然响起的声响或喊声收尾，不总结、不抒情。"
# 段落级模式（burst/open）共用的收尾律（单行版）
_RULE_ENDING_PARA = "- 收尾停在人物自己正在做的事上，不用突然响起的声响或喊声结束，不总结、不抒情。"


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


# ---- 轻档画像压缩（C3）已随知识检索平面 v3.1 退役（2026-08-27）----
# 实测证伪：「句级轻档少注入」的先验恰恰落在产出全部不可用的档位
# （stitch 0/7 采纳）。任务平权后五模式消费同一份完整知识，画像不再
# 按档压缩（docs/knowledge-retrieval-plane.md §1 公理二）。



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
    """专名约束块定义：硬块（防缝合/续写时称呼漂移造名）。

    措辞是「称呼规范」不是登场指令（2026-09-01 穿帮修复）：旧措辞「以下名称
    必须原样使用」被小模型读成「名单里的名字都要写进正文」，配合装配侧书级
    全量名单，把不在场的实体硬编进画面（trace 实证：工头喊「拧流光的螺栓」）。
    名单本身已由 stitch_context.scene_visible_proper_nouns 按
    在场∪死亡∪提及∪可见文本点名过滤，措辞再卸掉「必须用上」的推力。
    """
    return BudgetBlock(
        key="proper_nouns",
        header=(
            "\n\n# 实体称呼（硬约束）\n"
            "正文若写到下列名称，必须与此处完全一致，禁止改名、缩写或生造昵称；"
            "这只是称呼规范，不是登场清单——不要为了用上某个名字而安排情节："
        ),
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

def _wrap_kg(text: str) -> str:
    """知识平面硬块的包装（空=空串块；非空带 \\n\\n 前导，与其余块同约定）。"""
    return f"\n\n{text}" if text else ""


def render_system_blocks_with_usage(
    style_positive: str = "",
    author_samples: Optional[List[str]] = None,
    proper_nouns: Optional[List[str]] = None,
    canon_context: str = "",
    character_secrets: Optional[List[dict]] = None,
    memory_echoes: Optional[List[str]] = None,
    spatial_brief: str = "",
    mode: str = "",
    scene_identity: str = "",
    entities_text: str = "",
    worldview_text: str = "",
    relations_text: str = "",
    negative_constraints: str = "",
    warm_card: str = "",
) -> tuple:
    """渲染 system 知识块（知识检索平面 v3.1 注入序权威）。

    注入序（事实层全前于文风层——中档模型对 prompt 中部遗忘，连续性事实
    必须占据 primacy 位；docs/knowledge-retrieval-plane.md §6）：
    场景身份 → 在场实体 → canon → 私有 → 世界观 → 关系 → 禁词 →
    回响 → 空间 → 画像 → 样本。

    知识平面五块（scene/entities/worldview/relations/negative）为预渲染
    完整文本（services/context/knowledge_plane.py 产出，条目原子、一字
    不砍），不进 allocate——硬层无预算裁剪；usages 只覆盖旧七块中仍在
    预算器内的软块（画像/样本/回响/空间），默认预算下 allocate 恒等。

    在场实体块存在时取代旧专名块（名字已含于实体条目，避免重复注入）；
    无实体数据（空书/未迁移书）时保留专名块兜底（零变化契约）。
    """
    defs = [
        _style_block_def(style_positive),
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
    by_key = {b.key: b.render() for b in defs}
    if entities_text:
        by_key.pop("proper_nouns", None)  # 实体块已含全部名字，去重
    blocks = [
        ("scene", _wrap_kg(scene_identity)),
        ("warm", _wrap_kg(warm_card)),
        ("entities", _wrap_kg(entities_text)),
        ("canon", by_key.get("canon", "")),
        ("secrets", by_key.get("secrets", "")),
        ("worldview", _wrap_kg(worldview_text)),
        ("relations", _wrap_kg(relations_text)),
        ("negative", _wrap_kg(negative_constraints)),
        ("echoes", by_key.get("echoes", "")),
        ("spatial", by_key.get("spatial", "")),
        ("style_positive", by_key.get("style_positive", "")),
        ("author_samples", by_key.get("author_samples", "")),
    ]
    if not entities_text:
        # 专名兜底位：无知识平面实体块时维持旧序位置（entities 后、canon 前）
        blocks.insert(3, ("proper_nouns", by_key.get("proper_nouns", "")))
    return blocks, usages


def render_system_blocks(
    style_positive: str = "",
    author_samples: Optional[List[str]] = None,
    proper_nouns: Optional[List[str]] = None,
    canon_context: str = "",
    character_secrets: Optional[List[dict]] = None,
    memory_echoes: Optional[List[str]] = None,
    spatial_brief: str = "",
    mode: str = "",
    scene_identity: str = "",
    entities_text: str = "",
    worldview_text: str = "",
    relations_text: str = "",
    negative_constraints: str = "",
    warm_card: str = "",
) -> List[tuple]:
    """按真实注入序渲染 system 知识块，返回 [(key, block_text)]。

    五个 stitch builder（continue/burst/outline/open）的 system prompt 组装段
    统一走此函数——注入序 = 返回序（场景身份→在场实体→canon→私有→世界观→
    关系→禁词→回响→空间→画像→样本，事实层前置于文风层），空数据对应空串块
    （拼接后 prompt 逐字节零变化）。

    知识平面五块（scene/entities/worldview/relations/negative）由
    services/context/knowledge_plane.py 预渲染（条目原子、选中即完整、时态
    标注），此处只做注入序编排——改知识内容去知识平面，改注入序来这里。

    character_secrets 是 A1 私有通道（bundle.character_secrets，[{name, text}]）：
    私有实体档案只经此块注入（「AI 知晓但绝不直接写出」），装配层已同步
    排除——两轨不渗漏。

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
        scene_identity=scene_identity,
        entities_text=entities_text,
        worldview_text=worldview_text,
        relations_text=relations_text,
        negative_constraints=negative_constraints,
        warm_card=warm_card,
    )
    return blocks


# ============================================================
# 续写 prompt（缝合/代笔/顺写统一入口，mode 区分粒度）
# ============================================================

def _prev_summary_line(previous_summary: str) -> str:
    """紧前一章摘要行（知识平面 v3.1：恒选不截断，五模式统一注入）。"""
    return (
        f"\n# 上一章结尾（连续性参考，保持衔接，不重复其内容）\n{previous_summary}"
        if previous_summary else ""
    )


def _recency_pin_line(recency_pin: str) -> str:
    """recency 位重钉（user 尾部此刻硬事实；lost-in-the-middle 的 recency 锚）。"""
    return f"\n{recency_pin}" if recency_pin else ""


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
    scene_identity: str = "",
    entities_text: str = "",
    worldview_text: str = "",
    relations_text: str = "",
    negative_constraints: str = "",
    warm_card: str = "",
    previous_summary: str = "",
    recency_pin: str = "",
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
        scene_identity=scene_identity,
        entities_text=entities_text,
        worldview_text=worldview_text,
        relations_text=relations_text,
        negative_constraints=negative_constraints,
        warm_card=warm_card,
    ):
        system_prompt += _block

    parts_str = "、".join(picked_parts) if picked_parts else "（无——仅按作者原句顺势续写）"
    intent_line = f"\n# 章节意图（方向参考，非强制）\n{chapter_intent}" if chapter_intent else ""
    prev_line = _prev_summary_line(previous_summary)
    pin_line = _recency_pin_line(recency_pin)

    if mode == "stitch":
        # 追加式契约（2026-08-26 实测修复）：幽灵纯追加在作者原句之后，
        # 原句已在画布里——旧契约「原句一字不改保留在片段中」会致屏幕复读。
        user_prompt = f"""# 上文衔接（保持连续，不重复）
{rolling_prefix or "（开篇）"}{prev_line}
{intent_line}

# 作者原句（已在你身后的画布里——绝不重复它，从它的断点直接往下写）
{fragment}

# 选定镜头零件（必须落地为画面）
{parts_str}

请只输出续写部分：从作者原句的断点顺势接下去（原句停在半句就先自然补完这一句，从断点最后一个词的后面直接续，不要重说断点附近的词），把零件落地为具体画面。零件是画面灵感，作者正文的事实最高优先——零件与正文此刻的场景/时间明显矛盾时（如物件此刻并不在手边），改造零件贴合当下场景，改造不了就舍弃它，绝不硬塞。禁止以任何形式重复原句（原文复读、换说法复述都不行）。
{_RULE_NEW_INFO}
{_RULE_ENDING}
控制在 {target_chars} 字以内。只输出正文，不要标题、不要解释。{pin_line}"""
    else:  # continue
        user_prompt = f"""# 上文衔接（保持连续，不重复已写动作与意象）
{rolling_prefix or "（开篇）"}{prev_line}
{intent_line}

# 作者当前正文（顺着它的语气、人称、节奏往下写）
{fragment}

请顺着作者正文往下续写，控制在 {target_chars} 字以内：
{_RULE_NEW_INFO}
{_RULE_BREAKPOINT}
{_RULE_ENDING}
只输出续写部分，不要重复作者原文，不要标题、不要解释。{pin_line}"""
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
    scene_identity: str = "",
    entities_text: str = "",
    worldview_text: str = "",
    relations_text: str = "",
    negative_constraints: str = "",
    warm_card: str = "",
    previous_summary: str = "",
    recency_pin: str = "",
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
        scene_identity=scene_identity,
        entities_text=entities_text,
        worldview_text=worldview_text,
        relations_text=relations_text,
        negative_constraints=negative_constraints,
        warm_card=warm_card,
    ):
        system_prompt += _block

    intent_line = f"\n# 章节意图（方向参考，非强制）\n{chapter_intent}" if chapter_intent else ""
    prev_line = _prev_summary_line(previous_summary)
    pin_line = _recency_pin_line(recency_pin)
    if beat_guidance:
        guidance_block = f"""# 本段走向（作者选定）
{beat_guidance}
要求：必须覆盖走向的核心事件，但要把它铺开成具体的场景与动作，绝不允许一句话带过。"""
    else:
        guidance_block = """# 本段走向
（作者未指定——顺着上文的语气与悬念自然推进，写到一个小节拍收束处停笔）"""

    user_prompt = f"""# 上文衔接（保持连续，不重复已写动作与意象）
{rolling_prefix or "（开篇）"}{prev_line}
{intent_line}

{guidance_block}

# 作者当前正文（顺着它的语气、人称、节奏往下写）
{fragment}

请顺着作者正文连写 2-4 个段落，总字数控制在 {target_chars} 字以内，写到走向覆盖、场景自然收束处停笔，不要为凑字数拖沓。
{_RULE_ENDING_PARA}
段落之间用一个空行分隔。只输出续写部分，不要重复作者原文，不要标题、不要解释。{pin_line}"""
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
    scene_identity: str = "",
    entities_text: str = "",
    worldview_text: str = "",
    relations_text: str = "",
    negative_constraints: str = "",
    warm_card: str = "",
    previous_summary: str = "",
    recency_pin: str = "",
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
        scene_identity=scene_identity,
        entities_text=entities_text,
        worldview_text=worldview_text,
        relations_text=relations_text,
        negative_constraints=negative_constraints,
        warm_card=warm_card,
    ):
        system_prompt += _block

    intent_line = f"\n# 章节意图（方向参考，非强制）\n{chapter_intent}" if chapter_intent else ""
    prev_line = _prev_summary_line(previous_summary)
    pin_line = _recency_pin_line(recency_pin)
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
{rolling_prefix or "（开篇）"}{prev_line}
{intent_line}

# 细纲速记（作者亲笔，本段必须完整兑现的核心事件）
{outline_note}
要求：把速记铺开成具体的场景与动作，绝不允许一句话带过；速记里的字数说明（如「约300字」）是给你的预算提示，不要写进正文。

{after_block}
# 任务
请把细纲速记扩写成正文，总字数控制在 {target_chars} 字以内。只输出扩写的正文——不要复述细纲原文，不要标题、不要解释。{closing_line}{pin_line}"""
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
    warm_card: str = "",
    scene_identity: str = "",
    entities_text: str = "",
    relations_text: str = "",
    negative_constraints: str = "",
    recency_pin: str = "",
) -> tuple:
    """构建开篇点火 prompt（空章冷启动：大纲是唯一燃料）。

    定位"破纸引子"而非"成品章"：把作者从空白页捞出来，给出一个可改可续的起点。
    与 burst 的区别：无任何已写正文，大纲从"方向参考"升级为主输入。

    Args:
        outline_text: 本章大纲（主燃料；就近剂量由路由侧 outline_nearby 把关）
        previous_summary: 上一章结尾/摘要（恒选不截断，知识平面 v3.1）
        worldview_text: 世界观知识块（knowledge_plane 预渲染完整文本，经
            system 块注入——原 user 侧 200 字特判与双重截断已随 v3.1 退役）
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
        scene_identity=scene_identity,
        entities_text=entities_text,
        worldview_text=worldview_text,
        relations_text=relations_text,
        negative_constraints=negative_constraints,
        warm_card=warm_card,
    ):
        system_prompt += _block

    # 知识平面 v3.1（2026-08-27）：世界观改经 system 块完整注入（原 user 侧
    # 「世界观基调 200 字」特判退役——open 与其余四档同源同量，任务平权）；
    # previous_summary 恒选不截断；大纲就近剂量闸（路由侧）不变
    prev_line = f"\n# 上一章结尾（新章开头要与其自然衔接）\n{previous_summary}" if previous_summary else ""
    pin_line = _recency_pin_line(recency_pin)

    user_prompt = f"""# 本章大纲（这是唯一的创作依据，开头必须服务于它的第一段进展）
{(outline_text or "")[:STITCH_OUTLINE_MAX_CHARS] or "（无大纲）"}
{prev_line}

# 任务
作者面对空白页，请你为本章写开篇 2-5 个段落，总字数控制在 {target_chars} 字以内。
- 从一个具体的场景、动作或对话切入，把读者直接扔进现场——禁止"多年以后/这是一个/话说"这类概述式开场
- 只写"引子"：推进到大纲的第一个小进展、留出悬念就停笔，不要试图写完整章
{_RULE_ENDING_PARA}
- 段落之间用一个空行分隔
- 只输出正文，不要标题、不要章节号、不要解释。{pin_line}"""
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
场景锚定：推测画面发生在此刻的场景里——人物此刻在哪、正在做什么，以正文叙述与大纲节拍为准；不得因正文里的字面联想（如提到某本书、某个地名）就切换到另一个场景、时代或道具库。
只输出 JSON，不要解释。"""

def build_future_projection_prompt(
    written_text: str,
    intent: dict,
    nutrients: dict,
    soft_constraints: dict,
    spine_anchors: Optional[List[dict]] = None,
    encounters: Optional[List[str]] = None,
    outline_nearby: Optional[List[str]] = None,
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
        outline_nearby: 大纲就近节拍原文（2026-08-27 场景锚定；空=不注入零变化。
            推测组件此前看不到大纲，凭正文字面联想换场景——实测 2177 工地发愣被
            推测成民国书房，下游挂件链全锚错）

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
    # 大纲就近节拍（2026-08-27 场景锚定）：作者定的下一步是推测的空间/时间锚——
    # 无此块时推测凭正文字面联想自由发挥（实测幻觉出错误时代的整套场景）。
    # 空=整块缺席，prompt 与旧版逐字节一致
    nearby_block = ""
    if outline_nearby:
        nearby_lines = "\n".join(f"- {b}" for b in outline_nearby[:2])
        nearby_block = f"""
# 作者大纲·就近节拍（接下来 1-2 拍的原文——推测画面必须是通往它路上的合理一步，人物此刻在哪/在做什么以此为准，不得与节拍的场景矛盾）
{nearby_lines}
"""
    user_prompt = f"""# 本章意图
弧线：{intent.get('arc', '（未推断）')}
情绪走向：{intent.get('emotion_curve', [])}
铺陈要点：{intent.get('setup_points', [])}
{spine_block}{nearby_block}{encounter_block}
# 作者最近写的正文（衔接此处继续）
{written_text[-500:]}

# 角色此刻状态（软约束）
{soft_constraints.get('character_dynamics', '（无）')}

# 在场资产状态
{soft_constraints.get('asset_states', '（无）')}

# 可呼应的伏笔
{soft_constraints.get('open_hooks', '（无）')[:200]}

推测接下来的 2-3 个画面方向。每幅画面标注 "stage"："now"=作者此刻光标处的画面；"approach"=通往下一拍的过渡（渐近的脚步、将临的影子）；"beat"=下一拍事件本身；"after"=下一拍之后。**第一幅必须是 "now"**。输出 JSON：
{{"projections": [{{"event": "老烟用残手砸灭油灯", "anchors": ["渗血的绷带", "熄灭的灯"], "emotion": "压抑", "stage": "now"}}]}}{serve_note}"""
    return _FUTURE_PROJECTION_SYSTEM, user_prompt


# ============================================================
# 挂件生发 prompt（层 3 → 3-4 个镜头特写挂件）
# ============================================================
# 2026-09-02 约束治理一期：整段常量改分节条件拼装（剂量治理样板，编译器
# = constraints/prompt_sections.py 通用设施，dock 是第一个租户）。
# - 子句级条件化：节拍依赖子句（节拍保全检验/节拍>推测/绝不提前搬上来/
#   toward_beat 槽位）挂 when=has_outline_nearby；就近通用要求（下一屏/
#   文流第一）与场景锚定（道具两分/空间不瞬移/保底本场景）是无大纲书也
#   成立的通用约束，恒在场；
# - echo 槽位规则恒在（素材块缺席时模型自会跳过，规则本身无害）；
# - 删【自检】四问块（中档模型负资产——自检能力与模型强度正相关，检测
#   已下沉 dock 校对环代码闸）；
# - 强措辞收敛：原整段「铁律×3+绝不×3+必须×6+禁止×3+不许×2」15+ 处压到
#   个位数（lint=registry.scan_prompt_wording，验收闸测试锁）。
# 已知断言面：test_dock_nearby.py（短语+零大纲形态）与
# test_scene_anchoring_prompts.py（对拼装产物断言——原常量断言已重写）。

def _dock_system_sections() -> List:
    """dock system prompt 的分节定义（when 谓词消费 ctx.has_nearby）。"""
    from backend.services.constraints.prompt_sections import PromptSection

    def _has_nearby(ctx: Dict) -> bool:
        return bool(ctx.get("has_nearby"))

    def _no_nearby(ctx: Dict) -> bool:
        return not bool(ctx.get("has_nearby"))

    return [
        PromptSection(key="role", text="""你是一个物理镜头碎片生成器。基于作者当前段落、本章推测方向和设定养料，生成镜头特写挂件。

每个挂件是一个 8-14 字的【微型镜头】，作者扫一眼就能在脑中想象出那个画面，并立刻判断"要不要顺着写"。

"""),
        PromptSection(key="structure", text="""【结构要求 —— 每个碎片都要有"主语 + 具体动作/状态"】
- action 类：[谁] + [具体动词] + [对象/方向] → "林尘攥紧扳手摸向灯塔基座"
- scene 类：[具体物件/环境] + [可视感官细节] → "礁石滩泛着暗红的金属锈光"
- line 类：[完整台词原文] +（可选说话人）→ "别在退潮时回头。阿晚的声音"
- 扎根设定但生发新画面：角色动作符合其性格设定，但要是作者还没写过的具体动作

"""),
        PromptSection(key="slots", text="""【功能槽位 —— 每个碎片属于一个槽位，按槽位生发（作者要能看懂「选这枚会发生什么」）】
- slot=landing【接着写】（必有 1 枚，放首位）——接住作者刚写的：作者最后一句（或正说着的那句话）的"物理落点"——把抽象的感慨、判断、情绪翻译成人物此刻**主动做出**的一个小动作（把书往口袋深处按了按、把后半句咽回去、手上的活故意慢了半拍）。要是人物主动发出的动作——不是表情、不是静止状态
"""),
        PromptSection(
            key="slot-toward-beat",
            when=_has_nearby,
            text="""- slot=toward_beat【通往节拍】（出 1 枚）：通往「作者大纲·就近节拍」那拍的**第一步**过渡画面，不是节拍本身的画面
"""),
        PromptSection(key="slot-echo-ambient", text="""- slot=echo【呼应】（至多 1 枚）：呼应前情回响或读者期待的碎片——呼应哪一条就在 JSON 里标 from_memory/from_expectation + echo_ref（所呼应条目在对应素材块里的序号，从 1 数）。呼应是**当下场景里的新画面**侧面带出旧物/旧事（书页翻到夹层、扳手柄上的旧划痕），不是旧画面换个说法重演——重演前情等于没给选项
- slot=ambient【氛围】（其余补位）：无叙事包袱的画面（光影/声响/物件质感），作者随手就能用，不指向任何去向

"""),
        PromptSection(key="nearby-common", text="""【就近要求 —— 碎片是"下一屏"的画面，不是章末预告】
- 文流第一：碎片与作者当前段落的最后一句**直接衔接**——作者下一句就能顺着接上写，中间不需要任何过渡句

"""),
        PromptSection(
            key="beat-preservation",
            when=_has_nearby,
            text="""- 节拍保全检验（判断是否抢拍的唯一主判据）：把碎片想象着写进正文，大纲那一拍还完整可写吗？写完"工头的手拍上肩"，"突然被工头打断"就被消费掉了——抢拍，丢弃；写完"他按了按口袋里的书"，节拍毫发无损——通往它的第一步，允许。**写不坏节拍的才是第一步**
- 节拍事件本身和它紧接着的反应（被打断、惊得掉东西）都是作者的，碎片不写；碎片只发生在主角一侧（他的身体、他的物件、他的感知），节拍里的其他人物最多"在来的路上"，不许"已经到达"
- 节拍 > 推测：推测方向与大纲就近节拍的场景/时间对不上时，以节拍为准——推测只取其情绪，不取其场景与道具
- 跳到本章后段的高潮/转折/结局场面一律不出——核心事件等作者写到跟前再提，绝不提前搬上来

"""),
        PromptSection(
            key="no-beat-fallback",
            when=_no_nearby,
            text="""- 没有大纲节拍可用时，也只在当前文流上就近生发

"""),
        PromptSection(key="scene-anchoring", text="""【场景锚定 —— 碎片长在作者此刻的场景里】
- 道具分两类：**氛围件**（光线、灰尘、天气、远景、声响）可自由生发，不算发明；**上手件**——人物握、拿、放、捡、掏、开的那个物件——要有出处（本章正文/场景设定/设定养料/就近节拍四处之一）：人物碰过的物件会进入后续所有画面，作者接了它就欠下连续性债
- 不复述已写：碎片是还没落笔的画面——作者已写的画面（刚引用的原文、刚描写过的物件）换个说法再端上来，等于没给选项
- 空间不瞬移：碎片发生在当前段落的同一场景/时刻，或通向下一拍的过渡画面（抵达、开门、天亮——除非抵达本身就是那一拍的事件）
- 保底本场景：碎片中至少 2 个发生在当前段落的同一场景内——作者不换景就能直接落笔

"""),
        PromptSection(key="examples", text="""【反例 —— 这些是"太笼统"，不要产出】
× "传送带突然停转"（停转了然后呢？没有"谁"做什么）
× "环境变得压抑"（抽象形容词，不可视）
× "阿晚说过一些话"（什么话？没有内容）
× "林尘感到不安"（心理描写，违反本要求）
× "气氛紧张起来"（纯氛围概括，不可操作）

【正例 —— 这些是"具体可操作"，要产出这样的】
✓ "林尘攥紧扳手摸向灯塔基座"（主语+动作+对象，能展开成行为段）
✓ "礁石滩泛着暗红的金属锈光"（物件+视觉感官，能展开成环境段）
✓ "别在退潮时回头。阿晚的声音"（完整台词，能展开成对话/回忆段）
✓ "一只手从灯塔窗洞里伸出来"（物件+动作+位置，制造悬念）

"""),
        PromptSection(key="hard-rules", text="""硬性要求：
1. 禁心理描写（"心中一紧"/"感到不安"）、禁比喻（"宛如"）、禁抽象形容词（"压抑"/"紧张"）
2. 禁词表（以下词汇不用）：«BANNED_WORDS»
3. 角色动作参考其永恒设定（static_prompt 资料）——写出与设定相悖的动作会穿帮
4. 多样性：不要全是 action 或全是 line，混搭让作者有不同方向
5. landing 必居首位；呼应类至多 1 枚

只输出 JSON，不要解释。"""),
    ]


def build_dock_generator_prompt(
    recent_text: str,
    projections: list,
    nutrients: dict,
    hard_constraints: dict,
    direction_weights: dict = None,  # 已退役（B7），参数保留兼容
    salience_hints: Optional[List[str]] = None,
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
        direction_weights: 已退役参数（B7 方向权重葬礼；保留签名兼容，忽略）
        salience_hints: 热层六槽热集的具名提示行（salience.compute_salience 产出；空=无提示块
        reader_expectations: 读者期待（[{type, description, tension}]，最多取前 2 条进块；
            呼应期待的碎片须标 from_expectation，呼应=侧面暗示，绝不直接揭晓）
        spine_intent: 章级谋篇意图一句话（P1.4 M2；空=不注入。8-14 字零件吃
            画像的同款克制——只给方向不给展开）

    Returns:
        (system_prompt, user_prompt)
    """
    banned = "、".join(hard_constraints.get("banned_words", [])[:30])
    # 分节编译（约束治理一期）：无就近节拍→节拍依赖子句整节缺席；禁词表
    # 经 «BANNED_WORDS» 占位注入（不能用 str.format——prompt 含 JSON 花括号）
    from backend.services.constraints.prompt_sections import render_sections

    system_prompt = render_sections(
        _dock_system_sections(),
        {"has_nearby": bool(outline_nearby)},
    ).replace("«BANNED_WORDS»", banned or "（无）")

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

    # 注意力提示行（B7 · 方向权重葬礼后的转世）：热层六槽热集的具名提示
    # 取代抽象方向百分比——「该盯住谁/什么」比「主线 36%」对模型可操作性强
    # 一个层级；配额强制（高权重方向至少占一枚）随之废除（常量权重下的
    # 硬性扭曲）。direction 标注保留（分析面元数据）。
    if salience_hints:
        hint_lines = [f"- {h}" for h in salience_hints[:6]]
        dw_block = (
            "\n# 此刻值得盯住（注意力提示，参考非强制——正文事实与就近铁律优先）\n"
            + "\n".join(hint_lines) + "\n"
        )
    else:
        dw_block = ""

    # 读者期待块（账本为空则整块省略——不用账本的作者 prompt 零变化）。
    # 条目带 [1]/[2] 序号（echo_ref 的引用坐标系——模型报序号，后端按
    # 序号回查账本原文拼 note，模型不经手出处文本）
    exp_lines = []
    for i, e in enumerate((reader_expectations or [])[:2], start=1):
        if not isinstance(e, dict):
            continue
        desc = (e.get("description") or "")[:40]
        tension = e.get("tension") or 5
        if desc:
            exp_lines.append(f"- [{i}]（张力{tension}/10）{desc}")
    exp_block = ""
    if exp_lines:
        exp_block = f"""
# 读者期待（读者正在等的事；至多 1 个碎片【侧面】呼应——暗示/推进，绝不直接揭晓；呼应哪条就在该碎片标 "from_expectation": true + "echo_ref": 序号）
{chr(10).join(exp_lines)}
"""

    # 前情回响块（向量召回的更早章节片段——「伏笔呼应」类零件的素材源）。
    # 同样带序号（from_memory + echo_ref 的引用坐标系）
    echo_lines = [e.strip() for e in (memory_echoes or []) if e and e.strip()]
    echo_block = ""
    if echo_lines:
        echo_block = f"""
# 前情回响（更早章节的片段——可用作呼应素材；呼应哪条就在该碎片标 "from_memory": true + "echo_ref": 序号）
{chr(10).join(f'- [{i}] ' + e for i, e in enumerate(echo_lines[:2], start=1))}
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

    # 过采样（约束治理一期）：要求 4-6 枚，校对环丢违规件后仍保 3-4——
    # 检测器误报由过采样吸收；toward_beat 子句仅在有就近节拍时出现
    beat_clause = "给了就近节拍则含 1 枚 toward_beat；" if outline_nearby else ""

    user_prompt = f"""# 作者当前段落
{recent_text[:300]}
{spine_line}{nearby_block}
# 接下来的画面方向（方向参考——优先从作者当前段落生发，不得整句照搬推测画面）
{proj_text}
{dw_block}{exp_block}{echo_block}
# 设定养料（角色物理特征/资产/地点，自由用作画面素材）
角色：{nutrients.get('characters', '（无）')}
资产：{nutrients.get('assets', '（无）')}
地点：{nutrients.get('locations', '（无）')}

# 角色永恒设定（动作性格参考资料）
{chr(10).join(static_lines) if static_lines else '（无）'}

# Canon private 禁忌（以下内容绝不能在挂件里出现）
{hard_constraints.get('canon_private_labels', [])[:5] or '（无）'}

生成 4-6 个镜头特写挂件（每个 8-14 字，主语+具体动作/状态，作者能一眼想象出画面）。
按功能槽位生发（landing 必居首位；{beat_clause}呼应类至多 1 枚）。输出 JSON：
{{"parts": [{{"slot": "landing", "type": "action", "text": "林尘把书往口袋深处按了按"}}, {{"slot": "toward_beat", "type": "action", "text": "他拎起墙边最沉的备件箱", "direction": "主线"}}, {{"slot": "echo", "type": "action", "text": "扳手从指间滑落砸中脚边铁屑", "from_memory": true, "echo_ref": 1}}, {{"slot": "ambient", "type": "scene", "text": "天窗灰光里浮着机油味的尘", "direction": "环境"}}]}}"""
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
