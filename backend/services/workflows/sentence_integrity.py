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
终稿残句门禁（Sentence Integrity）—— 句子完整性扫描 + 定点修复。

职责：
- 0 LLM 扫描终稿中的残缺句（scan_sentence_defects，高精确度正则，宁漏勿误）
- 对命中句做定点修复（每条 1×creative，只给缺陷句+前后各一句上下文），
  带三重安全网（修复句不得再命中缺陷模式/长度比 [0.5, 2.0]/不得删除
  句中已注册专名），不过网保留原句

设计意图：
- 真实事故：残句活到终稿——"但演习的警报是的、急促的"（缺中心语）、
  "白霆的了一下"（缺动词）。渲染→wash→PRUNE→审计→一致性守卫五道关
  都不查句子完整性。
- 精确度优先：模式只匹配语法上不可能合法的形态，正常中文句子零误报；
  漏网残句的代价远低于误伤好句（误伤会触发无意义 LLM 改写）。

业务场景：
- BS-ADF Phase 7 之后、统计收尾之前跑终稿扫描（bsadf_workflow）

使用方式：
    defects = scan_sentence_defects(final_text)
    new_text, fixed, failures = await repair_sentence_defects(
        final_text, defects, registered_names=["白霆"], recorder=recorder,
    )

依赖项：
- services.llm.call_llm_with_usage（定点修复，REASONING_DISABLED）
- workflows.utils.clean_llm_output（修复输出清洗）
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.services.llm import call_llm_with_usage
from backend.services.llm.client import REASONING_DISABLED
from backend.services.observability.run_recorder import RunRecorder
from backend.services.observability.run_trace import trace_event
from backend.services.workflows.utils import clean_llm_output

logger = logging.getLogger(__name__)

# 每条缺陷 1×creative 的防御性成本上限：超出部分不修，记失败上报。
# 正常章节命中 0~3 条；上限防病态文本触发无界 LLM 调用。
MAX_SENTENCE_REPAIRS = 5

# 缺陷模式（高精确度，宁漏勿误）。每条：(缺陷类型, 正则, 人类可读描述)。
_DEFECT_PATTERNS: List[Tuple[str, "re.Pattern[str]", str]] = [
    # 缺动词：结构助词"的/地/得"后直接"了一下"（真实残句："白霆的了一下"）。
    # "他笑了一下"不匹配（助词与"了一下"之间有动词）。
    (
        "missing_verb",
        re.compile(r"[的地得]了一下"),
        "缺动词（结构助词后直接跟「了一下」）",
    ),
    # 缺中心语："是/地"后零字直接跟"的"再顿号（真实残句："警报是的、急促的"）。
    # "我的心是热的、真诚的"不匹配（"是"与"的"之间有字）。
    (
        "missing_head_noun",
        re.compile(r"(?:是|地)的、"),
        "缺中心语（「的」前缺名词）",
    ),
    # 句末悬空助词："地/得"直接收尾（如"他猛推得。"）。
    # "的。"合法（"好的。"），不匹配；"飞快地跑。"不匹配（"地"后有谓语）。
    (
        "dangling_auxiliary",
        re.compile(r"[地得](?=[。！？!?])"),
        "句末助词悬空（「地/得」后缺谓语或补语）",
    ),
]

# 句子终止符（分段/分句用；换行只作边界不进句内，防替换时吃掉段落分隔）
_SENT_END_RE = re.compile(r"[。！？!?…]+")
_SENT_END_CHARS = "。！？!?…"


def _iter_sentences(text: str):
    """按段切句，产出 (句子原文, start, end)（偏移基于原始 text）。

    句子跨度含结尾标点但绝不含换行——修复替换时不会吃掉段落分隔。
    """
    offset = 0
    for para in text.split("\n"):
        start = 0
        for m in _SENT_END_RE.finditer(para):
            sent = para[start:m.end()]
            if sent.strip():
                yield sent, offset + start, offset + m.end()
            start = m.end()
        tail = para[start:]
        if tail.strip():
            yield tail, offset + start, offset + len(para)
        offset += len(para) + 1


