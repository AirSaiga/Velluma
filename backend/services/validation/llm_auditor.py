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
LLM 级审计层（Phase 2 CP3.1c 新建）。

职责：
- 在代码级审计（CP3.1b）后，用 LLM 做深度一致性审计
- ConStory-Checker 四步流程（蓝图 §4.8.2）：
  1. 分类引导抽取：按 5 维度扫描矛盾易发片段
  2. 两两配对判定：对每对潜在矛盾，判定一致/矛盾（降误报）
  3. 证据链：对每个 finding，输出推理 + 原文引用 + 字符偏移
  4. 标准化 JSON 报告：输出 QualityReport.findings 格式
- PlotLedger 维度（decisions §3.5）：对 foreshadow_ops 逐条判定执行状态

业务场景：
- stream_handler / dual_track 在 REVIEWING 阶段调用 LLMAuditor.audit()
- 与代码级审计互补：代码级抓高频确定性病灶，LLM 抓一致性推理
- 输出 QualityReport.findings（blocker 级主要由本层产出）+ verdict + degraded

降级策略（蓝图 P5 失败不静默 + decisions §3.5）：
- LLM 调用失败 → 重试 ≤ 2 次
- JSON 解析失败 → 重试 ≤ 2 次（每次 prompt 追加"上次输出解析失败"提示）
- 重试耗尽 → verdict=unaudited + degraded={reason, action}
- 任何降级都通过 QualityReport.degraded 显式标记，不静默通过

与现有 AdversarialAligner 的关系：
- 保留 AdversarialAligner 用于"Draft vs Sketch 走向偏航检测"（must_hit_events 覆盖率）
- 本 LLMAuditor 用于"全文 5 维一致性"（时间线/角色/世界观/事实/风格）
- 两者互补，不替代
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.services.prompts.audit_prompts import (
    AUDIT_SYSTEM_PROMPT,
    VALID_CATEGORIES,
    VALID_FORESHADOW_STATUS,
    VALID_SEVERITIES,
    VALID_VERDICTS,
    build_audit_user_prompt,
)
from backend.services.workflows.utils import clean_llm_output

logger = logging.getLogger(__name__)


# ============================================================
# 输出契约
# ============================================================

@dataclass
class LLMAuditResult:
    """LLM 审计聚合结果。

    字段映射：
    - findings → QualityReport.findings（与代码级 findings 合并）
    - foreshadow_status → PlotLedger 更新输入（CP3.3 消费）
    - verdict → QualityReport.verdict（最终闸门结论）
    - degraded → QualityReport.degraded（降级标记，None 表示无降级）

    与 CodeAuditResult 区别：
    - CodeAuditResult 只产 warning/info；本结果可产 blocker
    - CodeAuditResult 无 verdict；本结果是最终闸门结论来源
    """

    findings: List[Dict[str, Any]] = field(default_factory=list)
    foreshadow_status: List[Dict[str, Any]] = field(default_factory=list)
    verdict: str = "unaudited"
    degraded: Optional[Dict[str, Any]] = None


# ============================================================
# LLM 调用签名（便于 mock 测试）
# ============================================================

# call_llm 签名：(system_prompt, user_prompt, ...) -> str
LLMCaller = Callable[..., Awaitable[str]]


# ============================================================
# LLMAuditor 主类
# ============================================================

