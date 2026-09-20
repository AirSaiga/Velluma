# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
上下文预算常量表（P5 批次 3 · A3a，docs/reports/foundation-hardening.md §4.1）。

收编自适应辅助注入链（设定 bundle / canon / RAG 回响 / 文风样本 /
stitch-ghost 五模式）散落的全部上下文截断与配额魔法数字。

纪律（D7 拍板：A3a 纯重构，零行为变化；A3b 机制落地，默认零变化）：
- A3a 段只做「改名搬家」——每个常量值必须与收编前逐字节一致，改值即任务失败；
- 安全绳：test_style_injection / test_context_contract / test_stitch_context /
  test_private_channel / test_world_bridge_presence / test_budget_allocate
  等单测锁死装配输出，全绿即证明 prompt 逐字节不变；
- 零三方/零项目 import——被 context / canon / rag / style / prompts / routes
  多方引用，保持零依赖防环（A3b 分配器只用标准库 dataclasses/typing）。

分组按数据域组织（角色/资产/地点/关系/canon/读者期待/前情回响/作者样本/
文风/空间/私有/书级杂项/模式剂量），命名带单位后缀：
_MAX_ENTRIES=条数上限 · _MAX_CHARS=字数上限 · _K=检索条数 · _FETCH_LIMIT=预取条数。
每个常量注释含：取舍理由 + 首版出处模块。

后续（A3b，已落地见文件尾「跨块动态分配」段）：allocate() 按优先级动态分配，
裁剪统一收口——本表是唯一调参界面（改剂量改这里，实测期的事）。

