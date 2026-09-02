# Velluma - NLE-ADF 3.0 挂件生发组件
# AGPL-3.0
"""
基于层 3 推测 + 设定养料，LLM 生发 3-4 个镜头特写挂件。

挂件是 6-12 字的物理画面碎片（"老烟用残手砸灭油灯"），不是角色名罗列、
不是抽象建议。作者吸附挂件 + Space 微缝合。

校对：挂件 vs 禁词/canon private/character static_prompt——违规挂件丢弃。
懒加载：projection 签名没变就不重算（orchestrator 据此判断）。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from backend.services.context.settings_bundle import load_chapter_settings_bundle
from backend.services.llm.client import REASONING_DISABLED, call_llm_with_usage
from backend.services.adaptive.observing import get_adaptive_recorder
# 就近节拍共享判据（2026-08-25 提取：stitch 意图块同消费），私有别名保既有引用
from backend.services.adaptive.outline_nearby import (
    outline_line_written as _outline_line_written,
    outline_nearby as _outline_nearby,
)
from backend.services.prompts.adaptive_prompts import build_dock_generator_prompt
from backend.services.utils.json_safe import parse_json_safe

logger = logging.getLogger(__name__)


async def _spine_intent(chapter_id: str, db) -> str:
    """章级谋篇意图一行（P1.4 M2；chapters 主键单行取，开销可忽略）。

    只在意图存在时返回；无脉络/查询失败返回空串（prompt 零变化）。
    """
    try:
        from backend.models import Chapter as _Chapter
        ch = await db.get(_Chapter, chapter_id)
        if ch is not None and isinstance(ch.spine, dict):
            return (ch.spine.get("intent") or {}).get("text", "") or ""
    except Exception:
        pass
    return ""


async def run(chapter_id: str, db, model_snapshot: Dict, budget_tokens: int = 1500, **kw) -> Dict:
    """挂件生发。由 orchestrator 调度，产出写回世界模型缓存。

    kw 可带 direction_weights（5 叙事方向权重），碎片按此分布生成并自标 direction。
    """
    direction_weights = kw.get("direction_weights") or None  # 已退役（B7 忽略）
    # B7 热层单车道：dock 消费 salience 六槽热集的具名提示（A/B 闸：
    # SALIENCE_DOCK_LANE 常量翻转即回退；影子 trace 由 orchestrator 常开）
    salience_hints = kw.get("salience_hints") or None
    bundle = await load_chapter_settings_bundle(chapter_id, db)

    # 取作者当前段落：心跳实时段（orchestrator 停顿心跳透传）→ 正文尾部（剥 HTML）。
    # ⚠ 不用层 1 事实——历史沉淀在作者删改后即过期，曾致挂件锚定已删除文本。
    from backend.services.adaptive.paragraph_source import (
        resolve_current_paragraph, written_text,
    )
    recent_text = resolve_current_paragraph(kw.get("recent_text") or "", bundle.content_text or "")
    if not recent_text or len(recent_text) < 30:
        return {"skipped": True, "reason": "正文不足"}

    # 接缝裁剪（2026-08-27 导师裁决）：beat/after 素材不进挂件 prompt——
    # 对服从度有限的模型，切断供给比命令拒绝可靠（LLM 没见过的素材漏不出来；
    # 同哲学先例：serves_anchor 代码闸门「不信任 prompt 约束」）
    projections = _prebeat_projections(model_snapshot.get("projections", []))
    nutrients = bundle.nutrients()
    hard = bundle.hard_constraints()
    soft = bundle.soft_constraints()

    # 前情召回（记忆倒灌）：让「呼应前情细节」类零件有素材；失败降级为空不阻塞
    # k=2 见 budget 表（A3a 收编：挂件轻路径回响条数与 stitch 分档）
    from backend.services.rag.recall import recall_memories
    from backend.services.context.budget import ECHOES_K_DOCK
    memory_echoes = await recall_memories(
        db,
        book_id=bundle.book_id or "",
        chapter_id=chapter_id,
        chapter_number=bundle.chapter_number,
        query_text=recent_text[-300:],
        k=ECHOES_K_DOCK,
    )
    # 读者期待 + 大纲就近节拍：prompt 素材与 _finalize_parts 的 note 拼装共用
    reader_expectations = soft.get("reader_expectations") or None
    outline_nearby = _outline_nearby(
        getattr(bundle, "outline_text", "") or "",
        written_text(bundle.content_text or ""),
    )

    sys_p, usr_p = build_dock_generator_prompt(
        recent_text, projections, nutrients, hard,
        direction_weights=direction_weights,
        salience_hints=salience_hints,
        reader_expectations=reader_expectations,
        memory_echoes=memory_echoes or None,
        spine_intent=await _spine_intent(chapter_id, db),
        outline_nearby=outline_nearby,
    )

    try:
        result = await call_llm_with_usage(
            system_prompt=sys_p,
            user_prompt=usr_p,
            model_type="creative",
            temperature=0.75,
            max_tokens=budget_tokens,
            reasoning_config=REASONING_DISABLED,
        )
        get_adaptive_recorder(str(chapter_id)).record_result(
            "adaptive.dock_generator", result, model_slot="creative")
        parsed = parse_json_safe(result.content or "") or {}
        raw_parts = parsed.get("parts", [])

        # ---- 校对：丢弃违规挂件 + 功能槽位规整（source/note 贯通）----
        # 约束治理一期（2026-09-02）：camera/psych/rehash/beat_overlap 下沉为
        # 枚举原因的代码闸（violates 只剩 canon/blocker 禁词），丢件落
        # constraint_events 台账（丢什么、为什么——剂量与服从率度量的数据源）。
        _DROP_CONSTRAINT_IDS = {
            "not_dict": "dock-part-shape",
            "too_short": "dock-part-shape",
            "overflow_tail": "dock-part-shape",
            "violates_hard": "dock-banned-words",
            "camera_stock": "dock-camera-stock",
            "psych_word": "dock-no-psych",
            "rehash": "dock-rehash",
            "beat_overlap": "dock-beat-overlap",
        }

        def _on_drop(reason: str, text: str = "", outcome: str = "drop") -> None:
            try:
                from backend.services.constraints.events import log_constraint_event

                log_constraint_event(
                    str(bundle.book_id or ""), str(chapter_id),
                    _DROP_CONSTRAINT_IDS.get(reason, "dock-part-shape"),
                    outcome, reason=reason,
                    detail={"text": text[:20], "model": (model_snapshot.get("meta") or {}).get("model_name", "") if isinstance(model_snapshot, dict) else ""},
                )
            except Exception:
                pass  # 埋点绝不阻塞校对环

        valid_parts = _finalize_parts(
            raw_parts,
            outline_nearby=outline_nearby,
            reader_expectations=reader_expectations,
            memory_echoes=memory_echoes,
            violates=lambda t: _violates(t, hard),
            recent_text=recent_text,
            projections=projections,
            check_beat_overlap=True,
            on_drop=_on_drop,
        )

        # 挂件产出缓存到世界模型（前端 heartbeat 响应里取）
        from backend.services.adaptive.world_model import WorldModelRepository
        repo = WorldModelRepository(db)
        sig = "|".join(p["key"] for p in valid_parts)
        await repo.set_dock_sig(chapter_id, sig)

        # 临时缓存挂件（写到一个临时字段供心跳读取——复用 layer3 的 metadata 思路）
        # 这里直接通过 db session 写一个内存 dict 给路由层取（路由层会重新拉一次）
        # 实际上前端拿挂件是通过 heartbeat 响应，我们把挂件存进 ORM 的临时字段
        await _cache_dock_parts(db, chapter_id, valid_parts)

        return {"count": len(valid_parts)}
    except Exception as e:
        logger.warning(f"[dock_generator] 失败: {e}")
        return {"error": str(e)}


# ============================================================
# 功能槽位规整（2026-08-29「不知所云」重构：provenance 贯通）
# ============================================================
# 四槽位与作者决策一一对应（导师裁决：内容分类学 → 功能分类学——
# 「这枚是什么题材」对选择毫无帮助，「选这枚会发生什么」才是答案）：
#   landing     接着写：作者最后一句的物理落点（固定 note，首位）
#   toward_beat 通往节拍：通往大纲就近节拍的第一步（note=节拍原文）
#   echo        呼应：前情/读者期待（note 按模型报的 echo_ref 回查素材原文拼装）
#   ambient     氛围：无叙事包袱（note 留白——留白本身是信息）
# note 一律后端拼装不经 LLM（mimo 服从度教训：模型自由创作出处=编造风险）；
# 槽位拿不到出处文本就降级 ambient（标签必须承载真实出处，否则不标）。
SOURCE_PRIORITY = {"landing": 0, "toward_beat": 1, "echo": 2, "ambient": 3}
_SLOTS = ("landing", "toward_beat", "echo", "ambient")


def _normalize_slot(p: Dict) -> str:
    """槽位归一：显式 slot 优先；旧契约 from_expectation → echo；其余 ambient。"""
    s = p.get("slot")
    if isinstance(s, str) and s in _SLOTS:
        return s
    if p.get("from_expectation"):
        return "echo"
    return "ambient"


def _clean_echo_note(raw: str) -> str:
    """把记忆/前情素材清洗成作者语言（2026-08-29 二轮实测：note 透传机器格式
    【前情事件·物品】第三章：… 对作者是乱码，还常被截断在格式中间）。

    剥【…】账本标签 → 「第N章：」规整为「第N章·」→ 去首尾杂 punctuation。
    【前情事件·物品】第三章：扳手砸中脚边铁屑 → 第三章·扳手砸中脚边铁屑
    """
    s = str(raw).strip()
    s = re.sub(r"^【[^】]*】", "", s)
    s = re.sub(r"^第([一二三四五六七八九十百零\d]+)章\s*[:：]\s*", r"第\1章·", s)
    return s.strip(" \t:：,，、;；")


def _assemble_note(slot: str, p: Dict, outline_nearby, reader_expectations, memory_echoes) -> str:
    """按槽位拼装后果短语（后端权威，模型不经手出处文本）。

    文案纪律（2026-08-29 二轮）：副行必须回答「选它之后那一百字会写成什么」
    ——来历词（呼应/出处）只作谓语，不单独成句。
    """
    if slot == "landing":
        return "接着刚才那句往下写"
    if slot == "toward_beat":
        beats = [str(b).strip() for b in (outline_nearby or []) if b and str(b).strip()]
        if beats:
            return f"往「{beats[0][:10]}」那拍走的第一步"
        return ""
    if slot == "echo":
        try:
            ref = int(p.get("echo_ref") or 0)
        except (TypeError, ValueError):
            ref = 0
        if ref >= 1:
            if p.get("from_expectation"):
                descs = [
                    (e.get("description") or "").strip()
                    for e in (reader_expectations or [])
                    if isinstance(e, dict) and (e.get("description") or "").strip()
                ]
                if ref <= len(descs):
                    return f"暗示读者在等：{descs[ref - 1][:12]}"
            elif p.get("from_memory"):
                echoes = [str(e).strip() for e in (memory_echoes or []) if e and str(e).strip()]
                if ref <= len(echoes):
                    cleaned = _clean_echo_note(echoes[ref - 1])
                    if cleaned:
                        return f"顺笔带出前情：{cleaned[:12]}"
        return ""
    return ""


def _finalize_parts(
    raw_parts: List,
    *,
    outline_nearby=None,
    reader_expectations=None,
    memory_echoes=None,
    violates=None,
    recent_text: str = "",
    projections=None,
    check_beat_overlap: bool = False,
    on_drop=None,
) -> List[Dict]:
    """校对 + 槽位规整 + note 拼装 + 槽位序排序（landing 首位）。

    violates(text) → True 的碎片丢弃（canon private/blocker 禁词，调用方
    注入判定）。旧形状（无 slot）碎片照常通过：槽位归一 ambient、无
    note——缓存里的历史零件/旧模型产出零破坏。

    约束治理一期（2026-09-02）：校对环从单一 violates 扩为枚举原因链——
    camera_stock / psych_word / rehash / beat_overlap 依次判定，on_drop
    (reason, text[, outcome]) 回调供台账埋点（None = 不埋，纯函数性不变）。
    reason 枚举：not_dict/too_short/violates_hard/camera_stock/psych_word/
    rehash/beat_overlap/overflow_head/overflow_tail；overflow_* 的 outcome
    =trim（过采样配额消化），与 drop=违规 分列（P2-1）。
    """
    icon_map = {"action": "👤", "scene": "⚙️", "line": "💬"}
    valid_parts: List[Dict] = []

    def _drop(reason: str, text: str = "", outcome: str = "drop") -> None:
        if on_drop is not None:
            try:
                on_drop(reason, text, outcome)
            except Exception:
                pass  # 埋点绝不阻塞校对环

    raw_all = raw_parts or []
    for overflow in raw_all[6:]:  # 输入截断（P2-1：过采样时代 7+ 枚不再静默消失）
        _drop("overflow_head", str(getattr(overflow, "get", lambda *_: "")("text") or "")[:20]
              if isinstance(overflow, dict) else "", outcome="trim")
    for p in raw_all[:6]:
        if not isinstance(p, dict):
            _drop("not_dict")
            continue
        text = (p.get("text", "") or "").strip()
        if not text or len(text) < 2:
            _drop("too_short", text)
            continue
        if violates and violates(text):
            _drop("violates_hard", text)
            continue
        if _has_camera_stock(text):
            _drop("camera_stock", text)
            continue
        if _has_psych_stock(text):
            _drop("psych_word", text)
            continue
        if recent_text and _is_rehash(text, recent_text, projections):
            _drop("rehash", text)
            continue
        if check_beat_overlap and _beats_overlap_hit(text, outline_nearby):
            _drop("beat_overlap", text)
            continue
        kind = p.get("type", "action")
        # direction 校验：必须是 5 方向之一，否则回退到"环境"（分析面元数据，
        # 前端已不渲染——2026-08-29 不知所云重构：退役字段不再上屏）
        direction = p.get("direction", "环境")
        if direction not in ("主线", "伏笔", "刻画", "环境", "关系"):
            direction = "环境"
        slot = _normalize_slot(p)
        note = _assemble_note(slot, p, outline_nearby, reader_expectations, memory_echoes)
        # 槽位拿不到出处 → 降级 ambient（留白而非谎标）
        if slot in ("toward_beat", "echo") and not note:
            slot = "ambient"
            note = ""
        # 截断到 16 字（prompt 允许 8-14 字，留余量防超长产出被生生截断）
        safe_text = text[:16]
        valid_parts.append({
            "key": f"{slot}:{safe_text[:12]}",
            "kind": kind,
            "icon": icon_map.get(kind, "✨"),
            "text": safe_text,
            "direction": direction,
            "source": slot,
            **({"note": note} if note else {}),
            # 期待账本衍生件标记（分析面；前端 echo note 取代了旧「期待」tag）
            **({"origin": "expectation"} if p.get("from_expectation") else {}),
        })
    # 槽位序排序（landing 首位 → toward_beat → echo → ambient；稳定排序）
    valid_parts.sort(key=lambda p: SOURCE_PRIORITY.get(p["source"], 3))
    for overflow in valid_parts[4:]:
        # outcome=trim（P2-1）：保 4 截断是过采样的配额消化，与 drop=违规 分列
        _drop("overflow_tail", overflow.get("text") or "", outcome="trim")
    return valid_parts[:4]


# 大纲就近节拍已提取共享（services/adaptive/outline_nearby.py，2026-08-25：
# stitch 意图块同消费）。保留私有别名——test_dock_nearby.py 等既有引用零改动。

# ---- 接缝裁剪（2026-08-27 导师裁决）：节拍边界是挂件取材的时间锚线 ----
# 推测组件按 prompt 契约为每幅画面标 stage（now/approach/beat/after）；
# beat/after（节拍事件本身及其后）不进挂件取材池——碎片 3「工头拍肩」+
# 4「弯腰捡书」曾把整条节拍弧预写完，作者连吸两枚一次 Space 就把自己的
# 转折点写穿了。切断供给 > 命令拒绝。
def _prebeat_projections(projs: list) -> list:
    """过滤掉节拍侧（beat/after）的推测，只留此刻（now）与逼近（approach）。

    降级策略：显式 beat/after 标注可信（直接丢弃，不占「首幅宽容」位）；
    缺标/乱标时首幅宽容视为 now（推测契约首幅必为 now）、其余保守视为
    节拍侧丢弃——宁可菜单薄，不可抢拍。
    纯函数：编排器的 dock 缓存签名同源消费（签名必须基于过滤后集合，
    否则裁剪变化不触发重算）。
    """
    keep: list = []
    seen = 0
    for p in projs or []:
        if not isinstance(p, dict) or p.get("__dock__") or p.get("__canon_watch__"):
            continue
        beats = p.get("possible_beats") or []
        stage = beats[0].get("stage") if beats and isinstance(beats[0], dict) else None
        if stage in ("beat", "after"):
            seen += 1
            continue
        if stage not in ("now", "approach") and seen > 0:
            seen += 1
            continue
        seen += 1
        keep.append(p)
    return keep


# 陈词嗅探清单（2026-08-27）：走神镜头/远景虚化家族——感知层菜单的第一眼
# 不能带生成层都在禁的库存词。保持小而狠（<10），勿堆叠。
CAMERA_STOCK_PHRASES = (
    "目光失焦", "望向远处", "望向远方", "轮廓模糊", "视线模糊",
    "瞳孔", "目光深邃", "目光空洞",
)

# 心理词族嗅探（2026-09-02 约束治理一期）：prompt 铁律「禁心理描写」的代码
# 侧执法（同一约束双层执法，registry 用同一 constraint_id 关联——
# dock-no-psych layers=[prompt, code_gate]）。与 CAMERA_STOCK 同构，小而狠。
PSYCH_STOCK_PHRASES = (
    "心中一紧", "感到不安", "心头一沉", "心里发慌", "暗自庆幸",
    "心中窃喜", "涌起一股", "不由得害怕",
)


def _has_camera_stock(text: str) -> bool:
    """碎片文本是否命中镜头陈词库存（命中即弃，校对环消费）。"""
    return any(w in text for w in CAMERA_STOCK_PHRASES)


def _has_psych_stock(text: str) -> bool:
    """碎片文本是否命中心理描写词族（命中即弃，校对环消费）。"""
    return any(w in text for w in PSYCH_STOCK_PHRASES)


def _is_rehash(text: str, recent_text: str, projections: list) -> bool:
    """碎片是否照搬推测原文/复述刚写的画面（dock-rehash 代码闸）。

    prompt 侧「不得整句照搬推测/不复述已写」对中档模型服从不足（2026-08-25
    实测 mimo 把推测逐条压缩成挂件）——下沉为 n-gram 重叠判定：碎片对
    最近正文或任一推测原文的 3 字片段命中率 ≥0.5（或整串捷径）即判照搬。
    text_match.matches 共享判据，无素材时返回 False（不误伤）。
    """
    from backend.services.adaptive.text_match import matches

    if recent_text and matches(text, recent_text, threshold=0.5):
        return True
    for p in (projections or []):
        if not isinstance(p, dict):
            continue
        for b in (p.get("possible_beats") or [])[:2]:
            if not isinstance(b, dict):
                continue
            event_text = str(b.get("event") or "").strip()
            if event_text and matches(text, event_text, threshold=0.5):
                return True
    return False


def _beats_overlap_hit(text: str, outline_nearby: list) -> bool:
    """碎片与就近节拍原文去标点后存在 ≥4 字连续重叠（dock-beat-overlap 闸）。

    抢拍 = 碎片把节拍事件本身的措辞写出来了（「写完它，那一拍就被消费掉」）。
    供给侧切断（_prebeat_projections）后模型仍看得到就近节拍文本——这是
    残余风险的确定性兜底。任何 4 字滑窗命中即等价于 ≥4 连续公共子串。
    """
    from backend.services.adaptive.text_match import FRAGMENT_INVALID_CHARS

    def _clean(s: str) -> str:
        return "".join(c for c in (s or "") if c not in FRAGMENT_INVALID_CHARS)

    cleaned = _clean(text)
    if len(cleaned) < 4:
        return False
    for beat in (outline_nearby or []):
        beat_clean = _clean(str(beat))
        if not beat_clean:
            continue
        for i in range(len(cleaned) - 3):
            if cleaned[i: i + 4] in beat_clean:
                return True
    return False


def _violates(text: str, hard: Dict) -> bool:
    """校对挂件是否违规（canon private 泄密 / blocker 级硬禁词）。

    severity 分级（2026-08-25 A2）：提醒级词只进 prompt 软提醒与审计统计，
    不在生成侧硬拦——曾因提醒级词（角色名误录负面清单）把锚定挂件全部
    静默丢弃。banned_words_blocker 键缺失（手工构造的 hard dict）回退
    banned_words 全量，保持旧行为。
    """
    for label in hard.get("canon_private_labels", []):
        if label and len(label) >= 2 and label in text:
            return True
    if "banned_words_blocker" in hard:
        banned = hard.get("banned_words_blocker") or []
    else:
        banned = hard.get("banned_words", [])
    for word in banned:
        if word and len(word) >= 2 and word in text:
            return True
    return False


async def _cache_dock_parts(db, chapter_id: str, parts: List[Dict]):
    """把挂件缓存到世界模型（存 layer3_projections 的伴生字段）。

    由于 WorldModelORM 没有专门的 dock_parts 字段，复用 layer3_projections
    的最后一项作为缓存载体（带 __dock__ 标记，前端/路由据此识别）。
    """
    from sqlalchemy import select
    from backend.models import WorldModelORM
    result = await db.execute(select(WorldModelORM).where(WorldModelORM.chapter_id == chapter_id))
    model = result.scalar_one_or_none()
    if model is None:
        return
    # 挂件缓存放进 layer3_projections 末尾的特殊项
    projections = list(model.layer3_projections or [])
    # 移除旧 dock 缓存
    projections = [p for p in projections if not (isinstance(p, dict) and p.get("__dock__"))]
    projections.append({"__dock__": True, "parts": parts, "ts": __import__("time").time()})
    model.layer3_projections = projections
