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
代码级审计层（Phase 2 CP3.1b 新建）。

职责：
- 在每章生成后、LLM 审计（CP3.1c）前，跑免费的纯 Python 文本扫描
- 产出量化指标（写 QualityReport.metrics）+ warning/info 级发现（写 QualityReport.findings）
- 零 token 成本（无 LLM / embedding 调用，禁词正则走 cliche_provider 缓存）

业务场景：
- stream_handler / dual_track 在 STITCHING 后调用 CodeAuditPipeline.run()
- 各 Auditor 独立可组合，失败不影响其他 Auditor（per-auditor try/except）
- 输出与 LLM 审计（CP3.1c）互补：代码级抓高频确定性病灶，LLM 抓一致性推理

7 个 Auditor（蓝图 §4.8.1 + decisions §3.3/§3.4）：
- ClichéAuditor     禁词命中率（每千字），数据源三层合并
- RhythmAuditor     句长分布 CV（burstiness）+ 连续同长句 + 段末升华
- DialogueAuditor   对话占比（按题材区间校验）
- EntityAuditor     在场一致性（BeatSpec.participants ∩ 正文角色名扫描）
- RedLineAuditor    红线引号词硬校验
- ContinuityAuditor 首末段与上/下章衔接（时间/地点/状态关键词漂移）
- WordCountAuditor  各拍/全章字数达标率

severity 设计（与 CP3.1a 契约一致）：
- 本层只产出 warning/info 级 finding
- blocker 由 LLM 审计（CP3.1c）产出
- 但 passed 字段会反映代码级硬违规（如 red_line_violations > 0 / blocker 禁词命中），
  供上层（CP3.2 精修闸门）决策；finding 仍记 warning 以便聚合展示
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# 输出契约
# ============================================================

@dataclass
class CodeAuditResult:
    """代码级审计聚合结果。

    字段映射：
    - metrics → QualityReport.metrics（量化指标，含 5 个固定键）
    - findings → QualityReport.findings（仅 warning/info 级，与 LLM 审计产出的 findings 合并）
    - passed → 是否通过代码级（无 blocker 级硬违规）

    metrics 固定键（CP3.1b 契约）：
    - cliche_hits_per_1k: float    禁词命中率（每千字）
    - sentence_len_cv: float       句长分布变异系数（Phase 2 仅参考不阻断）
    - dialogue_ratio: float        对话占比（0-1）
    - word_achieve_rate: float     字数达标率（0-1）
    - red_line_violations: int     红线引号词硬违反次数
    """

    metrics: Dict[str, Any] = field(default_factory=dict)
    findings: List[Dict[str, Any]] = field(default_factory=list)
    passed: bool = True

    def merge(self, other: "CodeAuditResult") -> "CodeAuditResult":
        """合并另一个 Auditor 的结果（用于 pipeline 聚合）。"""
        self.metrics.update(other.metrics)
        self.findings.extend(other.findings)
        self.passed = self.passed and other.passed
        return self


# ============================================================
# 工具函数
# ============================================================
# 「同一把尺子」原则（文风模块重构 S1，docs/style-module-redesign.md §7.3）：
# 句长切分/字数口径/变异系数/对话字符统计的规范实现已抽至
# services/style/fingerprint.py（作者样本与生成文本共用同一套算法），
# 此处按原名 alias 引入——审计指标口径不变，对拍单测（test_fingerprint.py）锁定同值。

from backend.services.style.fingerprint import (  # noqa: E402
    split_sentences as _split_sentences,
    count_words as _count_words,
    coefficient_of_variation as _coefficient_of_variation,
    count_dialogue_chars,
)


def _find_all_offsets(haystack: str, needle: str) -> List[Tuple[int, int]]:
    """返回 needle 在 haystack 中所有出现的 (start, end) 偏移。"""
    offsets: List[Tuple[int, int]] = []
    if not needle or not haystack:
        return offsets
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            break
        offsets.append((idx, idx + len(needle)))
        start = idx + 1  # 允许重叠匹配（中文禁词通常不重叠，但保守取 +1）
    return offsets


