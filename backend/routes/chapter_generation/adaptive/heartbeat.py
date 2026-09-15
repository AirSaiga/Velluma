# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""端点：heartbeat —— 作者状态心跳（调度器触发 + 快照/挂件/走向卡/感知带）。

本模块同时承载心跳的配套判定：谋篇进度（spine progress）、文风漂移轻提示、
收件箱积压提醒、世界模型快照提取（dock 挂件/Canon 感知/走向卡）。
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.database import AsyncSessionLocal
from backend.models import Chapter
from backend.repositories.world_repository import WorldRepository
from backend.services.adaptive.change_detector import AuthorState
from backend.services.adaptive.orchestrator import get_orchestrator
# 学着闭嘴（2026-08-25 战略定稿）：心跳提醒静音过滤的唯一权威在 quiet_learning
from backend.services.adaptive.quiet_learning import hint_mute_key, load_muted_keys
from backend.services.adaptive.observing import (
    bind_adaptive_trace,
    flush_adaptive_records,
)
# B2（2026-08-25 治理）：spine 锚点进度判定换 text_match 共享判据（勿另写滑窗）
from backend.services.adaptive.text_match import matches as text_matches
from backend.services.observability.run_trace import trace_event
from backend.services.utils.logging import get_runtime_logger

from .schemas import HeartbeatRequest, HeartbeatResponse

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["adaptive"])


# ============================================================
# 端点 1：heartbeat — 作者状态心跳
# ============================================================

