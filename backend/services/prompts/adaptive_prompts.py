# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - NLE-ADF 3.0 自适应辅助 prompt 模板
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

from typing import Dict, List, Optional

from backend.services.nlg.anti_ai_rules import DEFAULT_BAN_LIST
from backend.services.style.texture_contracts import render_texture_contract

# A3a 截断常量收敛（docs/reports/foundation-hardening.md §4.1）：注入剂量改引 budget 表。
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
- 禁病态微操：指尖颤了颤、瞳孔微缩、喉结滚动、嘴角微不可察（点到即止，可无——宁缺勿滥）
- 禁套路比喻：宛如、仿若、犹如、墨水滴进水里、沉睡的巨兽（点到即止，可无）
- 禁匀速句式：连续三句等长（用长短句交替）
- 禁解释性插嘴：眼神中闪过、心中涌起、仿佛在诉说（完全禁止）

# 禁词表（以下词汇禁止使用）
{banned_words}

# 心理描写限制
禁止直接心理升华与内心独白式总结（如"他感到愤怒"、"她知道自己必须坚强"）。
情绪必须用物理动作与环境呈现；每段至多 1 处间接心理暗示，且必须附着在具体动作上。

# 细节功能（好细节的尺子）
每个细节必须改变点什么：回答上文悬着的问题、与场内另一物发生关系、或携带人物的过去（「边缘已经起了毛」一个词就写出他反复重读）。三项皆不沾的静态贴图（手部小动作、材质、光线）点到即止，可无；可写可不写的细节，不写。限额不是配额，不必用满。
"""
# 2026-08-27 诊断轮：本节换血替换旧「感官描写指导」（每段至多 2 处感官细节）——
# 该指令只考核细节的具体性不考核功能性，中档模型把它解析成「插入特写道具=推进」，
# 限额被当配额用满，催生手部特写/材质/光线三类静态贴图库存。
# 2026-09-13 剂量归一：旧「每段至多 1 处」宽容额度与末尾白描契约（stitch/
# continue 专属「绝对禁止」分节）自相矛盾——额度句改「点到即止，可无」，与
# 高压服从位同意志；burst/open/outline 从「允许 1 处」变「未量化克制」为
# 可接受副作用（它们本无白描契约块，不受其管辖）。


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
# 质感档规则（2026-09-03 双轨契约）：替代 _RULE_NEW_INFO——准许停在当下
# 细写，唯一的推进是感受的加深；其余戒律（结尾/断点/复读）不受影响
_RULE_TEXTURE = "- 这一笔停在当下细写：把时间放慢，写此刻具体可感的东西——光线、声响、气味、手上的触感、人物的小动作与神情；不引入新事件、新人物、新物件，在原地停留一整段也完全允许，唯一的推进是感受的加深。"
_RULE_BREAKPOINT = "- 作者正文停在半句或半个判断上：第一句用最少的字把它补完，补完立即向前走，不再回头对它做文章。"
_RULE_ENDING = "- 最后一句停在人物自己正在做的事上（一个动作、一句话头、一个没想完的具体念头），不用突然响起的声响或喊声收尾，不总结、不抒情。"
# 段落级模式（burst/open）共用的收尾律（单行版）
_RULE_ENDING_PARA = "- 收尾停在人物自己正在做的事上，不用突然响起的声响或喊声结束，不总结、不抒情。"


def _spatial_block(spatial_brief: str) -> str:
    """D4-3 空间常识块（docs/reports/map-scale-spatial.md §5）：≤3 行粗估；空=零变化。"""
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
# ---- ——A3a，docs/reports/foundation-hardening.md §4.1；本模块 import 再导出， ----
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
    """作者私有设定块（A1 · docs/reports/foundation-hardening.md §3.1，D5 拍板语义）。

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
# system 块渲染（注入序权威，P5 B2 · docs/reports/foundation-hardening.md §2.1；
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
    texture_contract_overrides: Optional[Dict[str, Dict[str, str]]] = None,
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
        # 白描契约与假感官封杀令（2026-09-09 实测事故）：stitch/continue 专属
        # 末位分节（首尾高服从位；burst/open/outline 各有专职不受染，空串块
        # 拼接零变化——预览/试衣间同源不变量由此自动保持）。
        # 质感契约唯一权威在 services/style/texture_contracts.py（2026-09
        # 收编批；支持按书覆盖，overrides=books.texture_contracts），此处仅消费
        ("anti_pseudo_sensory", render_texture_contract(
            "anti_pseudo_sensory", mode, texture_contract_overrides,
        )),
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
    texture_contract_overrides: Optional[Dict[str, Dict[str, str]]] = None,
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
        texture_contract_overrides=texture_contract_overrides,
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


# ============================================================
# 单焦距主体守恒律（第二冲程 2026-09-09：极速单镜头展开的视点锁）
# ============================================================
# 作者点选分镜后的微缝合是「放大一瞬」而非「推进剧情」——依点选槽位注入
# 互斥的视点锁，防止 50 字微镜头被模型写成「镜头+人物动作+下一拍」的混合体。
# 措辞纪律：禁令用「不写/不出」（对齐 dock 剂量 lint 的克制精神）；锁相机
# 不锁情绪——物镜锁明写「情绪不走人物走物件」，防说明文化。

SUBJECT_LOCK_PROP = "prop"        # 物镜锁：prop/ambient → 只写器物/环境自身感官
SUBJECT_LOCK_SPEAKER = "speaker"  # 发话锁：landing/speaker → 焦点钉在发话者单人
SUBJECT_LOCK_REPLY = "reply"      # 静音锁：reply → 只写受话者开腔前的缓冲
SUBJECT_LOCK_HANDOFF = "handoff"  # 交接锁：桥接态 landing/speaker（2026-09-13 仲裁）——
                                  # 发话者话音落下后镜头切交主角侧完成物理引渡

