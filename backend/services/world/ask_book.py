# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 问书（行间手势速查，04 下一阶段设计稿）
"""
给「更懂这本书」装上调用口——系统对书的认知目前只用于主动「递」，本模块
补上作者主动「问」的通道（docs/next-phase/04-ask-the-book.md）。

定位铁律：**图书管理员，不是合著者**——只读作者自己的数据、答完即止无对话
上下文、每个事实附出处、一个字都不创作。

混合驱动，纯代码骨架：六类问题零 LLM 秒答；听不懂的走 M2 意图解析笼子
（LLM 只理解不生效，解析产物过硬闸）；复合问题走 M3 材料内合成（LLM 只在
检索到的真实材料内组织语言，引用的出处 id 必须都在材料里，编造即拒稿）。
检索不到答「没查到」——诚实是功能，不是失败。

副作用：数据纯读（LLM 观测经 recorder 记账）。问题原文落
data/ask_book_metrics.jsonl（M1 起的度量：问题类型分布校准六类覆盖度与
笼子大小——05 瘦身口径独立台账，不接协作事件总线）。
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Book, Chapter, PlotLedger, WorldEvent, WorldLocation
from backend.services.context.world_bridge import resolve_narrative_time
from backend.services.world.reader_ledger import load_reveal_rows

logger = logging.getLogger(__name__)

_MAX_EVENTS_SCAN = 500      # 实体出场扫描上限（本地书量级绰绰有余）
_MAX_CHAPTER_HITS = 3       # 「哪章写过」最多列三章
_SENT_SPLIT = re.compile(r"[。！？!?\n]+")


# ============================================================
# 小工具
# ============================================================

def _calendar_label(t: int) -> str:
    """连续日 → 架空历法标签（与前端 timeFormat 同 365/30 口径）。"""
    t = max(0, int(t))
    year = t // 365 + 1
    rem = t % 365
    month = rem // 30 + 1
    day = rem % 30 + 1
    return f"第{year}年{month}月{day}日"


def _strip_question_marks(q: str) -> str:
    return re.sub(r"[?？\s]", "", q or "").strip()


def _which_keyword(q: str) -> str:
    """「X 是在哪章写的？」→ 关键词 X：截到疑问词前，剥掉尾巴的谓词。"""
    m = re.search(r"(在哪章|哪一章|第几章|什么时候|何时|哪里)", q or "")
    if not m:
        return ""
    head = q[: m.start()]
    head = re.sub(r"(是|写的|说的|提到的|提到的|出现|定的|定过|定|写|说|提)?$", "", head.strip())
    return head.strip()


def _chapter_source(chapter: Any) -> Dict[str, Any]:
    return {
        "label": f"第 {getattr(chapter, 'chapter_number', '?')} 章",
        "type": "chapter",
        "chapter_id": str(getattr(chapter, "id", "") or ""),
    }


def _sentence_with_keyword(text: str, keywords: List[str]) -> str:
    """含任一关键词的首句（≤60 字）——「哪章写过」的原句出处。"""
    for s in _SENT_SPLIT.split(text):
        s = s.strip()
        if any(k in s for k in keywords if k):
            return s[:60]
    return ""


def _question_keywords(question: str, top: int = 3) -> List[str]:
    """问题 → 检索关键词（整句优先，jieba 抽词兜底——复合问句单串常常不命中）。"""
    kws = [_strip_question_marks(question)]
    kws = [k for k in kws if len(k) >= 2]
    try:
        import jieba.analyse

        kws += [w for w in jieba.analyse.extract_tags(question or "", topK=top) if len(w) >= 2]
    except Exception:
        pass
    seen = []
    for k in kws:
        if k not in seen:
            seen.append(k)
    return seen[:4]


async def _nearest_chapter_by_time(db: AsyncSession, book_id: str, t: int) -> Optional[Any]:
    """事件时刻 → 最近的前序章锚（「上次出场在第几章前后」的换算）。"""
    rows = (await db.execute(
        select(Chapter)
        .where(Chapter.book_id == book_id, Chapter.narrative_time.isnot(None))
        .order_by(Chapter.narrative_time.desc())
        .limit(200)
    )).scalars().all()
    for ch in rows:
        if int(ch.narrative_time) <= t:
            return ch
    return None


def _resolve_entity(name: str, entities: List[Any]) -> Optional[Any]:
    """名/别名精确 → 包含（最长名优先，多实体歧义不猜）。"""
    n = (name or "").strip()
    if not n:
        return None
    exact = []
    contains = []
    for e in entities:
        names = [str(e.name or "").strip()] + [str(a).strip() for a in (getattr(e, "aliases", None) or []) if a]
        for cand in names:
            if not cand:
                continue
            if cand == n:
                exact.append((len(cand), e))
            elif n in cand or cand in n:
                contains.append((len(cand), e))
    pool = exact or contains
    if not pool:
        return None
    hits = {str(e.id): e for _, e in sorted(pool, key=lambda x: -x[0])}
    return next(iter(hits.values())) if len(hits) == 1 else None


def _resolve_location(name: str, locations: List[Any]) -> Optional[Any]:
    n = (name or "").strip()
    if not n:
        return None
    for loc in locations:
        if (loc.name or "").strip() == n:
            return loc
    return None  # 不做模糊——地点错认比没查到贵


# ============================================================
# 六类纯代码回答（零 LLM）
# ============================================================

async def _answer_threads(db: AsyncSession, book_id: str, current: int) -> Dict[str, Any]:
    hooks = (await db.execute(
        select(PlotLedger).where(PlotLedger.book_id == book_id, PlotLedger.status == "open")
    )).scalars().all()
    if not hooks:
        return {"kind": "threads", "text": "没有没收的线头——账本上没有还开着的伏笔。", "sources": []}
    items = []
    oldest = 0
    for h in hooks:
        open_for = None
        if h.created_at_chapter is not None and current:
            open_for = max(0, current - int(h.created_at_chapter))
            oldest = max(oldest, open_for)
        items.append({"content": str(h.content or "")[:60], "ledger_key": str(h.ledger_key or ""), "chapters_open": open_for})
    items.sort(key=lambda r: -(r["chapters_open"] or 0))
    head = items[0]["content"]
    text = f"还有 {len(items)} 条没收的线头" + (
        f"，最久「{head}」吊了 {oldest} 章" if oldest else f"，最新一条「{head}」") + "。"
    sources = [{
        "label": f"伏笔：{it['content']}" + (f"（吊了 {it['chapters_open']} 章）" if it["chapters_open"] else ""),
        "type": "foreshadow",
        "ledger_key": it["ledger_key"],
    } for it in items[:5]]
    return {"kind": "threads", "text": text, "sources": sources}


async def _answer_reveals_due(db: AsyncSession, book_id: str, current: int) -> Dict[str, Any]:
    rows = await load_reveal_rows(db, book_id)
    due = [r for r in rows if r.get("expected_chapter") is not None and int(r["expected_chapter"]) <= current]
    if not due:
        return {"kind": "reveals_due", "text": f"第 {current} 章没有该揭的真相——揭示计划里没有到期或逾期的。", "sources": []}
    due.sort(key=lambda r: int(r["expected_chapter"]))
    parts = []
    sources = []
    for r in due[:6]:
        overdue = current - int(r["expected_chapter"])
        parts.append(f"「{r['label']}」" + (f"（已逾期 {overdue} 章）" if overdue > 0 else "（本章该揭）"))
        sources.append({"label": f"真相：{r['label']}", "type": "canon", "label_text": r["label"]})
    return {
        "kind": "reveals_due",
        "text": f"该抖出的真相 {len(due)} 条：" + "；".join(parts) + "。",
        "sources": sources,
    }


async def _answer_distance(
    db: AsyncSession, book_id: str, loc_a_name: str, loc_b_name: str
) -> Dict[str, Any]:
    book = await db.get(Book, book_id)
    scale = getattr(book, "map_scale", None) if book is not None else None
    locations = list((await db.execute(
        select(WorldLocation).where(WorldLocation.book_id == book_id)
    )).scalars().all())
    a = _resolve_location(loc_a_name, locations)
    b = _resolve_location(loc_b_name, locations)
    if a is None or b is None:
        missing = loc_a_name if a is None else loc_b_name
        return {"kind": "not_found", "text": f"没查到叫「{missing}」的地点——世界页的地点名单里没有。", "sources": []}
    if not scale or a.coord_x is None or a.coord_y is None or b.coord_x is None or b.coord_y is None:
        return {
            "kind": "not_found",
            "text": "没查到距离——这本书还没在世界页标定地图比例尺（或地点没标坐标）。",
            "sources": [],
        }
    from backend.services.world.spatial import distance_days, format_distance

    days = distance_days((a.coord_x, a.coord_y), (b.coord_x, b.coord_y), scale)
    if days is None:
        return {"kind": "not_found", "text": "没查到距离——比例尺换算没算出来。", "sources": []}
    return {
        "kind": "distance",
        "text": f"从{a.name}到{b.name}{format_distance(days, scale=scale)}。",
        "sources": [
            {"label": f"地点：{a.name}", "type": "location", "location_id": str(a.id)},
            {"label": f"地点：{b.name}", "type": "location", "location_id": str(b.id)},
        ],
    }


async def _answer_last_appearance(
    db: AsyncSession, book_id: str, entity: Any, t: int
) -> Dict[str, Any]:
    events = list((await db.execute(
        select(WorldEvent)
        .where(WorldEvent.book_id == book_id, WorldEvent.time_start <= t)
        .order_by(WorldEvent.time_start.desc(), WorldEvent.sequence_num.desc())
        .limit(_MAX_EVENTS_SCAN)
    )).scalars().all())
    eid = str(entity.id)
    hit = None
    for ev in events:
        parts = [str(p) for p in (ev.participant_ids or [])]
        if eid in parts:
            hit = ev
            break
    if hit is None:
        return {
            "kind": "not_found",
            "text": f"没查到{entity.name}的出场记录——事件账本里没有「{entity.name}」参与的事件。",
            "sources": [],
        }
    ch = await _nearest_chapter_by_time(db, book_id, int(hit.time_start or 0))
    where = f"（约第 {ch.chapter_number} 章前后）" if ch is not None else ""
    note = str(hit.note or hit.title or hit.event_type or "")[:60]
    sources = [{"label": f"事件：{note or hit.event_type}", "type": "world_event", "event_id": str(hit.id)}]
    if ch is not None:
        sources.append(_chapter_source(ch))
    return {
        "kind": "last_appearance",
        "text": f"{entity.name}上次出场在{_calendar_label(int(hit.time_start or 0))}{where}：{note or hit.event_type}。",
        "sources": sources,
    }


async def _answer_knows(
    db: AsyncSession, book_id: str, x: Any, y_name: str, t: int
) -> Dict[str, Any]:
    """X 知道 Y 吗：Y 是真相（canon 标签）→ belief 四值判定；Y 是角色 → Level 0 同场扫描。"""
    from backend.models import CanonNode
    from backend.repositories.world_repository import WorldRepository
    from backend.services.world.belief import BELIEVES_FALSE, KNOWS, fold_belief, proposition_status

    nodes = list((await db.execute(
        select(CanonNode).where(CanonNode.book_id == book_id)
    )).scalars().all())
    y_node = next((n for n in nodes if (n.label or "").strip() == (y_name or "").strip()), None)
    events = list((await db.execute(
        select(WorldEvent)
        .where(WorldEvent.book_id == book_id, WorldEvent.time_start <= t)
        .order_by(WorldEvent.time_start.asc(), WorldEvent.sequence_num.asc())
        .limit(_MAX_EVENTS_SCAN)
    )).scalars().all())

    if y_node is not None:
        state = fold_belief(events, t)
        status = proposition_status(str(y_node.id), {str(x.id)}, state)
        if status == KNOWS:
            text = f"按认知账本：{x.name}知道「{y_name}」（有被告知/目击/发现的记录）。"
        elif status == BELIEVES_FALSE:
            text = f"按认知账本：{x.name}对「{y_name}」持有误信（以为的是错的版本）。"
        else:
            text = f"按认知账本：没有{x.name}知晓「{y_name}」的证据——证据不足按不知道处理。"
        return {
            "kind": "knows",
            "text": text,
            "sources": [{"label": f"真相：{y_node.label}", "type": "canon", "label_text": y_node.label}],
        }

    # Y 当角色：Level 0 同场（共同参与同一事件 = 经历过）
    entities = await WorldRepository(db).entities.list_by_book(book_id)
    y = _resolve_entity(y_name, entities)
    if y is None:
        return {"kind": "not_found", "text": f"没查到叫「{y_name}」的真相或角色。", "sources": []}
    xid, yid = str(x.id), str(y.id)
    hit = None
    for ev in sorted(events, key=lambda e: (int(e.time_start or 0), int(e.sequence_num or 0)), reverse=True):
        parts = [str(p) for p in (ev.participant_ids or [])]
        if xid in parts and yid in parts:
            hit = ev
            break
    if hit is None:
        return {
            "kind": "knows",
            "text": f"没查到{x.name}与{y.name}的同场或被告知记录——按认知账本无法确认知道。",
            "sources": [],
        }
    ch = await _nearest_chapter_by_time(db, book_id, int(hit.time_start or 0))
    where = f"（约第 {ch.chapter_number} 章前后）" if ch is not None else ""
    note = str(hit.note or hit.event_type or "")[:60]
    return {
        "kind": "knows",
        "text": f"有过同场经历：{x.name}与{y.name}在{_calendar_label(int(hit.time_start or 0))}{where}同处「{note or hit.event_type}」——在场即知晓（Level 0）。",
        "sources": [{"label": f"事件：{note or hit.event_type}", "type": "world_event", "event_id": str(hit.id)}],
    }


async def _answer_which_chapter(db: AsyncSession, book_id: str, keyword: str) -> Optional[Dict[str, Any]]:
    from backend.services.utils.html_text import html_to_plain

    kws = _question_keywords(keyword)
    if not kws:
        return None
    chapters = list((await db.execute(
        select(Chapter).where(Chapter.book_id == book_id)
        .order_by(Chapter.chapter_number.asc())
    )).scalars().all())
    hits = []
    for ch in chapters:
        sent = _sentence_with_keyword(html_to_plain(ch.content_text or ""), kws)
        if sent:
            hits.append((ch, sent))
        if len(hits) >= _MAX_CHAPTER_HITS:
            break
    if not hits:
        return {"kind": "not_found", "text": f"没查到正文里写过「{kws[0]}」。", "sources": []}
    parts = [f"第 {ch.chapter_number} 章「{sent}」" for ch, sent in hits]
    return {
        "kind": "which_chapter",
        "text": f"「{kws[0]}」写在：" + "；".join(parts) + "。",
        "sources": [_chapter_source(ch) for ch, _ in hits],
    }


# ============================================================
# 主入口：模式识别 → 六类直答 → M2 意图笼 → M3 合成
# ============================================================

_RE_THREADS = re.compile(r"(线头|伏笔)")
_RE_THREADS_Q = re.compile(r"(几|多少|还有|剩|没收|哪些|什么)")
_RE_REVEALS = re.compile(r"(该|要).{0,6}(揭|抖|亮|说破|掀)|揭示|真相")
_RE_REVEALS_Q = re.compile(r"(这|本)章|到期")
_RE_DISTANCE = re.compile(r"(?P<a>[^，。？?]{1,14}?)到(?P<b>[^，。？?]{1,14}?)(走|得走|要走)?(多久|几天|多少天|多远|多长时间|多长)")
_RE_LAST = re.compile(r"(上次|最近|最后|上回)")
_RE_LAST_Q = re.compile(r"(出场|出现|露面|见到|什么时候|啥时候)")
# x 懒惰（动词字面紧跟其后天然定界）；y 贪婪吃满到句读——懒惰版在无行尾锚的
# re.search 下取最短匹配，「明姐的身世吗」被截成「明」致 canon 标签匹配失败
# 降级到角色分支（GUI 交叉验证缺陷 #2）；句尾语气词由 _strip_knows_tail 剥。
_RE_KNOWS = re.compile(r"(?P<x>[^，。？?]{1,14}?)(知道|晓得|认识)(?P<y>[^，。？?]{1,14})")
_RE_WHICH = re.compile(r"(在哪章|哪一章|第几章|什么时候写的|何时写的)")


def _strip_knows_tail(y: str) -> str:
    """剥掉 Y 尾部的语气词/问号（「明姐的身世吗」→「明姐的身世」）。"""
    return re.sub(r"[吗呢么啊呀]+[?？!！。]*$", "", (y or "").strip()).strip()


def classify_question(question: str) -> Optional[Dict[str, str]]:
    """纯函数：问题 → 结构化意图（六类之一或 None）。单测锚点。"""
    q = question or ""
    if _RE_THREADS.search(q) and _RE_THREADS_Q.search(q):
        return {"type": "threads"}
    if _RE_REVEALS.search(q) and _RE_REVEALS_Q.search(q):
        return {"type": "reveals_due"}
    m = _RE_DISTANCE.search(q)
    if m and m.group("a").strip() and m.group("b").strip():
        return {"type": "distance", "a": m.group("a").strip(), "b": m.group("b").strip()}
    m = _RE_KNOWS.search(q)
    if m and m.group("x").strip() and m.group("y").strip():
        y = _strip_knows_tail(m.group("y"))
        if y:  # 剥完语气词可能为空（「知道吗」无宾语）——不算 knows
            return {"type": "knows", "x": m.group("x").strip(), "y": y}
    if _RE_WHICH.search(q):
        return {"type": "which_chapter", "keyword": _which_keyword(q) or q}
    if _RE_LAST.search(q) and _RE_LAST_Q.search(q):
        return {"type": "last_appearance", "name_hint": q}
    return None


async def _dispatch(
    db: AsyncSession, book_id: str, chapter: Any, t: int, intent: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """结构化意图 → 对应检索器（六类共用；M2 解析产物与正则直答走同一扇门）。"""
    ty = intent.get("type")
    current = int(getattr(chapter, "chapter_number", 0) or 0)
    if ty == "threads":
        return await _answer_threads(db, book_id, current)
    if ty == "reveals_due":
        return await _answer_reveals_due(db, book_id, current)
    if ty == "distance":
        return await _answer_distance(db, book_id, str(intent.get("a") or ""), str(intent.get("b") or ""))
    if ty == "knows":
        from backend.repositories.world_repository import WorldRepository
        entities = await WorldRepository(db).entities.list_by_book(book_id)
        x = _resolve_entity(str(intent.get("x") or ""), entities)
        if x is None:
            return {"kind": "not_found", "text": f"没查到叫「{intent.get('x')}」的角色。", "sources": []}
        return await _answer_knows(db, book_id, x, str(intent.get("y") or ""), t)
    if ty == "which_chapter":
        return await _answer_which_chapter(db, book_id, str(intent.get("keyword") or ""))
    if ty == "last_appearance":
        from backend.repositories.world_repository import WorldRepository
        entities = await WorldRepository(db).entities.list_by_book(book_id)
        name = str(intent.get("name") or intent.get("name_hint") or "")
        ent = _resolve_entity(name, entities)
        if ent is None:
            # 正则没抓出名字（问题里嵌着角色名）→ 全实体扫描最长名命中
            hits = []
            for e in entities:
                for cand in [str(e.name or "")] + [str(a) for a in (getattr(e, "aliases", None) or []) if a]:
                    if cand and cand in (intent.get("name_hint") or intent.get("question") or ""):
                        hits.append((len(cand), e))
                        break
            uniq = {str(e.id): e for _, e in sorted(hits, key=lambda x: -x[0])}
            ent = next(iter(uniq.values())) if len(uniq) == 1 else None
        if ent is None:
            return {"kind": "not_found", "text": "没查到问的是哪位角色——点名试试（世界页名单里的名字）。", "sources": []}
        return await _answer_last_appearance(db, book_id, ent, t)
    if ty == "synthesis":
        return await _answer_synthesis(db, book_id, chapter, t, str(intent.get("question") or ""))
    return None


_NO_MATCH_HINT = (
    "没查到——这个问法我还没学会（只答书里的事实，不出主意）。"
    "可以试：「还有几条没收的伏笔？」「这章该揭什么真相？」「A到B走几天？」"
    "「X 上次出场是什么时候？」「X 知道 Y 吗？」「某某是在哪章写的？」"
)


async def _llm_parse_intent(
    db: AsyncSession, book_id: str, question: str, chapter_id: str
) -> Optional[Dict[str, Any]]:
    """M2 意图笼：LLM 只做翻译（问题→结构化查询），产物过硬闸才生效。"""
    from backend.repositories.world_repository import WorldRepository
    from backend.services.adaptive.observing import get_adaptive_recorder
    from backend.services.llm.client import REASONING_DISABLED, call_llm_with_usage
    from backend.services.utils.json_safe import parse_json_safe

    repo = WorldRepository(db)
    entities = await repo.entities.list_by_book(book_id)
    locations = await repo.locations.list_by_book(book_id)
    names = [str(e.name or "") for e in entities if e.name][:60]
    locs = [str(l.name or "") for l in locations if l.name][:60]
    system = (
        "你是查询意图解析器。作者在问自己小说的设定库一个问题，你把它解析成结构化查询。"
        "只输出 JSON，不解释。\n"
        "类型与字段：\n"
        '{"type":"last_appearance","name":"角色名"}  —— 某角色上次出场\n'
        '{"type":"knows","x":"角色名","y":"角色名或真相名"}  —— 谁知道什么\n'
        '{"type":"distance","a":"地点名","b":"地点名"}  —— 距离/日程\n'
        '{"type":"which_chapter","keyword":"要查的关键词"}  —— 哪章写过某内容\n'
        '{"type":"threads"}  —— 伏笔/线头清点\n'
        '{"type":"reveals_due"}  —— 该揭的真相\n'
        '{"type":"synthesis","question":"原问题"}  —— 需要综合多条记录的复合问题\n'
        f"角色名单（名字必须逐字取自这里）：{'、'.join(names) or '（空）'}\n"
        f"地点名单（名字必须逐字取自这里）：{'、'.join(locs) or '（空）'}\n"
        '解析不出以上任何一种就输出 {"type":"none"}。绝不编造名单外的名字。'
    )
    try:
        resp = await call_llm_with_usage(
            system_prompt=system,
            user_prompt=question[:200],
            model_type="creative",
            temperature=0.1,
            max_tokens=300,
            reasoning_config=REASONING_DISABLED,
        )
        raw = str(getattr(resp, "content", "") or (resp[0] if isinstance(resp, tuple) else "") or "")
        # 记账只吃 LLMResult 形状；测试 mock 的 (text, usage) 二元组跳过
        #（event_scout 同款防御——record_result 读 .model_name/.usage，tuple 会炸）
        if not isinstance(resp, tuple):
            get_adaptive_recorder(str(chapter_id)).record_result(
                "adaptive.ask_book.parse", resp, model_slot="creative")
        parsed = parse_json_safe(raw)
    except Exception as e:
        logger.debug(f"[ask_book] 意图解析失败（按没查到）: {e}")
        return None
    if not isinstance(parsed, dict):
        return None
    ty = str(parsed.get("type") or "")
    allowed = {"last_appearance", "knows", "distance", "which_chapter", "threads", "reveals_due", "synthesis"}
    if ty not in allowed:
        return None
    # 硬闸：角色/地点名必须能解析回真身，解析不回=拒答（不猜）
    if ty in ("last_appearance",):
        if _resolve_entity(str(parsed.get("name") or ""), entities) is None:
            return None
    if ty == "knows":
        if _resolve_entity(str(parsed.get("x") or ""), entities) is None:
            return None
    if ty == "distance":
        if not (_resolve_location(str(parsed.get("a") or ""), locations)
                and _resolve_location(str(parsed.get("b") or ""), locations)):
            return None
    parsed["question"] = question
    return parsed


async def _gather_materials(
    db: AsyncSession, book_id: str, question: str, t: int
) -> List[Dict[str, Any]]:
    """M3 材料袋：问题相关的真实记录（每条带材料 id，供 LLM 引用与校验）。"""
    mats: List[Dict[str, Any]] = []
    kws = _question_keywords(question)
    events = list((await db.execute(
        select(WorldEvent).where(WorldEvent.book_id == book_id, WorldEvent.time_start <= t)
        .order_by(WorldEvent.time_start.desc()).limit(_MAX_EVENTS_SCAN)
    )).scalars().all())
    for i, ev in enumerate(events[:6]):
        note = str(ev.note or ev.title or ev.event_type or "")[:80]
        if any(k in note or k in str(ev.event_type or "") for k in kws):
            mats.append({"id": f"e{i}", "text": f"{_calendar_label(int(ev.time_start or 0))}事件[{ev.event_type}]：{note}"})
    from backend.services.utils.html_text import html_to_plain
    chapters = list((await db.execute(
        select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.chapter_number.asc())
    )).scalars().all())
    for i, ch in enumerate(chapters):
        sent = _sentence_with_keyword(html_to_plain(ch.content_text or ""), kws)
        if sent:
            mats.append({"id": f"c{i}", "text": f"第{ch.chapter_number}章正文：「{sent}」"})
        if len(mats) >= 9:
            break
    return mats


async def _answer_synthesis(
    db: AsyncSession, book_id: str, chapter: Any, t: int, question: str
) -> Dict[str, Any]:
    """M3 材料内合成：LLM 只组织语言；引用的出处 id 必须都在材料袋里，编造即拒稿。"""
    from backend.services.adaptive.observing import get_adaptive_recorder
    from backend.services.llm.client import REASONING_DISABLED, call_llm_with_usage
    from backend.services.utils.json_safe import parse_json_safe

    mats = await _gather_materials(db, book_id, question, t)
    if not mats:
        return {"kind": "not_found", "text": "没查到相关记录。", "sources": []}
    system = (
        "你是图书管理员的口吻转换器。下面是检索到的真实材料，把能回答作者问题的部分"
        "组织成一段通顺中文答案。铁律：只许用材料里的信息，一个字不许编；每条结论"
        '标注依据材料 id。输出 JSON：{"text":"答案","source_ids":["e0","c1"]}'
        "（只列真实支撑结论的 id；材料答不了就输出空 text）。"
    )
    user = "材料：\n" + "\n".join(f"[{m['id']}] {m['text']}" for m in mats) + f"\n\n问题：{question[:200]}"
    try:
        resp = await call_llm_with_usage(
            system_prompt=system, user_prompt=user,
            model_type="creative", temperature=0.1, max_tokens=500,
            reasoning_config=REASONING_DISABLED,
        )
        raw = str(getattr(resp, "content", "") or (resp[0] if isinstance(resp, tuple) else "") or "")
        if not isinstance(resp, tuple):
            get_adaptive_recorder(str(getattr(chapter, "id", "") or "")).record_result(
                "adaptive.ask_book.synthesis", resp, model_slot="creative")
        parsed = parse_json_safe(raw)
    except Exception as e:
        logger.debug(f"[ask_book] 合成失败（按没查到）: {e}")
        return {"kind": "not_found", "text": "没查到。", "sources": []}
    if not isinstance(parsed, dict):
        return {"kind": "not_found", "text": "没查到。", "sources": []}
    text = str(parsed.get("text") or "").strip()
    ids = [str(s) for s in (parsed.get("source_ids") or []) if str(s)]
    valid_ids = {m["id"] for m in mats}
    # 出处铁律：引用材料袋外的 id = 编造出处 → 整稿拒收（宁拒勿假）
    if not text or any(i not in valid_ids for i in ids):
        return {"kind": "not_found", "text": "没查到——整理不出有出处的答案。", "sources": []}
    by_id = {m["id"]: m for m in mats}
    return {
        "kind": "synthesis",
        "text": text,
        "sources": [{"label": by_id[i]["text"][:60], "type": "material"} for i in ids if i in by_id],
    }


async def answer_question(
    db: AsyncSession, book_id: str, chapter: Any, question: str
) -> Dict[str, Any]:
    """问书主入口：纯代码直答 → M2 意图笼 → 没查到（答完即止，无对话上下文）。"""
    q = (question or "").strip()
    t = (await resolve_narrative_time(db, chapter)).t

    intent = classify_question(q)
    answer: Optional[Dict[str, Any]] = None
    if intent is not None:
        answer = await _dispatch(db, book_id, chapter, t, intent)
        # 仅「上次出场」型名字解析不出（口语称呼/嵌名问句）才交 M2 意图笼再试
        # ——真 not_found（地点不存在/没写过）是正确答案，不重烧 LLM
        if (
            intent.get("type") == "last_appearance"
            and answer is not None
            and answer.get("kind") == "not_found"
        ):
            answer = None
            intent = None
    if intent is None:
        intent = await _llm_parse_intent(db, book_id, q, str(getattr(chapter, "id", "") or ""))
        if intent is not None:
            answer = await _dispatch(db, book_id, chapter, t, intent)
    if answer is None:
        answer = {"kind": "no_match", "text": _NO_MATCH_HINT, "sources": []}
    return answer


# ============================================================
# 度量（05 瘦身口径：独立 jsonl，问题原文供 M4 分布校准）
# ============================================================

def _metrics_path() -> Path:
    """问书度量台账坐标（书级备份 book_archive 借用，不复制路径规则）。"""
    root = Path(__file__).resolve().parents[3]
    data_dir = Path(os.getenv("VELLUMA_DATA_DIR") or (root / "data"))
    return data_dir / "ask_book_metrics.jsonl"


def log_ask_metric(book_id: str, chapter_id: str, question: str, kind: str) -> None:
    try:
        path = _metrics_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "book_id": book_id,
                "chapter_id": chapter_id,
                "question": question[:200],
                "kind": kind,
            }, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"[ask_book] 度量写入失败（静默）: {e}")