@router.post("/{chapter_id}/adaptive/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    chapter_id: str,
    request: HeartbeatRequest,
    db: AsyncSession = Depends(get_db),
):
    """作者状态心跳 → 触发调度器（异步激活组件）→ 返回当前快照 + 挂件。

    前端双档防抖发（活跃 3s / 停顿 4s，见 useAdaptiveAssist.ts）。活跃档组件
    异步跑、下次心跳拿到产出；停顿档（paused_ms ≥4000）同步等 dock/projection/
    canon 组件，本次响应直接带回挂件。
    """
    bind_adaptive_trace(chapter_id)
    orch = get_orchestrator(chapter_id, lambda: AsyncSessionLocal())
    state = AuthorState(
        chapter_id=chapter_id,
        word_count=request.word_count,
        segment_count=request.segment_count,
        paused_ms=request.paused_ms,
        cursor_at_paragraph_end=request.cursor_at_paragraph_end,
        has_outline=request.has_outline,
        outline_text=request.outline_text,
        recent_text=request.recent_text,
        summoned=request.summoned,
        outline_notes=request.outline_notes,
        spine_intent=request.spine_intent,
        force_refresh=request.force_refresh,
        suffix_anchor=request.suffix_anchor,
    )
    result = await orch.on_heartbeat(state)
    snapshot = result.get("snapshot", {})

    # 章节对象提前取（谋篇进度/世界版本/漂移提示共用；失败静默 None 不阻塞心跳本体）
    chapter = None
    try:
        chapter = await db.get(Chapter, str(chapter_id))
    except Exception:
        chapter = None

    # 从世界模型拉挂件缓存（dock_generator 写入的 __dock__ 项）
    dock_parts = _extract_dock_parts(snapshot)
    # 旧卡年龄（2026-09-15 槽位治理）：dock 重算失败时旧缓存照发，前端据此刻
    # 在舱内标「N 分钟前的旧卡」；无件/无时间戳为 None
    dock_parts_age_s = _dock_parts_age_s(snapshot) if dock_parts else None
    # 句子级闸门（2026-08-25）：作者段落停在半句（无句末标点）时挂件闭嘴——
    # 此刻要的是把句子写完（Space 续写的活），缓存旧件也一并藏起；
    # 空段=段界不判半句（写完一段回车进新段是挂件黄金时机）；
    # Tab 显式点名（summoned）豁免，作者主权优先
    # dock_muted（2026-08-26 实测补强）：此前只清响应不清前端——旧件在舱里
    # 留存（章节恢复兜底/上一轮缓存），作者半句悬停时卡照样在屏。信号位让
    # 前端把「闭嘴」执行到端上：清舱收卡（Tab 点名会带 summoned 重取，无损）。
    from backend.services.adaptive.paragraph_source import ends_mid_sentence
    dock_muted = False
    if ends_mid_sentence(request.recent_text) and not request.summoned:
        dock_parts = []
        dock_muted = True
        dock_parts_age_s = None  # 件已清，年龄随之无意义
    # 走向卡（层 3 推测首 beat）——Ctrl+Space 走向卡舱的数据源
    direction_cards = _extract_direction_cards(snapshot, spine=chapter.spine if chapter is not None else None)
    # Canon 感知（canon_watch 写入的 __canon_watch__ 项）
    canon_hints = _extract_canon_hints(snapshot)

    intent = snapshot.get("intent", {})

    # 世界数据版本（写作页切片保鲜比对搭心跳便车；失败静默 None 不阻塞心跳本体）
    world_version = None
    try:
        if chapter is not None:
            world_version = await WorldRepository(db).world_version(str(chapter.book_id))
    except Exception:
        world_version = None

    # 文风漂移轻提示（完整落地批，设计稿 §5 心跳感知通道）：以 kind=style_drift
    # 并入 canon_hints——前端感知带零新增管线直接渲染。纯 code + 按内容长度缓存
    drift_hint = await _style_drift_hint_for_heartbeat(chapter, db)
    if drift_hint:
        canon_hints = list(canon_hints) + [drift_hint]

    # A5c 收件箱积压提醒（P5 §3.2）：全书 pending 候选 >5 条时以 kind=world_inbox
    # 并入 canon_hints——同走感知带柔性通道，不弹窗不抢焦点。短 TTL 缓存防抖
    inbox_hint = await _world_inbox_hint_for_heartbeat(chapter, db)
    if inbox_hint:
        canon_hints = list(canon_hints) + [inbox_hint]

    # 学着闭嘴（2026-08-25 战略定稿）：作者多次收起（感知带 ×）的提醒类别在此静音。
    # 安全类（leak/contradiction）永不进静音集——quiet_learning 白名单保证；
    # 失败静默：学习链路故障不阻塞心跳本体（静音集派生侧已内兜，此处再兜一层）。
    if chapter is not None and canon_hints:
        try:
            _muted_keys = await load_muted_keys(db, str(chapter.book_id))
            if _muted_keys:
                canon_hints = [
                    h for h in canon_hints
                    if hint_mute_key(str((h or {}).get("kind") or "")) not in _muted_keys
                ]
        except Exception:
            pass

    # 章级谋篇进度（P1.4 M2 §4.3）：纯算法零 LLM，宁漏勿误（B2 治理后走
    # text_match 共享判据的全片段命中 + 就近窗口；误报破坏信任，漏报作者自己
    # 划掉即可 + finish 报告兜底）。按内容 hash 缓存；pending→hit 迁移才写库
    spine_progress = await _spine_progress_for_heartbeat(chapter, orch, db)

    # 观测（P0-2）：心跳事件进 chapter 级 trace；顺路冲走累积的组件调用账
    # （含上一次心跳派生的后台组件——它们自开 session，只能靠后续请求落库）
    trace_event(
        "adaptive_heartbeat",
        word_count=request.word_count,
        paused_ms=request.paused_ms,
        activated=result.get("activated", []),
        dock_parts=len(dock_parts),
        direction_cards=len(direction_cards),
        canon_hints=len(canon_hints),
    )
    await flush_adaptive_records(chapter_id)

    return HeartbeatResponse(
        dock_parts=dock_parts,
        dock_muted=dock_muted,
        dock_parts_age_s=dock_parts_age_s,
        onstage_guests=_extract_onstage_guests(snapshot),
        direction_cards=direction_cards,
        intent_source=intent.get("source", "none"),
        intent_arc=intent.get("arc", ""),
        intent_confidence=intent.get("confidence", 0.0),
        fact_count=snapshot.get("fact_count", 0),
        total_words=snapshot.get("total_words", 0),
        activated=result.get("activated", []),
        signals=result.get("signals", []),
        canon_hints=canon_hints,
        world_version=world_version,
        spine_progress=spine_progress,
        last_component_errors=orch.last_component_errors(),
        # 第三弹（2026-09-14 光标派生取景框）：{loc_id, loc_name, derived, via}
        # ——derived=True 表示按正文推导（前端切片条出「正文推导」微标+一键钉定）
        active_scene=result.get("active_scene"),
    )


