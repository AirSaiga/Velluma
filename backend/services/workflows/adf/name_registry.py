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
专名注册表（Name Registry）—— 设定一致性四层防线之"专名基准"。

职责：
- 从本章实体（角色/地点/资产）+ Canon public 节点构建专名注册表
  （规范名 + 别名 → 全部合法表记形式）
- 渲染"# 专名表（硬约束）"prompt 区块，供写作期注入
- 零 LLM 回扫正文，产出专名 anomaly suspects（漂移/未注册人名/别名混用）

设计意图：
- 专名漂移（工头"老赵→老张"）是设定幻觉的高发症状，根因是 LLM 不知道
  "这个名字有且只有一个合法写法"。注册表把合法表记穷举出来，
  写作期作硬约束注入，生成后作代码级回扫候选（suspect）。
- 代码只做"suspect 候选"，判定权交给 Phase 7 的 LLM 一致性审计
  （jieba/滑窗有误报，如"老赵"vs"老赵头"，直接自动改风险大）。
- Canon 只提取 public 区块的节点 label 进注册表；private 标签不进专名表
  （避免在 prompt 里重复敏感词——private 约束走知识边界通道）。

业务场景：
- segment_writer.py Phase 4 正向流写作：每段硬约束区块的专名表来源
- consistency_guard.py Phase 7 一致性守卫：代码级预扫 + 手术安全网

使用方式：
    registry = build_name_registry(entities, locations, assets, canon_context)
    block = registry_to_prompt_block(registry)
    suspects = scan_name_anomalies(final_text, registry)

依赖项：
- jieba.posseg（可选，导入失败则跳过未注册人名检测）
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from backend.services.workflows.adf.setting_resolver import _get_field

logger = logging.getLogger(__name__)

# jieba 词性标注（检测未注册人名用）。导入失败则该项检测整体跳过，不影响其余功能。
try:
    import jieba.posseg as _pseg
except Exception:  # pragma: no cover - 环境缺 jieba 时兜底
    _pseg = None
    logger.warning("[NameRegistry] jieba.posseg 导入失败，未注册人名检测将被跳过")

# 专名长度过滤：过短（单字）误报率高，过长（>8 字）多为描述句而非专名
MIN_NAME_LEN = 2
MAX_NAME_LEN = 8

# 纯 CJK 字符判定（滑窗候选需过滤标点/空白混杂的碎片）
_CJK_RE = re.compile(r"^[一-鿿]+$")

# Canon 节点 label 提取："- 标签：内容" 行首格式（半角/全角冒号皆可）
_LABEL_RE = re.compile(r"^-\s+([^：:]+)[：:]", re.MULTILINE)


@dataclass
class NameRegistry:
    """专名注册表。

    Attributes:
        canonical_names: 规范名集合（角色/地点/资产/Canon public 节点 label）
        alias_to_canonical: 别名 → 规范名映射
        all_surface_forms: 全部合法表记形式（规范名 ∪ 别名）
        character_names: 角色规范名子集（在场提示只统计角色，不含地点/资产）
    """

    canonical_names: Set[str] = field(default_factory=set)
    alias_to_canonical: Dict[str, str] = field(default_factory=dict)
    all_surface_forms: Set[str] = field(default_factory=set)
    character_names: Set[str] = field(default_factory=set)


def _canon_section(canon_context: str, tag: str) -> str:
    """从 canon_context 提取指定标记（如 [public] / [private]）所在段落的文本。

    段落从 tag 出现处开始，到下一个 "## " 标题或全文结束为止。
    """
    if not canon_context or tag not in canon_context:
        return ""
    start = canon_context.find(tag)
    end = canon_context.find("\n## ", start)
    if end < 0:
        end = len(canon_context)
    return canon_context[start:end]


