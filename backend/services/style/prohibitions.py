# -*- coding: utf-8 -*-
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
文风禁忌面归一（任务包 A）——四源合并的唯一权威模块。

职责：
- 把散落在四处的文风禁忌数据合并为单一 ProhibitionSet：
  1. SystemCliche 表（cliche_provider 直查，DB 失败降级 default_cliches 种子；
     books.style_cliche_exemptions 为本书豁免 pattern 集，仅作用于本层）
  2. style_cards.negative_list（书级文风卡负面清单，[{word/phrase, alternative,
     severity}]——severity 可选，仅 "blocker" 原样收，缺省/非法一律 warning）
  3. books.style_blacklist（书级黑名单，str 逗号/换行分隔串或 str/dict 混合数组）
  4. anti_ai_rules.DEFAULT_BAN_LIST.banned_words（15 个静态反 AI 味词）
- 供 settings_bundle（prompt 注入）、StyleClicheValidator（fail-fast 校验）、
  scan-negative（审稿扫描）、defat_selection（清脂禁词）、refinery（精修禁词）、
  ADF segment_writer（文风契约）、ghost_guard（上屏前快检）共用

边界（⚠ 边界声明）：
- 静态层**只并入 DEFAULT_BAN_LIST.banned_words**。banned_regexes /
  banned_micro_actions 不进合并——它们是 ai_taste_meter（密度统计）、
  text_sanitizer（正则裁剪）、adf_prompts（反 AI 腔 prompt 区块）的专属数据，
  语义是「确定性裁剪素材」而非「禁忌词面」，混入会双重计数并误伤审计口径。
- 不做条数截断：截断（words/prompt_text 的 max_entries）是消费方的呈现策略，
  本模块只负责全集合并与按 pattern 先到先得去重（层序即优先级）。
- 不缓存：每次直查 SystemCliche（use_cache=False），增删改即时生效。

副作用：无（纯查询 + 编译）。警示：load_prohibition_set 系统层异常时降级种子库，
绝不让禁忌面加载失败阻塞上层流程。
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Pattern, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# 数据契约
# ============================================================

@dataclass(frozen=True)
class ProhibitionEntry:
    """单条禁忌（不可变）。

    Attributes:
        pattern: 禁忌 pattern（is_regex=False 时按字面匹配，消费侧 re.escape）
        is_regex: True 时 pattern 原样编译为正则
        alternative: 替代建议（prompt / 审稿展示用）
        severity: "blocker"（硬阻断）| "warning"（软警告）
        source: system_cliche | negative_list | book_blacklist | anti_ai_static
            （供消费方按来源做差异化处理，如 validate() 排除静态源防误伤）
    """
    pattern: str
    is_regex: bool = False
    alternative: Optional[str] = None
    severity: str = "warning"
    source: str = ""


class ProhibitionSet:
    """禁忌集合（编译后的只读视图）。

    构造时编译全部条目：is_regex 原样编译、否则 re.escape 字面匹配；
    re.error 的坏 pattern 静默跳过（宁漏勿炸）。空集合安全——所有方法
    对空集合返回空值。
    """

    def __init__(self, entries: Tuple[ProhibitionEntry, ...] = ()):
        self.entries: Tuple[ProhibitionEntry, ...] = tuple(entries)
        self.compiled: List[Tuple[Pattern[str], ProhibitionEntry]] = []
        for entry in self.entries:
            if not entry.pattern:
                continue
            try:
                actual = entry.pattern if entry.is_regex else re.escape(entry.pattern)
                self.compiled.append((re.compile(actual), entry))
            except re.error:
                continue  # 坏正则跳过（与旧 StyleClicheValidator 口径一致）

    # ---- 兼容视图：旧消费方三元素解包 (compiled, alternative, severity) ----

    @property
    def compiled_patterns(self) -> List[Tuple[Pattern[str], str, str]]:
        """旧契约视图 [(compiled, alternative, severity)]（ClichéAuditor 等在用）。"""
        return [
            (compiled, entry.alternative or "", entry.severity or "warning")
            for compiled, entry in self.compiled
        ]

    # ---- 呈现辅助（截断是消费方策略，这里只提供切片）----

    def _presentation_order(self) -> List[ProhibitionEntry]:
        """呈现序（Phase 3，修任务包 A 遗留）：作者负面清单第一档 → blocker
        次档 → 其余按原层序（存储序，sort 稳定性保原 index）。

        ⚠ 仅 words()/prompt_text() 两个呈现方法使用；entries 存储序与
        compiled/finditer 遍历序不变（匹配与去重行为零变化）。
        """
        return [
            entry
            for _idx, entry in sorted(
                enumerate(self.entries),
                key=lambda pair: (
                    pair[1].source != "negative_list",
                    pair[1].severity != "blocker",
                    pair[0],
                ),
            )
        ]

    def words(self, max_entries: int, severity: Optional[str] = None) -> List[str]:
        """前 N 条 pattern（呈现序：作者负面清单优先；prompt / 校对列表用）。

        severity 指定档位时只收该档（如 "blocker"——供生成侧硬拦截校对）；
        缺省 None 收全量（零变化契约：prompt 注入等存量消费方行为不变）。
        """
        return [
            e.pattern
            for e in self._presentation_order()
            if e.pattern and (severity is None or (e.severity or "warning") == severity)
        ][:max_entries]

    def prompt_text(self, max_entries: int) -> str:
        """顿号连接前 N 条 pattern；空集合返回空串（prompt 零变化契约）。"""
        words = self.words(max_entries)
        return "、".join(words) if words else ""

    # ---- 匹配 ----

    def finditer(self, text: str):
        """遍历全部编译条目，产 (match, entry) 生成器（供来源感知消费）。"""
        for compiled, entry in self.compiled:
            for m in compiled.finditer(text or ""):
                yield (m, entry)

    def __len__(self) -> int:
        return len(self.entries)

    def __bool__(self) -> bool:
        return bool(self.entries)