def _extract_dock_parts(snapshot: Dict) -> List[Dict]:
    """从世界模型快照的 projections 里提取 dock_generator 缓存的挂件。

    版本盐值过滤（2026-09-08 僵尸缓存修复）：__dock__ 项缺失 ver 或与本流水线
    版本不符 = 代码重构前的陈旧缓存——读取侧直接视为无件（活跃心跳不重算，
    若不在此拦，旧零件会在下一次停顿重算前持续上屏）；停顿心跳的签名侧
    （orchestrator，同源 DOCK_PIPELINE_VERSION）会触发重算覆盖。
    """
    from backend.services.adaptive.components.dock_generator import DOCK_PIPELINE_VERSION
    for proj in (snapshot.get("projections") or []):
        if isinstance(proj, dict) and proj.get("__dock__"):
            if proj.get("ver") != DOCK_PIPELINE_VERSION:
                return []
            return proj.get("parts", [])
    return []


def _dock_parts_age_s(snapshot: Dict) -> Optional[int]:
    """当前 __dock__ 缓存项的年龄（秒；2026-09-15 槽位治理）。

    缓存写入侧带 ts（dock_generator._cache_dock_parts）；版本过滤同
    _extract_dock_parts——不匹配视为无件。无项/无 ts 返回 None。
    """
    import time as _time
    from backend.services.adaptive.components.dock_generator import DOCK_PIPELINE_VERSION
    for proj in (snapshot.get("projections") or []):
        if isinstance(proj, dict) and proj.get("__dock__"):
            if proj.get("ver") != DOCK_PIPELINE_VERSION:
                return None
            ts = proj.get("ts")
            if not isinstance(ts, (int, float)) or ts <= 0:
                return None
            return max(0, int(_time.time() - ts))
    return None


def _extract_onstage_guests(snapshot: Dict) -> List[str]:
    """从 __dock__ 缓存项提取临时通行证名单（2026-09-09；版本过滤同上）。"""
    from backend.services.adaptive.components.dock_generator import DOCK_PIPELINE_VERSION
    for proj in (snapshot.get("projections") or []):
        if isinstance(proj, dict) and proj.get("__dock__"):
            if proj.get("ver") != DOCK_PIPELINE_VERSION:
                return []
            return [str(g) for g in (proj.get("guests") or []) if g]
    return []


# 文风漂移提示缓存（chapter_id → (content_len, hint|None)）——内容没变不重算
_STYLE_HINT_CACHE: Dict[str, tuple] = {}


# 谋篇进度缓存（chapter_id → (content_md5, progress|None)）——键为内容 hash
# （B2 治理 2026-08-25：旧键=内容长度，等长改写会吃到旧缓存的旧进度）
_SPINE_PROG_CACHE: Dict[str, tuple] = {}


