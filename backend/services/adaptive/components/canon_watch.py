# Velluma - NLE-ADF 3.0 Canon 感知组件
# AGPL-3.0
"""
作者写中心跳（停顿 ≥4s）触发：基于最近段落做 Canon 相关的轻感知。

与 dock_generator（镜头碎片生发）、post_process（完稿审计）的区别：
- dock_generator 产「可缝合的画面碎片」（动作型，进 SparkDock）
- post_process 是「完稿后」整章审计（低频、可跑 LLM）
- canon_watch 是「写中」实时感知（高频；hint 主体纯算法零 LLM，
  contradiction 分支低频 1×LLM），产「只读提醒」
  进独立的 adaptiveSuggestions 通道（感知带），绝不进 dock_parts

四类感知（kind）：
- appearance   ：本章绑定角色名出现在 recent_text（提示这是他的设定）
- callback     ：开放伏笔标签出现 / orphan hook 该回收了 / Canon 揭示计划
                 临近（C3，expected_reveal_chapter 距本章 ≤2 章）
- leak         ：Canon private 节点关键短语泄露到正文
- contradiction：涌现实体 vs 角色设定冲突（节流 LLM 抽实体，≥30s/章）

复用（全部纯算法零 LLM）：
- bundle.entities / bundle.open_hooks（章级绑定，子串匹配 recent_text）
- backend.services.canon.consistency.check_consistency（一次调用覆盖
  private 泄露 + orphan hook；数据来自 DB 权威查询）

产出缓存到 WorldModelORM.layer3_projections 末尾 __canon_watch__ 项
（仿 dock_generator._cache_dock_parts 的载体复用模式），heartbeat 端点
经 _extract_canon_hints 取出塞进响应。

警示：前 3 类（appearance/callback/leak）纯算法零 LLM，高频安全。
contradiction 需 LLM 抽实体，走独立节流（≥30s/章），成本可控。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from backend.services.context.settings_bundle import load_chapter_settings_bundle

logger = logging.getLogger(__name__)

# contradiction 检测节流：每章独立 ts，≥30s 才调一次 LLM 抽实体
_CONTRADICTION_TS: Dict[str, float] = {}
_CONTRADICTION_INTERVAL_S = 30


# ============================================================
# 主入口
# ============================================================

async def run(
    chapter_id: str,
    db,
    model_snapshot: Dict,
    budget_tokens: int = 0,
    **kw,
) -> Dict:
    """Canon 感知。由 orchestrator.on_heartbeat 停顿心跳同步调度。

    Returns:
        {"count": int} —— 产出 hint 数（仅用于调度日志，实际 hint 经 DB 缓存被路由层取）
    """
    bundle = await load_chapter_settings_bundle(chapter_id, db)

    # 最近段落（优先层 1 最近事实，fallback 章节正文尾部）
    recent_text = (bundle.content_text or "")[-500:]
    facts = model_snapshot.get("facts", [])
    if facts:
        recent_text = facts[-1].get("text", "")[-500:] or recent_text
    if not recent_text or len(recent_text) < 30:
        return {"skipped": True, "reason": "正文不足"}

    hints: List[Dict] = []
    seen: set = set()  # 去重 key

    # ---- 1. 角色出场感知 ----
    # 本章绑定角色名出现在 recent_text → 提示「写到他了，这是他的设定」
    for entity in (bundle.entities or []):
        name = _name_of(entity)
        if name and len(name) >= 2 and name in recent_text:
            key = f"appearance:{name}"
            if key in seen:
                continue
            seen.add(key)
            hints.append({
                "kind": "appearance",
                "node_label": name,
                "node_type": "character",
                "detail": _entity_brief(entity),
                "severity": "info",
            })

    # ---- 2. 开放伏笔回收时机 ----
    # 开放伏笔标签出现在 recent_text → 可考虑推进/回收
    for hook in (bundle.open_hooks or []):
        label = _label_of(hook)
        if label and len(label) >= 2 and label in recent_text:
            key = f"callback:{label}"
            if key in seen:
                continue
            seen.add(key)
            hints.append({
                "kind": "callback",
                "node_label": label,
                "node_type": "hook",
                "detail": "开放伏笔在本段出现，可考虑推进或回收",
                "severity": "info",
            })

    # ---- 3. Canon 一致性（private 泄露 + orphan hook）----
    # 复用 check_consistency：一次调用覆盖两类，数据来自 DB 权威查询
    if bundle.book_id:
        try:
            from backend.services.canon.consistency import check_consistency
            issues, _stats = await check_consistency(
                db, bundle.book_id, recent_text, include_llm_check=False,
            )
            for issue in issues[:8]:  # 限量，避免感知带刷屏
                kind = "leak" if issue.kind == "private_leak" else "callback"
                key = f"{kind}:{issue.kind}:{issue.node_label}"
                if key in seen:
                    continue
                seen.add(key)
                hints.append({
                    "kind": kind,
                    "node_label": issue.node_label or "",
                    "node_type": "canon",
                    "detail": issue.detail,
                    "severity": issue.severity,
                })
        except Exception as e:
            logger.warning(f"[canon_watch] check_consistency 失败: {e}")

    # ---- 3.5 揭示临近提醒（C3：expected_reveal_chapter 距本章 ≤2 章 → 感知带提示） ----
    # 纯算法零 LLM；作者定的揭示计划自己长脚走到写作现场。
    if bundle.book_id and bundle.chapter_number:
        try:
            from sqlalchemy import select as sa_select
            from backend.models import CanonNode as _CanonNode

            rows = (
                await db.execute(
                    sa_select(_CanonNode).where(
                        _CanonNode.book_id == bundle.book_id,
                        _CanonNode.expected_reveal_chapter.isnot(None),
                    )
                )
            ).scalars().all()
            for n in rows:
                gap = (n.expected_reveal_chapter or 0) - bundle.chapter_number
                if -1 <= gap <= 2 and (n.canon_text or "").strip():
                    key = f"reveal_due:{n.id}"
                    if key in seen:
                        continue
                    seen.add(key)
                    hints.append({
                        "kind": "callback",
                        "node_label": n.label,
                        "node_type": "canon",
                        "detail": (
                            f"揭示计划临近：预期第 {n.expected_reveal_chapter} 章（"
                            + ("就是本章" if gap == 0 else f"还差 {gap} 章")
                            + f"）——{n.reveal_plan[:60]}" if n.reveal_plan
                            else f"揭示计划临近：预期第 {n.expected_reveal_chapter} 章（"
                                + ("就是本章" if gap == 0 else f"还差 {gap} 章") + "）"
                        ),
                        "severity": "info",
                    })
        except Exception as e:
            logger.debug(f"[canon_watch] 揭示临近检查失败: {e}")

    # ---- 4. 设定矛盾（contradiction；节流 LLM 抽实体，≥30s/章）----
    # 与前 3 类（纯算法）不同：contradiction 需抽涌现实体比对角色设定，耗 1× LLM。
    # 节流保证心跳频率下成本可控（最频繁每 30s 一次）。复用 sediment 的
    # extract_emergent_facts + _detect_conflicts，零新检测代码。
    now = time.time()
    last_ct = _CONTRADICTION_TS.get(chapter_id, 0.0)
    if (
        recent_text
        and len(recent_text) >= 80
        and now - last_ct >= _CONTRADICTION_INTERVAL_S
        and bundle.entities  # 有角色设定才比对
    ):
        try:
            from backend.services.adaptive.emergent_facts import extract_emergent_facts
            from backend.services.adaptive.components.sediment import _detect_conflicts

            facts_data = await extract_emergent_facts(
                recent_text, beat_id=f"canonwatch_{chapter_id[:8]}"
            )
            conflicts = _detect_conflicts(facts_data.to_dict(), bundle)
            for c in conflicts[:3]:
                entity = c.get("entity", "") or ""
                if entity and entity not in seen:
                    seen.add(entity)
                    hints.append({
                        "kind": "contradiction",
                        "node_label": entity,
                        "node_type": "character",
                        "detail": f"可能与设定冲突：{c.get('new', '')[:50]}（已有：{c.get('existing', '')[:40]}）",
                        "severity": "warning",
                    })
            _CONTRADICTION_TS[chapter_id] = now
        except Exception as e:
            logger.warning(f"[canon_watch] contradiction 检测失败: {e}")

    # ---- 限量（感知带空间有限）+ 按严重度排序（矛盾/泄露优先）----
    hints = _rank_and_cap(hints, cap=10)

    # ---- 缓存到世界模型（供 heartbeat 路由层提取）----
    await _cache_canon_hints(db, chapter_id, hints)
    return {"count": len(hints)}


# ============================================================
# 辅助
# ============================================================

_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def _rank_and_cap(hints: List[Dict], cap: int = 10) -> List[Dict]:
    """按严重度排序（error>warning>info），限量。"""
    return sorted(hints, key=lambda h: _SEVERITY_RANK.get(h.get("severity", "info"), 2))[:cap]


def _name_of(obj: Any) -> str:
    """从 ORM 对象或 dict 提取 name（防御性）。"""
    if obj is None:
        return ""
    return getattr(obj, "name", None) or (obj.get("name") if isinstance(obj, dict) else "") or ""


def _label_of(obj: Any) -> str:
    """从 ORM 对象或 dict 提取 label（hook 用，fallback name）。"""
    if obj is None:
        return ""
    return (
        getattr(obj, "label", None)
        or (obj.get("label") if isinstance(obj, dict) else "")
        or _name_of(obj)
    )


def _entity_brief(entity: Any) -> str:
    """角色一句话简介（防御性提取，拿不到给通用文本）。"""
    desc = getattr(entity, "description", None) or (entity.get("description") if isinstance(entity, dict) else "") or ""
    role = getattr(entity, "role", None) or (entity.get("role") if isinstance(entity, dict) else "") or ""
    parts = [p.strip() for p in [role, desc] if p and p.strip()]
    return ("·".join(parts))[:60] if parts else "本章绑定角色"


async def _cache_canon_hints(db, chapter_id: str, hints: List[Dict]):
    """把 hints 缓存到世界模型（layer3_projections 末尾 __canon_watch__ 项）。

    仿 dock_generator._cache_dock_parts 的载体复用模式——WorldModelORM 没有专门
    字段，借 layer3_projections 末尾带标记项，heartbeat 端点据此识别提取。
    与 __dock__ 项互不干扰（各自带独立标记）。
    """
    from sqlalchemy import select
    from backend.models import WorldModelORM

    result = await db.execute(
        select(WorldModelORM).where(WorldModelORM.chapter_id == chapter_id)
    )
    model = result.scalar_one_or_none()
    if model is None:
        return
    projections = list(model.layer3_projections or [])
    # 移除旧 canon_watch 缓存
    projections = [
        p for p in projections if not (isinstance(p, dict) and p.get("__canon_watch__"))
    ]
    projections.append({"__canon_watch__": True, "hints": hints, "ts": time.time()})
    model.layer3_projections = projections