_SUBJECT_LOCK_TEXTS = {
    SUBJECT_LOCK_PROP: """# 单焦距·物镜锁（本笔只写器物/环境自身的物理感官）
- 镜头钉死在选中的器物或环境上：写它的形、色、声、温度、动静变化，写透即止
- 不写任何人物的动作、视线、台词——人此刻只是这枚镜头的缺席者
- 情绪不走人物走物件：让此刻的气氛落在物件的细节变化上（震颤的频率、油污的反光、灯光的明暗）——镜头是静的，落在什么上由情境决定
- 不推进到下一拍剧情；这一笔只是被放大的一瞬""",
    SUBJECT_LOCK_SPEAKER: """# 单焦距·发话锁（本笔只写发话者单人）
- 焦点钉死在发话者一人身上：他的生理反应与神态——喉音、呼吸、手指、眼神的落点
- 其他人此刻不出场、不插话、不做任何实质反应——他们要等下一笔
- 可以写他说出口的话的余势（尾音、停顿、重复半个词），不替他说下一句
- 不推进到下一拍剧情，不替任何人接话""",
    SUBJECT_LOCK_REPLY: """# 单焦距·静音锁（本笔只写受话者开腔前的缓冲）
- 只写受话者开口之前的身体停顿与微表情：呼吸变了、手指蜷了一下、抬眼又垂下
- 处于绝对静音期：不出任何回应台词——开口是作者的下一笔
- 不推进到下一拍剧情，不替他组织好要说的内容""",
    # 交接锁（2026-09-13 发话锁×桥接铁律仲裁）：桥接态下过渡要留在主角一侧，
    # 而发话者常非主角（如路人招呼）——「焦点钉死发话者」与「主角一侧」
    # 同位注入即主体死锁。视点交接契约：发话者话音落下（余势一瞬）→ 镜头
    # 切交主角侧完成物理引渡。措辞域中性（无生活化具象枚举，同目标 3 纪律）。
    SUBJECT_LOCK_HANDOFF: """# 单焦距·交接锁（桥接过渡：发话者话音落下，镜头切回主角一侧）
- 第一拍只承接发话的余势：话音落下、余音未散的那一瞬——不替发话者说新台词，不给他加新动作
- 随即把镜头切交主角一侧：他的身体先动——动作收拢、行装调整、周身感官的过渡、松劲与起步
- 过渡全程只跟主角一人：其他人物停在上一个画面里，不跟镜头、不抢戏
- 末句把画面引到下文首句的门口即止，不跨进去""",
}


def pick_subject_lock(picked_slots: Optional[List[str]], bridge: bool = False) -> str:
    """依点选槽位选定视点锁（互斥，纯函数）。

    优先序 物镜 > 静音 > 发话：多枚同缝时最独特的相机契约优先（物镜锁的
    「零人物」契约一旦混入人物动作即失效；发话锁与静音锁是人物焦点的两种
    相位，最后兜底）。toward_beat/echo/custom/空 → 不锁（默认缝合契约，
    逐字节零变化）。

    bridge（2026-09-13 模式仲裁）：桥接态下桥接引渡权高于静态发话锁——
    landing/speaker 的映射从发话锁切到交接锁（发话者话音落下→镜头切交
    主角侧完成物理引渡），消除「焦点钉死发话者」与「过渡留在主角一侧」
    的主体死锁（发话者常非主角）。物镜/静音锁与桥接不冲突（只写器物/
    只写开腔前缓冲，不定义镜头跟谁），不仲裁。
    """
    slots = {str(s or "").strip() for s in (picked_slots or [])}
    if slots & {"prop", "ambient"}:
        return SUBJECT_LOCK_PROP
    if "reply" in slots:
        return SUBJECT_LOCK_REPLY
    if slots & {"landing", "speaker"}:
        return SUBJECT_LOCK_HANDOFF if bridge else SUBJECT_LOCK_SPEAKER
    return ""