def build_name_registry(
    entities: Optional[List[Any]] = None,
    locations: Optional[List[Any]] = None,
    assets: Optional[List[Any]] = None,
    canon_context: str = "",
) -> NameRegistry:
    """构建专名注册表。

    数据来源：
    - entities: ChapterEntity 列表 → character.name + character.aliases
    - locations: ChapterMapLocation 列表 → location.name（+ aliases，若有）
    - assets: ChapterAsset 列表 → asset.name + asset.aliases
    - canon_context: 仅 [public] 区块的节点 label（正则 ^-\\s+([^：:]+)[：:]）

    过滤规则：表记长度 <2 或 >8 的项不收录（单字误报高、超长多为描述句）。

    Returns:
        NameRegistry（任何来源缺失时对应集合为空，不抛异常）
    """
    canonical: Set[str] = set()
    alias_map: Dict[str, str] = {}
    character_names: Set[str] = set()

    def _add(name: Any, aliases: Any = None, is_character: bool = False) -> None:
        name = (str(name).strip() if name else "")
        if not (MIN_NAME_LEN <= len(name) <= MAX_NAME_LEN):
            return
        canonical.add(name)
        if is_character:
            character_names.add(name)
        for alias in (aliases or []):
            alias = str(alias).strip()
            if not (MIN_NAME_LEN <= len(alias) <= MAX_NAME_LEN):
                continue
            if alias != name:
                alias_map[alias] = name

    # 角色（规范名 + 别名）
    for ent in (entities or []):
        char = _get_field(ent, "character")
        if char is None:
            continue
        _add(_get_field(char, "name"), _get_field(char, "aliases") or [], is_character=True)

    # 地点
    for cl in (locations or []):
        loc = _get_field(cl, "location") or cl
        if loc is None:
            continue
        _add(_get_field(loc, "name"), _get_field(loc, "aliases") or [])

    # 资产
    for ca in (assets or []):
        asset = _get_field(ca, "asset") or ca
        if asset is None:
            continue
        _add(_get_field(asset, "name"), _get_field(asset, "aliases") or [])

    # Canon public 节点 label（private 不进专名表，走知识边界通道）
    public_section = _canon_section(canon_context, "[public]")
    if public_section:
        for match in _LABEL_RE.finditer(public_section):
            _add(match.group(1).strip())

    return NameRegistry(
        canonical_names=canonical,
        alias_to_canonical=alias_map,
        all_surface_forms=canonical | set(alias_map.keys()),
        character_names=character_names,
    )


def registry_to_prompt_block(registry: NameRegistry, max_entries: int = 30) -> str:
    """渲染"# 专名表（硬约束）"prompt 区块。

    格式：规范名（别名：X、Y）逐行列出 + 使用约束指令。
    注册表为空时返回空串（prompt 里不出现该区块）。

    Args:
        registry: 专名注册表
        max_entries: 最多列出的条目数（防 token 爆炸；超出截断）

    Returns:
        prompt 区块文本；注册表为空时返回空串
    """
    if registry is None or not registry.canonical_names:
        return ""

    alias_by_canonical: Dict[str, List[str]] = {}
    for alias, canon in registry.alias_to_canonical.items():
        alias_by_canonical.setdefault(canon, []).append(alias)

    lines = []
    for name in sorted(registry.canonical_names)[:max_entries]:
        aliases = sorted(alias_by_canonical.get(name, []))
        if aliases:
            lines.append(f"- {name}（别名：{'、'.join(aliases)}）")
        else:
            lines.append(f"- {name}")

    return (
        "# 专名表（硬约束）\n\n"
        + "\n".join(lines)
        + "\n\n只许使用上列专名指称这些角色/地点/物品；"
          "禁止给同一人物起新称呼；禁止发明新的命名人物。"
    )


def _edit_distance_le1(a: str, b: str) -> bool:
    """判断两字符串编辑距离是否 ≤1（带早退的轻量实现，仅供短串使用）。"""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        # 等长：恰好一个字符不同（替换）
        return sum(1 for x, y in zip(a, b) if x != y) == 1
    # 长度差 1：一次插入/删除
    if la > lb:
        a, b = b, a
    i = j = 0
    skipped = False
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
        elif not skipped:
            skipped = True
            j += 1
        else:
            return False
    return True


