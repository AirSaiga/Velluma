# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
文章质感契约注册表（2026-09 白描封杀令收编批）。

唯一权威声明：凡「AI 该怎么写」的**系统级**质感约束（保护性规矩，非作者
个人口味），统一由本模块管辖。原「白描契约与假感官封杀令」硬编码在
services/prompts/adaptive_prompts.py，与文风模块并排存在、互不隶属；收编后
prompt 文件仅消费，不再持有文案。

两件资产，词令分家：
1. **系统默认契约（CONTRACTS）**：话语级行为规矩（禁脑补事故/禁台词抢跑/
   白描准则/禁逗号注水），块级注入 prompt，mode 门控（stitch/continue 专属
   末位高服从位），支持按书覆盖（books.texture_contracts JSON 列，
   缺键=系统默认）。文案系 2026-09-09 实测事故后**用户逐字拍板**，迁移时
   逐字保留。
2. **执法词表（ENFORCEMENT_ENTRY_SPECS）**：契约内病灶词的策展结构化版，
   供洗层（ghost_wash）/上屏快检（ghost_guard）/完稿审计三处旁路合并。
   **不进四源合并**——split_prohibition_tiers 渲染路径会撞「无卡无样本
   prompt 逐字节不变」零变化契约，hard_constraints 的 blocker 面会静默杀死
   挂件/走向卡候选（详见 docs/agent/style.md 质感契约节）。

执法词表策展说明：
- 全部 blocker 档、**不带 alternative**（对齐 default_cliches.py 2026-09-04
  审计修复：机械替身词会被洗层字面拼进正文）——洗层只记录命中 + 触发 P2
  句级修补重试。
- 「倒吸一口凉气」**有意不收录**：已是 SystemCliche blocker 种子
  （default_cliches.py），尊重作者在系统层的开关/豁免权，不重复收录。
- 「嘴角勾起」与已有「嘴角勾起一抹」重叠：洗层最长命中让位规则自动处理。
- 含 XX 占位病灶（震动顺着XX传进掌心）编成正则；「下意识地藏/缩」编正则
  防「下意识地」单用误伤正常叙述。

副作用：无（纯数据 + 纯函数）。文案改动只改本模块，prompt 即时生效。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# ============================================================
# 系统默认契约
# ============================================================

@dataclass(frozen=True)
class TextureRule:
    """契约内的单条可开关规矩（span 级拆条，逐字保留原行）。

    body = 该规矩在拍板原文中的**逐字文本段**（含尾部换行）；渲染=按序拼接
    启用段的原文，全启必须与 2026-09-09 拍板原文逐字节一致（SHA256 锁定）。
    """
    key: str
    title: str
    body: str


@dataclass(frozen=True)
class TextureContract:
    """单条质感契约（不可变）。

    Attributes:
        key: 稳定键（preview 块 key / 覆盖字典键，重命名=前端映射破坏）
        title: 人话标题（文风页「写作规矩」区展示）
        modes: 生效生成模式（stitch-ghost 五模式中的子集；末位高服从位注入）
        header: prompt 块头（含前导空行块间距约定与最高优先级框定）
        body: 契约全文（= 全启渲染结果；逐字保留的拍板原文）
        rules: 可独立开关的规矩项（段落级；空元组=整体开关契约）
    """
    key: str
    title: str
    modes: Tuple[str, ...]
    header: str
    body: str
    rules: Tuple[TextureRule, ...] = ()


# ============================================================
# 系统默认契约（白描封杀令）
# ============================================================

# ⚠ 规则段逐字保留（2026-09-09 实测事故后用户逐字拍板；拆条只切户籍不改字）。
# 结构：段1「绝对禁止」族（段头 + 规则 r1/r2）+ 段2 白描准则 + 段3 注水禁令；
# 段头随族内任一规矩存活（双关全关则整段消失，不留空头）。

_S1_HEAD = "【绝对禁止：假感官堆砌与生理微知觉（Anti-Pseudo-Sensory Ban）】\n"