# ============================================================
# 白描契约与假感官封杀令（2026-09-09 实测事故紧急植入，用户逐字拍板）
# ============================================================
# 已迁出本模块（2026-09 收编批）→ services/style/texture_contracts.py
# （文章质感契约注册表，文风模块唯一权威；含按书覆盖与执法词表）。
# 病史留存：病灶=神经敏感式生理微知觉 + AI 模式化情绪开关（通用模型
# trace），与 08-27「负面禁令少而狠」导师结论的张力已申报——本块系实测
# 事故后的用户逐字拍板，最高优先级偏置。词级执法由 texture_contracts
# 执法词表经洗层/上屏快检/完稿审计旁路兜底，prompt 只是第一层防线。


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
    texture_contract_overrides: Optional[Dict[str, Dict[str, str]]] = None,
    previous_summary: str = "",
    recency_pin: str = "",
    contract: str = "motion",
    intent_source: str = "",
    subject_lock: str = "",
    suffix_anchor: str = "",
    picked_slots: Optional[List[str]] = None,
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
        contract: 双轨生成契约（2026-09-03 质感批次）：motion（默认，逐字节
            零变化）/ texture（质感档——_RULE_NEW_INFO 换 _RULE_TEXTURE，
            准许停在当下细写；选档判据在 services/adaptive/texture_contract.py）
        intent_source: 意图来源分档（2026-09-03 线 A）：outline/request=作者
            材料（目的地框，默认零变化）/ inferred=AI 反推的下一步方向（亮明
            「AI 猜的」身份，措辞降级为柔性参照）/ baton=章首接力棒（承接框）
        subject_lock: 单焦距主体守恒律（第二冲程 2026-09-09，pick_subject_lock
            产出）：物镜/发话/静音三锁互斥注入；空=零变化
        suffix_anchor: 中插桥接后文锚（2026-09-09 FIM）：光标后 ≤300 字已写
            正文（2026-09-13 扩窗：原 1-2 句裁剪截在省略号处，后文物证缺席）——
            非空注入双端边界块（上文起点/下文落点）与桥接铁律
        picked_slots: 零件槽位（与 picked_parts 同序）：含 'custom' 时注入
            「素材指令」规则——自定义镜头是作者给的素材不是成品文本，须用
            模型自己的句子重写（实测事故：成句自定义被原样吞进幽灵）

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
        texture_contract_overrides=texture_contract_overrides,
    ):
        system_prompt += _block

    parts_str = "、".join(picked_parts) if picked_parts else "（无——仅按作者原句顺势续写）"
    # 意图块措辞定档（2026-09-03 trace 实证）：旧标题「章节意图（方向参考，非
    # 强制）」+节拍原文 verbatim，模型把节拍当「现在该写的场面」——3/3 幽灵
    # 落地即消费节拍。重框为「几步之后的目的地」：现在不写它本身，只写通往它
    # 路上的画面；输出侧由 ghost-guard-beat-rush 代码闸兜底（供给>闸门>偏置）。
    # 线 A 分档：AI 来源的意图（inferred/baton）必须亮身份——不冒充作者材料，
    # 措辞降为柔性参照（猜错是常态，模型被明告可以不理会）。
    if not chapter_intent:
        intent_line = ""
    elif intent_source == "inferred":
        intent_line = (
            f"\n# 下一步方向（AI 从已写内容猜的，可能猜错——只作柔性参照："
            f"对得上正文的走势就顺着走，对不上就忽略它）\n{chapter_intent}"
        )
    elif intent_source == "baton":
        intent_line = (
            f"\n# 承接上一章（章首衔接参照——顺着上一章的走向自然起笔，"
            f"不急着进新事件）\n{chapter_intent}"
        )
    else:
        intent_line = (
            f"\n# 几步之后的目的地（只作方向参照：现在不写它本身——它的场面、事件与"
            f"对白都留给几步之后，此刻只写通往它路上的画面）\n{chapter_intent}"
        )
    # 桥接铁律（FIM）：双端闭环——写完过渡即止，末句引向下文首句门口。
    # 主角一侧正向约束（2026-09-09 抢场事故）：旧版只说「不写什么」（下文禁
    # 区），模型面对空档最顺手的填充是把后文的登场反应提前演了（实测：幽灵
    # 「明姐迎上来攥着湿抹布」vs 后文「明姐端过来脸盆」——同叙事槽位换道具
    # 演两遍，字面闸零重合拦不住）——正向给出「写什么」：过渡留在主角身上。
    _has_suffix = bool(str(suffix_anchor or "").strip())
    bridge_rule = ""
    if _has_suffix:
        bridge_rule = (
            "\n桥接铁律（本笔是上下文之间的过渡）：\n"
            "- 过渡镜头留在主角一侧——他的动作收拢、行装调整、周身感官的过渡、松劲与起步；"
            "后文首句写谁登场、做什么、说什么，那就是下文的——其他人物此刻不出场、不抢戏；"
            "\n"
            "- 末句把画面引到下文首句的门口即止，不跨进去；下文里已写的动作、物件、台词"
            "一概不提前出现（换个道具演同一件事也算提前消耗），后文交代的位置与物证"
            "（人在哪、有什么、没有什么）同样不得违背，写完过渡即止。"
            "\n"
        )
    prev_line = _prev_summary_line(previous_summary)
    pin_line = _recency_pin_line(recency_pin)
    # 双轨契约：质感档把「每句必须推进」换成「停在当下细写」（其余戒律不动）
    advance_rule = _RULE_TEXTURE if contract == "texture" else _RULE_NEW_INFO

    # 中插桥接双端边界（2026-09-09 FIM）：光标停在上下文之间——注入下文锚
    # 与桥接铁律（上文起点=作者原句块天然承担）；空=逐字节零变化。
    # 2026-09-13 事故：120 字窗太窄（前端旧取窗又截在省略号处），后文物证
    # （「巷子里没灯」）没进锚，幽灵写出与之矛盾的「路边有灯」——窗放宽到
    # 300 字（对齐细纲胶囊双端锚定的后端口径），措辞补「不得与之矛盾」。
    suffix_block = ""
    if str(suffix_anchor or "").strip():
        _suffix = str(suffix_anchor).strip()[:300]
        suffix_block = (
            "\n# 下文已写（你只补它与上文之间的过渡，下文里的事一概不许提前消耗，"
            "也不得与它矛盾——其中的位置与物证同样已写定）\n"
            f"{_suffix}\n"
        )

    # 自定义镜头素材指令（2026-09-09 逐字回声事故）：作者的自定义输入常是
    # 成句散文，模型会原样吞进幽灵（+句号）——明确它是素材不是成品文本。
    # 仅 custom 槽位注入；空/无 custom=逐字节零变化
    custom_rule = (
        "\n自定义镜头是素材指令，不是成品文本：用你自己的句子把这个画面写进正文"
        "（句式与节奏按正文此刻的文风重新组织），不逐字照抄它的原文。\n"
        if (picked_slots or []) and "custom" in [str(x) for x in picked_slots]
        else ""
    )

    # 悬空引号交接指令（2026-09-13 目标 2·X 路线，prompt 偏置半边）：断点
    # 停在未闭合的开引号上时，模型最顺手的填充是另起动作子句——拼合上屏
    # 成「“林尘笑了笑，“…」双开引号（确定性修文须触碰画布或重排幽灵，
    # 均违反纯追加红线，故 prompt 显式定义交接义务 + 影子检攒语料双轨）。
    # 断点非悬空引号 = 逐字节零变化。
    dangling_quote_rule = (
        "\n断点引号交接（第一句直接接话）：作者正文停在一个未闭合的引号内——"
        "第一句先把这句话说完并补上闭合引号，不要另起动作或旁白；语气顺着"
        "前文说话人往下走。\n"
        if (fragment or "").rstrip()[-1:] in ("“", "「", "『", "\"")
        else ""
    )

    if mode == "stitch":
        # 视点锁注入（第二冲程）：三锁文本在零件块之后、指令区之前——
        # 相机契约紧贴零件出现，模型把它读作「这枚零件的拍法」；空=逐字节零变化
        lock_block = (
            f"\n{_SUBJECT_LOCK_TEXTS[subject_lock]}\n"
            if subject_lock in _SUBJECT_LOCK_TEXTS else ""
        )
        # 追加式契约（2026-08-26 实测修复）：幽灵纯追加在作者原句之后，
        # 原句已在画布里——旧契约「原句一字不改保留在片段中」会致屏幕复读。
        user_prompt = f"""# 上文衔接（保持连续，不重复）
{rolling_prefix or "（开篇）"}{prev_line}
{intent_line}

# 作者原句（已在你身后的画布里——绝不重复它，从它的断点直接往下写）
{fragment}{suffix_block}

# 选定镜头零件（必须落地为画面）
{parts_str}
{lock_block}{custom_rule}{dangling_quote_rule}
请只输出续写部分：从作者原句的断点顺势接下去（原句停在半句就先自然补完这一句，从断点最后一个词的后面直接续，不要重说断点附近的词），把零件落地为具体画面。{bridge_rule}零件是画面灵感，作者正文的事实最高优先——零件与正文此刻的场景/时间明显矛盾时（如物件此刻并不在手边），改造零件贴合当下场景，改造不了就舍弃它，绝不硬塞。禁止以任何形式重复原句（原文复读、换说法复述都不行）。
{advance_rule}
{_RULE_ENDING}
控制在 {target_chars} 字以内。只输出正文，不要标题、不要解释。{pin_line}"""
    else:  # continue
        user_prompt = f"""# 上文衔接（保持连续，不重复已写动作与意象）
{rolling_prefix or "（开篇）"}{prev_line}
{intent_line}

# 作者当前正文（顺着它的语气、人称、节奏往下写）
{fragment}
{dangling_quote_rule}
请顺着作者正文往下续写，控制在 {target_chars} 字以内：
{advance_rule}
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
    texture_contract_overrides: Optional[Dict[str, Dict[str, str]]] = None,
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
        texture_contract_overrides=texture_contract_overrides,
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

# ---- C3 outline 全锚点行（docs/reports/foundation-hardening.md §5.3）----
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
    texture_contract_overrides: Optional[Dict[str, Dict[str, str]]] = None,
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
        texture_contract_overrides=texture_contract_overrides,
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
    texture_contract_overrides: Optional[Dict[str, Dict[str, str]]] = None,
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
        texture_contract_overrides=texture_contract_overrides,
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
- next_direction：窄问题——作者接下来这一步最可能往哪写（一句话，落到画面层面，如"他压着怒火继续上工，等一个私下质问的机会"）。这是卡片舱定向的素材，比 arc 更重要
- evidence：你的判断依据——从正文里原样摘出的 1-3 句（逐字引用，不得改写）。交不出正文依据的判断会被丢弃
- emotion_curve：情绪走向（3-5 个阶段，每阶段 {phase, emotion, energy 1-10}）
- setup_points：本章应铺陈的要点（2-4 个，作者未来写作可呼应）
- deviations：如果你注意到正文走向与章节卡（must_hit_events/foreshadow_ops）有偏差，列出（每条一句话）；无偏差则空数组

扎根作者已写的正文（这是事实），参考设定养料（角色/世界观/前文摘要）。不要编造没写过的剧情。
作者亲手写下的材料（打算/速记胶囊/大纲）优先级最高——与正文迹象冲突时，以作者材料为准。
只输出 JSON，不要解释。"""