def _make_finding(
    *,
    severity: str,            # warning | info（本层不用 blocker）
    category: str,            # timeline | characterization | worldview | fact | style
    detail: str,
    quote: Optional[str] = None,
    offset: Optional[Tuple[int, int]] = None,
    beat_id: Optional[int] = None,
    suggestion: Optional[str] = None,
) -> Dict[str, Any]:
    """构造 finding dict（与 QualityReport.findings 项契约对齐）。"""
    return {
        "severity": severity,
        "category": category,
        "quote": quote,
        "offset": list(offset) if offset else None,
        "beat_id": beat_id,
        "detail": detail,
        "suggestion": suggestion,
    }


# ============================================================
# Auditor 基类
# ============================================================

class BaseAuditor:
    """所有代码级 Auditor 的基类。

    约定：
    - audit() 为 async（部分 Auditor 需异步加载禁词缓存）
    - 任何异常都被视为本 Auditor 失败，返回空结果（不阻断其他 Auditor）
    - auditor_name 用于日志定位
    """

    auditor_name: str = "base"

    async def audit(self, text: str, context: Dict[str, Any]) -> CodeAuditResult:
        try:
            return await self._audit(text, context)
        except Exception as e:
            logger.warning(
                f"[CodeAudit:{self.auditor_name}] 异常降级为空结果: "
                f"{type(e).__name__}: {e}"
            )
            return CodeAuditResult()

    async def _audit(self, text: str, context: Dict[str, Any]) -> CodeAuditResult:
        raise NotImplementedError


# ============================================================
# 1. ClichéAuditor — 禁词命中率（每千字）
# ============================================================
# 数据源三层合并（decisions §3.3 + 复用 StyleClicheValidator 的加载逻辑）：
# 1. SystemCliche 表（cliche_provider，带缓存，DB 失败降级种子）
# 2. book.style_blacklist（书级）
# 3. style_card.negative_list（书级 StyleCard）
#
# 关键差异（vs fail-fast 的 StyleClicheValidator）：
# - 本 Auditor 不阻断生成（已过 fail-fast 阶段），只统计 + 产 finding
# - 输出量化指标 cliche_hits_per_1k 供 A/B 对比与前端展示


class ClichéAuditor(BaseAuditor):
    """禁词命中率审计（蓝图 §4.8.1 AI 味病灶）。"""

    auditor_name = "cliche"

    async def _audit(self, text: str, context: Dict[str, Any]) -> CodeAuditResult:
        result = CodeAuditResult()
        if not text:
            result.metrics["cliche_hits_per_1k"] = 0.0
            return result

        word_count = max(1, _count_words(text))

        # 复用 StyleClicheValidator 的三层合并 + 编译缓存逻辑
        # （构造一次性 validator 即可触发 _ensure_loaded；后续直接用 _compiled_patterns）
        from backend.services.workflows.validators import StyleClicheValidator

        validator = StyleClicheValidator()
        # 预填 context 字段（StyleClicheValidator 在 _ensure_loaded 时读取）
        load_context = {
            "style_blacklist": _get_book_attr(context, "style_blacklist", []),
            "style_negative_list": _get_style_card_attr(context, "negative_list", []),
            # 系统层本书豁免（完整落地批）：三层合并时剔除被豁免的系统陈词
            "cliche_exemptions": _get_book_attr(context, "style_cliche_exemptions", []),
        }
        await validator._ensure_loaded(load_context)

        total_hits = 0
        blocker_hits = 0
        hit_phrases: Dict[str, int] = {}  # phrase → 次数（用于 finding 展示）

        for compiled, alternative, severity in validator._compiled_patterns:
            matches = compiled.findall(text)
            if not matches:
                continue
            # findall 在无分组时返回匹配字符串列表，有分组时返回分组列表
            # StyleClicheValidator 用 re.escape（非 regex）或原始 pattern（regex），
            # 通常无分组 → matches 是字符串列表
            for m in matches:
                phrase = m if isinstance(m, str) else (m[0] if m else "")
                if not phrase:
                    continue
                total_hits += 1
                hit_phrases[phrase] = hit_phrases.get(phrase, 0) + 1
                if severity == "blocker":
                    blocker_hits += 1

        per_1k = round((total_hits / word_count) * 1000, 3)
        result.metrics["cliche_hits_per_1k"] = per_1k

        # 产 finding（即便只命中 1 次也记录，供前端展示与精修输入）
        if hit_phrases:
            top_phrases = sorted(hit_phrases.items(), key=lambda kv: -kv[1])[:5]
            phrase_summary = "、".join(f"{p}×{c}" for p, c in top_phrases)
            severity_label = "warning" if blocker_hits > 0 or total_hits >= 3 else "info"
            result.findings.append(_make_finding(
                severity=severity_label,
                category="style",
                detail=(
                    f"禁词/AI 腔命中 {total_hits} 次（每千字 {per_1k}），"
                    f"其中 blocker 级 {blocker_hits} 次。高频项：{phrase_summary}"
                ),
                suggestion="按负面清单的替代建议重写，或用 POV 角色的私人偏见替换通用描写。",
            ))

        # passed 判定：存在 blocker 命中即代码级失败（虽然 finding 记 warning，
        # 但 passed=False 让上层 CP3.2 闸门可决策是否触发精修）
        if blocker_hits > 0:
            result.passed = False

        return result