RULE_PSEUDO_SENSORY = TextureRule(
    key="pseudo_sensory",
    title="严禁生理伪通感与廉价微表情",
    body=(
        "1. 严禁描写微观生理知觉与伪通感：\n"
        '   - 严禁出现："掌心发热/发烫"、"震动顺着XX传进掌心"、"指尖微凉/微颤"、"倒吸一口凉气"、"喉结滚动"、"呼吸一滞/一沉"等神经敏感式生理反应。\n'
        "2. 严禁套用AI模式化情绪开关：\n"
        '   - 严禁使用："眼里亮了一下又暗下去"、"眼中闪过一丝XX"、"下意识地藏/缩"、"嘴角勾起/扯动"等廉价微表情。\n'
    ),
)

RULE_NO_FABRICATION = TextureRule(
    key="no_fabrication",
    title="严禁脑补事故、替角色喊“成了”",
    body=(
        "3. 严禁擅自脑补事故与台词抢跑：\n"
        '   - 严禁擅自判定作者写完的动作是"失误/做错的"（如作者写接线成功，严禁脑补"那根接错的线头"）；\n'
        '   - 严禁擅自帮在场角色喊出"成了！"或展开下一段剧情争议。\n'
    ),
)

RULE_PLAIN_STYLE = TextureRule(
    key="plain_style",
    title="北方硬朗白描",
    body=(
        "【语言风格准则：北方硬朗白描（Narrative Economy）】\n"
        '1. 动词驱动，叙事经济：多用硬朗的动作动词，交代物理事实即可（如"把手在裤腿上蹭了蹭"、"侧耳听机器转动"），少用形容词与副词；\n'
        "2. 留白克制，拒绝作文腔：写动作就写动作，写器物就写器物，坚决剔除小学生作文式的通感抒情，语言质感向现实派短句靠拢。\n"
    ),
)

RULE_NO_COMMA_PAD = TextureRule(
    key="no_comma_pad",
    title="严禁逗号串联注水",
    body=(
        "【严禁逗号串联注水】：拒绝为了凑字数使用多个逗号串联同义从句。"
        "允许 25~35 字的短促利落单句，交代清楚动作或画面后立即使用句号收尾，宁短勿水。\n"
    ),
)

_BODY_LEADING = "\n"  # 三重引号块的前导换行（块间距约定的一部分）


def _compose_body(disabled: Optional[frozenset] = None) -> str:
    """按启用的规矩项逐字拼装契约正文（全启=拍板原文，SHA256 锁定）。

    disabled: 被关掉的规矩 key 集。段1 的段头随族内（r1/r2）任一规矩存活。
    """
    disabled = disabled or frozenset()
    segs: List[str] = []
    s1 = "" if "pseudo_sensory" in disabled else RULE_PSEUDO_SENSORY.body
    s1 += "" if "no_fabrication" in disabled else RULE_NO_FABRICATION.body
    if s1:
        s1 = _S1_HEAD + s1
        segs.append(s1)
    if "plain_style" not in disabled:
        segs.append(RULE_PLAIN_STYLE.body)
    if "no_comma_pad" not in disabled:
        segs.append(RULE_NO_COMMA_PAD.body)
    return _BODY_LEADING + "\n".join(segs)


# 全启 = 拍板原文（测试锁 SHA256：5f87fd9e…438c，迁移自 git HEAD
# adaptive_prompts._ANTI_PSEUDO_SENSORY_BLOCK 的逐字比对）。
SYSTEM_CONTRACT_BODY = _compose_body()

CONTRACTS: Dict[str, TextureContract] = {
    "anti_pseudo_sensory": TextureContract(
        key="anti_pseudo_sensory",
        title="白描契约与假感官封杀令",
        modes=("stitch", "continue"),
        # 前导空行=块间距约定（样本块裸收尾，无前导空行两节粘连、
        # 试衣间 \n\n# 块边界提取失位）——原 adaptive_prompts 注释口径迁移
        header="\n\n# 白描契约与假感官封杀令（最高优先级）\n",
        body=SYSTEM_CONTRACT_BODY,
        rules=(RULE_PSEUDO_SENSORY, RULE_NO_FABRICATION,
               RULE_PLAIN_STYLE, RULE_NO_COMMA_PAD),
    ),
}


def _disabled_rule_set(key: str, overrides: Optional[Dict[str, Any]]) -> frozenset:
    """从覆盖层读被关掉的规矩 key 集（只认契约登记过的规则键）。"""
    contract = CONTRACTS.get(key)
    if contract is None or not contract.rules:
        return frozenset()
    if not isinstance(overrides, dict) or not overrides:
        return frozenset()
    ov = overrides.get(key)
    if not isinstance(ov, dict):
        return frozenset()
    raw = ov.get("disabled_rules")
    if not isinstance(raw, (list, tuple, set)):
        return frozenset()
    known = {r.key for r in contract.rules}
    return frozenset(str(k) for k in raw if k in known)


