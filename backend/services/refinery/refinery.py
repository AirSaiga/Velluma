"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors (AGPL-3.0)
"""

"""
精修流水线主类（Refinery，V4.1 新建）。

职责（设计文档 §3）：
编排四工序：诊断 → 手术规划 → 局部手术 → 整体回读 → 抛光

设计要点：
- 不持有 DB session（工作流层约定）
- 诊断与精修分离：诊断（diagnose）产出问题清单，
  作者确认后才能调用精修（refine）。两阶段之间是对话式介入点 2。
- 所有降级显式标记

业务场景：
- routes/chapter_generation/refinery.py 调用
- ADF 生成完成后触发

使用示例：
    refinery = Refinery(recorder=recorder)
    # 第一阶段：诊断
    issues = await refinery.diagnose(raw_text, ctx)
    # ★ 作者确认（对话式介入点 2，路由层处理）
    # 第二阶段：精修
    result = await refinery.refine(raw_text, confirmed_decisions, ctx)
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from backend.services.observability.run_recorder import RunRecorder
from backend.services.refinery.diagnostician import diagnose
from backend.services.refinery.planner import plan_operations
from backend.services.refinery.surgeon import execute_surgery, apply_surgeries_to_text
from backend.services.refinery.holistic_reader import holistic_read
from backend.services.refinery.polisher import polish

logger = logging.getLogger(__name__)


@dataclass
class RefineryContext:
    """精修上下文（注入到各工序的 prompt）。"""
    purpose: str = ""                       # 章节主旨
    emotion_curve: str = ""                 # 情绪曲线文本
    canon_constraints: str = ""             # Canon 约束（private 字段清单等）
    canon_summary: str = ""                 # Canon 摘要（诊断用）
    character_states: str = ""              # 角色状态摘要
    active_hooks: str = ""                  # 活跃伏笔
    forbidden_terms: str = ""               # 禁止出现的词（private 字段名）
    author_intent: str = ""                 # 作者补充意图
    author_samples: str = ""                # 作者样本（第 4 期接入）
    enable_polish: bool = True              # 是否启用抛光
    mode: str = "deep"                      # deep | light


@dataclass
class RefineryResultData:
    """精修结果（dataclass 版本，供路由层序列化）。"""
    raw_text: str = ""
    issues: List[Dict[str, Any]] = field(default_factory=list)
    confirmed_issues: List[Dict[str, Any]] = field(default_factory=list)
    ignored_issues: List[Dict[str, Any]] = field(default_factory=list)
    operations: List[Dict[str, Any]] = field(default_factory=list)
    surgeries: List[Dict[str, Any]] = field(default_factory=list)
    holistic_verdict: Dict[str, Any] = field(default_factory=dict)
    polished_text: str = ""
    stats: Dict[str, Any] = field(default_factory=dict)
    degraded: List[Dict[str, Any]] = field(default_factory=list)