# ============================================================
# 2. RhythmAuditor — 句长分布 CV + 连续同长句 + 段末升华
# ============================================================
# decisions §4.2：CV 达标线已标定（Phase 3 CP4.3），RhythmAuditor 据 CV 区间发 warning finding。
# 三个子指标：
# - sentence_len_cv: 变异系数（< CV_THRESHOLD_LO → warning；> CV_THRESHOLD_HI → 健康）
# - 连续同长句：相邻句子长度差 ≤ 2 字符的连续段长度（≥ CONSECUTIVE_SAME_LEN_THRESHOLD → info）
# - 段末升华：检测段末/句末是否出现"升华/领悟/不可阻挡"类升华腔
#
# CP4.3 改造：CV 从"仅参考"升级为"区间校验 + warning finding"。
# ⚠ 不升级为 blocker：CV 是软指标，题材相关（动作戏短句多 CV 低，氛围描写长句多 CV 高）。
#   blocker 仍由 LLM 审计（CP3.1c）产出。


from backend.services.validation.thresholds import (
    CV_THRESHOLD_LO,
    CV_THRESHOLD_HI,
    CONSECUTIVE_SAME_LEN_THRESHOLD,
    SUBLIMATION_HITS_THRESHOLD,
)

_RHYTHM_SUBLIMATION_PATTERNS = [
    "仿佛", "似乎在诉说", "这一刻", "她/他终于明白", "命运的齿轮",
    "不可阻挡", "注定", "某种意义上的", "一切都将改变", "冥冥之中",
]


