# Velluma - NLE-ADF 3.0 后处理组件
# AGPL-3.0
"""
作者完稿时触发：对全章正文做审计/一致性/残句检查。

复用既有能力：
- run_post_step_phases（剪枝/审计/一致性/残句）——但它强依赖 BSAdfWorkflow 实例
- 降级方案：用 critique_chapter（无 DB 依赖的纯文本审阅）+ sentence_integrity

校对维度：
- 章节卡 must_hit_events 覆盖率
- Canon public 一致性 / private 泄露
- 伏笔 open_hooks 收束情况
- 残句门禁（sentence_integrity）
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from backend.services.adaptive.components.canon_checks import (
    check_canon_compliance,
    check_must_hit_coverage,
)
from backend.services.context.settings_bundle import load_chapter_settings_bundle

logger = logging.getLogger(__name__)


async def run(chapter_id: str, db, model_snapshot: Dict, budget_tokens: int = 8000, **kw) -> Dict:
    """后处理。由 orchestrator.on_finish 调度。"""
    bundle = await load_chapter_settings_bundle(chapter_id, db)
    full_text = _get_full_text(bundle)
    if not full_text or len(full_text) < 200:
        return {"skipped": True, "reason": "正文不足"}

    report: Dict[str, Any] = {"chapter_id": chapter_id, "word_count": len(full_text)}

    # ---- 1. 残句门禁（0 LLM，纯算法）----
    try:
        from backend.services.workflows.sentence_integrity import scan_sentence_defects
        defects = scan_sentence_defects(full_text)
        report["sentence_defects"] = defects[:10] if defects else []
    except Exception as e:
        logger.warning(f"[post_process] 残句扫描失败: {e}")

    # ---- 2. 章节卡覆盖率（纯算法，0 LLM）----
    report["coverage"] = check_must_hit_coverage(full_text, bundle)

    # ---- 1.5 谋篇附注（P1.4 §3.5）：未兑现锚点仅提示不阻塞；dropped 不计警示 ----
    try:
        from backend.models import Chapter as _Chapter
        ch = await db.get(_Chapter, chapter_id)
        if ch is not None and isinstance(ch.spine, dict):
            pending = [
                a.get("text", "") for a in ch.spine.get("anchors", [])
                if isinstance(a, dict) and a.get("status") == "pending" and a.get("text")
            ]
            if pending:
                report["spine_note"] = "这几条情节打算里列了还没写到：" + "、".join(pending[:5])
    except Exception as e:
        logger.debug(f"[post_process] 谋篇附注失败: {e}")

    # ---- 3. Canon 合规（纯算法）----
    report["canon_check"] = check_canon_compliance(full_text, bundle)

    # ---- 4. 整章审阅（1 LLM，可选——budget 足够时）----
    if budget_tokens >= 4000:
        try:
            critique = await _llm_critique(full_text, bundle)
            report["critique"] = critique
        except Exception as e:
            logger.warning(f"[post_process] LLM 审阅失败: {e}")

    return report


def _get_full_text(bundle) -> str:
    """完稿审阅对象：画布全文（剥 HTML）——画布即事实源。

    层 1 事实是沉淀审计账，作者删改后即过期，曾致完稿体检审阅的是
    facts 拼接而非真实正文（残句/覆盖率/审阅全部失真）。
    """
    from backend.services.adaptive.paragraph_source import written_text
    return written_text(bundle.content_text or "")


# 注：check_must_hit_coverage / check_canon_compliance 已抽到
# backend/services/adaptive/components/canon_checks.py（供 canon_watch 写中感知共用）


# ---- C3（2026-08-25 治理 P3-3）：审阅窗口改「首尾截取」 ----
# 旧 text[:6000] 使长章后半不在审阅视野（结局段/收尾伏笔的矛盾盲区）。
# 首 3000 + 尾 3000 拼接，中间标省略记号；短于 6000 时原样返回（逐字节零变化，
# 不插省略记号）。
_CRITIQUE_HEAD_CHARS = 3000
_CRITIQUE_TAIL_CHARS = 3000


def _critique_text_window(text: str) -> str:
    """审阅文本窗口：首尾各取一段，中间以省略记号衔接（纯函数）。"""
    if len(text) <= _CRITIQUE_HEAD_CHARS + _CRITIQUE_TAIL_CHARS:
        return text
    omitted = len(text) - _CRITIQUE_HEAD_CHARS - _CRITIQUE_TAIL_CHARS
    return (
        f"{text[:_CRITIQUE_HEAD_CHARS]}"
        f"\n\n（……中间 {omitted} 字省略，审阅聚焦本章开头与结尾……）\n\n"
        f"{text[-_CRITIQUE_TAIL_CHARS:]}"
    )


async def _llm_critique(text: str, bundle) -> Dict:
    """LLM 整章审阅（复用 critique 路由的纯文本审阅能力）。"""
    from backend.services.llm.client import call_llm_with_usage
    soft = bundle.soft_constraints()
    sys_p = "你是资深小说编辑。审阅以下章节正文，找出设定一致性问题、情节漏洞、伏笔遗漏。只输出 JSON。"
    usr_p = f"""# 章节正文
{_critique_text_window(text)}

# 本章必达事件（校对覆盖）
{soft.get('must_hit_events', '（无）')}

# 开放伏笔（检查是否收束）
{soft.get('open_hooks', '（无）')[:300]}

# 角色此刻状态（检查是否 OOC）
{soft.get('character_dynamics', '（无）')[:300]}

审阅。输出 JSON：
{{"issues": [{{"severity": "warning|info", "category": "consistency|plot|foreshadow|character", "detail": "..."}}], "verdict": "pass|needs_revision"}}"""
    result = await call_llm_with_usage(
        system_prompt=sys_p, user_prompt=usr_p,
        # 整章审阅是判断/审计任务（找设定矛盾、情节漏洞、伏笔遗漏），属分析型工作，
        # 走 reasoning 槽并保留 thinking（不传 REASONING_DISABLED）。与 BS-ADF
        # Phase 5 锚审计 / Phase 7 一致性守卫同类，本就该开思考。完稿后触发，
        # 延迟不敏感。此前用 creative 且漏传 reasoning_config——2026-08-25 语义
        # 修复前 get_default_reasoning_config 对 enabled=False 返回 None（不表态），
        # 思考状态随厂商默认漂移（现已修为显式关闭）。
        model_type="reasoning", temperature=0.3, max_tokens=2000,
    )
    # 观测记账：chapter_id 为空时跳过——get_adaptive_recorder("") 会在全局注册表
    # 创建 _RECORDERS[""] 孤儿（无章节归属，任何端点的 flush 都按 chapter_id 找
    # 不到它，永不冲账）。丢一条 critique 记账可接受（本就是异常场景），LLM 调用
    # 结果本身不受影响。
    recorder_chapter_id = str(bundle.chapter_id or "")
    if recorder_chapter_id:
        from backend.services.adaptive.observing import get_adaptive_recorder
        get_adaptive_recorder(recorder_chapter_id).record_result(
            "adaptive.post_process.critique", result, model_slot="reasoning")
    from backend.services.utils.json_safe import parse_json_safe
    return parse_json_safe(result.content or "") or {"verdict": "unknown"}