def scan_sentence_defects(text: str) -> List[dict]:
    """扫描文本中的残缺句（0 LLM，高精确度正则）。

    Args:
        text: 待扫描文本（通常是全章终稿）

    Returns:
        缺陷列表，每条：
        - sentence: 缺陷句原文（含结尾标点，是 text[position:position+len] 的精确子串）
        - type: 缺陷类型（missing_verb / missing_head_noun / dangling_auxiliary）
        - description: 人类可读描述
        - position: 缺陷句在 text 中的起始偏移
        - match: 命中的片段
        一句命中多种缺陷会产出多条（修复时按句去重）。
    """
    defects: List[dict] = []
    if not text:
        return defects
    for sent, start, _end in _iter_sentences(text):
        for dtype, pattern, desc in _DEFECT_PATTERNS:
            m = pattern.search(sent)
            if m:
                defects.append({
                    "sentence": sent,
                    "type": dtype,
                    "description": desc,
                    "position": start,
                    "match": m.group(0),
                })
    return defects


def _build_repair_prompt(
    defect: dict,
    prev_sentence: str,
    next_sentence: str,
) -> Tuple[str, str]:
    """构造定点修复 prompt（只给缺陷句+前后各一句，要求只修补该句）。"""
    system_prompt = (
        "你是中文小说文本修补助手。给定一句有残缺的小说正文，把它补全为通顺、"
        "完整的句子。只输出修补后的这一句本身，不要输出解释、引号或其他内容。"
        "严禁改动句意，严禁新增剧情信息，严禁改动句中的人名地名等专有名词。"
    )
    user_prompt = (
        f"残缺类型：{defect['description']}\n"
        f"上一句：{prev_sentence or '（无）'}\n"
        f"【待修补句】{defect['sentence']}\n"
        f"下一句：{next_sentence or '（无）'}\n\n"
        "请只输出修补后的完整句子（保留原结尾标点）。"
    )
    return system_prompt, user_prompt


async def _repair_one(
    defect: dict,
    prev_sentence: str,
    next_sentence: str,
    registered_names: List[str],
    recorder: Optional[RunRecorder],
    call_index: int,
) -> Tuple[Optional[str], str]:
    """修复单条缺陷句。返回 (修复句或 None, 失败原因/ok)。"""
    sentence = defect["sentence"]
    system_prompt, user_prompt = _build_repair_prompt(
        defect, prev_sentence, next_sentence,
    )
    try:
        # REASONING_DISABLED：修补是机械任务；必须显式传（空 dict 会被
        # client 的 truthy 检查吞掉）。max_tokens=1600：推理模型忽略关闭
        # 参数时给 content 留出生路（与 state_tracker 同事故）。
        if recorder is not None:
            async with recorder.record_call(
                stage=f"sentence_fix.{call_index}",
                model_slot="creative",
            ) as call_ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="creative",
                    temperature=0.3,
                    max_tokens=1600,
                    reasoning_config=REASONING_DISABLED,
                )
                call_ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=0.3,
                max_tokens=1600,
                reasoning_config=REASONING_DISABLED,
            )
    except Exception as e:
        logger.warning(f"[sentence_fix] 第 {call_index} 条修复 LLM 调用失败：{e}")
        return None, "llm_error"

    repaired = clean_llm_output(result.content or "").strip()
    # 模型偶尔带回引号/多行：取第一非空行并去引号
    repaired = next(
        (ln.strip().strip('"“”') for ln in repaired.splitlines() if ln.strip()),
        "",
    )

    # ---- 安全网（任一不过 → 保留原句）----
    if not repaired:
        return None, "empty_output"
    # 1. 修复句不得再命中任何缺陷模式
    if any(p.search(repaired) for _, p, _ in _DEFECT_PATTERNS):
        return None, "still_defective"
    # 2. 长度比 [0.5, 2.0]（防模型整段重写或砍光）
    if not (0.5 * len(sentence) <= len(repaired) <= 2.0 * len(sentence)):
        return None, "length_out_of_bounds"
    # 3. 不得删除原句中已出现的注册专名（简单子串检查）
    for name in registered_names:
        if name and name in sentence and name not in repaired:
            return None, "name_dropped"
    # 结尾标点补齐（模型偶尔丢标点，导致与下文粘连）
    if repaired[-1] not in _SENT_END_CHARS:
        repaired += sentence[-1] if sentence[-1] in _SENT_END_CHARS else "。"
    return repaired, "ok"


