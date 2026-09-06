# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - NLE-ADF 3.0 意图反推组件（层 2）
"""
从作者已写正文（+可选大纲）推断本章意图，写入世界模型层 2。

四条路径（2026-09-03 意图加固批次 + 线 C 接力棒，优先级从高到低）：
- from_spine：作者在打算 tab 写了一句话意图 → 最高信度（作者亲手材料，
  直接转化不调 LLM；纠正手势「不对」落的也是 spine.intent，经此即时生效）
- from_outline：作者有大纲 → 高信度（大纲即意图，附 must_hit 校对）
  （线 C：以上两条短路不读正文体量——章首空章写了打算/大纲也立刻上桌，
  旧序被「正文不足 100 字」闸门挡在门外）
- baton 接力棒：无材料且正文不足（章首冷启动）→ 上一章结尾摘要确定性
  接管（source=baton，纯拼接零 LLM 不空猜；stitch 兜底消费它，dock 不吃）
- from_text：都没有且正文够量 → LLM 反推（中信度，带三道加固：
  ① 喂全——spine 锚点/细纲胶囊速记/前文摘要/角色此刻状态/开放伏笔进输入；
  ② 问窄——next_direction「下一步往哪走」是比 arc 更轻的提问，卡片舱消费它；
  ③ 证据回查——evidence 必须逐字出自正文，代码闸验真，交不出依据即降信度
  （不赌模型自觉；猜错的信度跌破 dock 消费阈 0.5，舱不吃存疑方向））

校准（线 B 意图画像）：近期 intent_correct 纠正史（打算 tab「不对」手势的
埋点）作为 few-shot + 前几章作者亲笔意图轨迹进反推 prompt——把「平均作者」
的猜测往「这位作者」的口味上拉；纠正频繁（≥2）时追加保守指令（宁答
「方向不明」别硬编）。

校对：反推结果 vs ChapterCard.must_hit_events，偏差记入 intent.deviations
（不强制修正——只标注，作者主权）。
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.services.context.settings_bundle import load_chapter_settings_bundle
from backend.services.llm.client import call_llm_with_usage
from backend.services.adaptive.observing import get_adaptive_recorder
from backend.services.prompts.adaptive_prompts import build_intent_inference_prompt
from backend.services.adaptive.world_model import WorldModelRepository, ChapterIntent
from backend.services.utils.json_safe import parse_json_safe  # 复用容错解析

logger = logging.getLogger(__name__)

# dock 消费猜测方向的信度门槛（orchestrator/dock_generator 同口径）：
# 证据回查不过的反推跌破此线——舱不吃存疑方向（宁缺毋滥），展示层照常显示
DOCK_INTENT_MIN_CONFIDENCE = 0.5

# 纠正史读取缓存（book_id → (monotonic_ts, events)）——扫 jsonl 有 IO 成本
_CORR_SCAN_CACHE: Dict[str, Tuple[float, list]] = {}
_CORR_SCAN_TTL = 30.0


async def run(chapter_id: str, db, model_snapshot: Dict, budget_tokens: int = 1500, **kw) -> Dict:
    """意图反推。由 orchestrator 调度。

    kw 可带 outline_notes（前端心跳透传的细纲胶囊速记原文，作者最稀疏
    最真实的意图信号——胶囊会话级不落库，只在写作中经心跳供给）。
    """
    bundle = await load_chapter_settings_bundle(chapter_id, db)
    repo = WorldModelRepository(db)

    outline = bundle.outline_text or ""
    spine_intent, spine_anchors = await _spine_material(chapter_id, db)

    # ---- 作者亲手材料短路（不调 LLM）----
    # 打算一句话 > 大纲：spine intent 是作者蒸馏过的方向（含「不对」纠正手势
    # 的产物），比大纲首段更贴近「本章要去哪」。
    # 线 C（2026-09-03）：短路上移到正文体量闸门之前——spine/大纲都不读正文，
    # 章首空章也该立刻有作者意图上桌（旧序：冷启动章被「正文不足」挡在门外，
    # 作者写了打算也吃不到，直到憋出 100 字）。
    if spine_intent:
        intent = ChapterIntent(
            source="author",
            confidence=0.9,
            arc=spine_intent[:120],
            setup_points=_extract_setup_points(bundle),
            must_hits=_get_must_hits(bundle),
            foreshadows=_get_foreshadows(bundle),
            deviations=[],
        )
        await repo.set_intent(chapter_id, intent)
        return {"source": "author", "confidence": 0.9, "via": "spine"}
    if outline.strip():
        intent = ChapterIntent(
            source="author",
            confidence=0.85,
            arc=_extract_arc_from_outline(outline),
            setup_points=_extract_setup_points(bundle),
            must_hits=_get_must_hits(bundle),
            foreshadows=_get_foreshadows(bundle),
            deviations=[],  # 有大纲时偏差少，省 LLM
        )
        await repo.set_intent(chapter_id, intent)
        return {"source": "author", "confidence": 0.85}

    # 正文来源：画布全文（剥 HTML）——画布即事实源。层 1 事实是沉淀审计账，
    # 作者删改后即过期，不得代替正文（曾致意图反推被已删除文本带偏）
    from backend.services.adaptive.paragraph_source import written_text
    written = written_text(bundle.content_text or "")
    if len(written.strip()) < 100:
        # 章首接力棒（线 C）：冷启动章（无材料+正文不足）不空猜——上一章结尾
        # 摘要就是本章开场最确定的方向，纯拼接接管（零 LLM），标 source=baton
        # 供 stitch 兜底消费（线 A）且与猜测分档。无摘要=全书第一章，保持跳过。
        baton = _baton_from_previous(bundle)
        if baton is not None:
            await repo.set_intent(chapter_id, baton)
            return {"source": "baton", "confidence": baton.confidence,
                    "via": "previous_summary"}
        return {"skipped": True, "reason": "正文不足"}

    # ---- 无作者材料：LLM 反推（加固三路：喂全/问窄/证据回查）----
    nutrients = bundle.nutrients()
    soft = bundle.soft_constraints()
    # 线 B 意图画像（2026-09-03）：纠正史扩窗取量（统计用全量计数，教材仍只
    # 展示最近 3 条——prompt 侧截断）+ 前几章作者亲笔意图轨迹
    corrections = _recent_intent_corrections(str(bundle.book_id or ""), limit=20)
    trajectory = await _chapter_intent_trajectory(bundle, db)
    sys_p, usr_p = build_intent_inference_prompt(
        written, outline, nutrients, soft,
        spine_anchors=spine_anchors or None,
        outline_notes=[n for n in (kw.get("outline_notes") or []) if n] or None,
        corrections=corrections or None,
        intent_trajectory=trajectory or None,
        correction_count=len(corrections),
    )
    try:
        result = await call_llm_with_usage(
            system_prompt=sys_p,
            user_prompt=usr_p,
            # 意图反推是归纳/判断任务（推断本章弧线、情绪曲线、标注偏差），
            # 属分析型工作，走 reasoning 槽并保留 thinking（不传 REASONING_DISABLED）。
            # 此前用 creative + 关 thinking，是「用生成配置干分析的活」。
            # 此为后台异步任务（heartbeat 触发），延迟不敏感；只在大纲为空时才调。
            model_type="reasoning",
            temperature=0.2,
            max_tokens=budget_tokens,
        )
        get_adaptive_recorder(str(chapter_id)).record_result(
            "adaptive.intent_inference", result, model_slot="reasoning")
        parsed = parse_json_safe(result.content or "") or {}

        # 证据回查（代码闸）：模型必须交出正文原句作依据——交不出/编造的
        # 猜测降信度到 dock 消费阈之下（舱不吃存疑方向，展示层不受影响）。
        # 不赌模型自觉：「交证据」是 prompt 请求，「验证据」是代码裁决
        evidence = _valid_evidence(parsed.get("evidence") or [], written)
        next_direction = str(parsed.get("next_direction") or "").strip()[:120]
        confidence = 0.55 if evidence else 0.4
        if not str(parsed.get("arc") or "").strip() and not next_direction:
            confidence = 0.0  # 空反推：arc 与方向双缺，等同没猜

        intent = ChapterIntent(
            source="inferred",
            confidence=confidence,
            arc=str(parsed.get("arc") or "").strip(),
            emotion_curve=parsed.get("emotion_curve", []),
            setup_points=parsed.get("setup_points", []),
            must_hits=_get_must_hits(bundle),
            foreshadows=_get_foreshadows(bundle),
            deviations=parsed.get("deviations", []),
            next_direction=next_direction,
            evidence=evidence,
        )
        await repo.set_intent(chapter_id, intent)
        return {"source": "inferred", "confidence": confidence, "arc": intent.arc}
    except Exception as e:
        logger.warning(f"[intent_inference] LLM 反推失败: {e}")
        return {"error": str(e)}


# ============================================================
# 作者亲手材料（spine）与证据回查——纯函数区
# ============================================================

async def _spine_material(chapter_id: str, db) -> Tuple[str, List[str]]:
    """打算 tab 的作者材料：一句话意图 + pending 锚点文本。

    与 dock_generator._spine_intent 同源的轻量直查（chapters 主键单行，
    开销可忽略）；无脉络/查询失败返回空（零变化契约）。
    """
    try:
        from backend.models import Chapter as _Chapter
        ch = await db.get(_Chapter, chapter_id)
        if ch is None or not isinstance(ch.spine, dict):
            return "", []
        intent_text = ((ch.spine.get("intent") or {}).get("text") or "").strip()
        anchors = [
            str(a.get("text") or "").strip()
            for a in (ch.spine.get("anchors") or [])
            if isinstance(a, dict) and a.get("status") != "dropped"
            and str(a.get("text") or "").strip()
        ]
        return intent_text, anchors[:5]
    except Exception:
        return "", []


def _baton_from_previous(bundle) -> "Optional[ChapterIntent]":
    """章首接力棒（2026-09-03 线 C）：冷启动章的确定性意图接管。

    无作者材料（spine/大纲皆空）且正文不足时，上一章结尾摘要就是本章开场
    最确定的方向——纯拼接零 LLM，不猜。source=baton 与 author/inferred 分档：
    dock 猜测链只认 inferred（baton 不进舱，避免摘要复读成挂件）；stitch 兜底
    （线 A）认 inferred+baton（衔接参照正是短续写缺的）。
    信度 0.6：确定性接管但只是方向参照，低于作者材料（0.85/0.9）。
    无摘要（全书第一章）→ None（保持旧「正文不足」跳过，零变化）。
    """
    summary = str(getattr(bundle, "previous_summary", "") or "").strip()
    if not summary:
        return None
    return ChapterIntent(
        source="baton",
        confidence=0.6,
        arc="承接上一章：" + summary[:100],
        # next_direction 留空——arc 即内容载体（stitch 兜底 next_direction 缺省
        # 回落 arc）；写死一句通用衔接语反而稀释信息
        setup_points=[],
        must_hits=[],
        foreshadows=[],
        deviations=[],
    )


async def _chapter_intent_trajectory(bundle, db) -> List[str]:
    """前几章作者亲笔「打算」轨迹（2026-09-03 线 B 意图画像）。

    取同书本章之前最近 12 章的 spine，过滤出写了意图的章，最近 5 条按章序
    （旧→新）排成「第N章：…」行——反推 prompt 的口味画像素材（学这位作者
    写意图的粒度与口吻）。无书号/无章号/全空 → 空表（缺席零变化契约）；
    查询失败静默返空（画像是增强不是前提）。
    """
    try:
        book_id = getattr(bundle, "book_id", None)
        current_no = getattr(bundle, "chapter_number", None)
        if not book_id or current_no is None:
            return []
        from sqlalchemy import select as _select

        from backend.models import Chapter as _Chapter
        rows = (await db.execute(
            _select(_Chapter.chapter_number, _Chapter.spine)
            .where(_Chapter.book_id == book_id)
            .order_by(_Chapter.chapter_number.desc())
            .limit(12)
        )).all()
        picked: List[Tuple[int, str]] = []
        for no, spine in rows:
            if no is None or int(no) >= int(current_no):
                continue
            if not isinstance(spine, dict):
                continue
            text = str(((spine.get("intent") or {}).get("text")) or "").strip()
            if text:
                picked.append((int(no), text[:80]))
            if len(picked) >= 5:
                break
        picked.reverse()  # 查询是倒序取近，展示按章序（旧→新）读成长线
        return [f"第{no}章：{text}" for no, text in picked]
    except Exception:
        return []


def _norm_for_match(s: str) -> str:
    """证据回查的规范化：去标点空白——模型摘句常带标点出入，比对按字面骨架。"""
    from backend.services.adaptive.text_match import FRAGMENT_INVALID_CHARS
    return "".join(c for c in (s or "") if c not in FRAGMENT_INVALID_CHARS)


def _valid_evidence(evidence: Any, written: str) -> List[str]:
    """证据回查（代码闸）：只保留逐字出自正文的依据句（规范化后 ≥4 字子串）。

    模型编造的「依据」在此整类掐死——交不出正文依据的猜测不配高信度。
    返回清洗后的有效依据（保原文、截 60 字、至多 3 条）。
    """
    haystack = _norm_for_match(written)
    if not haystack:
        return []
    valid: List[str] = []
    for e in (evidence or []):
        s = str(e or "").strip().strip("「」『』\"'")
        if len(_norm_for_match(s)) >= 4 and _norm_for_match(s) in haystack:
            valid.append(s[:60])
        if len(valid) >= 3:
            break
    return valid


def _collab_paths() -> List[Path]:
    """collab 埋点文件路径（轮转份 + 当前份）。

    ⚠ 与 quiet_learning._collab_paths 同款推导，有意复制（该函数是模块私有）：
    锚定项目根不随 CWD 漂移，尊重 VELLUMA_DATA_DIR 运行时覆盖。
    ⚠ 本模块比 quiet_learning 深一层（components/ 子包）——parents[4] 才是
    项目根（2026-09-03 审计实证：复制时写成 parents[3] 指向 backend/data，
    纠正史回喂静默失效）。
    """
    root = Path(__file__).resolve().parents[4]
    data_dir = Path(os.getenv("VELLUMA_DATA_DIR") or (root / "data"))
    base = data_dir / "collab_events.jsonl"
    return [base.with_name(base.name + ".1"), base]


def _recent_intent_corrections(book_id: str, limit: int = 3) -> List[Dict]:
    """近期意图纠正史（kind=intent_correct，新到旧）——反推 prompt 的口味教材。

    失败/无埋点静默返空（校准是增强不是前提）；按书 30s 缓存防抖。
    """
    if not book_id:
        return []
    now = time.monotonic()
    ent = _CORR_SCAN_CACHE.get(book_id)
    if ent and now - ent[0] < _CORR_SCAN_TTL:
        return ent[1][:limit]
    events: List[Dict] = []
    for path in _collab_paths():
        try:
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"intent_correct"' not in line:  # 快速预筛，减少 json 解析量
                        continue
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if e.get("kind") != "intent_correct":
                        continue
                    if str(e.get("book_id") or "") != str(book_id):
                        continue
                    d = e.get("detail") or {}
                    guessed = str(d.get("guessed") or "").strip()
                    corrected = str(d.get("corrected") or "").strip()
                    if guessed and corrected:
                        events.append({"guessed": guessed, "corrected": corrected,
                                       "ts": str(e.get("ts") or "")})
        except Exception as exc:
            logger.debug(f"[intent_inference] 纠正史扫描跳过损坏文件 {path}: {exc}")
    # 新到旧（ts 为 ISO 串，字典序即时间序；缺失排尾）
    events.sort(key=lambda x: x.get("ts") or "", reverse=True)
    _CORR_SCAN_CACHE[book_id] = (now, events)
    return events[:limit]


def _extract_arc_from_outline(outline: str) -> str:
    """从大纲提取一句话弧线（取首条像剧情的行，截断）。

    卷首致辞过滤（2026-09-03 实测）：大纲常以「以罗曼·罗兰的巨著《约翰·
    克利斯朵夫》……名言开篇」这类引语/指示开头——首行直连把它当本章弧线，
    打算 tab 的猜测行整行怪掉。元信息行判据与就近节拍供给共用同一权威
    （outline_nearby.outline_line_is_meta：整行引语/含《》/超短指示行），
    取第一条候选；全都不像剧情回退首行非空行（宁要朴素，不可空）。
    """
    from backend.services.adaptive.outline_nearby import outline_line_is_meta

    lines = [l.strip() for l in outline.strip().split("\n") if l.strip()]
    if not lines:
        return ""
    for l in lines:
        if outline_line_is_meta(l):
            continue
        return l[:120]
    return lines[0][:120]


def _extract_setup_points(bundle) -> list:
    """铺陈要点（从章节卡或大纲提取）。"""
    cc = bundle.chapter_card
    if cc and getattr(cc, "must_hit_events", None):
        return [e.get("event", "") if isinstance(e, dict) else str(e) for e in cc.must_hit_events[:4]]
    return []


def _get_must_hits(bundle) -> list:
    cc = bundle.chapter_card
    if not cc:
        return []
    return [e.get("event", "") if isinstance(e, dict) else str(e) for e in (cc.must_hit_events or [])[:6]]


def _get_foreshadows(bundle) -> list:
    cc = bundle.chapter_card
    if not cc:
        return []
    ops = cc.foreshadow_ops or []
    return [f"{o.get('action', '')} {o.get('note', '')}".strip() if isinstance(o, dict) else str(o) for o in ops[:4]]