class RhythmAuditor(BaseAuditor):
    """句长节奏审计（蓝图 §4.8.1 AI 味病灶；decisions §4.2 CV 区间标定）。

    CP4.3 改造：CV 从"仅参考"升级为"区间校验 + warning finding"。
    - CV < CV_THRESHOLD_LO（0.35）→ warning finding（句长单调，AI 味重）
    - CV ∈ [LO, HI] → 健康，不发 finding
    - CV > CV_THRESHOLD_HI（0.80）→ 健康多变，不发 finding
    """

    auditor_name = "rhythm"

    async def _audit(self, text: str, context: Dict[str, Any]) -> CodeAuditResult:
        result = CodeAuditResult()
        sentences = _split_sentences(text)
        if not sentences:
            result.metrics["sentence_len_cv"] = 0.0
            return result

        lengths = [float(len(s)) for s in sentences]
        cv = round(_coefficient_of_variation(lengths), 3)
        result.metrics["sentence_len_cv"] = cv

        # 子指标 0：CV 区间校验（CP4.3 新增，warning 级）
        if cv < CV_THRESHOLD_LO:
            result.findings.append(_make_finding(
                severity="warning",
                category="style",
                detail=(
                    f"句长分布变异系数 CV={cv} 低于健康下限 {CV_THRESHOLD_LO}，"
                    f"句长过于单调（AI 默认分布常见，等长句子堆叠）。"
                ),
                suggestion=(
                    "主动打散句长：穿插短句（≤10 字）、反问、单字段落，"
                    "与长句（≥30 字）交错制造呼吸感。"
                ),
            ))

        # 子指标 1：连续同长句（长度差 ≤ 2 的最长连续段）
        max_run = 1
        cur_run = 1
        for i in range(1, len(lengths)):
            if abs(lengths[i] - lengths[i - 1]) <= 2:
                cur_run += 1
                max_run = max(max_run, cur_run)
            else:
                cur_run = 1

        if max_run >= CONSECUTIVE_SAME_LEN_THRESHOLD:
            result.findings.append(_make_finding(
                severity="info",
                category="style",
                detail=(
                    f"检测到 {max_run} 个连续句子长度差异 ≤ 2 字，"
                    f"节奏单调（CV={cv}）。AI 默认分布易产出等长句子。"
                ),
                suggestion="主动打散句长：用短句、反问、单字段落制造呼吸感。",
            ))

        # 子指标 2：段末升华腔扫描
        full_text = text
        sublimation_hits = []
        for pat in _RHYTHM_SUBLIMATION_PATTERNS:
            # 简化：直接字面匹配（不处理 she/he 的中英文）
            for m in re.finditer(re.escape(pat), full_text):
                sublimation_hits.append((m.start(), pat))
        if len(sublimation_hits) >= SUBLIMATION_HITS_THRESHOLD:
            sample = sublimation_hits[0]
            result.findings.append(_make_finding(
                severity="info",
                category="style",
                quote=sample[1],
                offset=(sample[0], sample[0] + len(sample[1])),
                detail=(
                    f"检测到 {len(sublimation_hits)} 处段末升华腔表达"
                    f"（如「{sample[1]}」）。这是 RLHF house voice 的典型产物。"
                ),
                suggestion="用具体的感官细节或角色动作替代抽象升华。",
            ))

        # CP4.3：CV 区间校验已发 warning finding（见上方子指标 0），
        # 但不升级为 blocker（CV 是软指标，题材相关；blocker 由 LLM 审计产出）。
        # passed 不受 RhythmAuditor 影响。
        return result


# ============================================================
# 3. DialogueAuditor — 对话占比（按题材区间校验）
# ============================================================
# 对话识别：中文引号「」""''（） + 英文 " ' '
# 题材区间（heuristic 默认，decisions 未细化，Phase 2 用经验值）：
# - 默认目标 0.2~0.5；偏差过大记 finding
# - 可被 StyleCard.dialogue_ratio_target 覆盖（CP2.2 已加字段）


# 对话识别：引号口径见 fingerprint.count_dialogue_chars（同一把尺子）


class DialogueAuditor(BaseAuditor):
    """对话占比审计（蓝图 §4.8.1 节奏病灶）。"""

    auditor_name = "dialogue"

    async def _audit(self, text: str, context: Dict[str, Any]) -> CodeAuditResult:
        result = CodeAuditResult()
        if not text:
            result.metrics["dialogue_ratio"] = 0.0
            return result

        word_count = max(1, _count_words(text))
        dialogue_chars = count_dialogue_chars(text)
        ratio = round(dialogue_chars / word_count, 3)
        result.metrics["dialogue_ratio"] = ratio

        # 目标区间：StyleCard 覆盖优先，否则用默认
        target = _get_style_card_attr(context, "dialogue_ratio_target", None)
        if target is not None:
            # 给目标 ±0.2 容差
            lo = max(0.0, target - 0.2)
            hi = min(1.0, target + 0.2)
        else:
            lo, hi = 0.2, 0.5

        if ratio < lo:
            result.findings.append(_make_finding(
                severity="info",
                category="style",
                detail=f"对话占比 {ratio} 低于目标区间 [{lo}, {hi}]，叙事密度偏高。",
                suggestion="适度增加对白以推进情节、外化角色冲突。",
            ))
        elif ratio > hi:
            result.findings.append(_make_finding(
                severity="info",
                category="style",
                detail=f"对话占比 {ratio} 高于目标区间 [{lo}, {hi}]，可能缺乏环境与心理描写。",
                suggestion="穿插 POV 角色的内心活动或环境细节，避免纯对话流。",
            ))

        # 对话占比是题材相关的软指标，不影响 passed
        return result