# ---- B2（2026-08-25 治理，docs/adaptive-assist-hardening.md P2）：判定参数 ----
# hit 档阈值=全部滑窗片段命中：hit 是「3 字滑窗」一族三处判定里唯一写库的
# （pending→hit 只前进不回退，不可逆），取最严档。旧判据 jieba topK=3 通用词
# 全命中——「他没有」「不多时」类词几乎必然散落在任何长文本里，大面积误 hit；
# 3 字滑窗片段比 jieba 单词具体得多，全命中可把通用词噪声压到近零。
SPINE_HIT_THRESHOLD = 1.0
# 临近岔路低阈值档（有意保留的宽松提示语义，M3 §5）：1/3 等效「任一~两个
# 片段现身」≈ 旧『任一关键词现身』的提示强度。它只多一张走向卡舱硬提示卡
# （不写库、作者可无视），宽松无害。
SPINE_NEAR_BRANCH_THRESHOLD = 1.0 / 3.0
# 增量区段就近窗口：常规心跳增量几十字；幽灵草稿连写采纳/心跳停跳后一次
# 可能积数千字。封顶 2000（≈ 两轮 burst 连写 700 字 + 一轮打字）覆盖真实
# 增量上限，同时把「大块文本里任意散落拼凑命中」的噪声面封住；窗口外的
# 更早文本属于已判定区段，漏判由 finish 报告 spine_note 兜底（宁漏勿误）。
SPINE_GROWTH_TAIL_CHARS = 2000


def _build_spine_progress(
    spine: Any, anchors: List[Any], near_branches: Optional[List[Dict]] = None,
) -> Dict:
    """进度组装（纯函数）：意图一句话 + 锚点清单 + pending 计数 + 人话 hint。"""
    pending_count = sum(1 for a in anchors if isinstance(a, dict) and a.get("status") == "pending")
    progress = {
        "intent": (spine or {}).get("intent", {}).get("text", ""),
        "anchors": [
            {"id": a.get("id", ""), "text": a.get("text", ""), "status": a.get("status", "pending")}
            for a in anchors if isinstance(a, dict)
        ],
        "pending_count": pending_count,
        "hint": f"还有 {pending_count} 条情节没写到" if pending_count else "打算里的情节都写到了",
    }
    if near_branches:
        progress["near_branches"] = near_branches
    return progress