def scan_name_anomalies(text: str, registry: NameRegistry) -> List[Dict[str, Any]]:
    """零 LLM 回扫正文，产出专名 anomaly suspects（供 Phase 7 LLM 审计确认）。

    三类检测：
    (a) 变体漂移（name_drift）：对注册表每个 ≥2 字的名字，在正文中用 2-4 字滑窗
        找"共享首字且等长编辑距离 ≤1（仅替换）但不在 all_surface_forms"的候选，
        候选须在正文出现 ≥2 次才报（降误报）。
        只判等长替换：长度差 1 的候选几乎全是注册名的前后文窗口
        （"林尘没"="林尘"+动词、"统合"⊂"统合局"），真实漂移极少改变名字长度。
        典型：注册"老赵"，正文反复出现"老张"（共享"老"且后缀不同）。
    (b) 未注册人名（unregistered_name）：jieba.posseg 词性 nr 的词，
        过滤单字、过滤已注册，出现 ≥2 次才报。jieba 不可用时整项跳过。
    (c) 别名/规范名混用（alias_mix）：info 级统计，不算 suspect 报警，
        仅供审计参考（同一人物别名与规范名在正文中都出现）。

    Args:
        text: 待扫正文（整章）
        registry: 专名注册表

    Returns:
        suspect dict 列表，每项含 type/name/count/detail 等字段
    """
    suspects: List[Dict[str, Any]] = []
    if not text or registry is None or not registry.all_surface_forms:
        return suspects

    forms = registry.all_surface_forms

    # ---- (a) 变体漂移：滑窗候选 + 共享前缀 + 编辑距离 ≤1 ----
    # 统计正文中全部 2-4 字纯 CJK 子串的出现次数（重叠滑窗）
    counts: Dict[str, int] = {}
    n = len(text)
    for length in (2, 3, 4):
        for i in range(n - length + 1):
            cand = text[i:i + length]
            if _CJK_RE.match(cand):
                counts[cand] = counts.get(cand, 0) + 1

    # 按首字索引注册名，候选只与共享前缀（≥1 字）的名字比对
    by_first_char: Dict[str, List[str]] = {}
    for name in forms:
        if len(name) >= MIN_NAME_LEN:
            by_first_char.setdefault(name[0], []).append(name)

    drifted: Set[str] = set()
    for cand, cnt in counts.items():
        if cnt < 2 or cand in forms or cand in drifted:
            continue
        # 误报过滤 1：候选是注册名的"使用形态"而非漂移——
        # 以注册名开头（"林尘没"="林尘"+动词）或是注册名的子串（"统合"⊂"统合局"）
        if any(cand.startswith(f) or cand in f for f in forms if f != cand):
            continue
        for name in by_first_char.get(cand[0], ()):
            # 误报过滤 2：只判等长替换（老张↔老赵）。
            # 长度差 1 的"漂移"几乎全是注册名的前后文窗口（林尘没/统合局第），
            # 真实专名漂移极少改变名字长度
            if len(cand) == len(name) and _edit_distance_le1(cand, name):
                canonical = registry.alias_to_canonical.get(name, name)
                suspects.append({
                    "type": "name_drift",
                    "name": cand,
                    "canonical": canonical,
                    "matched_form": name,
                    "count": cnt,
                    "detail": (
                        f"正文出现「{cand}」{cnt} 次，与注册名「{name}」"
                        f"共享前缀且仅差 1 字，疑似专名漂移"
                    ),
                })
                drifted.add(cand)
                break

    # ---- (b) 未注册人名：jieba 词性 nr ----
    if _pseg is not None:
        try:
            nr_counts: Dict[str, int] = {}
            for word, flag in _pseg.cut(text):
                word = word.strip()
                if flag == "nr" and len(word) >= MIN_NAME_LEN and word not in forms:
                    nr_counts[word] = nr_counts.get(word, 0) + 1
            for word, cnt in nr_counts.items():
                if cnt < 2 or word in drifted:
                    continue
                suspects.append({
                    "type": "unregistered_name",
                    "name": word,
                    "count": cnt,
                    "detail": (
                        f"jieba 识别为人名「{word}」（出现 {cnt} 次），"
                        f"但不在专名注册表中，疑似发明的新命名人物"
                    ),
                })
        except Exception as e:
            logger.warning(f"[NameRegistry] jieba 人名检测异常，跳过: {e}")

    # ---- (c) 别名/规范名混用统计（info 级，不报警）----
    for alias, canonical in registry.alias_to_canonical.items():
        alias_count = text.count(alias)
        canonical_count = text.count(canonical)
        if alias_count > 0 and canonical_count > 0:
            suspects.append({
                "type": "alias_mix",
                "name": alias,
                "canonical": canonical,
                "count": alias_count,
                "severity": "info",
                "detail": (
                    f"「{canonical}」出现 {canonical_count} 次、其别名「{alias}」"
                    f"出现 {alias_count} 次，存在混用（info 级，供参考）"
                ),
            })

    return suspects
