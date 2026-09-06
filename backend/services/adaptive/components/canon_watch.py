# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - NLE-ADF 3.0 Canon 感知组件
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

    # 最近段落：心跳实时段（orchestrator 停顿心跳透传）→ 正文尾部（剥 HTML）。
    # ⚠ 不用层 1 事实——历史沉淀在作者删改后即过期，曾致感知锚定已删除文本。
    from backend.services.adaptive.paragraph_source import resolve_current_paragraph
    recent_text = resolve_current_paragraph(kw.get("recent_text") or "", bundle.content_text or "")
    if not recent_text or len(recent_text) < 30:
        return {"skipped": True, "reason": "正文不足"}

    hints: List[Dict] = []
    seen: set = set()  # 去重 key

    # 词边界出场判定共用一次分词（角色名 + 伏笔标签；jieba 不可用回退子串）
    token_spans = _token_spans(recent_text)

    # ---- 1. 角色出场感知 ----
    # 本章绑定角色名出现在 recent_text → 提示「写到他了，这是他的设定」
    # P2 治理（B4）：裸子串会把「高山」误命中「高山上」——改走词边界判定，
    # 判据见 _name_in_text。
    for entity in (bundle.entities or []):
        name = _name_of(entity)
        if name and len(name) >= 2 and _name_in_text(name, recent_text, token_spans):
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
    # P2 治理（B4 顺带）：标签同为专有名词，词边界判定同样受益——但物件
    # 标签跟方位字是「物确实在场」（「玉佩上的裂纹」），不启用人名那套
    # 方位粘连排除（locative_guard=False），只吃跨词误中（「月高」不在
    # 「明月高悬」的边界上）这一层降噪。
    for hook in (bundle.open_hooks or []):
        label = _label_of(hook)
        if label and len(label) >= 2 and _name_in_text(
            label, recent_text, token_spans, locative_guard=False
        ):
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
            # 世界内核 B2：揭示临近走 Intent 双读（新表 reveal 意图优先，
            # canon_nodes.expected_reveal_chapter 兜底；口径仍为距本章 ≤2 章）
            from backend.repositories.intent_repository import IntentRepository

            rows = await IntentRepository(db).read_merge_reveals(
                book_id=bundle.book_id,
                chapter_number=bundle.chapter_number,
                within_chapters=2,
            )
            for r in rows:
                target_ch = r.get("expected_reveal_chapter") or 0
                gap = target_ch - bundle.chapter_number
                key = f"reveal_due:{r.get('canon_node_id') or r.get('label')}"
                if key in seen:
                    continue
                seen.add(key)
                hints.append({
                    "kind": "callback",
                    "node_label": r.get("label") or "真相揭示",
                    "node_type": "canon",
                    "detail": (
                        f"揭示计划临近：预期第 {target_ch} 章（"
                        + ("就是本章" if gap == 0 else f"还差 {gap} 章") + "）"
                        + (f"——{r.get('label', '')[:60]}" if r.get("source") == "intent" else "")
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
                    # 文案点名矛盾词对（2026-08-29「不知所云」修复）：旧文案
                    # 直接甩两段原文（new[:50]/existing[:40]），触发词埋在句中，
                    # 作者看不出哪里矛盾；现在第一眼是「正文写X，设定是Y」
                    pair = c.get("pair") or []
                    pair_txt = (
                        f"正文写「{pair[1]}」，设定是「{pair[0]}」——"
                        if len(pair) == 2 else "可能与设定冲突："
                    )
                    hints.append({
                        "kind": "contradiction",
                        "node_label": entity,
                        "node_type": "character",
                        "detail": (
                            f"{pair_txt}{c.get('new', '')[:30]}"
                            f"（已有：{c.get('existing', '')[:30]}）"
                        ),
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

# ---- 词边界出场判定（B4，P2 治理 2026-08-25）----

# 方位/处所粘连字：人名后紧跟这些单字 token 时读作「X上/X中」的普通名词
# 短语（「高山上」是山不是人），不算角色出场。「的」刻意不在此列——
# 「高山的剑」是所有格，恰是角色被提及的高频句式。
_LOCATIVE_EXTEND_CHARS = set("上下中里边前后之间旁内外")


def _token_spans(text: str):
    """jieba 分词并建字符位置索引 [(start, end, token)]；失败返回 None。

    返回 None 时调用方回退旧子串匹配（柔性红线：感知带宁旧勿炸）。
    每次心跳只分词一次，角色名与伏笔标签共用；recent_text ≤500 字，
    开销可忽略。惰性 import + try/except：jieba 缺失/词库损坏不炸心跳。
    """
    try:
        import jieba
        tokens = jieba.lcut(text)
    except Exception as e:
        logger.debug(f"[canon_watch] jieba 分词失败，出场判定回退子串匹配: {e}")
        return None
    spans = []
    pos = 0
    for tok in tokens:
        spans.append((pos, pos + len(tok), tok))
        pos += len(tok)
    return spans


def _name_in_text(name: str, text: str, spans=None, *, locative_guard: bool = True) -> bool:
    """专有名词（角色名/伏笔标签）是否在文本中出场（词边界感知，B4）。

    旧判据是裸子串（「高山」命中「高山上」）。新判据：名字的某次出现
    必须对齐完整 token 边界——覆盖该次出现的连续 token 拼接恰为名字本身
    （「月高」跨在「明月高悬」的 明月/高悬 边界上 → 不算；「欧阳明」被
    「欧阳明亮」整体盖住 → 不算）；locative_guard=True 时再排除「人名 +
    方位粘连字」的普通名词读法（「高山上」）。代价是成语整块切分时
    （「高山仰止」）人名漏判——info 级感知宁漏勿误，可接受。
    spans 为 None（jieba 不可用）时回退旧子串行为。
    """
    if not name or not text:
        return False
    if spans is None:
        return name in text
    start = 0
    while True:
        i = text.find(name, start)
        if i < 0:
            return False
        j = i + len(name)
        covered = "".join(tok for (s, e, tok) in spans if s < j and e > i)
        if covered == name and not (
            locative_guard
            and any(
                s == j and e == j + 1 and tok in _LOCATIVE_EXTEND_CHARS
                for (s, e, tok) in spans
            )
        ):
            return True
        start = i + 1


_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def _rank_and_cap(hints: List[Dict], cap: int = 10) -> List[Dict]:
    """按严重度排序（error>warning>info），限量。"""
    return sorted(hints, key=lambda h: _SEVERITY_RANK.get(h.get("severity", "info"), 2))[:cap]


def _name_of(obj: Any) -> str:
    """从实体视图提取名字（防御性）。

    ⚠ 形状事故（2026-08-26 实测发现）：bundle.entities 两种来源都不在顶层
    挂 .name——旧 ChapterEntity 与 world 桥的 WorldEntityAdapter 均为
    ent.character.name 访问链（settings_bundle._entity_name 同判据）。旧实现
    读顶层 .name 恒空 → 出场提醒自诞生起零命中（26 次心跳 hints 恒 0 实证）。
    dict 形态（旧缓存/测试桩）保留顶层 name 兜底。
    """
    if obj is None:
        return ""
    if isinstance(obj, dict):
        char = obj.get("character")
        if isinstance(char, dict):
            return str(char.get("name") or "")
        return str(obj.get("name") or "")
    char = getattr(obj, "character", None)
    if char is not None:
        return getattr(char, "name", "") or ""
    return getattr(obj, "name", "") or ""


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
    """角色一句话简介（防御性提取，拿不到给通用文本）。

    优先 world 桥视图的 character.static_prompt（世界页档案一句话），旧表
    description/role 兜底；全缺席回退通用文本——不读 dynamic_state（状态行
    归切片条，感知带保持一句话轻量）。
    """
    if entity is None:
        return "本章绑定角色"
    char = getattr(entity, "character", None) or (
        entity.get("character") if isinstance(entity, dict) else None
    )
    parts: List[str] = []
    if char is not None:
        sp = getattr(char, "static_prompt", "") or (
            char.get("static_prompt", "") if isinstance(char, dict) else ""
        )
        if sp:
            parts.append(str(sp))
    desc = getattr(entity, "description", None) or (entity.get("description") if isinstance(entity, dict) else "") or ""
    role = getattr(entity, "role", None) or (entity.get("role") if isinstance(entity, dict) else "") or ""
    parts += [p.strip() for p in [role, desc] if p and p.strip()]
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