# ============================================================
# 4. EntityAuditor — 在场一致性（BeatSpec.participants ∩ 正文角色名扫描）
# ============================================================
# decisions §3.3：双源对照
# - 预期在场 = BeatSpec.participants（context.beats[].participants）
# - 实际出现 = 正文扫描角色名 + 别名（context.characters[].name + aliases）
# - 不一致 = finding：
#   a) 正文出现 participants 之外的角色名 → warning（疑似串场/幻觉）
#   b) participants 中某角色正文完全未出现 → warning（疑似遗漏）


class EntityAuditor(BaseAuditor):
    """在场角色一致性审计（蓝图 §4.8.1 幻觉病灶；decisions §3.3 数据源）。"""

    auditor_name = "entity"

    async def _audit(self, text: str, context: Dict[str, Any]) -> CodeAuditResult:
        result = CodeAuditResult()
        if not text:
            return result

        characters: List[Dict[str, Any]] = context.get("characters", []) or []
        beats: List[Dict[str, Any]] = context.get("beats", []) or []

        # 构造 name → (display_name, aliases) 索引
        # 支持两种 Character 表征：{name, aliases} 或 ORM 对象（getattr）
        name_to_aliases: Dict[str, List[str]] = {}
        all_names: List[Tuple[str, str]] = []  # (display_name, match_name)
        for char in characters:
            name = _get(char, "name") or ""
            aliases = _get(char, "aliases", []) or []
            if not name:
                continue
            name_to_aliases[name] = list(aliases)
            all_names.append((name, name))
            for alias in aliases:
                if alias:
                    all_names.append((name, alias))

        if not all_names:
            # 无角色数据则跳过（无法判定在场一致性）
            return result

        # 扫描正文：哪些角色（按 display_name 聚合）出现过
        present_display_names: set = set()
        for display_name, match_name in all_names:
            if match_name in text:
                present_display_names.add(display_name)

        # 逐拍对照（若有 beats 数据）
        for beat in beats:
            beat_no = _get(beat, "position") or _get(beat, "beat_id")
            # beat_id 可能是字符串或 None；position 是 int
            beat_no_int = beat_no if isinstance(beat_no, int) else None

            participants = _get(beat, "participants", []) or []
            # participants 可能是字符串列表或 dict 列表
            expected_names: List[str] = []
            for p in participants:
                pname = p if isinstance(p, str) else (_get(p, "name") or _get(p, "character_name") or "")
                if pname:
                    expected_names.append(pname)

            if not expected_names:
                continue

            # a) 预期在场但正文未出现的角色（疑似遗漏）
            missing = [n for n in expected_names if n not in present_display_names]
            if missing:
                result.findings.append(_make_finding(
                    severity="warning",
                    category="characterization",
                    beat_id=beat_no_int,
                    detail=(
                        f"Beat {beat_no} 预期在场角色未在正文中出现：{', '.join(missing)}。"
                        f"（代码扫描局限：仅检测名字字面出现，可能漏代词指代）"
                    ),
                    suggestion="确认该角色是否被 POV 视角合理观察；若应出场，补充其动作或对白。",
                ))

            # b) 正文出现但 participants 之外的角色（疑似串场/幻觉）
            # 注意：全章视角下，某角色可能在其他 beat 出现，此处只对
            # "完全不在任何 beat.participants" 的角色告警（更保守）
            # —— 简化处理：检测出现在正文但不在本 beat.participants 的"全章预期之外"角色
            all_expected = set()
            for b in beats:
                for p in (_get(b, "participants", []) or []):
                    pname = p if isinstance(p, str) else (_get(p, "name") or "")
                    if pname:
                        all_expected.add(pname)
            unexpected = present_display_names - all_expected
            # 只在第一个 beat 报一次（避免重复）
            if unexpected and beat is beats[0]:
                for uname in sorted(unexpected):
                    result.findings.append(_make_finding(
                        severity="warning",
                        category="worldview",
                        detail=(
                            f"角色「{uname}」在正文中出现，但未在任何 beat.participants 中声明。"
                            f"疑似串场或幻觉（除非 POV 合理观察到）。"
                        ),
                        suggestion="若为新角色，补充自报姓名或显式登场描写；若是幻觉则删除。",
                    ))
                break  # 全章级告警只报一次

        return result


