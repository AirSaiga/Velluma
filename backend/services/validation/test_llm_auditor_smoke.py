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
CP3.1c LLM 级审计 smoke test（独立运行，不依赖 pytest）。

覆盖：
- LLMAuditor 类完整、含 audit 方法
- prompt 含"重点扫中段"指令（ConStory-Bench）
- 解析成功路径：findings + foreshadow_status + verdict
- 解析失败 → 重试 ≤ 2 → degraded + verdict=unaudited（修病灶 8 失败静默）
- LLM 调用异常 → 重试 ≤ 2 → degraded + verdict=unaudited
- PlotLedger evidence 约束：executed 无 evidence → 降级 skipped（decisions §3.5）
- severity/category 非法值规范化
- blocker finding 但 verdict=pass → 自动升级 pass_with_fixes
- merge_audit_results 合并代码级 + LLM 级
- 空 chapter_text 短路
"""

import asyncio
import json
import sys
from typing import List


async def main() -> int:
    from backend.services.validation import LLMAuditor, LLMAuditResult, merge_audit_results
    from backend.services.validation.code_auditors import CodeAuditResult
    from backend.services.prompts.audit_prompts import (
        AUDIT_SYSTEM_PROMPT,
        build_audit_user_prompt,
        VALID_SEVERITIES,
        VALID_CATEGORIES,
        VALID_VERDICTS,
    )

    failures: List[str] = []

    def check(cond: bool, msg: str) -> None:
        if cond:
            print(f"  [OK] {msg}")
        else:
            print(f"  [FAIL] {msg}")
            failures.append(msg)

    print("=== 1. Prompt 含五维 + 重点扫中段 + PlotLedger ===")
    # 验证 system prompt 含五维扫描清单
    for dim in ["timeline", "characterization", "worldview", "fact", "style"]:
        check(dim in AUDIT_SYSTEM_PROMPT or dim in build_audit_user_prompt("测试文本"),
              f"五维含 {dim}")
    # 验证 user prompt 含"重点扫中段"指令
    sample_prompt = build_audit_user_prompt("这是一段测试正文。" * 50)
    check("重点扫" in sample_prompt or "ConStory" in sample_prompt,
          "user prompt 含'重点扫中段'（ConStory-Bench）指令")
    check("中段" in sample_prompt, "user prompt 标识中段字符区间")

    print("\n=== 2. 解析成功路径（mock LLM 返回合规 JSON）===")
    good_response = json.dumps({
        "findings": [
            {
                "severity": "blocker",
                "category": "timeline",
                "quote": "昨夜大雨倾盆",
                "offset": [100, 108],
                "beat_id": 4,
                "detail": "beat2 中票据已在男主袖中，beat4 又出现在桌上，物件状态矛盾",
                "suggestion": "删除 beat4 桌上票据的描写",
            },
            {
                "severity": "warning",
                "category": "characterization",
                "quote": "他笑了笑",
                "offset": [200, 205],
                "beat_id": None,
                "detail": "角色语气偏移",
                "suggestion": "改为冷笑",
            },
        ],
        "foreshadow_status": [
            {
                "ledger_id": "hk-001",
                "status": "executed",
                "evidence_quote": "渡口票据首次出现",
                "note": "本章 beat3 落地",
            },
            {
                "ledger_id": "hk-002",
                "status": "skipped",
                "evidence_quote": "",
                "note": "本章未触及",
            },
        ],
        "verdict": "pass_with_fixes",
    })

    call_log: List[str] = []

    async def good_caller(system_prompt, user_prompt):
        call_log.append("call")
        return good_response

    auditor = LLMAuditor(llm_caller=good_caller)
    result = await auditor.audit(
        "这是一段测试正文。" * 50,
        chapter_card={"foreshadow_ops": [{"ledger_id": "hk-001"}, {"ledger_id": "hk-002"}]},
    )
    check(len(result.findings) == 2, "解析出 2 个 findings")
    check(result.findings[0]["severity"] == "blocker", "首个 finding severity=blocker")
    check(result.findings[0]["offset"] == [100, 108], "offset 正确保留")
    check(result.findings[0]["beat_id"] == 4, "beat_id 正确保留为 int")
    check(len(result.foreshadow_status) == 2, "解析出 2 个 foreshadow_status")
    check(result.verdict == "pass_with_fixes", "verdict=pass_with_fixes")
    check(result.degraded is None, "成功路径无 degraded")
    check(len(call_log) == 1, "成功路径只调用 1 次 LLM")

    print("\n=== 3. PlotLedger evidence 约束（decisions §3.5）===")
    # executed 但无 evidence_quote → 应降级为 skipped
    no_evidence_response = json.dumps({
        "findings": [],
        "foreshadow_status": [
            {
                "ledger_id": "hk-bad",
                "status": "executed",
                "evidence_quote": "",  # 空 evidence
                "note": "声称已落地但无证据",
            },
        ],
        "verdict": "pass",
    })

    async def no_evidence_caller(system_prompt, user_prompt):
        return no_evidence_response

    auditor2 = LLMAuditor(llm_caller=no_evidence_caller)
    result2 = await auditor2.audit("正文内容。" * 30)
    check(len(result2.foreshadow_status) == 1, "foreshadow_status 仍保留 1 条")
    check(result2.foreshadow_status[0]["status"] == "skipped",
          "executed 无 evidence 降级为 skipped（§3.5）")

    print("\n=== 4. JSON 解析失败 → 重试 ≤ 2 → degraded + unaudited ===")
    call_count = [0]

    async def bad_json_caller(system_prompt, user_prompt):
        call_count[0] += 1
        return "这不是合法 JSON {缺少括号"

    auditor3 = LLMAuditor(max_retries=2, llm_caller=bad_json_caller)
    result3 = await auditor3.audit("正文内容。" * 30)
    check(call_count[0] == 3, f"重试耗尽：调用 3 次（首次 + 2 重试），实际 {call_count[0]}")
    check(result3.verdict == "unaudited", "解析失败 verdict=unaudited")
    check(result3.degraded is not None, "解析失败有 degraded 标记")
    check(result3.degraded.get("reason", "").startswith("json_decode_error") or
          "json" in result3.degraded.get("reason", "").lower(),
          f"degraded.reason 含 json 解析错误: {result3.degraded.get('reason')}")
    check(result3.degraded.get("action") == "mark_unaudited", "degraded.action=mark_unaudited")

    print("\n=== 5. LLM 调用异常 → 重试 ≤ 2 → degraded + unaudited ===")
    exc_count = [0]

    async def exception_caller(system_prompt, user_prompt):
        exc_count[0] += 1
        raise RuntimeError("模拟 LLM 服务不可用")

    auditor4 = LLMAuditor(max_retries=2, llm_caller=exception_caller)
    result4 = await auditor4.audit("正文内容。" * 30)
    check(exc_count[0] == 3, f"异常重试耗尽：调用 3 次，实际 {exc_count[0]}")
    check(result4.verdict == "unaudited", "LLM 异常 verdict=unaudited")
    check(result4.degraded is not None, "LLM 异常有 degraded 标记")
    check("llm_call_exception" in result4.degraded.get("reason", ""),
          "degraded.reason 含 llm_call_exception")

    print("\n=== 6. 解析失败后重试成功（恢复路径）===")
    attempt_idx = [0]

    async def recover_caller(system_prompt, user_prompt):
        attempt_idx[0] += 1
        if attempt_idx[0] == 1:
            return "坏 JSON 第一次"
        return good_response  # 第二次成功

    auditor5 = LLMAuditor(max_retries=2, llm_caller=recover_caller)
    result5 = await auditor5.audit(
        "正文内容。" * 30,
        chapter_card={"foreshadow_ops": []},
    )
    check(attempt_idx[0] == 2, f"首次失败 + 第二次成功：共调用 2 次，实际 {attempt_idx[0]}")
    check(result5.verdict == "pass_with_fixes", "恢复路径 verdict 正常")
    check(result5.degraded is None, "恢复路径无 degraded")
    check(len(result5.findings) == 2, "恢复路径正常解析 findings")

    print("\n=== 7. severity/category 非法值规范化 ===")
    bad_values_response = json.dumps({
        "findings": [
            {
                "severity": "CRITICAL",  # 非法
                "category": "plot",      # 非法
                "detail": "测试问题",
            },
            {
                "detail": "",  # 无 detail → 丢弃
            },
        ],
        "verdict": "unknown_status",  # 非法
    })

    async def bad_values_caller(system_prompt, user_prompt):
        return bad_values_response

    auditor6 = LLMAuditor(llm_caller=bad_values_caller)
    result6 = await auditor6.audit("正文。" * 30)
    check(len(result6.findings) == 1, "无 detail 的 finding 被丢弃，保留 1 个")
    check(result6.findings[0]["severity"] == "warning", "非法 severity 降级为 warning")
    check(result6.findings[0]["category"] == "fact", "非法 category 降级为 fact")
    check(result6.verdict == "pass_with_fixes", "非法 verdict 降级为 pass_with_fixes")

    print("\n=== 8. blocker finding 但 verdict=pass → 自动升级 ===")
    contradict_response = json.dumps({
        "findings": [
            {"severity": "blocker", "category": "timeline", "detail": "时间线崩塌"},
        ],
        "verdict": "pass",  # 与 blocker 矛盾
    })

    async def contradict_caller(system_prompt, user_prompt):
        return contradict_response

    auditor7 = LLMAuditor(llm_caller=contradict_caller)
    result7 = await auditor7.audit("正文。" * 30)
    check(result7.verdict == "pass_with_fixes",
          "存在 blocker 但 verdict=pass → 自动升级为 pass_with_fixes")

    print("\n=== 9. merge_audit_results 合并代码级 + LLM 级 ===")
    code_result = CodeAuditResult(
        metrics={
            "cliche_hits_per_1k": 0.4,
            "sentence_len_cv": 0.62,
            "dialogue_ratio": 0.31,
            "word_achieve_rate": 0.97,
            "red_line_violations": 2,
        },
        findings=[
            {"severity": "warning", "category": "style", "detail": "代码级禁词命中"},
        ],
        passed=False,  # 红线违反
    )
    llm_result = LLMAuditResult(
        findings=[
            {"severity": "blocker", "category": "timeline", "detail": "LLM 级时间线矛盾"},
        ],
        verdict="pass",  # 故意给 pass，应被代码级 passed=False 升级
        degraded=None,
    )
    metrics, findings, verdict, degraded = merge_audit_results(code_result, llm_result)
    check(metrics["red_line_violations"] == 2, "metrics 来自代码级")
    check(len(findings) == 2, "findings 合并（代码级 1 + LLM 级 1）")
    check(verdict == "pass_with_fixes",
          "代码级 passed=False + LLM verdict=pass → 升级为 pass_with_fixes")
    check(degraded is None, "无降级")

    # 反例：代码级 passed=True + LLM verdict=fail → 保持 fail
    code_ok = CodeAuditResult(metrics={}, findings=[], passed=True)
    llm_fail = LLMAuditResult(findings=[], verdict="fail")
    _, _, v2, _ = merge_audit_results(code_ok, llm_fail)
    check(v2 == "fail", "代码级通过 + LLM fail → 保持 fail")

    print("\n=== 10. 空 chapter_text 短路 ===")

    async def should_not_call(system_prompt, user_prompt):
        raise RuntimeError("不应被调用")

    auditor8 = LLMAuditor(llm_caller=should_not_call)
    result8 = await auditor8.audit("")
    check(result8.verdict == "pass", "空正文短路 verdict=pass")
    check(result8.degraded is not None, "空正文有 degraded 标记")
    check(result8.degraded.get("reason") == "empty_chapter_text", "degraded.reason=empty_chapter_text")

    print("\n=== 11. foreshadow_ops 数量对齐（PlotLedger 维度）===")
    # 章节卡声明 3 个 ops，LLM 只返回 2 个 status → 不强制对齐（容忍）
    partial_response = json.dumps({
        "findings": [],
        "foreshadow_status": [
            {"ledger_id": "op-1", "status": "executed", "evidence_quote": "证据 A"},
            {"ledger_id": "op-2", "status": "skipped"},
        ],
        "verdict": "pass",
    })

    async def partial_caller(system_prompt, user_prompt):
        return partial_response

    auditor9 = LLMAuditor(llm_caller=partial_caller)
    result9 = await auditor9.audit(
        "正文。" * 30,
        chapter_card={"foreshadow_ops": [{"ledger_id": "op-1"}, {"ledger_id": "op-2"}, {"ledger_id": "op-3"}]},
    )
    check(len(result9.foreshadow_status) == 2,
          "容忍 LLM 部分返回（3 ops 中只 2 个 status 不报错）")
    check(result9.verdict == "pass", "无 findings → verdict=pass")

    print("\n" + "=" * 50)
    if failures:
        print(f"FAILED: {len(failures)} 项")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CP3.1c SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