def build_intent_inference_prompt(
    written_text: str,
    outline_text: str,
    nutrients: dict,
    soft_constraints: dict,
    *,
    spine_intent: str = "",
    spine_anchors: Optional[List[str]] = None,
    outline_notes: Optional[List[str]] = None,
    corrections: Optional[List[dict]] = None,
    intent_trajectory: Optional[List[str]] = None,
    correction_count: int = 0,
) -> tuple:
    """构建意图反推 prompt。

    Args:
        written_text: 作者已写的正文（层 1 拼接）
        outline_text: 章节大纲（可为空——此时纯从正文反推）
        nutrients: 设定养料（SettingsBundle.nutrients()）
        soft_constraints: 软约束（SettingsBundle.soft_constraints()，含 must_hit_events）
        spine_intent: 打算 tab 的一句话意图（作者亲手材料，最高优先级；空=缺席零变化）
        spine_anchors: 打算里的 pending 锚点文本（空=缺席零变化）
        outline_notes: 正文里细纲胶囊的速记原文（作者最稀疏最真实的意图信号；空=缺席）
        corrections: 近期纠正史 [{guessed, corrected}]——作者口味校准教材（空=缺席）
        intent_trajectory: 前几章作者亲笔「打算」轨迹（按章序「第N章：…」行，
            2026-09-03 线 B 意图画像——学这位作者的粒度与口吻；空=缺席零变化）
        correction_count: 纠正史总条数（≥2 时追加保守指令——纠正频繁说明
            这位作者的方向常被猜错，宁答「方向不明」也别硬编）

    Returns:
        (system_prompt, user_prompt)
    """
    # 作者亲手材料块（意图加固 2026-09-03）：稀疏材料的优先级最高——反推的任务
    # 是补齐作者没写的，不是覆盖作者写下的
    author_block = ""
    parts = []
    if spine_intent.strip():
        parts.append(f"本章打算（作者写的方向一句话）：{spine_intent.strip()[:60]}")
    anchor_lines = [a.strip() for a in (spine_anchors or []) if a and a.strip()]
    if anchor_lines:
        parts.append("本章非写不可的情节（作者定的）：" + "；".join(anchor_lines[:5]))
    note_lines = [n.strip() for n in (outline_notes or []) if n and n.strip()]
    if note_lines:
        parts.append("正文里的速记胶囊（作者随手记的剧情备忘）：\n" + "\n".join(f"- {n[:60]}" for n in note_lines[:5]))
    if parts:
        author_block = "\n# 作者亲手材料（最高优先级——与它冲突时以它为准）\n" + "\n\n".join(parts) + "\n"

    # 意图画像块（2026-09-03 线 B）：作者在前几章亲手定的「打算」轨迹——
    # 把「平均作者」往「这位作者」的粒度/口吻上拉（学表达习惯，不抄内容）
    trajectory_block = ""
    traj_lines = [t.strip() for t in (intent_trajectory or []) if t and t.strip()]
    if traj_lines:
        trajectory_block = (
            "\n# 这位作者在前几章亲手定的方向（按章序——学他/她写意图的粒度与口吻，"
            "不是抄内容）\n" + "\n".join(f"- {t[:80]}" for t in traj_lines[:5]) + "\n"
        )

    # 纠正史块（意图加固 2026-09-03）：作者过去把 AI 的猜测改成过什么——
    # 口味校准的 few-shot 教材，把「平均作者」往「这位作者」拉。
    # 线 B 纠正量统计：纠正频繁 = 这位作者的方向常被猜错 → 追加保守指令
    # （拿不准就答「方向不明」——硬编的猜测会被作者纠正，不如诚实降级）
    correction_block = ""
    corr_lines = []
    for c in (corrections or [])[:3]:
        if not isinstance(c, dict):
            continue
        g = str(c.get("guessed") or "").strip()[:40]
        r = str(c.get("corrected") or "").strip()[:60]
        if g and r:
            corr_lines.append(f"- AI 曾猜「{g}」，作者纠正为「{r}」")
    if corr_lines:
        correction_block = (
            "\n# 这位作者的纠正史（校准口味用——他/她过去怎样修正猜测）\n"
            + "\n".join(corr_lines) + "\n"
        )
        if correction_count >= 2:
            correction_block += (
                f"（近期已有 {correction_count} 次纠正——猜保守一点："
                f"拿不准就在 next_direction 答「方向不明」，别硬编）\n"
            )

    # 喂全（意图加固 2026-09-03）：开放伏笔与角色此刻状态是判断「接下来往哪走」
    # 的关键上下文——条件注入，无数据缺席（旧书零变化）
    extra_lines = ""
    open_hooks = str(soft_constraints.get("open_hooks") or "").strip()
    if open_hooks:
        extra_lines += f"开放伏笔（还没回收的线）：{open_hooks[:200]}\n"
    dynamics = str(soft_constraints.get("character_dynamics") or "").strip()
    if dynamics:
        extra_lines += f"角色此刻状态：{dynamics[:200]}\n"

    user_prompt = f"""# 章节大纲
{outline_text or "（作者未提供大纲，请从正文反推）"}
{author_block}{trajectory_block}{correction_block}
# 作者已写正文
{written_text[:2000]}

# 设定养料
角色：{nutrients.get('characters', '（无）')}
世界观：{nutrients.get('worldview_text', '（无）')[:200]}
前文摘要：{nutrients.get('previous_summary', '（无）')[:200]}
{extra_lines}
# 章节卡参考（软约束，作者可偏离，偏离要标注）
必达事件：{soft_constraints.get('must_hit_events', '（无）')}
伏笔操作：{soft_constraints.get('foreshadow_ops', '（无）')}

推断本章意图。输出 JSON：
{{"arc": "...", "next_direction": "...", "evidence": ["正文原句 1", "..."], "emotion_curve": [{{"phase": "开端", "emotion": "紧张", "energy": 6}}], "setup_points": ["..."], "deviations": ["..."]}}"""
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
    """dock system prompt 的分节定义（when 谓词消费 ctx.has_nearby / template）。

    在场制分节（2026-09-08 红队「地面+重力场」重构）：ctx.has_onstage 时启用
    三档物质性（T1 自然力/T2 派生质感须指源/T3 上手物白名单）与情境模板
    （dialogue/combat/panorama）分节；legacy 形态（无 onstage）分节集合与
    拼装顺序逐字节等同旧实现——零变化契约。
    """
    from backend.services.constraints.prompt_sections import PromptSection

    def _has_nearby(ctx: Dict) -> bool:
        return bool(ctx.get("has_nearby"))

    def _no_nearby(ctx: Dict) -> bool:
        return not bool(ctx.get("has_nearby"))

    def _has_guess_only(ctx: Dict) -> bool:
        # 意图入舱（2026-09-03）：无大纲就近节拍、但有意图反推的方向猜测时，
        # toward_beat 槽位改由猜测供料（猜想的「目的地」取代作者大纲节拍）
        return not bool(ctx.get("has_nearby")) and bool(ctx.get("has_guess"))

    def _onstage(ctx: Dict) -> bool:
        return bool(ctx.get("has_onstage"))

    def _no_onstage(ctx: Dict) -> bool:
        return not bool(ctx.get("has_onstage"))

    def _default_tpl(ctx: Dict) -> bool:
        # 模板只在在场制下分派（build 侧归一：无 onstage 强制 default）——
        # dialogue/combat/panorama 模板自带槽位取向，toward_beat 子句退位
        return ctx.get("template") == "default"

    def _dialogue(ctx: Dict) -> bool:
        return ctx.get("template") == "dialogue"

    def _combat(ctx: Dict) -> bool:
        return ctx.get("template") == "combat"

    def _panorama(ctx: Dict) -> bool:
        return ctx.get("template") == "panorama"

    def _bridge(ctx: Dict) -> bool:
        # 中插桥接（2026-09-09 FIM）：光标停在上下文之间——位置事实最硬，
        # 优先于一切场景模板，且不依赖在场制（legacy 书同样分派）
        return ctx.get("template") == "bridge"

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
            when=lambda ctx: _has_nearby(ctx) and _default_tpl(ctx),
            text="""- slot=toward_beat【通往节拍】（出 1 枚）：通往「作者大纲·就近节拍」那拍的**第一步**过渡画面，不是节拍本身的画面
"""),
        PromptSection(
            key="slot-toward-guess",
            when=lambda ctx: _has_guess_only(ctx) and _default_tpl(ctx),
            text="""- slot=toward_beat【通往方向】（出 1 枚）：通往「本章方向猜测」那一步的过渡画面——方向是 AI 从正文猜的（作者没写大纲），只取方向感，不编造猜测里没有的情节事件
"""),
        PromptSection(
            key="slot-echo-mat",
            when=lambda ctx: bool(ctx.get("has_echo_mat")),
            text="""- slot=echo【呼应】（至多 1 枚）：呼应前情回响或读者期待的碎片——呼应哪一条就在 JSON 里标 from_memory/from_expectation + echo_ref（所呼应条目在对应素材块里的序号，从 1 数）。呼应是**当下场景里的新画面**侧面带出旧物/旧事（书页翻到夹层、扳手柄上的旧划痕），不是旧画面换个说法重演——重演前情等于没给选项
"""),
        PromptSection(
            key="slot-echo-none",
            when=lambda ctx: not bool(ctx.get("has_echo_mat")),
            # 前情强买强卖修复（2026-09-11）：无相关回响/期待素材时不再要求
            # 呼应件——召回侧已加相关性门，此处同口径放开（允许零呼应）
            text="""- slot=echo：本批无相关前情或读者期待素材——无需强行生成呼应件，全部生成现场分镜镜头（呼应类允许零枚）
"""),
        PromptSection(key="slot-ambient", text="""- slot=ambient【氛围】（其余补位）：无叙事包袱的画面（光影/声响/物件质感），作者随手就能用，不指向任何去向

"""),
        PromptSection(
            key="slots-dialogue",
            when=_dialogue,
            text="""- slot=reply【接话缓冲】（对白时刻出 1 枚）：受话人接住刚落那句话的微前兆——指尖停住、抬眼、把到嘴边的话咽回去；只写反应的开头，回应与打断本身是作者的
- slot=prop【在场特写】（出 1 枚）：镜头对准「本场在册」里的一件物或一个人，JSON 里标 "anchor_ref": 序号（在册名单的序号，从 1 数）；半句台词起步（台词+说话人小动作）可作 landing/reply 的形态
"""),
        PromptSection(
            key="slots-combat",
            when=_combat,
            text="""- 搏杀时刻的槽位取向：landing 写主角一侧的起手交换（他的身体、他的兵器、他的感知）；ambient 写感官闪现（痛感、呼吸、声响——来源指得出来）；slot=prop 写环境武器（「本场在册」里的物，标 anchor_ref）；破绽、胜负、转折不出——那些是节拍
"""),
        PromptSection(
            key="slots-bridge",
            when=_bridge,
            text="""- 中插桥接（本批补写上下文之间的十秒过渡）：机位四取向，每枚落在一类——物理整理（手上与身上的动作收拢、行装与器具的调整，如收工具、系外袍、勒枪背带）/ 环境基底感官（温度、光线、声响的起伏变化，如暮色压下来、风里的湿气变了、远处的响动停了）/ 身体动势（重心与步伐的变化、力气的松紧，如脚步放慢、攥拳又松开、呼出一口长气）/ 视线流转（目光从上一动作的客体移向下一幕的方向）——示例只示意类别，写正文此刻真实可取的物件与感官，不照抄示例物件
- 下文已写的事实是禁区：user 材料里「下文已写」块中的事（登场的人、说出的话、做出的动作）一概不出——过渡只写抵达它之前的路
- 末枚机位把画面引向下文首句的门口，但不跨进去
"""),
        PromptSection(
            key="slots-panorama",
            when=_panorama,
            text="""- 初入新地的槽位取向：ambient 写定场质感（以「本场在册」场景行的地点档案为源）；slot=prop 写第一件可上手物（「本场在册」，标 anchor_ref）；landing 写人物踏入的第一步；新地的人物与物件以「本场在册」为准，册外不添
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
        PromptSection(key="scene-anchoring-head", text="""【场景锚定 —— 碎片长在作者此刻的场景里】
"""),
        PromptSection(
            key="props-two-class",
            when=_no_onstage,
            text="""- 道具分两类：**氛围件**（光线、灰尘、天气、远景、声响）可自由生发，不算发明；**上手件**——人物握、拿、放、捡、掏、开的那个物件——要有出处（本章正文/场景设定/设定养料/就近节拍四处之一）：人物碰过的物件会进入后续所有画面，作者接了它就欠下连续性债
"""),
        PromptSection(
            key="props-three-tier",
            when=_onstage,
            text="""- 道具三档（「本场在册」已列出此刻在场的人物与物件）：**自然力**（天气、光线、声响、气温——无主不可拾）自由生发；**派生质感**（气味、反光、震动、浮尘）要指得出它的来源物——指不出来源的质感就是造物；**上手物件与出场人物**只从「本场在册」或本章正文已出现者里取：人物碰过的物件会进入后续所有画面，作者接了它就欠下连续性债
"""),
        PromptSection(key="scene-anchoring-rest", text="""- 不复述已写：碎片是还没落笔的画面——作者已写的画面（刚引用的原文、刚描写过的物件）换个说法再端上来，等于没给选项
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
3. 多样性：不要全是 action 或全是 line，混搭让作者有不同方向
4. landing 必居首位；呼应类至多 1 枚

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
    intent_guess: str = "",
    onstage: Optional[Dict] = None,
    template: str = "default",
    suffix_anchor: str = "",
) -> tuple:
    """构建挂件生发 prompt。

    Args:
        recent_text: 作者当前段落（≤400 字，超长保尾——作者的真位置在段尾）
        projections: 层 3 推测（SegmentProjection.to_dict() 列表）
        nutrients: 设定养料（角色物理特征/资产/地点）
        hard_constraints: 硬约束（banned_words / canon_private_labels；character_statics
            键仍在 bundle 但 dock 已不消费——2026-09-13 B2 输入减肥批移除 statics 注入）
        direction_weights: 已退役参数（B7 方向权重葬礼；保留签名兼容，忽略）
        salience_hints: 热层六槽热集的具名提示行（salience.compute_salience 产出；空=无提示块
        reader_expectations: 读者期待（[{type, description, tension}]，最多取前 2 条进块；
            呼应期待的碎片须标 from_expectation，呼应=侧面暗示，绝不直接揭晓）
        spine_intent: 章级谋篇意图一句话（P1.4 M2；空=不注入。8-14 字零件吃
            画像的同款克制——只给方向不给展开）
        intent_guess: 意图反推的下一步方向（2026-09-03 意图入舱；仅无大纲就近
            节拍时由调用方传入——toward_beat 槽位的猜测供料。空=逐字节零变化）
        onstage: 本场在册压缩投影（2026-09-08 红队「地面」；None=零变化契约——
            legacy 书 prompt 逐字节等同旧实现。结构：
            {entities: [{name, state}], props: [{name, desc}], scene_line,
             offstage_characters, offstage_assets}）
        template: 情境分镜模板（default/dialogue/combat/panorama/bridge；除
            bridge（光标位置事实，不依赖在场制）外，无 onstage 时强制归一
            default——场景模板分节只在在场制下分派）
        suffix_anchor: 中插桥接后文锚（2026-09-09 FIM）：光标后 ≤300 字边界窗
            （2026-09-13 扩窗，原 1-2 句）
            已写正文——非空即编译 bridge 模板与「下文已写」禁区块

    Returns:
        (system_prompt, user_prompt)
    """
    banned = "、".join(hard_constraints.get("banned_words", [])[:30])
    # 桥接供给切断（2026-09-09 FIM 实测「卡片接着文末写」事故）：桥的方向由
    # 后文锚定义——此前只摘了槽位子句，素材块照灌。推测/方向猜测/就近节拍
    # 全部以画布全文（含光标后已写内容）为坐标系推导，桥接态下是「已写后文
    # 的剧透」而非方向（实测：插入点在送别，推测块与猜测块全是文末饭桌场景，
    # 卡片被拽去接着文末写）。切断供给>命令拒绝（同哲学先例：_prebeat_projections
    # 接缝裁剪——LLM 没见过的素材漏不出来）。空 suffix_anchor=逐字节零变化。
    is_bridge = bool(str(suffix_anchor or "").strip())
    # 分节编译（约束治理一期）：无就近节拍→节拍依赖子句整节缺席；禁词表
    # 经 «BANNED_WORDS» 占位注入（不能用 str.format——prompt 含 JSON 花括号）
    # 2026-09-03：猜测供料形态（无节拍+有方向猜测）编译进 toward_beat 变体子句
    guess_only = not outline_nearby and bool(intent_guess.strip()) and not is_bridge
    # 在场制归一（2026-09-08 红队「地面」）：无投影时模板强制 default——
    # 模板分节引用「本场在册」，投影缺席时分节悬空
    if not onstage and template != "bridge":
        template = "default"
    from backend.services.constraints.prompt_sections import render_sections

    system_prompt = render_sections(
        _dock_system_sections(),
        {
            # 桥接态按「无节拍供给」编译系统分节（素材块已切断，分节与材料同口径）
            "has_nearby": bool(outline_nearby) and not is_bridge,
            "has_guess": guess_only,
            "has_onstage": bool(onstage),
            "template": template,
            # 回响素材有无（2026-09-11 柔性化）：回响与期待都空时 echo 槽位
            # 分节换「允许零呼应」变体，与召回侧相关性门同口径
            "has_echo_mat": bool(memory_echoes or reader_expectations),
        },
    ).replace("«BANNED_WORDS»", banned or "（无）")

    # 推测方向摘要（桥接态切断：推测锚的是全文末尾的「接下来」，插入点处是后文剧透）
    # B2 输入减肥（2026-09-13）：降为 1 条×1 拍——8-14 字零件只需要一个方向
    # 暗示，多条推测喂给小模型实测只会被逐条压缩成挂件（mimo 教训）。
    proj_lines = []
    if not is_bridge:
        for p in (projections or [])[:1]:
            beats = p.get("possible_beats", []) if isinstance(p, dict) else []
            for b in beats[:1]:
                proj_lines.append(f"- {b.get('event', '')}（焦点：{b.get('anchors', [])}）")
    proj_text = "\n".join(proj_lines) if proj_lines else "（无推测，基于当前段落自由生发）"

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
    if outline_nearby and not is_bridge:
        nearby_lines = "\n".join(f"- {b}" for b in outline_nearby[:2])
        nearby_block = f"""
# 作者大纲·就近节拍（几步之外的目的地——剧情正朝那里去；碎片只给通往它的第一步，不是节拍本身的画面）
{nearby_lines}
"""

    # 方向猜测块（2026-09-03 意图入舱）：无大纲就近节拍时，意图反推的
    # 下一步方向顶上「目的地」位——如实标注是 AI 猜的（作者没写大纲），
    # 只取方向感；有真节拍时此块缺席（作者材料永远压过猜测）
    guess_block = ""
    if guess_only:
        guess_block = f"""
# 本章方向猜测（AI 从正文反推的，作者没写大纲——供定向参考；碎片只给通往它的第一步，不编造猜测之外的情节事件）
{intent_guess.strip()[:80]}
"""

    # 本场在册块（2026-09-08 红队「地面」）：T3 白名单 + anchor_ref 序号坐标系
    # （entities 在前 props 在后统一编号——模型报序号，后端回查拼 note，模型
    # 不经手出处文本，与 echo_ref 同一防御哲学）
    onstage_block = ""
    if onstage:
        _ent = onstage.get("entities") or []
        _prop = onstage.get("props") or []
        _reg_lines = []
        for i, e in enumerate(_ent, start=1):
            _st = str(e.get("state") or "").strip()
            _reg_lines.append(f"- [{i}] {e.get('name')}" + (f"：{_st[:20]}" if _st else ""))
        for j, p in enumerate(_prop, start=len(_ent) + 1):
            _d = str(p.get("desc") or "").strip()
            _reg_lines.append(f"- [{j}] {p.get('name')}" + (f"：{_d[:16]}" if _d else ""))
        _scene = str(onstage.get("scene_line") or "").strip()
        if _reg_lines or _scene:
            _body = "\n".join(_reg_lines) if _reg_lines else "（此刻无在册人物/物件）"
            if _scene:
                _body += f"\n场景：{_scene}"
            onstage_block = (
                "\n# 本场在册（此刻在场的人物与物件——上手物件与出场人物只从这里或正文已出现处取；"
                "特写哪件就标 anchor_ref 序号）\n" + _body + "\n"
            )

    # 中插桥接后文锚块（2026-09-09 FIM）：下文是禁区边界而非素材——
    # 过渡机位严禁提前消耗其中事实；空=整块缺席（零变化契约）。
    # 2026-09-13 事故：120 字截断让后文物证缺席（幽灵「路边有灯」vs 后文
    # 「巷子里没灯」）——放宽到 300 字并补「不得与之矛盾」。
    suffix_block = ""
    if str(suffix_anchor or "").strip():
        suffix_block = (
            "\n# 下文已写（你要补的是它与上文之间的过渡——块里的事一概不许提前发生，"
            "也不得与之矛盾）\n"
            f"- {str(suffix_anchor).strip()[:300]}\n"
        )

    # 过采样（约束治理一期）：要求 4-6 枚，校对环丢违规件后仍保 3-4——
    # 检测器误报由过采样吸收；toward_beat 子句仅在有就近节拍/方向猜测时出现。
    # 引力措辞（2026-09-08 红队「重力场」）：在场制下配额退役——节拍/猜测是
    # 染色矢量不是专职槽位义务；legacy 书保持配额原文（零变化契约）
    if template == "bridge":
        beat_clause = ""   # 桥的方向由后文锚定义，不吃大纲引力/意图猜测
    elif onstage:
        if outline_nearby:
            beat_clause = "碎片的画面方向贴近就近节拍即可，无需专职代表；"
        elif guess_only:
            beat_clause = "碎片的画面方向贴近方向猜测即可，无需专职代表；"
        else:
            beat_clause = ""
    elif outline_nearby:
        beat_clause = "给了就近节拍则含 1 枚 toward_beat；"
    elif guess_only:
        beat_clause = "含 1 枚 toward_beat（通往方向猜测）；"
    else:
        beat_clause = ""

    # 养料在场制拆分（2026-09-08 红队 R1）：在册全行 + 场外仅名字——上手件
    # 的「设定养料」全书池出处就地收窄为「本场在册」；无 onstage 用原养料
    # （legacy 逐字节零变化）
    if onstage:
        _ent = onstage.get("entities") or []
        _chars_text = "；".join(
            f"{e.get('name')}" + (f"（{str(e.get('state') or '')[:20]}）" if str(e.get("state") or "").strip() else "")
            for e in _ent
        ) or "（无在场人物）"
        _off_chars = onstage.get("offstage_characters") or []
        if _off_chars:
            _chars_text += f"\n（场外人物，只可经呼应带出：{'、'.join(_off_chars[:12])}）"
        _assets_text = "；".join(str(p.get("name")) for p in (onstage.get("props") or [])) or "（无在场物件）"
        _off_assets = onstage.get("offstage_assets") or []
        if _off_assets:
            _assets_text += f"\n（场外物件：{'、'.join(_off_assets[:12])}）"
        _locations_text = str(onstage.get("scene_line") or "").strip() or "（无场景钉）"
    else:
        _chars_text = nutrients.get("characters", "（无）")
        _assets_text = nutrients.get("assets", "（无）")
        _locations_text = nutrients.get("locations", "（无）")

    user_prompt = f"""# 作者当前段落
{recent_text[-400:]}
{onstage_block}{suffix_block}{spine_line}{nearby_block}{guess_block}
# 接下来的画面方向（方向参考——优先从作者当前段落生发，不得整句照搬推测画面）
{proj_text}
{dw_block}{exp_block}{echo_block}
# 设定养料（角色物理特征/资产/地点，自由用作画面素材）
角色：{_chars_text}
资产：{_assets_text}
地点：{_locations_text}

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