# ============================================================
# 5. RedLineAuditor — 红线引号词硬校验
# ============================================================
# 蓝图 §4.8.1 + decisions §3.4 封闭约束
# 数据源：beats[].red_lines + book.core_motifs_taboos
# 启发式：从红线文本中提取引号内的"绝对禁止词"（沿用 PlotLogicValidator 逻辑）
# 命中 → red_line_violations += 1 + finding（passed=False）


class RedLineAuditor(BaseAuditor):
    """红线引号词硬校验（蓝图 §4.8.1 幻觉/越界病灶；decisions §3.4）。"""

    auditor_name = "red_line"

    async def _audit(self, text: str, context: Dict[str, Any]) -> CodeAuditResult:
        result = CodeAuditResult()
        result.metrics["red_line_violations"] = 0
        if not text:
            return result

        # 汇总所有红线约束文本
        constraint_texts: List[str] = []
        for beat in (context.get("beats") or []):
            for rl in (_get(beat, "red_lines", []) or []):
                if isinstance(rl, str):
                    constraint_texts.append(rl)
                elif isinstance(rl, dict):
                    # 兼容 {text, ...} 结构
                    t = rl.get("text") or rl.get("rule") or ""
                    if t:
                        constraint_texts.append(t)

        taboos = _get_book_attr(context, "core_motifs_taboos", "")
        if isinstance(taboos, str) and taboos:
            constraint_texts.append(taboos)

        if not constraint_texts:
            return result

        # 提取引号内短语（中英文引号）
        forbidden_phrases: set = set()
        for constraint in constraint_texts:
            # 中文引号「」『』""'' 与英文 "'"
            quoted = re.findall(r"[“\"「『']([^””」』']+)[”\"」』']", constraint)
            for q in quoted:
                q = q.strip()
                if q and len(q) <= 50:  # 过滤过长的"引号短语"（非绝对禁止词）
                    forbidden_phrases.add(q)

        if not forbidden_phrases:
            return result

        violations = 0
        sample_violations: List[Tuple[str, Tuple[int, int]]] = []
        for phrase in forbidden_phrases:
            offsets = _find_all_offsets(text, phrase)
            if offsets:
                violations += len(offsets)
                if len(sample_violations) < 3:
                    sample_violations.append((phrase, offsets[0]))

        result.metrics["red_line_violations"] = violations

        if violations > 0:
            result.passed = False
            for phrase, offset in sample_violations:
                result.findings.append(_make_finding(
                    severity="warning",  # 本层契约：blocker 由 LLM 审计产出
                    category="worldview",
                    quote=phrase,
                    offset=offset,
                    detail=f"正文出现红线禁止词「{phrase}」（共 {len(_find_all_offsets(text, phrase))} 次）。",
                    suggestion="删除该表述，或按红线说明替换为允许的写法。",
                ))

        return result