副作用：无（纯常量 + 纯函数）。
"""

from dataclasses import dataclass, replace
from typing import Dict, List, Optional

# ============================================================
# 角色（characters）
# ============================================================

# 世界 overlay 角色名单上限——prompt 预算护栏：20+ 角色书只送「在场 → 有事态
# → 重要度」排序最优的前 16 名（A2 在场提权后第一键为在场）。
# 首版出处：services/context/world_bridge.py load_world_overlay

# 角色 prompt 文本行数上限——bundle 侧二次收口：world 名单 16 条进
# _characters_text 再截 8（旧章级绑定路径同一函数同一上限）；A1 起先过滤
# private 后截，公开实体顶替空出的席位。
# 首版出处：services/context/settings_bundle.py _characters_text

# 每角色永恒设定（static_prompt）注入字数——world 八字段结构化档案（外貌/
# 性格/背景/目标/动机/语言习惯/习惯/技能）的紧凑摘要预算，200 字够放
# 两三个字段的全文。
# 首版出处：services/context/settings_bundle.py _characters_text

# 每角色此刻状态（dynamic_state）注入字数——「位于北岸要塞，在途（进度40%）」
# 类切片行天然短，150 字封顶防异常长事态灌爆。
# 首版出处：services/context/settings_bundle.py _characters_text

# ============================================================
# 资产（assets）
# ============================================================

# 世界 overlay 资产名单上限——资产无位置状态（事件溯源哲学），纯重要度
# 降序取前 8。
# 首版出处：services/context/world_bridge.py load_world_overlay

# 资产 prompt 文本行数上限——_assets_text 逐行（A1：private 资产先过滤）。
# 首版出处：services/context/settings_bundle.py _assets_text
ASSETS_PROMPT_MAX_ENTRIES = 8

# 每条资产简介注入字数——intro/描述只当画面素材，120 字摘要够用。
# 首版出处：services/context/settings_bundle.py _assets_text

# ============================================================
# 地点（locations）
# ============================================================

# 世界 overlay 地点名单上限——WorldLocation 只取 name 进 prompt（无档案
# 文本），12 个够覆盖一书的地理骨架。
# 首版出处：services/context/world_bridge.py load_world_overlay

# 地点 prompt 文本行数上限——纯名称行，6 个防罗列。
# 首版出处：services/context/settings_bundle.py _locations_text
LOCATIONS_PROMPT_MAX_ENTRIES = 6

# ============================================================
# 关系（relations）
# ============================================================

# 世界 overlay 关系名单上限——只留 t 时刻活跃边（A2：任一端在场提前），
# 仍截 8。
# 首版出处：services/context/world_bridge.py load_world_overlay

# 关系 prompt 文本行数上限——旧表路径与世界路径共用 _relationships_text。
# 首版出处：services/context/settings_bundle.py _relationships_text
RELATIONS_PROMPT_MAX_ENTRIES = 8

# 每条关系描述注入字数——「师徒（授业三年）」类短语，80 字封顶。
# 首版出处：services/context/settings_bundle.py _relationships_text

# ============================================================
# Canon（真相层：表/里/伏笔）
# ============================================================

# [private] 真相条数上限——秘密是强约束（每条带两行禁令说明），10 条封顶
# 防 prompt 被禁忌占满。
# 首版出处：services/canon/consistency.py build_canon_context_for_prompt
CANON_PRIVATE_MAX_ENTRIES = 10

# [private] 每条真相文本（canon_text）字数——秘密的「是什么」，150 字。
# 首版出处：services/canon/consistency.py build_canon_context_for_prompt
CANON_PRIVATE_TEXT_MAX_CHARS = 150

# [private] 揭示计划（reveal_plan）字数——「第N章由谁揭穿」类短语，80 字。
# 首版出处：services/canon/consistency.py build_canon_context_for_prompt
CANON_REVEAL_PLAN_MAX_CHARS = 80

# [public] 节点预取条数——fetch 15 再过滤（非 hook 且有 public_text）取前 10，
# 预取留余量防过滤后不足额。
# 首版出处：services/canon/consistency.py build_canon_context_for_prompt
CANON_PUBLIC_FETCH_LIMIT = 15

# [public] 已建立事实条数上限——「必须遵守」级约束，与 private 同量级 10 条。
# 首版出处：services/canon/consistency.py build_canon_context_for_prompt
CANON_PUBLIC_MAX_ENTRIES = 10

# [public] 每条事实文本（public_text）字数——已建立事实宜短促可核对，120 字。
# 首版出处：services/canon/consistency.py build_canon_context_for_prompt
CANON_PUBLIC_TEXT_MAX_CHARS = 120

# [hook] 伏笔账本（plot_ledgers）预取条数——open 状态先 fetch 30，过滤
# 「有真相面文本」后取前 8。
# 首版出处：services/canon/consistency.py build_canon_context_for_prompt
CANON_HOOK_LEDGER_FETCH_LIMIT = 30

# [hook] 伏笔块条数上限——账本线、未迁移 canon hook 兜底线、块最终封顶
# 三处同值（改额度三处同动，预取跟随块配额才不会白取）。
# 首版出处：services/canon/consistency.py build_canon_context_for_prompt
CANON_HOOK_MAX_ENTRIES = 8

# [hook] 每条伏笔行文本字数——「[key] 强度=N：真相一句话」格式，100 字。
# 账本线与兜底线两处同值。
# 首版出处：services/canon/consistency.py build_canon_context_for_prompt
CANON_HOOK_TEXT_MAX_CHARS = 100

# ---- canon 段的下游抽取（hard_constraints，解析 build 出的 canon_context）----

# 泄密校对用 private 标签词上限——解析 [private] 段「- 标签：」行取前 10，
# 与注入侧条数同量级（注入多少校多少）。
# 首版出处：services/context/settings_bundle.py _extract_canon_private_labels
CANON_PRIVATE_LABEL_MAX_ENTRIES = 10

# public 事实行抽取字数——与注入侧 canon 表条目（120 字）同口径镜像。
# 首版出处：services/context/settings_bundle.py _extract_canon_public_facts
CANON_PUBLIC_FACT_MAX_CHARS = 120

# public 事实行抽取条数——与注入侧条数（10 条）同口径镜像。
# 首版出处：services/context/settings_bundle.py _extract_canon_public_facts
CANON_PUBLIC_FACT_MAX_ENTRIES = 10

# ============================================================
# 读者期待（reader_mirror）
# ============================================================

# 活跃期待条数上限——按张力降序前 3，供方向权重（读者力）与 dock 零件
# 生发消费；期待是参考力不是主约束，少量即可。
# 首版出处：services/context/settings_bundle.py _reader_expectations_view
READER_EXPECTATION_MAX_ENTRIES = 3

# 每条期待描述字数——一句话说清「读者在等什么」，40 字。
# 首版出处：services/context/settings_bundle.py _reader_expectations_view
READER_EXPECTATION_DESC_MAX_CHARS = 40

# ============================================================
# 前情回响（RAG 记忆倒灌，services/rag/recall.py）
# ============================================================

# 每条回响截断字数——回响是「呼应素材」不是复述，160 字半段足够锚定
# 细节；B 层（词法）与 V 层（向量）两处同口径。
# 首版出处：services/rag/recall.py
ECHOES_MAX_CHARS = 160

# stitch 五模式回响条数（k）——亦是 recall_memories 的签名默认值（当前
# 无隐式调用方；显式传 k 的只有 stitch=3 / dock=2）。
# 首版出处：services/rag/recall.py + services/context/stitch_context.py
ECHOES_K_STITCH = 3

# 挂件生发（dock）回响条数——轻路径（8-14 字零件吃不到长上下文），少占预算。
# 首版出处：services/adaptive/components/dock_generator.py
ECHOES_K_DOCK = 2

# A 层结构化前情（世界事件）条数——精确但更「干」，少量即可；实际生效值
# = min(本常量, k)。原模块内私有常量 _WORLD_ECHO_LIMIT，A3a 收编改名。
# 首版出处：services/rag/recall.py
ECHOES_WORLD_MAX_ENTRIES = 3

# 召回查询命中世界实体上限——防长文本全员命中把 A 层摊薄。原模块内私有
# 常量 _MATCHED_ENTITY_LIMIT，A3a 收编改名。
# 首版出处：services/rag/recall.py
ECHOES_MATCHED_ENTITY_MAX = 4

# 向量流 embedding 查询截断——embedding 输入封顶，长 query 只送前 500 字
# 语义。
# 首版出处：services/rag/recall.py _vector_echoes
ECHOES_EMBED_QUERY_MAX_CHARS = 500

# ============================================================
# 作者样本（few-shot 笔迹示范，services/style/retrieval.py）
# ============================================================

# 样本条数 k——「一段范例胜过十句形容」，但 few-shot 多则稀释主任务；
# 亦是 retrieve_author_samples 的签名默认值（stitch 装配显式同值传递）。
# k≤2 × 1200 字 ≈ 单次注入 ≤2400 字（文风设计稿 §4 E1 预算口径）。
# 首版出处：services/style/retrieval.py
AUTHOR_SAMPLES_MAX_K = 2

# burst 档样本条数（C3 · docs/reports/foundation-hardening.md §5.3）：走向卡连写是
# 段落级生成，范例权重最高 → k 2→3 加量；其余四模式维持 MAX_K=2 不变
# （stitch 装配按 mode 选 k）。首版出处：services/context/stitch_context.py
AUTHOR_SAMPLES_K_BURST = 3

# burst 档样本块配额增量（C3 样本加量 +1250）：k=3 满配比 k=2 多 1 条
#（"【示范 3】\n" 7 字 + AUTHOR_SAMPLE_MAX_CHARS=1200 + 条间 "\n\n" 2 = 1209，
# 向上取整 1250 吸收逐字计数误差）——MODE_CONTEXT_BUDGETS["burst"] 与
# MODE_BLOCK_BUDGET_OVERRIDES 的 burst 样本配额同用此剂量。
AUTHOR_SAMPLES_C3_TOPUP = 1250

# 每条样本截断字数——truncate_sample 句界截断的窗口上限。
# 首版出处：services/style/retrieval.py
AUTHOR_SAMPLE_MAX_CHARS = 1200

# ============================================================
# 文风（正面画像渲染，settings_bundle.render_style_positive）
# ============================================================

# 画像五维每维取值字数——「短句为主，偶尔长句铺陈」级一句话画像，120 字。
# 首版出处：services/context/settings_bundle.py render_style_positive
STYLE_PROFILE_VALUE_MAX_CHARS = 120

# 段落节奏描述字数——「两长一短」类节奏口诀，80 字。
# 首版出处：services/context/settings_bundle.py render_style_positive
STYLE_PARAGRAPH_RHYTHM_MAX_CHARS = 80

# 画像块总行数上限——五维（≤5）+ 段落节奏（1）理论最多 6 行，10 是防御性
# 封顶（防画像字段膨胀）。2026-09-14 去参数化：旋钮行（≤3）与对话目标行
# 移除后由 14 收缩回 10——省出的注意力让给亲笔样本（few-shot 示范块）。
# 首版出处：services/context/settings_bundle.py render_style_positive
STYLE_POSITIVE_MAX_LINES = 10

# ============================================================
# 空间常识（D4 比例尺切片，docs/reports/map-scale-spatial.md §5）
# ============================================================

# spatial_brief 注入字数——「≤3 行粗估」的距离行块，300 字封顶；双门槛
# （world_sourced 且已标定）不满足时整块为空（零变化契约）。
# 首版出处：services/prompts/adaptive_prompts.py _spatial_block
SPATIAL_BRIEF_MAX_CHARS = 300

# ============================================================
# 私有设定（A1 secrets 通道，docs/reports/foundation-hardening.md §3.1）
# ============================================================

# 私有块条数上限——与 canon 表/里（各 10 条）同量级取保守值：秘密条目过多
# 本身是设定异味。批次 2 落地时即在 adaptive_prompts 预埋 A3a 收编点注释。
# 首版出处：services/prompts/adaptive_prompts.py（A1）；原位置 import 再导出
SECRETS_BLOCK_MAX_ENTRIES = 8

# 私有块每条字数——与 canon 表条目（150/120 字）同口径，够放「背景+目标」
# 两字段摘要；私有序列不做条内换行处理（static_prompt 天然多行按原样截断）。
# 首版出处：services/prompts/adaptive_prompts.py（A1）；原位置 import 再导出
SECRETS_ENTRY_MAX_CHARS = 150

# ============================================================
# 书级杂项（摘要/母题/禁词/章节卡/伏笔/专名，settings_bundle）
# ============================================================

# 滚动摘要（rolling_summary）注入字数——全书前情的滚动压缩，to_prompt_context
# 与 nutrients 两条出口同值。
# 首版出处：services/context/settings_bundle.py SettingsBundle
ROLLING_SUMMARY_MAX_CHARS = 500

# 书级核心母题禁忌（core_motifs_taboos）注入字数——母题是定调短语不是檄文。
# 首版出处：services/context/settings_bundle.py SettingsBundle
CORE_MOTIFS_MAX_CHARS = 300

# 禁词合并上限（prohibitions 四源合并：SystemCliche + style_blacklist +
# negative_list + 反 AI 腔禁词表）——合并去重后截 60，防 prompt 膨胀。
# 首版出处：settings_bundle._merge_banned_words（已随任务包 B 双写收敛删除）；
# 现权威消费方：services/style/prohibitions.py
BANNED_WORDS_MERGED_MAX_ENTRIES = 60

# 禁词 prompt 文本行上限——style_negative 顿号串再截 30（校对列表与
# 文本行两级口径）。
# 首版出处：settings_bundle._style_negative_text（已随任务包 B 双写收敛删除）；
# 现权威消费方：services/style/prohibitions.py（prompt_text 同口径顿号串）

# 开放伏笔（open_hooks）prompt 行数上限——「本章可呼应」的提示面。
# 首版出处：services/context/settings_bundle.py _hooks_text

# 每条伏笔内容注入字数——带/不带 ledger_key 两分支同值。
# 首版出处：services/context/settings_bundle.py _hooks_text

# 章节卡必达事件条数上限——章节卡文本与软约束两条出口同值（同一
# must_hit_events 字段的两视角）。
# 首版出处：services/context/settings_bundle.py _chapter_card_text /
# _must_hit_events_text

# 章节卡伏笔操作条数上限——埋设/推进/回收的操作清单，两条出口同值。
# 首版出处：services/context/settings_bundle.py _chapter_card_text /
# _foreshadow_ops_text

# 专名表（proper_nouns）默认上限——角色名+资产名防缝合称呼漂移。
# 首版出处：services/context/settings_bundle.py SettingsBundle.proper_nouns
PROPER_NOUNS_MAX_ENTRIES = 20

# ============================================================
# 模式剂量（stitch-ghost 注入窗口）
# ============================================================

# open（点火）大纲主燃料——空章冷启动时大纲是唯一创作依据，给足 800 字；
# 路由装配与 build_opening_prompt 内部双重截断同值（幂等护栏）。
# 首版出处：routes/chapter_generation/adaptive.py stitch 路由 +
# services/prompts/adaptive_prompts.py build_opening_prompt
STITCH_OUTLINE_MAX_CHARS = 800

# open（点火）世界观基调——只定基调不铺设定，200 字克制；路由与 builder
# 双截同值。
# 首版出处：同上
STITCH_WORLDVIEW_MAX_CHARS = 200

# open（点火）上一章结尾摘要——衔接提示而非剧情回顾，300 字（builder 侧
# 单点截断，路由透传原文）。
# 首版出处：services/prompts/adaptive_prompts.py build_opening_prompt
STITCH_PREV_SUMMARY_MAX_CHARS = 300

# outline/burst 模式衔接窗口（rolling_prefix 尾窗）——段落级续写需要更长
# 语气锚；context-preview 取章节正文尾部同窗口（预览与注入同源）。
# 首版出处：routes/chapter_generation/adaptive.py（stitch 路由 + context-preview）
# 2026-08-25 实测调窗（500→1200）：真实 trace 显示窗口长期顶满上限，burst 要写
# 700 字却只看 500 字上文，场景级连贯不够——段落级生成配场景级视野。
STITCH_ROLLING_LONG_MAX_CHARS = 1200

# stitch/continue 模式衔接窗口——顺句续写小窗口防束缚手感（continue 轻档）。
# 首版出处：routes/chapter_generation/adaptive.py stitch 路由
# 2026-08-25 实测调窗（200→800）：真实 trace 坐实「驴头不对马嘴」主因之一——
# 窗口钉死上限（200/200），模型只看得见两三句话，不知道此刻场景在哪；
# 800 字 ≈ 一个完整场景的上下文，token 代价约 +400/次，可接受。
STITCH_ROLLING_SHORT_MAX_CHARS = 800

# outline 模式后文锚定窗口（after_text 头窗）——细纲胶囊后文只做「引向」，
# 300 字足够。
# 首版出处：routes/chapter_generation/adaptive.py stitch 路由
STITCH_AFTER_TEXT_MAX_CHARS = 300

# 记忆召回 query 的正文尾窗——回响检索锚只需最近语气（B2 起随装配段
# 迁至 stitch_context，值自旧路由逐字继承）。
# 首版出处：services/context/stitch_context.py assemble_stitch_context
STITCH_RECALL_QUERY_TAIL_CHARS = 150

# 章节意图兜底 / open 召回 query 的大纲前 200 字——作者未显式给意图时用
# 大纲开头代言。
# 首版出处：services/context/stitch_context.py assemble_stitch_context
STITCH_INTENT_OUTLINE_MAX_CHARS = 200

# outline 档 spine 全锚点行条数上限（C3 · docs/reports/foundation-hardening.md §5.3）
# ——「本章锚点：A（待兑现）；B（已兑现）…」注入意图区。与路由侧
# SPINE_MAX_ANCHORS=5（routes/chapter_generation/adaptive.py 端点 5.6）同值：
# spine 存档即已 ≤5，此处是 builder 直调调用方的防御性封顶。
# 首版出处：services/prompts/adaptive_prompts.py build_outline_expand_prompt
STITCH_OUTLINE_SPINE_ANCHORS_MAX = 5

# 谋篇建议（spine-suggest）LLM 预算——保留 thinking 的设计意图不变，但 800
# 曾被 MiMo 隐藏思考整个烧光返回空（2026-08-25 真实 trace：finish=length、
# content 空）。给思考留真实余量；空输出仍兜底重试一次（端点侧 REASONING_DISABLED）。
# 首版出处：routes/chapter_generation/adaptive.py 端点 spine-suggest
SPINE_SUGGEST_MAX_TOKENS = 2400


# ============================================================
# 跨块动态分配（A3b · docs/reports/foundation-hardening.md §4.2，2026-08-20）
# ============================================================

# 机制分两级：
# - 块内级（既有，不动）：各块候选条目由生产者按优先级排序并按上方常量截条数
#   （world_bridge 名单序=在场→事态→重要度 / recall 质量序 / retrieval 偏好序），
#   本期不改任何条目上限；
# - 跨块级（本期新增）：每模式一个 system 注入总字符预算 MODE_CONTEXT_BUDGETS，
#   只有总预算被实际突破时才裁剪——软块按 SOFT_BLOCK_TRIM_ORDER 从尾往前收缩
#   （先减条数，减到零整块缺席），硬块（canon/secrets/proper_nouns——作者录的
#   强约束数据）永不裁剪。软块让出的额度自动反哺硬块的存活空间（硬块内容以
#   上方常量上限为天花板，不无限膨胀——builder 已按常量截断，allocate 不扩）。
#
# 纪律（D7 后半）：初值 = 各块常量 worst-case 总和 → 默认路径 allocate 是恒等
# 操作，注入逐字节不变（test_budget_allocate 零变化锁）。分模式差异化剂量
# （continue 轻 / burst 重）留待实测期与批次 4（C3）调参——本期五模式同值。

# 名字/标签类字段（实体名 / canon 标签 / 伏笔 key）无常量上限，按 16 字/个计
# ——现实命名远低于此；这是初值表的显式假设。改名超长的书可能触发预算收缩，
# 属机制设计内行为（预览预算条可见被裁信息，不是静默丢弃）。
_NAME_ALLOWANCE_CHARS = 16


# ---- 每块配额（BLOCK_CHAR_BUDGETS）----
# 逐块 worst-case 计算（固定头按 adaptive_prompts._xxx_block 实际文案逐字数，
# 条目按本表常量上限 + 名字 16 字假设；数值向上取整，吸收逐字计数误差）：
#
# style_positive = 1460
#   固定头 56（两行标题+说明行）+ 10 行（STYLE_POSITIVE_MAX_LINES，2026-09-14
#   旋钮行移除后 14→10）× 139（"- "+标签16+"："+画像值 120）+ 9 个换行
#   ——56+1390+9=1455，取整 1460。
# author_samples = 2500
#   固定头 42 + 2 条（AUTHOR_SAMPLES_MAX_K）×（"【示范 1】\n" 7 字 +
#   AUTHOR_SAMPLE_MAX_CHARS=1200）+ 条间 "\n\n" 2 + 尾句 37——实测 2494。
#   ⚠ 配额按 k=2（continue 档）编制；burst 档 k=3（C3）的配额在
#   MODE_BLOCK_BUDGET_OVERRIDES 按模式覆盖，基表不追高。
# proper_nouns = 420
#   固定头 79（标题行+「称呼规范非登场清单」引导句，2026-09-01 穿帮修复改
#   措辞后实测变长）+ 20 名（PROPER_NOUNS_MAX_ENTRIES）× 16 字
#   + 19 个顿号——实测 418。
# canon = 5480
#   块头 20 + canon_context 三段 worst-case（consistency.build_canon_context_
#   for_prompt 格式）：[private] 段头 33 + 10 条×（"- "+标签16+"："+150
#   （CANON_PRIVATE_TEXT_MAX_CHARS）+"（揭示计划："+80
#   （CANON_REVEAL_PLAN_MAX_CHARS）+"）"+ 换行 + 提醒行 37 + 换行）；
#   [public] 段头 23 + 10 条×（"- "+标签16+"："+120
#   （CANON_PUBLIC_TEXT_MAX_CHARS））+ 换行；[hook] 段头 25 + 8 条
#   （CANON_HOOK_MAX_ENTRIES）×（"- [key16] 强度=999："+100
#   （CANON_HOOK_TEXT_MAX_CHARS））+ 换行——实测（含块头）5475。
# secrets = 1400
#   固定头 37 + 8 条（SECRETS_BLOCK_MAX_ENTRIES）×（"- "+名16+"："+150
#   （SECRETS_ENTRY_MAX_CHARS））+ 7 个换行——实测 1396。
# echoes = 545
#   固定头 52（标题行+说明行）+ 3 条（ECHOES_K_STITCH）×（"- "+
#   ECHOES_MAX_CHARS=160）+ 2 个换行——实测 540。
# spatial = 325
#   固定头 24 + SPATIAL_BRIEF_MAX_CHARS=300——实测 324。
#
# 「实测」= 按上述口径构造满配输入、用 adaptive_prompts 现行块渲染函数量出的
# 精确长度（2026-08-20）；test_budget_allocate 的零变化锁用同一口径复验。
BLOCK_CHAR_BUDGETS: Dict[str, int] = {
    "style_positive": 1460,
    "author_samples": 2500,
    "proper_nouns": 420,
    "canon": 5480,
    "secrets": 1400,
    "echoes": 545,
    "spatial": 325,
}


# ---- 每模式总预算（MODE_CONTEXT_BUDGETS）----
# 初值 = Σ BLOCK_CHAR_BUDGETS = 12650（默认路径零变化的硬前提）。
# 预算口径 = render_system_blocks 七块字符总和（adaptive_prompts 注入序），
# 不含共享基座 _base_system 与 user prompt——基座是常量脚手架，没有分配问题。
# C3（§5.3，批次 4 分模式差异化首版）：burst 档样本 k=3 → 总预算上调
# AUTHOR_SAMPLES_C3_TOPUP（C3 样本加量 +1250），满配不触发 allocate 裁剪；
# 其余四模式维持基数（默认零变化）。
_MODE_CONTEXT_BUDGET_BASE = sum(BLOCK_CHAR_BUDGETS.values())

MODE_CONTEXT_BUDGETS: Dict[str, int] = {
    "continue": _MODE_CONTEXT_BUDGET_BASE,
    "stitch": _MODE_CONTEXT_BUDGET_BASE,
    "burst": _MODE_CONTEXT_BUDGET_BASE + AUTHOR_SAMPLES_C3_TOPUP,
    "outline": _MODE_CONTEXT_BUDGET_BASE,
    "open": _MODE_CONTEXT_BUDGET_BASE,
}

# ---- 按模式覆盖的块配额（C3）----
# 基表 BLOCK_CHAR_BUDGETS 按 k=2（continue 档）编制；burst 档 author_samples
# k=3 的配额在此上浮（同 AUTHOR_SAMPLES_C3_TOPUP 口径）。只作用于
# BlockUsage.budget_chars——预览预算条/调参界面的「每块配额」展示，防 burst
# 满配未裁剪、预算条却显示超配额的假超支观感；不影响 allocate 裁剪判定
# （裁剪只看模式总预算）。
MODE_BLOCK_BUDGET_OVERRIDES: Dict[str, Dict[str, int]] = {
    "burst": {
        "author_samples": BLOCK_CHAR_BUDGETS["author_samples"] + AUTHOR_SAMPLES_C3_TOPUP,
    },
}


# ---- 块硬度与裁剪序 ----
# 硬块（永不裁剪）：canon 表/里（强约束）、secrets（A1 私有设定）、proper_nouns
# （防称呼漂移的硬约束）——作者录的强约束数据不因预算丢失，宁可总注入超支。
HARD_BLOCK_KEYS = ("canon", "secrets", "proper_nouns")

# 软块裁剪序（从尾往前收缩：先减条数，减到零整块缺席）：
# echoes（呼应素材，最可让）→ author_samples（范例，重但可减条）→
# spatial（距离常识，单条块一裁即缺席）→ style_positive（画像行，
# 块头语义要求成段，最后动）。
SOFT_BLOCK_TRIM_ORDER = ("echoes", "author_samples", "spatial", "style_positive")


# ---- 分配单元与结果 ----

@dataclass
class BudgetBlock:
    """allocate 的分配单元：一个 system 注入块。

    entries 是**最终条目文本**（已含 "- " 行前缀 / "【示范 N】" 编号等块内
    格式），按生产者优先级序排列、已按本表常量截过条数——allocate 只做跨块
    级的减条，不改块内格式。render(entries=None) 用原条目渲染；空条目 →
    空串（整块缺席，prompt 逐字节零残留）。
    """

    key: str
    header: str                # 条目存活 ≥1 时渲染的固定头（含前导换行）
    entries: List[str]
    footer: str = ""           # 条目存活 ≥1 时渲染在条目后的固定尾（样本块收束句）
    separator: str = "\n"      # 条目连接符（样本块为 "\n\n"）
    hard: bool = False         # 硬块标记（HARD_BLOCK_KEYS），永不裁剪

    def render(self, entries: Optional[List[str]] = None) -> str:
        ents = self.entries if entries is None else entries
        if not ents:
            return ""
        return self.header + self.separator.join(ents) + self.footer


@dataclass
class BlockUsage:
    """单块配额使用明细（A3b 预览预算条与调参界面的数据源）。"""

    key: str
    chars: int                 # 裁剪后实际字符数（= render 长度）
    budget_chars: int          # 该块配额（BLOCK_CHAR_BUDGETS；0=未知块）
    entries_total: int         # 裁剪前条数（生产者给的满额）
    entries_kept: int          # 裁剪后存活条数
    trimmed: bool              # 是否被裁（entries_kept < entries_total）

    @property
    def trimmed_entries(self) -> int:
        return self.entries_total - self.entries_kept


@dataclass
class AllocationResult:
    """allocate 输出：裁剪后块列表 + 每块配额使用明细 + 总账。"""

    blocks: List[BudgetBlock]
    usages: List[BlockUsage]
    budget: int
    total_chars: int           # 裁剪后总字符（仍超预算=硬块撑死不让的部分）
    trimmed_any: bool          # 是否实际触发了裁剪（False=恒等路径）


def allocate(
    blocks: List[BudgetBlock],
    budget: int,
    block_budgets: Optional[Dict[str, int]] = None,
) -> AllocationResult:
    """把块列表压进总预算（纯函数；默认预算下恒等，注入逐字节不变）。

    规则（docs/reports/foundation-hardening.md §4.2）：
    1. 总字符 ≤ 预算 → 恒等返回（零变化安全绳——初值表即按此设计）；
    2. 超支 → 软块按 SOFT_BLOCK_TRIM_ORDER 从最可让的块开始，从尾往前逐条
       弃置（生产者优先级序的尾部=最不重要），减到零该块整块缺席；
    3. 硬块（hard=True）永不裁剪——全部软块让空仍超支时，超额保留
       （宁可超支不丢强约束）；硬块天花板是 builder 侧常量截断，本函数不扩。

    block_budgets（C3）：按模式覆盖的块配额（MODE_BLOCK_BUDGET_OVERRIDES），
    只影响 usages.budget_chars 的展示口径，不影响裁剪判定；缺省用基表
    BLOCK_CHAR_BUDGETS（既有调用方零变化）。

    纯度：不改动入参（块与条目列表均复制后操作），同输入同输出。
    复杂度：软块条目总数 ≤ 24（3+3+1+14；burst 档样本 C3 后 k=3），
    逐条重渲染对账可忽略。
    """
    quotas = BLOCK_CHAR_BUDGETS if block_budgets is None else {
        **BLOCK_CHAR_BUDGETS, **block_budgets,
    }
    working = [replace(b, entries=list(b.entries)) for b in blocks]
    originals = {b.key: len(b.entries) for b in blocks}

    def _total() -> int:
        return sum(len(b.render()) for b in working)

    total = _total()
    trimmed_any = total > budget
    if trimmed_any:
        for key in SOFT_BLOCK_TRIM_ORDER:
            if total <= budget:
                break
            blk = next((b for b in working if b.key == key and not b.hard), None)
            if blk is None:
                continue
            while total > budget and blk.entries:
                blk.entries.pop()  # 尾部=生产者优先级最低的条目
                total = _total()

    usages = [
        BlockUsage(
            key=b.key,
            chars=len(b.render()),
            budget_chars=quotas.get(b.key, 0),
            entries_total=originals[b.key],
            entries_kept=len(b.entries),
            trimmed=len(b.entries) < originals[b.key],
        )
        for b in working
    ]
    return AllocationResult(
        blocks=working,
        usages=usages,
        budget=budget,
        total_chars=total,
        trimmed_any=trimmed_any,
    )