async def _spine_progress_for_heartbeat(chapter: Any, orch, db: AsyncSession) -> Optional[Dict]:
    """章级谋篇进度判定（P1.4 M2，设计稿 §4.3——纯算法零 LLM）。

    B2 治理（2026-08-25）：判定走 text_match 共享判据（3 字滑窗片段命中率，
    禁止在此另写滑窗逻辑）——hit=全部片段命中**新增区段**（就近窗口内）；
    临近岔路走低阈值档宽松提示。增量区段由 orchestrator 记录的上次正文长度
    推（**首轮只记基线不判定**——进程重启后 growth=全文的大面积误 hit 不可逆，
    宁漏勿误，漏判由 finish 报告 spine_note 兜底；改写收缩退化为尾部 500 字）。
    结果按内容 hash 缓存；pending→hit 迁移才写库（progress 只前进不回退）。
    """
    if chapter is None:
        return None
    cid = str(chapter.id)
    spine = chapter.spine if isinstance(chapter.spine, dict) else None
    anchors = list((spine or {}).get("anchors") or [])
    content = chapter.content_text or ""
    content_md5 = hashlib.md5(content.encode("utf-8")).hexdigest()
    if not anchors:
        orch._last_content_len = len(content)
        _SPINE_PROG_CACHE.pop(cid, None)
        return None

    cached = _SPINE_PROG_CACHE.get(cid)
    if cached is not None and cached[0] == content_md5:
        orch._last_content_len = len(content)
        return cached[1]

    # 首轮（orchestrator 内存态归零——进程重启/重新进章后 _last_content_len=-1）：
    # 只记基线长度，不做 hit 判定。旧行为本轮 growth=全文，通用关键词大面积
    # 误 hit 写库不可逆（hit 只前进不回退）；宁漏勿误——漏判有 finish 报告
    # spine_note 兜底提醒，误判没有出路
    if getattr(orch, "_last_content_len", -1) < 0:
        orch._last_content_len = len(content)
        progress = _build_spine_progress(spine, anchors)
        _SPINE_PROG_CACHE[cid] = (content_md5, progress)
        return progress

    prev_len = orch._last_content_len
    growth = content[prev_len:] if len(content) > prev_len else content[-500:]

    changed = False
    near_branches = []
    try:
        for a in anchors:
            if not isinstance(a, dict) or a.get("status") != "pending" or not a.get("text"):
                continue
            anchor_text = str(a["text"])
            # hit：全片段命中新增区段（就近窗口内）。整串捷径仅对 ≥3 字锚点
            # 开放——2 字通用词的裸子串命中（「高山」∈「高山上」）正是旧噪声
            # 之源；无可判片段（<3 字锚点）按未命中处理，不给它留回归的门
            # （漏判有 finish 报告 spine_note 兜底）
            if text_matches(
                anchor_text, growth,
                threshold=SPINE_HIT_THRESHOLD,
                tail_chars=SPINE_GROWTH_TAIL_CHARS,
                exact_shortcut=len(anchor_text) >= 3,
            ):
                a["status"] = "hit"
                changed = True
            # 临近岔路（M3 §5）：带岔路标记的 pending 锚点走低阈值档宽松判定
            # （写到附近了但还没兑现）→ 走向卡舱硬提示置顶其走向选项。
            # 有意宽松：只多一张提示卡、不写任何库，作者可无视
            elif (
                isinstance(a.get("branch"), dict)
                and a["branch"].get("options")
                and text_matches(
                    anchor_text, growth,
                    threshold=SPINE_NEAR_BRANCH_THRESHOLD,
                    tail_chars=SPINE_GROWTH_TAIL_CHARS,
                )
            ):
                near_branches.append({
                    "id": a.get("id", ""),
                    "text": a.get("text", ""),
                    "options": a["branch"]["options"],
                })
    except Exception as e:
        logger.debug(f"[adaptive/spine] 进度判定失败（不阻塞心跳）: {e}")

    if changed:
        # 防并发 PATCH 整包覆盖：commit 前重读，hit 只前进。
        # spine 在本函数开头读入，判 hit 期间作者侧防抖 PATCH /adaptive/spine 可能
        # 已落库（改意图/增删锚点/划掉锚点）——直接把「旧快照+hit」整包写回会静默
        # 回滚作者的编辑。这里先结束当前读事务再 refresh 整行拿最新 spine，把已判
        # hit 的锚点（按 id 匹配、仅 pending→hit 单向，不碰其他字段）应用到新鲜
        # anchors 上再整体写回：作者的编辑保留，hit 迁移不丢。
        # refresh/commit 异常沿用现状语义：debug 吞掉，绝不阻塞心跳返回（此时
        # progress 仍用本地 anchors 组装，hit 只是不落库、下轮重判）。
        try:
            # 先 commit 结束本会话至今的读事务（本会话到此只读，无写入副作用）——
            # 防 SQLite WAL/PG 快照语义下 refresh 仍读到旧事务快照
            await db.commit()
            await db.refresh(chapter)  # 同 session 强制重 SELECT 整行
            fresh_spine = chapter.spine if isinstance(chapter.spine, dict) else {}
            # 逐锚点浅拷贝（dict(a)），两个目的：
            # ① JSONB 列无 mutable 追踪——直接改 ORM 值对象内层 dict 不会产生脏标记，
            #    且 SQLAlchemy 标量属性按「值相等」判变更，共享内层 dict 会让
            #    改写后的新包与 committed 值判等 → flush 静默跳过 UPDATE（实测踩坑）；
            # ② 新旧值可区分，保证整体赋值一定被识别为变更、落库一定发生。
            fresh_anchors = [
                dict(a) if isinstance(a, dict) else a
                for a in (fresh_spine.get("anchors") or [])
            ]
            if fresh_anchors:
                hit_ids = {
                    a.get("id") for a in anchors
                    if isinstance(a, dict) and a.get("status") == "hit" and a.get("id")
                }
                for fa in fresh_anchors:
                    if (
                        isinstance(fa, dict) and fa.get("id")
                        and fa.get("id") in hit_ids and fa.get("status") == "pending"
                    ):
                        fa["status"] = "hit"
                chapter.spine = {**fresh_spine, "anchors": fresh_anchors}
                await db.commit()
            else:
                # 作者已清空锚点（编辑权在作者）：无 hit 可迁移，不回写防污染
                pass
            # 局部变量同步到新鲜值：后续 progress 组装（intent/锚点清单）以最新为准
            spine = fresh_spine or None
            anchors = fresh_anchors
        except Exception as e:
            logger.debug(f"[adaptive/spine] 进度写库失败（不阻塞心跳）: {e}")

    progress = _build_spine_progress(spine, anchors, near_branches)
    _SPINE_PROG_CACHE[cid] = (content_md5, progress)
    orch._last_content_len = len(content)
    return progress