# 空集合常量（消费方降级 / 测试哨兵）
EMPTY_PROHIBITION_SET = ProhibitionSet(())


# ============================================================
# 四源合并加载（唯一权威入口）
# ============================================================

async def load_prohibition_set(
    db: Any = None,
    *,
    book: Any = None,
    style_card: Any = None,
    style_blacklist: Optional[Any] = None,
    negative_list: Optional[Any] = None,
    cliche_exemptions: Optional[Any] = None,
) -> ProhibitionSet:
    """合并四源禁忌面，返回编译好的 ProhibitionSet。

    层序即优先级（同 pattern 先到先得，保留先层条目的 alternative/severity/source）：
    system_cliche → negative_list → book_blacklist → anti_ai_static。

    Args:
        db: 可选 AsyncSession。None 时系统层走种子降级（行为与旧路径一致）
        book: Book ORM（缺省参数时读 style_cliche_exemptions / style_blacklist）
        style_card: StyleCard ORM（缺省参数时读 negative_list）
        style_blacklist: 显式覆盖书级黑名单（str 分隔串 / list[str|dict]）
        negative_list: 显式覆盖负面清单（list[dict]）
        cliche_exemptions: 显式覆盖本书豁免 pattern 集（仅作用于系统层）

    Returns:
        ProhibitionSet：任何一层失败都降级为「跳过该层」，绝不抛异常。
    """
    # ---- 本书豁免集（仅剔除系统层；参数优先，缺省读 book）----
    if cliche_exemptions is None and book is not None:
        cliche_exemptions = getattr(book, "style_cliche_exemptions", None)
    exemptions: set = set()
    if isinstance(cliche_exemptions, (list, tuple, set)):
        exemptions = {str(p) for p in cliche_exemptions if p}

    entries: List[ProhibitionEntry] = []
    seen: set = set()

    def _add(
        pattern: Any,
        is_regex: bool,
        alternative: Any,
        severity: Any,
        source: str,
    ) -> None:
        """先到先得收录（空 pattern / 已见 pattern 跳过）。"""
        if not pattern or not isinstance(pattern, str):
            return
        if pattern in seen:
            return
        seen.add(pattern)
        entries.append(ProhibitionEntry(
            pattern=pattern,
            is_regex=is_regex,
            alternative=alternative if isinstance(alternative, str) and alternative else None,
            severity=severity if isinstance(severity, str) and severity else "warning",
            source=source,
        ))

    # ---- 层① SystemCliche（DB 直查失败降级种子库）----
    try:
        from backend.services.style.cliche_provider import get_active_cliches
        system_items: List[Dict[str, Any]] = await get_active_cliches(db=db, use_cache=False)
    except Exception as e:
        logger.warning(f"[Prohibitions] SystemCliche 加载失败，降级种子库: {e}")
        from backend.services.style.default_cliches import get_all_seed_cliches
        system_items = get_all_seed_cliches()
    for item in system_items:
        pattern = item.get("pattern", "")
        if pattern in exemptions:
            continue  # 本书豁免：仅剔除系统层，不动其他层
        _add(pattern, bool(item.get("is_regex", False)),
             item.get("alternative"), item.get("severity", "warning"), "system_cliche")

    # ---- 层② style_cards.negative_list（仅 dict 条目，word/phrase 键兼容）----
    if negative_list is None and style_card is not None:
        negative_list = getattr(style_card, "negative_list", None)
    if negative_list and isinstance(negative_list, list):
        for item in negative_list:
            if not isinstance(item, dict):
                continue
            word = item.get("word") or item.get("phrase") or ""
            if not word:
                continue
            # severity 白名单（Phase 3）：仅 "blocker" 原样收，None/非法串一律
            # "warning"（与层③ dict 形态的容错口径对齐，防脏数据流进下游闸门）
            raw_sev = item.get("severity")
            _add(word, False, item.get("alternative"),
                 raw_sev if raw_sev == "blocker" else "warning", "negative_list")

    # ---- 层③ books.style_blacklist（str 分隔串 / list[str|dict] 三形态）----
    if style_blacklist is None and book is not None:
        style_blacklist = getattr(book, "style_blacklist", None)
    blacklist_items: List[Any] = []
    if isinstance(style_blacklist, str):
        blacklist_items = [c.strip() for c in re.split(r"[,，\n]", style_blacklist) if c.strip()]
    elif isinstance(style_blacklist, (list, tuple)):
        blacklist_items = list(style_blacklist)
    for item in blacklist_items:
        if isinstance(item, str):
            _add(item, False, None, "warning", "book_blacklist")
        elif isinstance(item, dict):
            word = item.get("word") or item.get("phrase") or ""
            if not word:
                continue
            _add(word, False, item.get("alternative"),
                 item.get("severity", "warning"), "book_blacklist")

    # ---- 层④ 静态反 AI 词表（仅 banned_words，见模块 docstring 边界声明）----
    try:
        from backend.services.nlg.anti_ai_rules import DEFAULT_BAN_LIST
        for w in DEFAULT_BAN_LIST.banned_words:
            _add(w, False, None, "warning", "anti_ai_static")
    except Exception as e:
        logger.warning(f"[Prohibitions] 静态反 AI 词表加载失败（跳过该层）: {e}")

    return ProhibitionSet(tuple(entries))