def resolve_contract_body(
    key: str,
    overrides: Optional[Dict[str, Any]] = None,
) -> str:
    """契约生效正文：本书覆盖优先，缺键/无覆盖回系统默认。

    overrides 形态（books.texture_contracts 列）：{key: {"body": str,
    "disabled_rules": [rule_key, ...]}}。优先级：非空 body（整文覆盖，
    高级编辑态）> disabled_rules（规矩开关）> 系统默认。body 为 None/空串/
    纯空白、disabled_rules 为空或全未知键 → 视为无覆盖（恢复系统默认）。
    """
    contract = CONTRACTS.get(key)
    if contract is None:
        return ""
    if isinstance(overrides, dict) and overrides:
        ov = overrides.get(key)
        if isinstance(ov, dict):
            body = ov.get("body")
            if isinstance(body, str) and body.strip():
                return body
            disabled = _disabled_rule_set(key, overrides)
            if disabled and contract.rules:
                return _compose_body(disabled)
    return contract.body


def normalize_texture_overrides(raw: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """PUT 载荷净化（纯函数，路由与测试共用口径）。

    - 未知键丢弃（契约键集以 CONTRACTS 为准，客户端版本漂移不脏库）；
    - body 非空串 → {"body": 文本}（整文覆盖优先）；
    - 否则 disabled_rules 含已知规矩键 → {"disabled_rules": [已知键]}；
    - 两者皆空/形态非法 → 丢弃（=恢复该契约系统默认）。
    """
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return out
    for key, ov in raw.items():
        if key not in CONTRACTS or not isinstance(ov, dict):
            continue
        body = ov.get("body")
        if isinstance(body, str) and body.strip():
            out[key] = {"body": body}
            continue
        raw_dr = ov.get("disabled_rules")
        if isinstance(raw_dr, (list, tuple, set)):
            known = {r.key for r in CONTRACTS[key].rules}
            dr = [str(k) for k in raw_dr if k in known]
            if dr:
                out[key] = {"disabled_rules": dr}
    return out


def render_texture_contract(
    key: str,
    mode: str,
    overrides: Optional[Dict[str, Any]] = None,
) -> str:
    """按 mode 门控渲染契约 prompt 块（空=零变化契约的空串块）。

    mode 不在契约 modes → 空串（burst/open/outline 各有专职不受染）。
    """
    contract = CONTRACTS.get(key)
    if contract is None or mode not in contract.modes:
        return ""
    body = resolve_contract_body(key, overrides)
    if not body.strip():
        return ""
    return contract.header + body


# ============================================================
# 执法词表（病灶词策展；洗层/上屏快检/完稿审计旁路合并）
# ============================================================

# (pattern, is_regex)——与 ProhibitionEntry 的构造参数对齐（见
# texture_enforcement_entries）。alternative 一律不设（模块 docstring 口径）。
ENFORCEMENT_ENTRY_SPECS: Tuple[Tuple[str, bool], ...] = (
    ("掌心发热", False),
    ("掌心发烫", False),
    ("震动顺着.{1,8}传进掌心", True),
    ("指尖微凉", False),
    ("指尖微颤", False),
    ("喉结滚动", False),
    ("呼吸一滞", False),
    ("呼吸一沉", False),
    ("眼里亮了一下又暗下去", False),
    ("眼中闪过一丝", False),
    ("下意识地(藏|缩)", True),
    ("嘴角勾起", False),
    ("嘴角扯动", False),
)


def texture_enforcement_entries() -> Tuple[Any, ...]:
    """执法词表 → ProhibitionEntry 元组（blocker、无替代词、source 标记）。

    依赖方向：本模块 → prohibitions（单向，无环）。消费方用
    ProhibitionSet(tuple(ps.entries) + texture_enforcement_entries()) 旁路合并。
    """
    from backend.services.style.prohibitions import ProhibitionEntry
    return tuple(
        ProhibitionEntry(
            pattern=pattern,
            is_regex=is_regex,
            alternative=None,
            severity="blocker",
            source="texture_contract",
        )
        for pattern, is_regex in ENFORCEMENT_ENTRY_SPECS
    )