async def _style_drift_hint_for_heartbeat(chapter: Any, db: AsyncSession) -> Optional[Dict]:
    """文风漂移心跳轻提示（设计稿 §5）：章尾 3000 字同尺测量 vs 目标/健康带。

    纯 code 零 LLM；显著偏离才返回提示卡（kind=style_drift，走 canon_hints 管线）。
    任何失败/文本过短 → None（绝不阻塞心跳）。
    """
    if chapter is None:
        return None
    # 同一把尺子红线：content_text 是 HTML（编辑器 getHTML 落库），测量前必须
    # 先剥——与文风页章指纹/负面命中/章节收编同一剥法（routes/style._plain_text）
    from backend.services.utils.html_text import html_to_plain

    content = html_to_plain(getattr(chapter, "content_text", "") or "")
    cache_key = str(chapter.id)
    cached = _STYLE_HINT_CACHE.get(cache_key)
    if cached is not None and cached[0] == len(content):
        return cached[1]

    hint: Optional[Dict] = None
    if len(content) >= 400:
        try:
            from backend.repositories import AuthorSampleRepository
            from backend.services.style.fingerprint import (
                aggregate_corpus, compute_style_drift_hint,
            )
            from backend.services.validation.thresholds import CV_THRESHOLD_LO, CV_THRESHOLD_HI

            # 2026-09-14 去参数化：对话目标不再读作者拨的浮点数（已冻结只读），
            # 改为「与你自己语料的实测对话占比比」——样本聚合即作者自己的锚，
            # 比拍脑袋的目标数字诚实；零样本 → None（该维提示缺席，CV/重复度照常）。
            # （原生效卡查询随之退役——漂移提示不再消费卡的任何字段。）
            target = None
            samples = await AuthorSampleRepository(db).list_by_book(chapter.book_id)
            if samples:
                corpus_fp = aggregate_corpus(
                    [s.content or "" for s in samples], max_chars=8000,
                )
                target = corpus_fp.get("dialogue_ratio") or None
            message = compute_style_drift_hint(
                content[-3000:], target, CV_THRESHOLD_LO, CV_THRESHOLD_HI,
            )
            if message:
                hint = {
                    "kind": "style_drift",
                    "node_label": "文风",
                    "node_type": "style",
                    "detail": message,
                }
        except Exception:
            hint = None
    _STYLE_HINT_CACHE[cache_key] = (len(content), hint)
    return hint


# ============================================================
# A5c 收件箱积压提醒（P5 §3.2）：全书 pending 候选计数 → 柔性感知带提示
# ============================================================
# 红线（P5 §9 提示不拦截）：只提示，永不阻断写作动作；查询失败静默缺席。
# ============================================================

WORLD_INBOX_HINT_THRESHOLD = 5
WORLD_INBOX_CACHE_TTL_S = 10.0  # 心跳 3-4s 一次，10s TTL 砍掉约 2/3 计数查询