class LLMAuditor:
    """LLM 级一致性审计器（ConStory-Checker 式证据链）。

    用法：
        auditor = LLMAuditor()
        result = await auditor.audit(
            chapter_text=text,
            chapter_card=card,
            characters=chars,
            prev_chapter_summary=prev,
            code_audit_findings=code_findings,
            beats=beats,
        )
        # result.findings → QualityReport.findings
        # result.verdict → QualityReport.verdict
    """

    def __init__(
        self,
        *,
        max_retries: int = 2,
        temperature: float = 0.1,
        max_tokens: int = 3000,
        llm_caller: Optional[LLMCaller] = None,
    ):
        """
        Args:
            max_retries: LLM 调用/解析失败时的最大重试次数（蓝图 §4.8.2：≤2）
            temperature: 推理温度（低温度保证证据链稳定，默认 0.1）
            max_tokens: 单次响应上限（findings 列表通常 < 2000 token）
            llm_caller: 可选的 LLM 调用闭包（测试时注入 mock；默认用 call_llm）
        """
        self.max_retries = max_retries
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._llm_caller = llm_caller

    async def _default_llm_caller(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """默认 LLM 调用闭包（reasoning 槽，JSON 模式）。

        decisions §4.1：审计走 reasoning 槽（低温度 0.1，证据链推理）。
        """
        from backend.services.llm import call_llm

        return await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_type="reasoning",
            temperature=self.temperature,
            response_format={"type": "json_object"},
            max_tokens=self.max_tokens,
        )

    async def _invoke_llm(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """统一调用入口（默认或注入的 caller）。"""
        caller = self._llm_caller or self._default_llm_caller
        return await caller(system_prompt, user_prompt)

    # --------------------------------------------------------
    # 主入口
    # --------------------------------------------------------

    async def audit(
        self,
        chapter_text: str,
        *,
        chapter_card: Optional[Dict[str, Any]] = None,
        characters: Optional[List[Dict[str, Any]]] = None,
        prev_chapter_summary: Optional[str] = None,
        code_audit_findings: Optional[List[Dict[str, Any]]] = None,
        beats: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMAuditResult:
        """执行 LLM 级审计（ConStory-Checker 四步流程）。

        Args:
            chapter_text: 本章正文
            chapter_card: 章节卡（含 foreshadow_ops / continuity / must_hit_events）
            characters: 涉及角色列表
            prev_chapter_summary: 上章摘要
            code_audit_findings: 代码级审计命中（作为重点复查提示）
            beats: 节拍列表

        Returns:
            LLMAuditResult：含 findings / foreshadow_status / verdict / degraded
        """
        if not chapter_text or not chapter_text.strip():
            return LLMAuditResult(
                verdict="pass",
                degraded={"reason": "empty_chapter_text", "action": "skip_audit"},
            )

        user_prompt = build_audit_user_prompt(
            chapter_text,
            chapter_card=chapter_card,
            characters=characters,
            prev_chapter_summary=prev_chapter_summary,
            code_audit_findings=code_audit_findings,
            beats=beats,
        )

        # 重试循环：LLM 调用 + JSON 解析，失败重试 ≤ max_retries 次
        last_error: Optional[str] = None
        for attempt in range(1, self.max_retries + 2):  # 首次 + max_retries 重试
            try:
                raw_response = await self._invoke_llm(AUDIT_SYSTEM_PROMPT, user_prompt)
            except Exception as e:
                last_error = f"llm_call_exception: {type(e).__name__}: {str(e)[:200]}"
                logger.warning(
                    f"[LLMAudit] 第 {attempt} 次 LLM 调用失败: {last_error}"
                )
                if attempt > self.max_retries:
                    break
                continue

            # 解析 JSON
            parsed, parse_error = self._parse_response(raw_response)
            if parse_error:
                last_error = parse_error
                logger.warning(
                    f"[LLMAudit] 第 {attempt} 次响应解析失败: {parse_error}"
                )
                # 下次重试时追加解析失败提示（让 LLM 修正格式）
                user_prompt = (
                    user_prompt
                    + f"\n\n【上次输出解析失败】{parse_error}。请严格按 JSON 格式重新输出。"
                )
                if attempt > self.max_retries:
                    break
                continue

            # 成功：校验 + 规范化
            findings, foreshadow_status, verdict = self._normalize(parsed)
            logger.info(
                f"[LLMAudit] 审计成功（第 {attempt} 次）：findings={len(findings)}, "
                f"verdict={verdict}, foreshadow_ops={len(foreshadow_status)}"
            )
            return LLMAuditResult(
                findings=findings,
                foreshadow_status=foreshadow_status,
                verdict=verdict,
                degraded=None,
            )

        # 重试耗尽 → 降级（失败不静默）
        logger.error(f"[LLMAudit] 重试 {self.max_retries} 次后仍失败，降级为 unaudited")
        return LLMAuditResult(
            verdict="unaudited",
            degraded={
                "reason": last_error or "unknown",
                "action": "mark_unaudited",
                "detail": f"retries_exhausted={self.max_retries}",
            },
        )

    # --------------------------------------------------------
    # 响应解析与规范化
    # --------------------------------------------------------

    def _parse_response(self, raw: str) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """解析 LLM 响应为 dict。

        Returns:
            (parsed_dict, None) 成功； (None, error_msg) 失败。
        """
        if not raw or not raw.strip():
            return None, "empty_response"

        cleaned = clean_llm_output(raw)
        if not cleaned:
            return None, "empty_after_clean"

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            return None, f"json_decode_error: {str(e)[:120]}"

        if not isinstance(data, dict):
            return None, f"response_not_dict: type={type(data).__name__}"

        return data, None

    def _normalize(
        self,
        data: Dict[str, Any],
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
        """校验并规范化 LLM 输出为 findings / foreshadow_status / verdict。

        规范化策略（宽容但不放任）：
        - 字段类型不符的项跳过（不整批丢弃）
        - severity/category/verdict 非法值降级为合法默认
        - offset 长度异常的修正或置 null
        - foreshadow_status 缺 evidence_quote 的 executed/modified → 降级为 skipped
          （decisions §3.5：无 evidence 不入库）
        """
        findings: List[Dict[str, Any]] = []
        for raw_f in (data.get("findings") or []):
            if not isinstance(raw_f, dict):
                continue
            norm = self._normalize_finding(raw_f)
            if norm:
                findings.append(norm)

        foreshadow_status: List[Dict[str, Any]] = []
        for raw_fs in (data.get("foreshadow_status") or []):
            if not isinstance(raw_fs, dict):
                continue
            norm = self._normalize_foreshadow(raw_fs)
            if norm:
                foreshadow_status.append(norm)

        verdict = data.get("verdict", "pass_with_fixes")
        if verdict not in VALID_VERDICTS:
            verdict = "pass_with_fixes"

        # 一致性兜底：若存在 blocker finding 但 verdict=pass，升级为 pass_with_fixes
        if verdict == "pass" and any(f["severity"] == "blocker" for f in findings):
            verdict = "pass_with_fixes"

        return findings, foreshadow_status, verdict

    def _normalize_finding(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """规范化单个 finding。返回 None 表示丢弃。"""
        detail = raw.get("detail")
        if not detail or not str(detail).strip():
            # 无 detail 的 finding 无价值（无推理过程）
            return None

        severity = raw.get("severity", "warning")
        if severity not in VALID_SEVERITIES:
            severity = "warning"

        category = raw.get("category", "fact")
        if category not in VALID_CATEGORIES:
            category = "fact"

        offset = raw.get("offset")
        offset_tuple = None
        if isinstance(offset, list) and len(offset) == 2:
            try:
                s, e = int(offset[0]), int(offset[1])
                if 0 <= s <= e:
                    offset_tuple = (s, e)
            except (TypeError, ValueError):
                offset_tuple = None

        beat_id = raw.get("beat_id")
        if beat_id is not None:
            try:
                beat_id = int(beat_id)
            except (TypeError, ValueError):
                beat_id = None

        return {
            "severity": severity,
            "category": category,
            "quote": (raw.get("quote") or "")[:200] or None,
            "offset": list(offset_tuple) if offset_tuple else None,
            "beat_id": beat_id,
            "detail": str(detail)[:1000],
            "suggestion": (raw.get("suggestion") or "")[:500] or None,
        }

    def _normalize_foreshadow(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """规范化单个 foreshadow_status。返回 None 表示丢弃。

        decisions §3.5：无 evidence 的 executed/modified 降级为 skipped。
        """
        ledger_id = raw.get("ledger_id")
        if not ledger_id:
            return None

        status = raw.get("status", "skipped")
        if status not in VALID_FORESHADOW_STATUS:
            status = "skipped"

        evidence = (raw.get("evidence_quote") or "").strip()

        # 关键约束：executed/modified 必须有 evidence，否则降级为 skipped
        if status in ("executed", "modified") and not evidence:
            status = "skipped"
            evidence = ""

        return {
            "ledger_id": str(ledger_id),
            "status": status,
            "evidence_quote": evidence[:200] if evidence else None,
            "note": (raw.get("note") or "")[:300] or None,
        }


# ============================================================
# 合并代码级 + LLM 级审计结果（供 stream_handler 调用）
# ============================================================

def merge_audit_results(
    code_result: Any,  # CodeAuditResult
    llm_result: LLMAuditResult,
) -> tuple[Dict[str, Any], List[Dict[str, Any]], str, Optional[Dict[str, Any]]]:
    """合并双层审计结果为 QualityReport 字段元组。

    蓝图 §4.8.3：QualityReport = metrics(代码级) + findings(双层合并) + verdict(LLM 主导) + degraded。

    Args:
        code_result: CP3.1b CodeAuditResult
        llm_result: CP3.1c LLMAuditResult

    Returns:
        tuple: (metrics, findings, verdict, degraded)
        - metrics: 来自 code_result.metrics
        - findings: code_result.findings + llm_result.findings 合并
        - verdict: llm_result.verdict（LLM 是最终闸门）；但若 code_result.passed=False
          且 LLM 未给 fail，则至少 pass_with_fixes
        - degraded: llm_result.degraded（若 LLM 降级）；否则 None
    """
    metrics = dict(getattr(code_result, "metrics", {}) or {})
    findings: List[Dict[str, Any]] = []
    findings.extend(getattr(code_result, "findings", []) or [])
    findings.extend(llm_result.findings)

    verdict = llm_result.verdict
    # 代码级硬违规（如 red_line_violations > 0）至少升级到 pass_with_fixes
    if (
        getattr(code_result, "passed", True) is False
        and verdict == "pass"
    ):
        verdict = "pass_with_fixes"

    degraded = llm_result.degraded

    return metrics, findings, verdict, degraded