async def repair_sentence_defects(
    text: str,
    defects: List[dict],
    registered_names: Optional[List[str]] = None,
    recorder: Optional[RunRecorder] = None,
) -> Tuple[str, int, List[dict]]:
    """对扫描命中的缺陷句逐条定点修复（每条 1×creative，安全网不过保留原句）。

    Args:
        text: 原始文本（scan_sentence_defects 的输入，缺陷偏移基于它）
        defects: scan_sentence_defects 的输出
        registered_names: 已注册专名清单（修复安全网：原句中已出现的专名
            不得被修复句删除）
        recorder: RunRecorder（记 token 用量，可选）

    Returns:
        (新文本, 修复成功数, 失败列表)。失败列表每条含
        sentence/type/reason（llm_error/empty_output/still_defective/
        length_out_of_bounds/name_dropped/repair_cap）。
    """
    failures: List[dict] = []
    if not text or not defects:
        return text, 0, failures
    names = [n for n in (registered_names or []) if n]

    # 同一句只修一次（一句可能命中多种缺陷）
    unique: Dict[int, dict] = {}
    for d in defects:
        unique.setdefault(d["position"], d)
    items = sorted(unique.values(), key=lambda d: d["position"])

    # 成本上限：超出不修，记失败
    overflow = items[MAX_SENTENCE_REPAIRS:]
    items = items[:MAX_SENTENCE_REPAIRS]
    for d in overflow:
        failures.append({
            "sentence": d["sentence"][:50],
            "type": d["type"],
            "reason": "repair_cap",
        })

    # 上下文句表基于原始文本算一次（替换不回写它，只用于 prompt）
    sentences = [sent for sent, _s, _e in _iter_sentences(text)]
    pos_to_idx = {}
    for idx, (sent, start, _e) in enumerate(_iter_sentences(text)):
        pos_to_idx[start] = idx

    new_text = text
    fixed = 0
    # 按位置倒序替换：前面的替换不影响后面（位置更靠前）缺陷的偏移
    for call_index, d in enumerate(reversed(items)):
        pos = d["position"]
        sent = d["sentence"]
        idx = pos_to_idx.get(pos, -1)
        prev_sent = sentences[idx - 1] if idx > 0 else ""
        next_sent = sentences[idx + 1] if 0 <= idx < len(sentences) - 1 else ""

        repaired, reason = await _repair_one(
            d, prev_sent, next_sent, names, recorder, call_index + 1,
        )
        if repaired is None:
            failures.append({
                "sentence": sent[:50],
                "type": d["type"],
                "reason": reason,
            })
            trace_event(
                "sentence_defect_fix_failed",
                type=d["type"], reason=reason, sentence=sent[:80],
            )
            continue
        new_text = new_text[:pos] + repaired + new_text[pos + len(sent):]
        fixed += 1
        trace_event(
            "sentence_defect_fixed",
            type=d["type"], before=sent[:80], after=repaired[:80],
        )
        logger.info(f"[sentence_fix] 修复残句（{d['type']}）：{sent[:30]}… → {repaired[:30]}…")

    return new_text, fixed, failures


async def repair_single_defect(
    defect: dict,
    context_text: str,
    registered_names: Optional[List[str]] = None,
    recorder: Optional[RunRecorder] = None,
) -> Tuple[Optional[str], str]:
    """作者裁决式单条修复（adaptive 审校闭环 P1.2）。

    与 repair_sentence_defects（批处理、直接改文本）的根本区别：本函数
    **只产修复句，不改正文**——采不采纳由作者在前端裁决（作者裁决即闸门）。
    前后句上下文从 context_text 中按句定位自动取。

    Args:
        defect: scan_sentence_defects 输出的缺陷条目（sentence/type/description）
        context_text: 缺陷句所在的正文（当前章节全文）
    Returns:
        (修复句或 None, ok / 失败原因)——安全网与 _repair_one 完全一致
        （still_defective / length_out_of_bounds / name_dropped 等）。
    """
    target = defect.get("sentence", "")
    sentences = list(_iter_sentences(context_text))
    prev_s, next_s = "", ""
    for idx, (sent, _s, _e) in enumerate(sentences):
        if sent == target:
            if idx > 0:
                prev_s = sentences[idx - 1][0]
            if idx < len(sentences) - 1:
                next_s = sentences[idx + 1][0]
            break
    return await _repair_one(defect, prev_s, next_s, registered_names or [], recorder, 0)
