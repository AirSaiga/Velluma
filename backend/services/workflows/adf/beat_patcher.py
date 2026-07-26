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
节拍补写器（Beat Patcher）—— 大纲节拍覆盖校验 + 缺失节拍定点补写。

职责：
- 解析 chapter.outline_text 自由文本为节拍清单（story_beats 表全库仅 5 行，
  不可用，只能解析 outline_text）
- 代码级覆盖预判（0 LLM，suspect 模式）：jieba 词覆盖率，只作审计提示
- 锚点定位：把审计 LLM 给的 insert_anchor_quote 定位到段落下标
- Phase 6.5 编排：对缺失节拍做定点插入补写（0~2×creative）+ 护栏

设计意图：
- 真实事故：开篇"读书/工头"节拍整段缺失、结尾"白霆放过流光"未写，
  既有校验（锚点审计/前置条件补埋）都不核对了 outline——前置条件补埋是
  "关键词级"内嵌补写，治不了"整场戏缺失"，需要独立的定点插入补写器。
- 防幻觉：missing 节拍必须带 insert_anchor_quote（引文锚定，与一致性审计
  canon_evidence 同一哲学）；引文在正文中找不到 → 代码侧降级"只上报不补写"。
- 明确不做：partial 节拍不补写（小缺口不值得冒险）；单次最多补 2 个节拍
  （缺口大 = 该重新生成，不是补丁能糊的）。
- 全部异常降级：节拍功能任何一步失败都不影响主流程。

业务场景：
- workflows/adf/structure_checker.py Phase 5：节拍清单 + 预判进审计 prompt
- workflows/adf/adf_workflow.py Phase 6.5：patch_missing_beats 定点补写

使用方式：
    beats = parse_outline_beats(chapter.outline_text)
    suspects = score_beat_coverage(beats, full_text)
    result = await patch_missing_beats(final_text, audit.missing_beats, ...)

依赖项：
- jieba（可选，导入失败则 score_beat_coverage 全部返回"未知"）
- workflows.adf.dedup_guard.segment_too_similar（防 LLM 抄邻段凑数）
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.services.llm import call_llm_with_usage
from backend.services.observability.run_recorder import RunRecorder
from backend.services.prompts.adf_prompts import build_beat_patch_prompt
from backend.services.workflows.adf.dedup_guard import segment_too_similar

logger = logging.getLogger(__name__)

# jieba 切词（覆盖预判用）。导入失败则预判整体降级为"未知"，
# 审计 prompt 不标注预判，其余功能不受影响。
try:
    import jieba as _jieba
except Exception:  # pragma: no cover - 环境缺 jieba 时兜底
    _jieba = None
    logger.warning("[BeatPatcher] jieba 导入失败，节拍覆盖预判将返回'未知'")

# 节拍解析规则
MIN_BEAT_CHARS = 6    # 短于此的碎片行（如"序章""转折"）不是节拍
MAX_BEATS = 15        # 节拍数上限（防超长大纲灌爆审计 prompt）

# 覆盖预判：jieba 内容词（≥2 字）在正文中的命中率低于此值 → 疑似缺失
COVERAGE_MISSING_THRESHOLD = 0.35

# 补写护栏
PATCH_MIN_CHARS = 80    # 补写输出下限（过短等于没写）
PATCH_MAX_CHARS = 600   # 补写输出上限（过长说明 LLM 在重写而非补写）
MAX_PATCH_BEATS = 2     # 单次补写节拍数上限（缺口大 = 该重新生成）

# 归一化：只保留文字/数字（去空白与全部标点），用于锚点兜底匹配
_NON_WORD_RE = re.compile(r"[^\w]", re.UNICODE)
_CJK_RE = re.compile(r"[一-鿿]")


def parse_outline_beats(outline_text: str) -> List[str]:
    """把 outline_text 自由文本解析为节拍清单（每行一个节拍）。

    规则：按行切分 → 去空白行 → 过滤 <6 字碎片行 → 上限 15 个。
    空大纲返回空列表（调用方整个功能跳过，零开销）。

    Args:
        outline_text: chapter.outline_text（自由文本，每行一个节拍）

    Returns:
        节拍字符串列表（保持原行顺序）
    """
    if not outline_text:
        return []
    beats: List[str] = []
    for line in outline_text.splitlines():
        line = line.strip()
        if len(line) < MIN_BEAT_CHARS:
            continue
        beats.append(line)
        if len(beats) >= MAX_BEATS:
            break
    return beats