# ============================================================
# 6. ContinuityAuditor — 首末段衔接（时间/地点/状态关键词漂移）
# ============================================================
# 蓝图 §4.8.1 幻觉病灶
# 输入：
# - 本章首段（text 前 200 字）+ 末段（后 200 字）
# - prev_chapter_summary（context.prev_chapter_summary）→ 末段对照
# - next_chapter_summary（context.next_chapter_summary）→ 首段对照（若有）
# - chapter_card.continuity（context.chapter_card.continuity）：from_chapter / location / time_gap
#
# 启发式检测（轻量，无 LLM）：
# - continuity.location 若指定，检查首段是否提及该地点关键词
# - continuity.time_gap 若指定（如"次日"/"三日后"），检查首段时间词是否矛盾
# - 末段与下章摘要若有共同实体，检查是否被"凭空消失"


class ContinuityAuditor(BaseAuditor):
    """首末段衔接审计（蓝图 §4.8.1 幻觉病灶）。"""

    auditor_name = "continuity"

    async def _audit(self, text: str, context: Dict[str, Any]) -> CodeAuditResult:
        result = CodeAuditResult()
        if not text:
            return result

        chapter_card = context.get("chapter_card") or {}
        continuity = chapter_card.get("continuity") or {}

        first_segment = text[:300]
        last_segment = text[-300:]

        # 检测 1：location 衔接
        expected_location = continuity.get("location")
        if expected_location and isinstance(expected_location, str):
            # 简化：把 expected_location 按非字母数字字符切关键词
            keywords = [w.strip() for w in re.split(r"[（）()\s,，、;；]+", expected_location) if len(w.strip()) >= 2]
            hit = any(kw in first_segment for kw in keywords) if keywords else True
            if not hit:
                result.findings.append(_make_finding(
                    severity="info",
                    category="worldview",
                    detail=(
                        f"本章首段未出现 continuity.location 关键词「{expected_location}」，"
                        f"地点衔接可能与上章不一致。"
                    ),
                    suggestion="在首段显式点明地点，或确认本章场景切换有合理过渡。",
                ))

        # 检测 2：time_gap 衔接
        time_gap = continuity.get("time_gap")
        if time_gap and isinstance(time_gap, str):
            # 时间词漂移检测（极简化）
            # 例如 time_gap="次日"，但首段出现"当夜/刚才/同时" → 疑似矛盾
            time_marker_map = {
                "次日": ["当夜", "刚才", "同时", "此刻", "瞬间"],
                "当日": ["次日", "几天后", "后来", "翌日"],
                "几天后": ["刚才", "立刻", "马上", "随即"],
            }
            contradicting = time_marker_map.get(time_gap, [])
            for cm in contradicting:
                if cm in first_segment:
                    result.findings.append(_make_finding(
                        severity="warning",
                        category="timeline",
                        quote=cm,
                        detail=(
                            f"continuity.time_gap 声明「{time_gap}」，"
                            f"但首段出现时间词「{cm}」，疑似时间线矛盾。"
                        ),
                        suggestion="修正首段时间表述，使其与 continuity 声明一致。",
                    ))
                    break

        # 检测 3：与上章末段的状态关键词重合度（极轻量）
        prev_summary = context.get("prev_chapter_summary")
        if prev_summary and isinstance(prev_summary, str):
            # 提取上章摘要中的名词性关键词（长度 ≥ 3 的连续非空白段）
            prev_keywords = set(re.findall(r"[\u4e00-\u9fa5A-Za-z]{3,}", prev_summary))
            first_keywords = set(re.findall(r"[\u4e00-\u9fa5A-Za-z]{3,}", first_segment))
            # 过滤通用词（极简黑名单）
            generic = {"一个", "他们", "什么", "这是", "那是", "自己"}
            overlap = (prev_keywords & first_keywords) - generic
            if prev_keywords and not overlap and len(prev_keywords) >= 3:
                result.findings.append(_make_finding(
                    severity="info",
                    category="timeline",
                    detail=(
                        f"本章首段与上章摘要无任何 3+ 字关键词重合，"
                        f"衔接可能跳跃（上章摘要关键词 {len(prev_keywords)} 个）。"
                    ),
                    suggestion="在首段呼应上章的关键物件/状态/角色，提升连贯感。",
                ))

        return result


