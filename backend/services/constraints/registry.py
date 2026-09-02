# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 约束登记册（约束治理一期 · docs/constraint-governance.md 唯一权威）
"""
约束登记册：每条约束声明自己住哪层、由谁执法、失败代价由谁承担、什么状态。

设计意图（2026-09-02，导师框架「违约三要素 × 执法五形态」）：
- 判据不再是「代码判得了吗」，而是执法位置选择——供给切断(input) > 输出
  代码闸(gate) > 确定性改写(rewrite) > prompt 偏置(prompt) > 事后审计(audit)；
- status 是代码内数据不是文档：shadow（只埋点不动作）→ live → report-only
  → retired 留档，翻转即生效，promote 门槛写在各条 origin/commentary；
- surface = 失败代价承担者：menu（作者没见过的菜单件，可自动丢弃）、
  ghost（已上屏幽灵，只提示绝不拦截）、report（只进报告）、data（数据层）。

首批只录有执法挂钩的约束（~25 条）；纯文档性条文惰性补录——一次性转录
全部条文是誊写工作量且分类错误会污染换模型 checklist（导师审查裁决）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# 执法形态（可靠性降序）
ENFORCE_INPUT = "input"          # 供给切断（最高：拿不到就无法违反）
ENFORCE_GATE = "gate"            # 输出代码闸（确定性判定，丢弃/过滤）
ENFORCE_REWRITE = "rewrite"      # 确定性改写（截断/替换/剥离）
ENFORCE_PROMPT = "prompt"        # prompt 偏置（概率性，服从率 <100%）
ENFORCE_LOG = "log"              # 只埋点（shadow/report-only/数据度量）

# 失败代价承担者
SURFACE_MENU = "menu"            # 菜单件——可自动丢弃
SURFACE_GHOST = "ghost"          # 幽灵草稿——只提示不拦截（作者主权红线）
SURFACE_REPORT = "report"        # 只进完稿报告/台账
SURFACE_DATA = "data"            # 数据层读面

# 生命周期
STATUS_SHADOW = "shadow"          # 只埋点不动作（攒精确率数据）
STATUS_LIVE = "live"              # 在役执法
STATUS_REPORT_ONLY = "report-only"
STATUS_RETIRED = "retired"


@dataclass(frozen=True)
class Constraint:
    """一条约束的登记项。layers 列出该约束的所有执法层（同一约束多层执法
    用同一 id 关联——如 dock 心理词族 prompt 禁令+代码嗅探双层）。"""

    id: str
    statement: str
    layers: List[str] = field(default_factory=list)
    enforcement: str = ENFORCE_LOG
    surface: str = SURFACE_GHOST
    status: str = STATUS_LIVE
    when: str = ""          # 条件注入谓词的人读描述（数据驱动编译器消费其代码形态）
    origin: str = ""        # 事故/决策溯源
    cost_chars: Optional[int] = None  # prompt 条文的字符成本（代码闸条文为 None）


REGISTRY: List[Constraint] = [
    # ---- 字数与接缝（stitch 输出闸族，2026-08-26/08-29 事故迁移）----
    Constraint(
        id="outline-word-gate",
        statement="outline/burst 长稿字数双层闸：超 target×1.6 压缩重试，仍超句界截断 ×1.5（保尾）",
        layers=[ENFORCE_REWRITE], enforcement=ENFORCE_REWRITE, surface=SURFACE_GHOST,
        origin="kimi/mimo 对字数指令严重不服从（120 目标实测 600-700 字）",
    ),
    Constraint(
        id="stitch-word-gate",
        statement="stitch/continue 字数两级闸：保头截断 ×1.5 + 压缩改写，空产出回落截取稿",
        layers=[ENFORCE_REWRITE], enforcement=ENFORCE_REWRITE, surface=SURFACE_GHOST,
        origin="2026-08-28 扩面/08-29 两级（用户拍板）",
    ),
    Constraint(
        id="stitch-repeat-strip",
        statement="幽灵不得复读作者原句：等价类前缀剥离",
        layers=[ENFORCE_REWRITE], enforcement=ENFORCE_REWRITE, surface=SURFACE_GHOST,
        origin="2026-08-26 缝合契约反转",
    ),
    Constraint(
        id="stitch-tail-repeat-strip",
        statement="半句断点的尾缀复读剥离（产出以原句尾缀开头即剥）",
        layers=[ENFORCE_REWRITE], enforcement=ENFORCE_REWRITE, surface=SURFACE_GHOST,
        origin="2026-08-29「续写接不上」事故（trace 实证）",
    ),
    Constraint(
        id="seam-first-sentence-exempt",
        statement="压缩改写首句豁免：补完断点的首句物理摘出不进压缩",
        layers=[ENFORCE_REWRITE], enforcement=ENFORCE_REWRITE, surface=SURFACE_GHOST,
        origin="2026-08-29 压缩模型删除衔接首句事故",
    ),
    Constraint(
        id="proper-noun-visible-filter",
        statement="专名称呼表只含 在场∪死亡∪本章提及∪可见文本点名的名字（供给切断：名字不进 prompt 无从被硬编）",
        layers=[ENFORCE_INPUT], enforcement=ENFORCE_INPUT, surface=SURFACE_GHOST,
        origin="2026-09-01「工头拧流光螺栓」穿帮（书级全量名单+必须原样使用被当登场指令）",
    ),
    # ---- ghost_guard 上屏快检族（只提示不拦截）----
    Constraint(
        id="ghost-guard-dead-speak",
        statement="死者名出现于幽灵文本 → 疑点提示",
        layers=[ENFORCE_GATE], enforcement=ENFORCE_GATE, surface=SURFACE_GHOST,
        origin="P5 ghost_guard 四检",
    ),
    Constraint(
        id="ghost-guard-canon-leak",
        statement="canon [private] 标签词复现 → 泄底提示",
        layers=[ENFORCE_GATE], enforcement=ENFORCE_GATE, surface=SURFACE_GHOST,
    ),
    Constraint(
        id="ghost-guard-secret-leak",
        statement="私有档案 ≥4 字片段复现 → 泄底提示",
        layers=[ENFORCE_GATE], enforcement=ENFORCE_GATE, surface=SURFACE_GHOST,
    ),
    Constraint(
        id="ghost-guard-cliche-hit",
        statement="禁忌面命中（任一 blocker 或总数 ≥3）→ 提示",
        layers=[ENFORCE_GATE], enforcement=ENFORCE_GATE, surface=SURFACE_GHOST,
    ),
    Constraint(
        id="ghost-guard-out-of-scene",
        statement="非在场/提及名单的实体名 × 上手级动词框架共现 → 越界登场疑点（shadow：只落台账不进 GHOST_DONE）",
        layers=[ENFORCE_INPUT, ENFORCE_GATE], enforcement=ENFORCE_GATE, surface=SURFACE_GHOST,
        status=STATUS_SHADOW,
        when="visible_names 非空（world 书）",
        origin="2026-09-01 流光穿帮的输出侧镜像；promote 门槛=语料库准入+≥20 次真实命中人工抽检 FP<10%",
    ),
    # ---- dock 挂件校对环族（菜单件可自动丢弃）----
    Constraint(
        id="dock-banned-words",
        statement="挂件命中 canon private 标签/blocker 禁词 → 丢件（prompt 禁词表+代码校对双层）",
        layers=[ENFORCE_PROMPT, ENFORCE_GATE], enforcement=ENFORCE_GATE, surface=SURFACE_MENU,
    ),
    Constraint(
        id="dock-camera-stock",
        statement="挂件命中镜头陈词（目光失焦族）→ 丢件",
        layers=[ENFORCE_GATE], enforcement=ENFORCE_GATE, surface=SURFACE_MENU,
        origin="2026-08-27 感知层菜单第一眼不带生成层在禁的库存词",
    ),
    Constraint(
        id="dock-no-psych",
        statement="挂件禁心理描写：prompt 铁律禁令+代码词族嗅探双层（同一约束两层执法）",
        layers=[ENFORCE_PROMPT, ENFORCE_GATE], enforcement=ENFORCE_GATE, surface=SURFACE_MENU,
    ),
    Constraint(
        id="dock-rehash",
        statement="挂件不得整句照搬推测/复述已写画面：n-gram 重叠检测超阈值丢件",
        layers=[ENFORCE_PROMPT, ENFORCE_GATE], enforcement=ENFORCE_GATE, surface=SURFACE_MENU,
        origin="2026-08-25 实测 mimo 把推测逐条压缩成挂件（prompt 杠杆不够，2026-09-02 下沉代码）",
    ),
    Constraint(
        id="dock-beat-overlap",
        statement="挂件与就近节拍原文去标点后 ≥4 字连续重叠 → 抢拍丢件（供给侧切断的残余兜底）",
        layers=[ENFORCE_GATE], enforcement=ENFORCE_GATE, surface=SURFACE_MENU,
        origin="2026-08-26 节拍对白事故（mimo 三连不服从→2026-08-27 供给切断→2026-09-02 重叠检测补残余）",
    ),
    Constraint(
        id="dock-part-shape",
        statement="挂件形状过滤（非 dict/短于 2 字/尾部超编裁剪）",
        layers=[ENFORCE_GATE], enforcement=ENFORCE_GATE, surface=SURFACE_MENU,
    ),
    Constraint(
        id="dock-prebeat-supply-cut",
        statement="节拍侧（beat/after）推测素材不进挂件取材池（切断供给>命令拒绝）",
        layers=[ENFORCE_INPUT], enforcement=ENFORCE_INPUT, surface=SURFACE_MENU,
        origin="2026-08-27 导师裁决：碎片 3+4 曾把整条节拍弧预写完",
    ),
    Constraint(
        id="dock-note-backend-assembly",
        statement="挂件出处副行一律后端拼装，模型不经手出处文本（自由创作出处=编造风险）",
        layers=[ENFORCE_INPUT], enforcement=ENFORCE_INPUT, surface=SURFACE_MENU,
        origin="2026-08-29「不知所云」重构",
    ),
    # ---- 呈现平面（洗层/保名）----
    Constraint(
        id="wash-blocker-replace",
        statement="blocker+alternative 禁词词边界替换（warning 永不动手）",
        layers=[ENFORCE_REWRITE], enforcement=ENFORCE_REWRITE, surface=SURFACE_GHOST,
        origin="三平面分权 P1（2026-08-29）",
    ),
    Constraint(
        id="wash-p2-repair",
        statement="残留 blocker 单次句级修补（60s 冷却+严格验收）",
        layers=[ENFORCE_REWRITE], enforcement=ENFORCE_REWRITE, surface=SURFACE_GHOST,
    ),
    Constraint(
        id="deai-name-guard",
        statement="去AI味改写稿中 kg 在场/死者名单实体名必须逐字保留否则回退原稿",
        layers=[ENFORCE_REWRITE], enforcement=ENFORCE_REWRITE, surface=SURFACE_GHOST,
        origin="deai 集成契约 §6",
    ),
    # ---- 数据层（在场推演救回，2026-09-02）----
    Constraint(
        id="lexical-presence-fallback",
        statement="participant/事件定位缺失的实体从事件 note 词法命中补在场，标 presence_source=lexical（不回写事实源）",
        layers=[ENFORCE_INPUT], enforcement=ENFORCE_INPUT, surface=SURFACE_DATA,
        origin="实例书事件无结构化链接→在场推演恒空（流光事故深层土壤）",
    ),
    Constraint(
        id="event-participant-gap",
        statement="事件缺参与者结构化链接 → 台账计数（数据缺口可度量；补录走回填脚本/切片 badge 提示）",
        layers=[ENFORCE_LOG], enforcement=ENFORCE_LOG, surface=SURFACE_DATA,
        status=STATUS_LIVE,
    ),
    # ---- report-only（只进台账/报告）----
    Constraint(
        id="persona-drift",
        statement="幽灵叙述段第一人称密度异常（人称漂移）→ 只落台账，不上屏",
        layers=[ENFORCE_LOG], enforcement=ENFORCE_LOG, surface=SURFACE_REPORT,
        status=STATUS_REPORT_ONLY,
        origin="B5 report-only 起步（导师裁决：攒数据后再决定是否进感知带）",
    ),
]

_BY_ID: Dict[str, Constraint] = {c.id: c for c in REGISTRY}


def get_constraint(constraint_id: str) -> Optional[Constraint]:
    return _BY_ID.get(constraint_id)


def status_of(constraint_id: str) -> str:
    """约束当前状态（未知 id 返回 live——登记滞后不阻塞执法）。"""
    c = _BY_ID.get(constraint_id)
    return c.status if c else STATUS_LIVE


# ============================================================
# 强措辞 lint（剂量治理的度量面；词典=导师定档七词，section 标题计入）
# ============================================================

STRONG_WORDS = ("铁律", "绝不", "必须", "禁止", "不许", "严禁", "务必")


def scan_prompt_wording(text: str) -> Dict[str, int]:
    """统计 prompt 文本中的强措辞用字（剂量治理度量面）。

    返回 {词: 出现次数, ...}（仅非零项）+ "total" 总计。基线事实：dock
    prompt 2026-09-02 前强措辞 15+ 处（铁律×3 节名+绝不×3+必须×6+禁止×3+
    不许×2）——编译器化后验收闸=「铁律」≤3 且 total 较基线显著下降。
    """
    counts: Dict[str, int] = {}
    total = 0
    for w in STRONG_WORDS:
        n = text.count(w)
        if n:
            counts[w] = n
            total += n
    counts["total"] = total
    return counts