def _content_words(text: str) -> List[str]:
    """jieba 切词取内容词：≥2 字且含 CJK 字符（去标点/单字/纯符号）。"""
    words = []
    for word in _jieba.cut(text):
        word = word.strip()
        if len(word) >= 2 and _CJK_RE.search(word):
            words.append(word)
    return words


def score_beat_coverage(
    beats: List[str],
    full_text: str,
) -> List[Dict[str, Any]]:
    """代码级节拍覆盖预判（0 LLM，suspect 模式）。

    对每个节拍：jieba 切出内容词（≥2 字），计算在归一化正文中的命中率，
    <35% 标"疑似缺失"，否则"疑似缺失"的反面"疑似覆盖"。

    ⚠ 只做提示：审计 prompt 里给每个节拍标注代码预判，最终判定权在 LLM
    （防代码误报，也防 LLM 漏看长节拍清单）。jieba 不可用时全部返回"未知"，
    审计 prompt 不标注预判。

    Args:
        beats: parse_outline_beats 的输出
        full_text: 整章正文

    Returns:
        [{"beat": str, "coverage": float|None, "guess": "疑似覆盖"|"疑似缺失"|"未知"}]
    """
    results: List[Dict[str, Any]] = []
    if not beats:
        return results

    if _jieba is None:
        return [{"beat": b, "coverage": None, "guess": "未知"} for b in beats]

    norm_text = _NON_WORD_RE.sub("", full_text or "")
    for beat in beats:
        words = set(_content_words(beat))
        if not words or not norm_text:
            results.append({"beat": beat, "coverage": None, "guess": "未知"})
            continue
        hit = sum(1 for w in words if w in norm_text)
        coverage = hit / len(words)
        guess = "疑似缺失" if coverage < COVERAGE_MISSING_THRESHOLD else "疑似覆盖"
        results.append({"beat": beat, "coverage": round(coverage, 3), "guess": guess})
    return results


def anchor_in_text(text: str, anchor_quote: str) -> bool:
    """判断锚点引文是否能在正文中定位（原文子串 → 归一化子串，两级兜底）。

    用于 structure_checker 的伪锚过滤：审计 LLM 给的 insert_anchor_quote
    为空或在正文中找不到 → 该节拍降级"只上报不补写"（patchable=False）。
    """
    quote = (anchor_quote or "").strip()
    if not quote or not text:
        return False
    if quote in text:
        return True
    norm_quote = _NON_WORD_RE.sub("", quote)
    if not norm_quote:
        return False
    return norm_quote in _NON_WORD_RE.sub("", text)


def locate_insert_position(
    paras: List[str],
    anchor_quote: str,
) -> Optional[int]:
    """把锚点引文定位到段落下标（原文子串 → 归一化子串，两级兜底）。

    归一化逻辑与 refiner._norm_with_map 同思路（去标点空白后子串匹配），
    但为简化不维护下标映射——这里只需要段号，不需要字符级位置。

    Args:
        paras: 段落列表（已按 \\n\\n 切分）
        anchor_quote: 审计 LLM 给的 insert_anchor_quote

    Returns:
        锚点所在段的下标；找不到返回 None（调用方放弃该节拍，只上报）
    """
    quote = (anchor_quote or "").strip()
    if not quote:
        return None
    # 第一级：原文子串
    for idx, para in enumerate(paras):
        if quote in para:
            return idx
    # 第二级：归一化子串（容忍 LLM 引文的标点/空白差异）
    norm_quote = _NON_WORD_RE.sub("", quote)
    if not norm_quote:
        return None
    for idx, para in enumerate(paras):
        if norm_quote in _NON_WORD_RE.sub("", para):
            return idx
    return None


@dataclass
class BeatPatchResult:
    """节拍补写产出。

    Attributes:
        new_text: 补写后的正文（无成功补写时等于原文）
        patched: 成功补写的节拍原文列表
        failed: 补写失败/被放弃的节拍 [{beat, reason}]（含护栏拦截，
            不含 patchable=False 的——那些根本没进补写流程）
    """

    new_text: str = ""
    patched: List[str] = field(default_factory=list)
    failed: List[Dict[str, str]] = field(default_factory=list)