# 积压计数缓存（book_id → (monotonic_ts, count)）——settle/finish 落新候选时主动失效
_WORLD_INBOX_CACHE: Dict[str, tuple] = {}


def build_world_inbox_hint(
    pending_count: int, threshold: int = WORLD_INBOX_HINT_THRESHOLD,
) -> Optional[Dict]:
    """纯函数：pending 计数 → world_inbox 提示卡（≤阈值返回 None，宁静默勿刷屏）。"""
    if pending_count <= threshold:
        return None
    return {
        "kind": "world_inbox",
        "node_label": "世界收件箱",
        "node_type": "world",
        "detail": f"收件箱积压 {pending_count} 条世界变化待确认",
        "severity": "info",
    }


async def _pending_candidates_count(db: AsyncSession, book_id: str) -> int:
    """全书 pending 候选计数（book 级；调用方各自兜异常——提醒是柔性信号，不阻塞）。"""
    from backend.models import WorldEventCandidate

    result = await db.execute(
        select(func.count(WorldEventCandidate.id)).where(
            WorldEventCandidate.book_id == book_id,
            WorldEventCandidate.status == "pending",
        )
    )
    return int(result.scalar() or 0)


async def _world_inbox_hint_for_heartbeat(chapter: Any, db: AsyncSession) -> Optional[Dict]:
    """心跳积压提醒：短 TTL 计数缓存（防抖 + 省查询），超阈值才产卡。"""
    if chapter is None:
        return None
    book_id = str(chapter.book_id)
    cached = _WORLD_INBOX_CACHE.get(book_id)
    now = time.monotonic()
    if cached is not None and now - cached[0] < WORLD_INBOX_CACHE_TTL_S:
        count = cached[1]
    else:
        try:
            count = await _pending_candidates_count(db, book_id)
            _WORLD_INBOX_CACHE[book_id] = (now, count)
        except Exception as e:
            logger.debug(f"[adaptive/heartbeat] 收件箱计数失败（不阻塞心跳）: {e}")
            return None
    return build_world_inbox_hint(count)


def _extract_canon_hints(snapshot: Dict) -> List[Dict]:
    """从世界模型快照的 projections 里提取 canon_watch 缓存的 Canon 感知 hints。"""
    for proj in (snapshot.get("projections") or []):
        if isinstance(proj, dict) and proj.get("__canon_watch__"):
            return proj.get("hints", [])
    return []


def _extract_direction_cards(snapshot: Dict, spine: Any = None) -> List[Dict]:
    """从层 3 推测提取走向卡（跳过 __dock__ 缓存项；每个推测取首个 beat）。

    走向卡 = {event, anchors}，一句话剧情走向，供 Ctrl+Space 走向卡舱选择。
    P1.4 M2：推测带合法 serves_anchor（命中本章非 dropped 锚点 id）时随卡透传——
    防御第二道（写入侧 future_projection 已闸过一道）。
    """
    valid_ids = {
        a.get("id") for a in ((spine or {}).get("anchors") or [])
        if isinstance(a, dict) and a.get("status") != "dropped" and a.get("id")
    }
    cards: List[Dict] = []
    for proj in (snapshot.get("projections") or []):
        if not isinstance(proj, dict) or proj.get("__dock__"):
            continue
        for beat in (proj.get("possible_beats") or [])[:1]:
            event = (beat.get("event") or "").strip() if isinstance(beat, dict) else ""
            if not event:
                continue
            card = {
                "event": event[:60],
                "anchors": [str(a)[:20] for a in (beat.get("anchors") or [])][:3],
            }
            sa = beat.get("serves_anchor") if isinstance(beat, dict) else None
            if sa and sa in valid_ids:
                card["serves_anchor"] = sa
            if isinstance(beat, dict) and beat.get("from_encounter") is True:
                card["from_encounter"] = True
            cards.append(card)
    return cards[:3]