class Refinery:
    """精修流水线主类（V4.1）。

    两阶段 API：
        issues = await refinery.diagnose(raw_text, ctx)
        # ★ 作者确认（外部）
        result = await refinery.refine(raw_text, decisions, ctx)

    设计要点：
    - diagnose 阶段只调 1 次 LLM（诊断）
    - refine 阶段调多次 LLM（手术 + 回读 + 抛光）
    - 两阶段之间是对话式介入点 2（路由层处理）
    """

    def __init__(self, recorder: Optional[RunRecorder] = None):
        self.recorder = recorder

    # ============================================================
    # 第一阶段：诊断
    # ============================================================

    async def diagnose(
        self,
        raw_text: str,
        ctx: RefineryContext,
    ) -> List[Dict[str, Any]]:
        """工序 4.5.1：诊断（1 次 reasoning LLM）。

        Args:
            raw_text: 待诊断的完整正文
            ctx: 精修上下文

        Returns:
            issue dict 列表
        """
        issues = await diagnose(
            raw_text=raw_text,
            purpose=ctx.purpose,
            emotion_curve=ctx.emotion_curve,
            canon_summary=ctx.canon_summary,
            author_intent=ctx.author_intent,
            recorder=self.recorder,
        )

        # 轻量模式：自动给 medium/low 标 auto（不需要作者确认）
        if ctx.mode == "light":
            for issue in issues:
                if issue.get("severity") in ("medium", "low"):
                    issue["status"] = "auto"

        return issues

    # ============================================================
    # 第二阶段：精修（手术+回读+抛光）
    # ============================================================

    async def refine(
        self,
        raw_text: str,
        decisions: List[Dict[str, Any]],
        ctx: RefineryContext,
        original_issues: Optional[List[Dict[str, Any]]] = None,
        progress_callback: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    ) -> RefineryResultData:
        """工序 4.5.3-4.5.6：精修（手术+回读+抛光）。

        Args:
            raw_text: 原始粗坯
            decisions: 作者对每个 issue 的决策（issue_id + decision）
                decision: "confirmed" | "ignored"
            ctx: 精修上下文
            original_issues: 原始诊断的问题清单（从 diagnose 阶段传来）
            progress_callback: V4.3 流式回调 (event, data) → Any
                事件：OPERATION_START / SURGERY_DONE / REREAD_DONE / POLISH_DONE

        Returns:
            RefineryResultData
        """
        result = RefineryResultData(raw_text=raw_text)
        result.issues = original_issues or []

        # 1. 应用作者决策，过滤出 confirmed + auto 的 issues
        decision_map = {d.get("issue_id"): d.get("decision", "ignored") for d in decisions}
        confirmed: List[Dict[str, Any]] = []
        ignored: List[Dict[str, Any]] = []

        for issue in (original_issues or []):
            iid = issue.get("id")
            dec = decision_map.get(iid, "ignored")
            if dec == "confirmed":
                issue["status"] = "confirmed"
                confirmed.append(issue)
            elif issue.get("status") == "auto":
                # 轻量模式自动确认的
                confirmed.append(issue)
            else:
                issue["status"] = "ignored"
                ignored.append(issue)

        # 加入作者补充的 custom issues
        for d in decisions:
            if d.get("decision") == "confirmed" and d.get("custom_issue"):
                ci = dict(d["custom_issue"])
                ci["status"] = "confirmed"
                ci["type"] = ci.get("type", "custom")
                confirmed.append(ci)
                result.issues.append(ci)

        result.confirmed_issues = confirmed
        result.ignored_issues = ignored

        if not confirmed:
            logger.info("[Refinery] 无确认的问题，跳过手术直接抛光")
            # 跳过手术，直接抛光
            polished = raw_text
            if ctx.enable_polish:
                try:
                    polished = await polish(
                        full_text=raw_text,
                        author_samples=ctx.author_samples,
                        recorder=self.recorder,
                    )
                except Exception as e:
                    result.degraded.append({"phase": "polish", "reason": str(e)[:200]})
                    polished = raw_text
            result.polished_text = polished
            self._fill_stats(result)
            return result

        # 2. 手术规划
        try:
            operations = plan_operations(
                confirmed_issues=confirmed,
                context_summary_template=ctx.purpose,
                canon_constraints=ctx.canon_constraints,
            )
        except Exception as e:
            logger.exception(f"[Refinery] 手术规划失败: {e}")
            result.degraded.append({"phase": "planning", "reason": str(e)[:200]})
            operations = []

        result.operations = operations

        # 3. 段落拆分
        paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]

        # 4. 局部手术（串行）
        surgeries: List[Dict[str, Any]] = []
        for op_idx, op in enumerate(operations):
            # 流式回调：手术开始
            if progress_callback:
                try:
                    await progress_callback("OPERATION_START", {
                        "operation_id": op.get("id"),
                        "operation_index": op_idx + 1,
                        "total_operations": len(operations),
                        "issue_ids": op.get("issue_ids", []),
                        "target_paragraphs": op.get("target_paragraphs", []),
                    })
                except Exception as cb_e:
                    logger.warning(f"[Refinery] progress_callback OPERATION_START 失败: {cb_e}")
            try:
                surgery = await execute_surgery(
                    operation=op,
                    paragraphs=paragraphs,
                    purpose=ctx.purpose,
                    emotion_curve=ctx.emotion_curve,
                    character_states=ctx.character_states,
                    canon_constraints=ctx.canon_constraints,
                    active_hooks=ctx.active_hooks,
                    forbidden_terms=ctx.forbidden_terms,
                    recorder=self.recorder,
                )
                surgeries.append(surgery)
                # 流式回调：手术完成
                if progress_callback:
                    try:
                        await progress_callback("SURGERY_DONE", {
                            "operation_id": surgery.get("operation_id"),
                            "diff_summary": surgery.get("diff_summary", ""),
                            "applied": surgery.get("applied", False),
                            "operation_index": op_idx + 1,
                            "total_operations": len(operations),
                        })
                    except Exception as cb_e:
                        logger.warning(f"[Refinery] progress_callback SURGERY_DONE 失败: {cb_e}")
            except Exception as e:
                logger.warning(f"[Refinery] 手术 {op.get('id')} 异常: {e}")
                result.degraded.append({
                    "phase": "surgery",
                    "operation_id": op.get("id"),
                    "reason": str(e)[:200],
                })

        result.surgeries = surgeries

        # 5. 应用手术到段落
        revised_paragraphs = apply_surgeries_to_text(paragraphs, surgeries)
        revised_text = "\n\n".join(revised_paragraphs)

        # 6. 整体回读
        surgeries_summary = "\n".join(
            f"- {s.get('operation_id')}: {s.get('diff_summary', '')}"
            for s in surgeries if s.get("applied")
        )
        try:
            verdict = await holistic_read(
                full_text=revised_text,
                purpose=ctx.purpose,
                emotion_curve=ctx.emotion_curve,
                canon_constraints=ctx.canon_constraints,
                surgeries_summary=surgeries_summary,
                recorder=self.recorder,
            )
            result.holistic_verdict = verdict
        except Exception as e:
            logger.warning(f"[Refinery] 整体回读异常（不阻塞）: {e}")
            result.holistic_verdict = {"verdict": "pass", "remaining_issues": []}
            result.degraded.append({"phase": "holistic_read", "reason": str(e)[:200]})

        # 7. 抛光
        text_for_polish = revised_text
        if ctx.enable_polish:
            try:
                polished = await polish(
                    full_text=text_for_polish,
                    author_samples=ctx.author_samples,
                    recorder=self.recorder,
                )
                result.polished_text = polished
            except Exception as e:
                logger.warning(f"[Refinery] 抛光异常（不阻塞）: {e}")
                result.polished_text = text_for_polish
                result.degraded.append({"phase": "polish", "reason": str(e)[:200]})
        else:
            result.polished_text = text_for_polish

        self._fill_stats(result)
        logger.info(
            f"[Refinery] 精修完成：{len(confirmed)} 确认 → {len(operations)} 手术 → "
            f"verdict={result.holistic_verdict.get('verdict')}"
        )
        return result

    def _fill_stats(self, result: RefineryResultData) -> None:
        result.stats = {
            "raw_word_count": len(result.raw_text),
            "final_word_count": len(result.polished_text),
            "issues_total": len(result.issues),
            "issues_confirmed": len(result.confirmed_issues),
            "issues_ignored": len(result.ignored_issues),
            "operations_executed": len([s for s in result.surgeries if s.get("applied")]),
            "holistic_verdict": result.holistic_verdict.get("verdict", ""),
        }