async def patch_missing_beats(
    final_text: str,
    missing_beats: List[Dict[str, Any]],
    purpose: str,
    style_contract: str,
    name_registry_block: str,
    recorder: Optional[RunRecorder] = None,
) -> BeatPatchResult:
    """Phase 6.5: 对缺失节拍做定点插入补写（0~2×creative）。

    流程：取 patchable 的 missing 节拍（最多 MAX_PATCH_BEATS 个）→ 锚点定位
    → 1×creative 补写过渡段 → 护栏（长度/防抄邻段）→ 插入重拼。
    每个节拍的锚点定位都在当前段落列表上重新进行（前一次插入会移位段号）。

    Args:
        final_text: 当前最新正文（Phase 6 重拼后；Phase 6 未跑则为剪枝后文本）
        missing_beats: audit.missing_beats（含 patchable 标记）
        purpose: 章节主旨
        style_contract: 文风契约（_build_style_contract 输出）
        name_registry_block: 专名表硬约束文本（可为空串）
        recorder: RunRecorder（stage=adf.beat_patch.{序号}）

    Returns:
        BeatPatchResult（全部失败时 new_text == final_text）
    """
    result = BeatPatchResult(new_text=final_text)
    if not final_text or not final_text.strip():
        return result

    patchable = [b for b in (missing_beats or []) if b.get("patchable")][:MAX_PATCH_BEATS]
    if not patchable:
        return result

    paras = [p for p in final_text.split("\n\n") if p.strip()]
    changed = False

    for seq, beat_info in enumerate(patchable, start=1):
        beat = (beat_info.get("beat") or "").strip()
        quote = beat_info.get("insert_anchor_quote") or ""
        position = beat_info.get("insert_position") or "after"
        if position not in ("before", "after"):
            position = "after"

        # 1. 锚点定位（每次在当前段落列表上重新定位，防前次插入移位）
        anchor_idx = locate_insert_position(paras, quote)
        if anchor_idx is None:
            logger.warning(f"[BeatPatcher] 节拍「{beat[:30]}」锚点定位失败，放弃补写")
            result.failed.append({"beat": beat, "reason": "anchor_not_found"})
            continue

        anchor_before = paras[anchor_idx - 1] if position == "before" else paras[anchor_idx]
        anchor_after = paras[anchor_idx] if position == "before" else (
            paras[anchor_idx + 1] if anchor_idx + 1 < len(paras) else "（本章结尾）"
        )

        # 2. 1×creative 补写
        system_prompt, user_prompt = build_beat_patch_prompt(
            beat=beat,
            purpose=purpose,
            anchor_before=anchor_before,
            anchor_after=anchor_after,
            insert_position=position,
            style_contract=style_contract,
            name_registry_block=name_registry_block,
        )
        try:
            if recorder is not None:
                async with recorder.record_call(
                    stage=f"adf.beat_patch.{seq}",
                    model_slot="creative",
                ) as call_ctx:
                    llm_result = await call_llm_with_usage(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        model_type="creative",
                        temperature=0.7,
                        max_tokens=2048,
                    )
                    call_ctx.set_result(llm_result)
            else:
                llm_result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="creative",
                    temperature=0.7,
                    max_tokens=2048,
                )
            patch_text = (llm_result.content or "").strip()
        except Exception as e:
            logger.warning(f"[BeatPatcher] 节拍「{beat[:30]}」补写 LLM 失败: {e}")
            result.failed.append({"beat": beat, "reason": "llm_exception"})
            continue

        # 3. 护栏：长度 + 防抄邻段（任一违反则放弃该节拍，保留原文）
        if not (PATCH_MIN_CHARS <= len(patch_text) <= PATCH_MAX_CHARS):
            logger.warning(
                f"[BeatPatcher] 节拍「{beat[:30]}」补写输出 {len(patch_text)} 字，"
                f"超出 [{PATCH_MIN_CHARS}, {PATCH_MAX_CHARS}] 护栏，放弃"
            )
            result.failed.append({"beat": beat, "reason": "length_guard"})
            continue
        if segment_too_similar(patch_text, anchor_before) or (
            anchor_after != "（本章结尾）" and segment_too_similar(patch_text, anchor_after)
        ):
            logger.warning(f"[BeatPatcher] 节拍「{beat[:30]}」补写与邻段高度重复，放弃")
            result.failed.append({"beat": beat, "reason": "duplicate_guard"})
            continue

        # 4. 插入重拼
        insert_at = anchor_idx if position == "before" else anchor_idx + 1
        paras.insert(insert_at, patch_text)
        result.patched.append(beat)
        changed = True
        logger.info(
            f"[BeatPatcher] 节拍「{beat[:30]}」补写成功："
            f"{len(patch_text)} 字，插入段 P{insert_at}"
        )

    if changed:
        result.new_text = "\n\n".join(paras)
    return result