# ============================================================
# 7. WordCountAuditor — 各拍/全章字数达标率
# ============================================================
# 蓝图 §4.8.1 指令遵循病灶
# 输入：
# - 全文字数（_count_words(text)）
# - 目标字数：chapter_card.word_target（首选）或 beats[].word_count_target 之和
# 输出：
# - word_achieve_rate: 0-1（实际 / 目标，> 1 截到 1）
# - 各拍字数分布（若 beats 提供分段）— Phase 2 简化为全章级


class WordCountAuditor(BaseAuditor):
    """字数达标率审计（蓝图 §4.8.1 指令遵循病灶）。"""

    auditor_name = "word_count"

    async def _audit(self, text: str, context: Dict[str, Any]) -> CodeAuditResult:
        result = CodeAuditResult()
        actual = _count_words(text)

        # 目标字数：chapter_card.word_target 优先，否则 beats 之和
        target = 0
        chapter_card = context.get("chapter_card") or {}
        card_target = chapter_card.get("word_target")
        if isinstance(card_target, int) and card_target > 0:
            target = card_target
        else:
            for beat in (context.get("beats") or []):
                wct = _get(beat, "word_count_target", 0) or 0
                if isinstance(wct, (int, float)) and wct > 0:
                    target += int(wct)

        if target <= 0:
            # 无目标则跳过（无法计算达标率）
            result.metrics["word_achieve_rate"] = 1.0
            return result

        rate = round(min(1.0, actual / target), 3)
        result.metrics["word_achieve_rate"] = rate

        if actual < target * 0.7:
            result.findings.append(_make_finding(
                severity="warning",
                category="fact",
                detail=(
                    f"字数 {actual} 远低于目标 {target}（达标率 {rate}）。"
                    f"指令遵循度不足，可能漏写情节或描写。"
                ),
                suggestion="扩充场景细节、角色心理或对白；检查是否漏写 beats。",
            ))
        elif actual > target * 1.5:
            result.findings.append(_make_finding(
                severity="info",
                category="fact",
                detail=(
                    f"字数 {actual} 显著超出目标 {target}（{rate * 100:.0f}%）。"
                    f"可能存在注水或节奏拖沓。"
                ),
                suggestion="检查是否有重复描写或离题段落，适度精简。",
            ))

        return result


# ============================================================
# Pipeline 聚合器
# ============================================================

class CodeAuditPipeline:
    """代码级审计管道聚合器（CP3.1b 出口）。

    用法：
        pipeline = CodeAuditPipeline()
        result = await pipeline.run(text, context)
        # result.metrics → QualityReport.metrics
        # result.findings → QualityReport.findings
        # result.passed → 闸门决策
    """

    def __init__(self, auditors: Optional[List[BaseAuditor]] = None):
        self.auditors: List[BaseAuditor] = auditors or [
            ClichéAuditor(),
            RhythmAuditor(),
            DialogueAuditor(),
            EntityAuditor(),
            RedLineAuditor(),
            ContinuityAuditor(),
            WordCountAuditor(),
        ]

    async def run(self, text: str, context: Dict[str, Any]) -> CodeAuditResult:
        """运行所有 Auditor，聚合结果。

        每个 Auditor 独立 try/except（在 BaseAuditor.audit 中），失败不影响其他。
        metrics/findings 顺序合并；passed 取逻辑与。
        """
        aggregated = CodeAuditResult()
        for auditor in self.auditors:
            single = await auditor.audit(text, context)
            aggregated.merge(single)
        return aggregated


# ============================================================
# 上下文访问辅助函数
# ============================================================

def _get(obj: Any, key: str, default: Any = None) -> Any:
    """兼容 dict 和 ORM 对象的属性访问。"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _get_book_attr(context: Dict[str, Any], key: str, default: Any = None) -> Any:
    """从 context.book（dict 或 ORM）读取字段。"""
    book = context.get("book")
    return _get(book, key, default)


def _get_style_card_attr(context: Dict[str, Any], key: str, default: Any = None) -> Any:
    """从 context.style_card（dict 或 ORM）读取字段。"""
    style_card = context.get("style_card")
    return _get(style_card, key, default)
