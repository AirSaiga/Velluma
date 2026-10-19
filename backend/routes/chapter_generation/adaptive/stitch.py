# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""端点：stitch-ghost —— 幽灵草稿缝合续写（SSE 五模式 stitch/continue/burst/open/outline）。

先生成后播放：上下文装配 -> LLM -> 字数闸 -> 返修环 -> deai -> 洗层 -> 终检
-> 打字机推流。确定性闸门/后处理在 services/adaptive/stitch_gates.py。
"""
from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from backend.core.dependencies import get_db
from backend.models import Chapter
from backend.services.adaptive.observing import (
    bind_adaptive_trace,
    flush_adaptive_records,
    get_adaptive_recorder,
)
from backend.services.adaptive.outline_nearby import outline_nearby
from backend.services.adaptive.paragraph_source import (
    normalize_for_match,
    sentence_clean_tail,
)
from backend.services.adaptive.stitch_gates import (
    MICRO_STITCH_TARGET_MAX,
    OUTLINE_WC_HARD_RATIO,
    OUTLINE_WC_TRUNCATE_RATIO,
    STITCH_MAX_TOKENS_FLOOR,
    STITCH_WC_HARD_RATIO,
    STITCH_WC_TRUNCATE_RATIO,
    _bridge_actor_steal,
    _build_violation_repair_prompt,
    _excise_violating_sentences,
    _is_micro_lens,
    _normalize_bridge_seam,
    _normalize_ghost_punctuation,
    _postprocess_repair_draft,
    _split_first_sentence,
    _strip_colliding_open_quote,
    _strip_fragment_prefix,
    _truncate_at_sentence,
    _truncate_keep_tail,
    detect_dangling_quote_collision,
)
from backend.services.context.budget import (
    STITCH_AFTER_TEXT_MAX_CHARS,
    STITCH_OUTLINE_MAX_CHARS,
    STITCH_ROLLING_LONG_MAX_CHARS,
    STITCH_ROLLING_SHORT_MAX_CHARS,
)
from backend.services.context.knowledge_plane import KnowledgeView, kg_block_kwargs
from backend.services.context.stitch_context import assemble_stitch_context
from backend.services.llm.client import REASONING_DISABLED, call_llm_with_usage
from backend.services.observability.run_trace import trace_event
from backend.services.prompts.adaptive_prompts import (
    build_burst_prompt,
    build_continue_prompt,
    build_opening_prompt,
    build_outline_expand_prompt,
    pick_subject_lock,
)
from backend.services.prompts.prompt_version import PROMPT_VERSION
from backend.services.utils.logging import get_runtime_logger
from backend.services.utils.sse import build_sse_event, build_sse_error
from backend.services.validation.ghost_guard import check_ghost_text

from .events import _log_constraint_event
from .heartbeat import _style_drift_hint_for_heartbeat
from .schemas import StitchGhostRequest
from .spine import _spine_anchor_rows_for_prompt

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["adaptive"])


# P2 修补重试纪律（三平面分权·呈现平面，2026-08-29 导师方案 §二）：残留
# blocker（无替代词）→ 单次句级修补。每章 60s 冷却 + 在飞去重（复用停顿心跳
# 双烧事故的教训模式）；限流/失败/超时静默降级为 chip 呈现——终点永远是作者裁决。
_GHOST_REPAIR_TS: Dict[str, float] = {}
_GHOST_REPAIR_INFLIGHT: set = set()
_GHOST_REPAIR_COOLDOWN_S = 60.0

# 质量拒稿熔断（约束治理二期，2026-09-02）：返修环拒稿是「宁缺毋错」的硬终点，
# 但弱模型可能频繁返修失败把续写功能打没——章级滑窗 10min 内 ≥2 次拒稿即熔断，
# 降级为「带病上屏+醒目警示」（终点回到作者裁决），落 breaker_open 台账。
# 窗口自然老化自愈：熔断期内不再记新拒稿，旧拒稿超窗即恢复硬闸。
_QUALITY_REJECT_TS: Dict[str, List[float]] = {}
_QUALITY_BREAKER_WINDOW_S = 600.0
_QUALITY_BREAKER_THRESHOLD = 2


def _record_quality_reject(chapter_id: str) -> bool:
    """记一次拒稿并返回熔断是否开启（章级滑窗 ≥ 阈值）。开启后本次应降级
    上屏而非拒稿；熔断期内不再记新拒稿（窗口老化即自愈）。"""
    now = time.time()
    cid = str(chapter_id)
    ts = [t for t in _QUALITY_REJECT_TS.get(cid, []) if now - t <= _QUALITY_BREAKER_WINDOW_S]
    ts.append(now)
    _QUALITY_REJECT_TS[cid] = ts
    return len(ts) >= _QUALITY_BREAKER_THRESHOLD

# ============================================================
# 端点 5：stitch-ghost — 微缝合（SSE，保留不变）
# ============================================================

@router.post("/{chapter_id}/adaptive/stitch-ghost")
async def stitch_ghost(
    chapter_id: str,
    request: StitchGhostRequest,
    db: AsyncSession = Depends(get_db),
):
    """续写/缝合幽灵草稿，SSE 打字机推流。不依赖 run_id（自由路径）。"""
    bind_adaptive_trace(chapter_id)
    trace_event("adaptive_stitch_start", mode=request.mode, target_chars=request.target_chars)
    # 方向采纳回报（B7）：负反馈力学已退役——保留为行为信号埋点
    # （热层行为乘子的数据源：一次肯定胜过三次否定，见 salience 模块头）
    if request.adopted_direction:
        trace_event("direction_adopted", direction=request.adopted_direction)

    # 上下文装配（B2 单一装配源）：bundle/召回/文风检索统一下沉到
    # services/context/stitch_context.py——本路由与 context-preview 端点共用
    # 同一函数（预览与注入同源红线），行为与旧内联段逐字节一致。
    # P5 漂移锚样（2026-08-29）：本章漂移提醒在态 → 检索加成收藏样本
    # （内容哈希缓存的心跳侧口径复用，纯 code 零 LLM；防御式——查库失败
    # 视为无漂移，不阻塞装配）。
    _drift_anchor = False
    _chapter_row = None
    try:
        _chapter_row = await db.get(Chapter, str(chapter_id))
        if _chapter_row is not None:
            _drift_anchor = await _style_drift_hint_for_heartbeat(_chapter_row, db) is not None
    except Exception:
        _drift_anchor = False
    ctx = await assemble_stitch_context(
        chapter_id=chapter_id,
        mode=request.mode,
        fragment=request.fragment,
        rolling_prefix=request.rolling_prefix,
        db=db,
        chapter_intent=request.chapter_intent,
        drift_anchor=_drift_anchor,
        # 2026-09-02 after_text 泄漏手术：仅出现于胶囊后文的名字不进称呼表
        # （scene_visible_proper_nouns 内部判定；其余模式空串零变化）
        after_text=request.after_text or "",
        # v2 显式场景双通路：合法值透传样本检索，空/非法回落自动判定
        scene_type=request.scene_type,
    )
    bundle = ctx.bundle
    proper_nouns = ctx.proper_nouns
    chapter_intent = ctx.chapter_intent
    memory_echoes = ctx.memory_echoes
    style_positive = ctx.style_positive
    author_samples = ctx.author_samples
    # 知识检索平面 v3.1：五模式统一消费知识视图（任务平权——模式差异只在
    # 任务指令，docs/knowledge-retrieval-plane.md §1 公理二）。防御式取用：
    # kg 缺失（测试桩/降级）=空视图=块缺席=零变化，不阻塞生成路径
    kg = getattr(ctx, "kg", None) or KnowledgeView()
    kg_kwargs = kg_block_kwargs(kg)

    # ============================================================
    # 约束治理二期（2026-09-02）：返修环/终检的共享素材，路由侧一次算好
    # ============================================================
    # ① canon label→命题 id 映射（原快检块内联查询上提——预检与终检复用同一份，
    #    一次轻查询）
    _label_map: Dict[str, str] = {}
    _bundle_book_id = getattr(bundle, "book_id", None)  # 测试桩 bundle 可能无此字段
    if _bundle_book_id:
        try:
            from backend.models import CanonNode as _CN

            _rows = (await db.execute(
                select(_CN.id, _CN.label).where(_CN.book_id == _bundle_book_id)
            )).all()
            _label_map = {label: str(nid) for nid, label in _rows if label}
        except Exception:
            _label_map = {}
    # ② 地点穿越闸素材（第六检候选）：场景作用域闭包外的已知地点名表。
    #    闭包 = 场景钉自身+祖先（scene_scope_ids 既有口径）∪ 全部后裔
    #    （保守裁决：建筑内走到下属房间算合法转场，不误报）。关闭条件（任一
    #    即 None，整检不跑零变化）：非 world 书 / 无场景钉 / 无地点数据。
    #    第三弹（2026-09-14 光标派生取景框）：闭包中心优先消费光标前正文派生
    #    的取景地（ctx.active_loc_id）——进屋后续写不再把「明姐家的脸盆」当
    #    越界候选；未派生回退本章钉（零变化契约）。
    _off_scene_loc_names: Optional[List[str]] = None
    try:
        _scene_loc_id = str(getattr(ctx, "active_loc_id", "") or "") or (
            str(getattr(_chapter_row, "scene_location_id", None) or "")
            if _chapter_row is not None else ""
        )
        if getattr(bundle, "world_sourced", False) and _scene_loc_id:
            from backend.services.world.location_tree import (
                collect_subtree_ids,
                locations_by_id,
                scene_scope_ids,
            )

            _locs = getattr(bundle, "locations", None) or []
            if _locs:
                _by_id = locations_by_id(_locs)
                _legal = set(scene_scope_ids(_locs, _scene_loc_id)) | set(
                    collect_subtree_ids(_locs, _scene_loc_id)
                )
                _off_scene_loc_names = [
                    (getattr(l, "name", "") or "").strip()
                    for k, l in _by_id.items()
                    if k not in _legal and len((getattr(l, "name", "") or "").strip()) >= 2
                ]
    except Exception:
        _off_scene_loc_names = None
    # ②b 抢拍闸素材（第七检候选，2026-09-03）：大纲就近节拍原文表（装配侧
    #    与意图块同源同一份）+ 作者正文尾部（合法承接排除项）。只在
    #    stitch/continue 开闸——open/outline/burst 的本职就是写节拍/开篇，
    #    对它们「写节拍」不是违规（整检关闭，零变化）。
    _rush_beats_guard: Optional[List[str]] = None
    if request.mode in ("stitch", "continue"):
        _beats = list(getattr(ctx, "outline_beats", None) or [])
        if _beats:
            _rush_beats_guard = _beats
    _written_tail_guard = ((request.rolling_prefix or "") + " " + (request.fragment or "")).strip()
    # ②c 名单演出 shadow 素材（第八检候选）：kg 在场名单；空表→None（整检
    #    关闭，非 world 书/无在场推演的书零变化）
    _present_names_guard: Optional[List[str]] = (
        list(getattr(kg, "present_names", None) or []) or None
    )
    # ②d 信念泄漏 shadow 素材（第十检候选，2026-09-03 线 D）：私有真相命题中
    #    「此刻在场者无人知晓」的里文本短语表。命题级判定走 B3 信念域设施
    #    （fold_belief 折事件流 → proposition_status 四值回答）；有任一在场者
    #    知晓即合法（知情者的合法 POV 叙述），不进入候选。
    #    关闭条件（任一即 None，整检不跑零变化）：非 world 书 / 无 private
    #    canon 命题 / 查询失败。
    _unknown_canon_phrases: Optional[List[Dict[str, str]]] = None
    if getattr(bundle, "world_sourced", False) and _bundle_book_id:
        try:
            from backend.models import (
                CanonNode as _CN2,
                WorldEvent as _WE,
            )
            from backend.services.validation.ghost_guard import _secret_phrases
            from backend.services.world.belief import (
                KNOWS as _KNOWS,
                fold_belief as _fold_belief,
                proposition_status as _prop_status,
            )

            _priv = (await db.execute(
                select(_CN2.id, _CN2.label, _CN2.canon_text).where(
                    _CN2.book_id == _bundle_book_id,
                    _CN2.visibility == "private",
                )
            )).all()
            if _priv:
                _t_now = getattr(bundle, "world_time", 0) or 0
                _ev_rows = (await db.execute(
                    select(_WE).where(
                        _WE.book_id == _bundle_book_id,
                        _WE.time_start <= _t_now,
                    )
                )).scalars().all()
                _belief = _fold_belief(list(_ev_rows), _t_now)
                _perspective = list(getattr(kg, "present_entity_ids", None) or [])
                _phrases: List[Dict[str, str]] = []
                for _nid, _label, _canon_text in _priv:
                    if _prop_status(str(_nid), _perspective, _belief) == _KNOWS:
                        continue  # 在场者有人知道——写出来是合法 POV 叙述
                    for _seg in _secret_phrases(str(_canon_text or "")):
                        _phrases.append({
                            "node_id": str(_nid),
                            "label": str(_label or ""),
                            "phrase": _seg,
                        })
                _unknown_canon_phrases = _phrases
        except Exception:
            _unknown_canon_phrases = None  # 零变化契约：素材装配失败整检关闭
    # ③ 快检台账埋点（预检/终检共用同一回调 → (约束, 结果, 明细) 去重，
    #    返修成功后终检不会把同一命中记两次；命中语义=首次检测）
    _guard_event_keys: set = set()

    def _on_guard_event(cid: str, outcome: str, reason: str, detail) -> None:
        key = (cid, outcome, str(detail or {}))
        if key in _guard_event_keys:
            return
        _guard_event_keys.add(key)
        _log_constraint_event(
            str(_bundle_book_id or ""), str(chapter_id), cid, outcome,
            reason=reason, detail=detail,
        )
    # B0.2 context_manifest（docs/reports/world-kernel-construction-plan.md §1）：
    # 每次生成记录逐块明细 + 稳定前缀哈希——「注入未消费率」与前缀稳定性
    # 观测的数据源（scripts/analyze_context_manifest.py 消费），B8 冷层的
    # 第一道开工许可按此数据签发
    try:
        _blocks_detail = [{"key": k, "chars": len(t)} for k, t in ctx.system_blocks()]
        _prefix_text = "".join(
            t for k, t in ctx.system_blocks()
            if k in ("scene", "entities", "proper_nouns", "canon", "secrets",
                     "worldview", "relations", "negative")
        )
        _prefix_sha = hashlib.sha1(_prefix_text.encode("utf-8")).hexdigest()[:12]
    except Exception:
        _blocks_detail, _prefix_sha = [], ""
    trace_event(
        "context_manifest",
        mode=request.mode,
        blocks=_blocks_detail,
        prefix_sha1=_prefix_sha,
        # 2026-09-01 穿帮修复后的审计位：记录过滤后的最终专名表（对照
        # kg.unselected 可回放「某实体为何没进称呼表」——工头拧流光螺栓事故
        # 的诊断路径依赖过 trace 里能看见注入了什么名字）
        proper_nouns=list(proper_nouns)[:24],
        selected=list(getattr(kg, "selected_keys", []) or [])[:40],
        unselected=list(getattr(kg, "unselected", []) or [])[:40],
        knowledge_chars=kg.total_chars() if isinstance(kg, KnowledgeView) else 0,
    )

    # P1-3（C1）短窗观测→2026-08-25 实测调窗：观测埋点回收的真实案例坐实短窗是
    # 「驴头不对马嘴」主因（used_len 长期钉死 200 上限）——常量已按实测上调
    # （SHORT 800 / LONG 1200，见 budget.py），观测键保留以持续回收配比数据。
    # 截窗走句界净截（窗首丢弃半截句，防模型误以为要续窗首）；
    # open 模式不消费 rolling_prefix。
    _rolling_cap = (
        0 if request.mode == "open"
        else STITCH_ROLLING_LONG_MAX_CHARS if request.mode in ("outline", "burst")
        else STITCH_ROLLING_SHORT_MAX_CHARS
    )
    rolling_windowed = (
        sentence_clean_tail(request.rolling_prefix or "", _rolling_cap).strip() if _rolling_cap else ""
    )

    # 双轨生成契约选档（2026-09-03 质感批次）：stitch/continue 由代码选定
    # 本笔「推进 or 停在当下细写」——零件槽位优先，无零件走尾部动作密度兜底；
    # 其余模式恒 motion（各有专职）。埋点供选档分布/采纳率校准。
    from backend.services.adaptive.texture_contract import pick_contract

    stitch_contract = pick_contract(request.mode, request.picked_slots, rolling_windowed)
    trace_event(
        "adaptive_stitch_contract",
        mode=request.mode, contract=stitch_contract,
        slots=[str(s) for s in (request.picked_slots or [])][:4],
        tail_chars=len(rolling_windowed),
    )

    if request.mode == "open":
        # 点火（冷启动）：空章 + 大纲 → 开篇引子。大纲是唯一燃料，无已写正文
        # 点火剂量闸（2026-08-25 实测修复）：全章地图在场模型就往终点冲（真实事故：
        # 700 字点火写完了袭击+跌落全序列，作者整段删除）——空章就近=开头一两拍，
        # 只给开头；无合格节拍行的短大纲回退原文截断（剂量天然小，不算破闸）
        _open_beats = outline_nearby(bundle.outline_text or "", "")
        open_outline = (
            "\n".join(_open_beats) if _open_beats
            else bundle.outline_text[:STITCH_OUTLINE_MAX_CHARS]
        )
        system_prompt, user_prompt = build_opening_prompt(
            outline_text=open_outline,
            previous_summary=bundle.previous_summary or "",
            proper_nouns=proper_nouns,
            canon_context=bundle.canon_context,
            target_chars=request.target_chars,
            memory_echoes=memory_echoes,
            style_positive=style_positive,
            author_samples=author_samples,
            spatial_brief=bundle.spatial_brief,
            character_secrets=bundle.character_secrets,
            recency_pin=kg.recency_pin,
            texture_contract_overrides=getattr(bundle, "texture_contracts", None),
            **kg_kwargs,
        )
    elif request.mode == "outline":
        # 细纲扩写：作者亲笔速记 + 双端正文锚定 → 小段正文（前文承接 + 后文引向）
        # M3 三锚定：胶囊挂了锚点时，锚点文本一并注入意图块
        # C3（docs/reports/foundation-hardening.md §5.3）：spine 全锚点行——全章谋篇
        # 盘面（含兑现状态）随意图区注入；无 spine → 行缺席，prompt 逐字节不变
        spine_anchor_rows = await _spine_anchor_rows_for_prompt(chapter_id, db)
        system_prompt, user_prompt = build_outline_expand_prompt(
            outline_note=request.fragment.strip(),
            rolling_prefix=rolling_windowed,
            after_text=(request.after_text or "")[:STITCH_AFTER_TEXT_MAX_CHARS].strip(),
            proper_nouns=proper_nouns,
            canon_context=bundle.canon_context,
            target_chars=request.target_chars,
            chapter_intent=chapter_intent,
            memory_echoes=memory_echoes,
            style_positive=style_positive,
            author_samples=author_samples,
            spatial_brief=bundle.spatial_brief,
            character_secrets=bundle.character_secrets,
            serves_anchor=request.serves_anchor.strip(),
            spine_anchors=spine_anchor_rows,
            previous_summary=kg.previous_summary,
            recency_pin=kg.recency_pin,
            texture_contract_overrides=getattr(bundle, "texture_contracts", None),
            **kg_kwargs,
        )
    elif request.mode == "burst":
        # 段落级连写：走向卡驱动 + 更大衔接窗口 + 更快打字机节奏
        system_prompt, user_prompt = build_burst_prompt(
            fragment=request.fragment.strip(),
            rolling_prefix=rolling_windowed,
            beat_guidance=request.beat_guidance.strip(),
            proper_nouns=proper_nouns,
            canon_context=bundle.canon_context,
            target_chars=request.target_chars,
            chapter_intent=chapter_intent,
            memory_echoes=memory_echoes,
            style_positive=style_positive,
            author_samples=author_samples,
            spatial_brief=bundle.spatial_brief,
            character_secrets=bundle.character_secrets,
            previous_summary=kg.previous_summary,
            recency_pin=kg.recency_pin,
            texture_contract_overrides=getattr(bundle, "texture_contracts", None),
            **kg_kwargs,
        )
    else:
        system_prompt, user_prompt = build_continue_prompt(
            fragment=request.fragment.strip(),
            rolling_prefix=rolling_windowed,
            mode=request.mode,
            picked_parts=request.picked_parts,
            proper_nouns=proper_nouns,
            canon_context=bundle.canon_context,
            target_chars=request.target_chars,
            chapter_intent=chapter_intent,
            memory_echoes=memory_echoes,
            style_positive=style_positive,
            author_samples=author_samples,
            spatial_brief=bundle.spatial_brief,
            character_secrets=bundle.character_secrets,
            previous_summary=kg.previous_summary,
            recency_pin=kg.recency_pin,
            contract=stitch_contract,
            # 2026-09-13 模式仲裁：桥接态下交接锁取代发话锁（桥接引渡权
            # 高于静态发话锁——发话者常非主角，两锁同注即主体死锁）
            subject_lock=pick_subject_lock(
                request.picked_slots,
                bridge=bool((request.suffix_anchor or "").strip()),
            ),
            picked_slots=[str(x) for x in (request.picked_slots or [])],
            suffix_anchor=(request.suffix_anchor or "").strip(),
            intent_source=getattr(ctx, "intent_source", "") or "",
            texture_contract_overrides=getattr(bundle, "texture_contracts", None),
            **kg_kwargs,
        )

    async def _stream():
        recorder = get_adaptive_recorder(chapter_id)
        try:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=0.7,
                # 推理模型预算余量见 STITCH_MAX_TOKENS_FLOOR（C2）：deepseek 类
                # 即使 REASONING_DISABLED 仍烧 ~800-1000 隐藏思考 tokens，
                # 下限太薄会「续写产出为空」
                max_tokens=max(STITCH_MAX_TOKENS_FLOOR, request.target_chars * 2 + 1000),
                reasoning_config=REASONING_DISABLED,
            )
            recorder.record_result(f"adaptive.stitch_ghost.{request.mode}", result, model_slot="creative")
            text = (result.content or "").strip().strip('"').strip('"').strip()
            if not text:
                yield build_sse_error("续写产出为空，请重试")
                return
            # 字数硬闸门（outline 模式）：超 target×1.6 先带压缩反馈重试一次，
            # 仍超则保尾截断到 ×1.5（末段承接段豁免，P1-1）。先生成后播放，
            # 对前端完全透明
            if request.mode == "outline" and request.target_chars > 0:
                hard_limit = int(request.target_chars * OUTLINE_WC_HARD_RATIO)
                if len(text) > hard_limit:
                    compressed = await call_llm_with_usage(
                        system_prompt=system_prompt,
                        user_prompt=(
                            f"{user_prompt}\n\n# 上次输出被拒\n"
                            f"上次输出 {len(text)} 字，超过 {hard_limit} 字硬上限。"
                            f"请压缩到 {request.target_chars} 字以内：删减重复修饰与冗余动作，"
                            f"细纲核心事件必须全部保留。只输出压缩后的正文。"
                        ),
                        model_type="creative",
                        temperature=0.7,
                        # 压缩重试同烧隐藏思考 tokens，同 STITCH_MAX_TOKENS_FLOOR 下限（C2）
                        max_tokens=max(STITCH_MAX_TOKENS_FLOOR, request.target_chars * 2 + 1000),
                        reasoning_config=REASONING_DISABLED,
                    )
                    recorder.record_result("adaptive.stitch_ghost.compress", compressed, model_slot="creative")
                    cand = (compressed.content or "").strip()
                    if cand:
                        text = cand
                if len(text) > hard_limit:
                    # P1-1（A3）：保尾截断——末段承接段（引向 after_text）完整
                    # 保留，超字从前往后句界删节；末段自身超限在 helper 内退化
                    # 为尾截。仅 outline 模式进此分支，其他模式口径不变
                    text = _truncate_keep_tail(text, int(request.target_chars * OUTLINE_WC_TRUNCATE_RATIO))
                    logger.info(
                        f"[adaptive/stitch-ghost] 细纲扩写字数末次仍超上限，"
                        f"保尾截断到 {len(text)} 字（目标 {request.target_chars}）"
                    )
            fragment = request.fragment.strip()
            # P1-2（A4→2026-08-26 契约反转）：幽灵是纯追加插入，作者原句已在
            # 画布里——拼回（把原句塞回句首）必造成屏幕重复，改为**复读剥离**：
            # 模型若仍把原句吐回来（prompt 已禁，等价类变体兜底），剥掉前缀只留续写。
            # 2026-09-13 扩门：continue 同受此契约（「端上一盆一盆」口吃穿透——
            # 顺句续写同样复读断点，词尾重叠消解 _strip_fragment_tail_repeat
            # 内嵌于此函数）；burst 段尾断点的复读形态少，观察一轮再议
            if request.mode in ("stitch", "continue") and fragment:
                text = _strip_fragment_prefix(text, fragment)
            # 双开引号碰撞（2026-09-11）：断点=悬空开引号 × 幽灵以开引号起头
            # → 剥幽灵的开引号（stitch/continue 两模式共用——Space 顺句续写
            # 同样会遇到作者刚打了个 “ 就续写）
            if request.mode in ("stitch", "continue") and fragment:
                text = _strip_colliding_open_quote(text, fragment)
                # 悬空开引号 × 动作前缀影子检（2026-09-13 目标 2·Z 路线）：
                # 幽灵首字符非引号的碰撞形态——既有剥除救不了（那是另一形态），
                # 修文须触碰画布或重排幽灵（纯追加红线）→ 只落台账攒语料，
                # 频率数据出来后再定执法路线（prompt 引导同步在案）
                if detect_dangling_quote_collision(text, fragment):
                    trace_event("adaptive_dangling_quote", mode=request.mode,
                                ghost_head=text[:24])
                    try:
                        from backend.services.constraints.events import log_constraint_event
                        log_constraint_event(
                            str(getattr(getattr(ctx, "bundle", None), "book_id", "") or ""),
                            str(chapter_id), "stitch-dangling-quote", "hit",
                            reason="ghost_restarts_after_dangling_quote",
                            detail={"ghost_head": text[:24]},
                        )
                    except Exception:
                        pass  # 影子埋点绝不阻塞生成
            # 桥接接缝归一（2026-09-09 FIM）：双端边界扩写的尾部与后文首句
            # 交接——归一须在字数闸/返修环之前（归一会改长度）
            if (request.suffix_anchor or "").strip():
                text = _normalize_bridge_seam(text, request.suffix_anchor)
                # 桥接抢场影子检（shadow）：幽灵末句与后文首句共享登场者 →
                # 后文的登场反应被提前演了（换道具的同槽位撞车，字面闸盲区）
                _steal = _bridge_actor_steal(text, request.suffix_anchor, proper_nouns)
                if _steal:
                    trace_event("adaptive_bridge_actor_steal", actor=_steal,
                                ghost_tail=text[-40:])
                    try:
                        from backend.services.constraints.events import log_constraint_event
                        log_constraint_event(
                            str(ctx.bundle.book_id or "") if hasattr(ctx, "bundle") else "",
                            str(chapter_id), "stitch-bridge-actor-steal", "hit",
                            reason="ghost_tail_shares_suffix_actor",
                            detail={"actor": _steal, "ghost_tail": text[-40:]},
                        )
                    except Exception:
                        pass  # 影子埋点绝不阻塞生成


            # 字数硬闸扩面（2026-08-28，2026-08-29 改两级）：stitch/continue
            # 超过 target×1.6 → 先保头句界截到 ×1.5，再把截取稿发回模型按目标
            # 字数压缩改写（用户拍板方案：纯截断常断在平淡处，压缩改写把同样
            # 信息收得更有效）。压缩产物超硬限再句界截一次；空产出回落截取稿
            # ——永不劣于纯截断。放在复读剥离之后：复读原句不计入续写配额。
            # ⚠ 断点衔接首句豁免压缩（2026-08-29 接缝断裂事故）：压缩模型
            # 看不到作者断点，曾把「补完断点的首句」（『…在这个世道，这句』+
            # 『话像块锈铁卡在齿缝里。』）当修饰整句删除——作者的半句永远悬空，
            # 上屏读作「在这个世道，这句扳手悬在传动轴旁…」。修复：首句物理
            # 摘出、只压缩剩余部分，产物=首句+压缩稿——衔接句永不进压缩，
            # 零依赖模型服从（三平面纲领：prompt 管不住的确定性约束下沉代码层）。
            # 压缩 prompt 同时带作者断点尾句，给剩余部分保衔接语义提供坐标。
            # 线 E（2026-09-03）：burst/open 同进此闸——700 字承诺下的超产=
            # 快进剧情（冲章同族），闸只抓 ×1.6 严重超产，正常浮动不碰。
            if request.mode in ("stitch", "continue", "burst", "open") and request.target_chars > 0:
                stitch_hard_limit = int(request.target_chars * STITCH_WC_HARD_RATIO)
                # 微镜头免压缩分支（第二冲程 2026-09-09）：50 字级单镜头展开
                # 超 ×1.6 只保头句界截断（零 LLM 往返）——轻微超产（61~80 字）
                # 句子自然完结优先全盘接受，绝不进压缩返修的漫长等待
                if _is_micro_lens(request.mode, request.target_chars):
                    if len(text) > stitch_hard_limit:
                        text = _truncate_at_sentence(text, stitch_hard_limit)
                elif len(text) > stitch_hard_limit:
                    anchor, body = _split_first_sentence(text)
                    # 首句缺席（无句读极端长句）或首句吃掉大半配额（>×0.6）时
                    # 豁免失去意义 → 退整稿压缩（prompt 仍带断点坐标）
                    if not anchor or len(anchor) > int(request.target_chars * 0.6):
                        anchor, body = "", text
                    head = _truncate_at_sentence(
                        body,
                        max(int(request.target_chars * STITCH_WC_TRUNCATE_RATIO) - len(anchor), 40),
                    )
                    body_target = max(request.target_chars - len(anchor), 40)
                    frag_ctx = (
                        f"作者正文停在：『…{fragment[-40:]}』（续写草稿正是在补它/接它）\n"
                        if fragment else ""
                    )
                    anchor_ctx = (
                        f"草稿开头的衔接句『{anchor}』已单独保留、不在下面草稿里，"
                        f"压缩稿不要复述它。\n" if anchor else ""
                    )
                    # open 无作者断点（开篇是整段起笔），措辞适配——不讲「断点」
                    draft_label = (
                        "续写草稿，超出了" if request.mode != "open"
                        else "开篇草稿，超出了"
                    )
                    compressed = await call_llm_with_usage(
                        system_prompt=system_prompt,
                        user_prompt=(
                            f"{frag_ctx}{anchor_ctx}"
                            f"下面是一段{draft_label} {request.target_chars} 字目标"
                            f"（现 {len(head)} 字）。请压缩改写到 {body_target} 字以内："
                            f"保持开头的衔接语义不变，删减修饰与重复动作，每个细节都要推进信息。"
                            f"只输出压缩后的正文，不要解释。\n\n--- 草稿 ---\n{head}"
                        ),
                        model_type="creative",
                        temperature=0.7,
                        max_tokens=max(STITCH_MAX_TOKENS_FLOOR, request.target_chars * 2 + 1000),
                        reasoning_config=REASONING_DISABLED,
                    )
                    recorder.record_result("adaptive.stitch_ghost.compress", compressed, model_slot="creative")
                    cand = (compressed.content or "").strip()
                    if cand:
                        # 模型若在压缩稿里复述衔接句（已被告知不要），剥掉再拼
                        if anchor and cand.startswith(anchor):
                            cand = cand[len(anchor):].lstrip()
                        if cand:
                            merged = anchor + cand
                            if len(merged) > stitch_hard_limit:
                                merged = anchor + _truncate_at_sentence(
                                    cand,
                                    max(int(request.target_chars * STITCH_WC_TRUNCATE_RATIO) - len(anchor), 40),
                                )
                            text = merged
                        else:
                            text = anchor + head
                    else:
                        text = anchor + head
                        logger.info(
                            f"[adaptive/stitch-ghost] {request.mode} 压缩改写空产出，"
                            f"回落截取稿 {len(text)} 字（目标 {request.target_chars}）"
                        )
            # 自定义镜头逐字回声影子检（2026-09-09 实测事故：作者的自定义
            # 成句被原样吞进幽灵）：prompt 侧已注入「素材指令须重写」规则，
            # 本检攒服从率语料——改写良好=零事件，照抄=hit
            if request.picked_slots and request.picked_parts:
                for _cp, _cs in zip(request.picked_parts, request.picked_slots):
                    if _cs == "custom" and _cp and len(_cp) >= 8:
                        if normalize_for_match(_cp) in normalize_for_match(text):
                            trace_event("adaptive_custom_verbatim", part=_cp[:24])
                            try:
                                from backend.services.constraints.events import log_constraint_event
                                log_constraint_event(
                                    str(getattr(getattr(ctx, "bundle", None), "book_id", "") or ""),
                                    str(chapter_id), "stitch-custom-verbatim", "hit",
                                    reason="custom_part_echoed_verbatim",
                                    detail={"part": _cp[:24], "ghost_head": text[:24]},
                                )
                            except Exception:
                                pass  # 影子埋点绝不阻塞生成
                        break

            # ============================================================
            # 缝合返修环（约束治理二期，2026-09-02；docs/constraint-governance.md
            # §二期唯一权威）：预检硬违规（登记册 live + 显式 repair 资格）→
            # 带稿改写重试 1 次 → 句级切除（三豁免）→ 拒稿不上屏（熔断降级）。
            # 位置：字数闸之后、deai 之前——违规原稿绝不进任何后续通道（wash
            # 原稿快照/deai 抛光防回退污染纪律）；返修稿重跑确定性后处理。
            # 终检（warnings 上屏）在 wash P2 之后——那里产出的修补稿也必须过检。
            # ============================================================
            from backend.services.validation.ghost_guard import repair_eligible
            from backend.services.validation.repair_loop import (
                ACTION_EXCISED,
                ACTION_REPAIRED,
                ACTION_REJECTED,
                run_repair_loop,
            )

            repaired_payload: Dict = {}
            breaker_open = False
            try:
                _precheck = check_ghost_text(
                    text, bundle, canon_node_ids_by_label=_label_map,
                    visible_names=list(proper_nouns or []),
                    off_scene_locations=_off_scene_loc_names,
                    outline_beats=_rush_beats_guard,
                    written_tail=_written_tail_guard,
                    present_names=_present_names_guard,
                    unknown_canon_phrases=_unknown_canon_phrases,
                    on_event=_on_guard_event,
                )
                _hard = [w for w in _precheck if repair_eligible(w)]
                if _hard:
                    async def _repair_regenerate(draft: str, viols: List[Dict]) -> str:
                        rep = await call_llm_with_usage(
                            system_prompt=system_prompt,
                            user_prompt=_build_violation_repair_prompt(
                                mode=request.mode,
                                fragment=fragment,
                                target_chars=request.target_chars,
                                violations=viols,
                                draft=draft,
                            ),
                            model_type="creative",
                            temperature=0.3,
                            max_tokens=max(STITCH_MAX_TOKENS_FLOOR, len(draft) * 2 + 800),
                            reasoning_config=REASONING_DISABLED,
                        )
                        recorder.record_result(
                            "adaptive.stitch_ghost.repair", rep, model_slot="creative")
                        cand = (rep.content or "").strip().strip('"').strip('"').strip()
                        if not cand:
                            return ""
                        # 返修稿重跑确定性后处理（零 LLM 版——调用 3 次封顶纪律）
                        return _postprocess_repair_draft(
                            cand, request.mode, fragment, request.target_chars)

                    def _hard_violations_of(t: str) -> List[Dict]:
                        # 验收与预检同一套判定；on_event=None——验收不重复记 hit
                        return [w for w in check_ghost_text(
                            t, bundle, canon_node_ids_by_label=_label_map,
                            visible_names=list(proper_nouns or []),
                            off_scene_locations=_off_scene_loc_names,
                            outline_beats=_rush_beats_guard,
                            written_tail=_written_tail_guard,
                            present_names=_present_names_guard,
                            unknown_canon_phrases=_unknown_canon_phrases,
                        ) if repair_eligible(w)]

                    outcome = await run_repair_loop(
                        text, _hard,
                        regenerate=_repair_regenerate,
                        recheck=_hard_violations_of,
                        excise=lambda t, viols: _excise_violating_sentences(
                            t, viols, mode=request.mode, target_chars=request.target_chars),
                        max_retries=1,
                    )
                    _kinds = sorted({str(w.get("kind") or "") for w in _hard if w.get("kind")})
                    if outcome.action in (ACTION_REPAIRED, ACTION_EXCISED):
                        text = outcome.text
                        # items=逐条人话明细（09-08 作者可见性）：与疑点条明细
                        # 同口径——只透传 ghost_guard 的设定侧触发词与说明，
                        # 违规原稿仍不进任何前端通道（防回退污染纪律不变）
                        repaired_payload = {
                            "count": len(_hard),
                            "kinds": outcome.fixed_kinds,
                            "action": outcome.action,
                            "items": [
                                {
                                    "kind": str(w.get("kind") or ""),
                                    "span_text": str(w.get("span_text") or ""),
                                    "message": str(w.get("message") or ""),
                                }
                                for w in _hard if isinstance(w, dict)
                            ],
                        }
                        for cid in {
                            "ghost-guard-" + k.replace("_", "-") for k in _kinds
                        }:
                            _log_constraint_event(
                                str(_bundle_book_id or ""), str(chapter_id), cid,
                                "repair" if outcome.action == ACTION_REPAIRED else "excise",
                                reason="repair_loop", detail={"kinds": _kinds},
                            )
                        trace_event(
                            "adaptive_stitch_repair",
                            mode=request.mode, action=outcome.action,
                            kinds=_kinds, attempts=outcome.attempts,
                            text_len=len(text),
                        )
                    elif outcome.action == ACTION_REJECTED:
                        if _record_quality_reject(str(chapter_id)):
                            # 熔断降级：带病上屏 + 终检醒目警示（终点回到作者裁决）
                            breaker_open = True
                            _log_constraint_event(
                                str(_bundle_book_id or ""), str(chapter_id),
                                "ghost-repair-loop", "breaker_open",
                                reason="reject_window_threshold",
                                detail={"kinds": _kinds},
                            )
                            trace_event(
                                "adaptive_stitch_repair",
                                mode=request.mode, action="breaker_open", kinds=_kinds,
                            )
                        else:
                            for cid in {
                                "ghost-guard-" + k.replace("_", "-") for k in _kinds
                            }:
                                _log_constraint_event(
                                    str(_bundle_book_id or ""), str(chapter_id), cid,
                                    "reject", reason="repair_loop_exhausted",
                                    detail={"kinds": _kinds},
                                )
                            trace_event(
                                "adaptive_stitch_reject",
                                mode=request.mode, kinds=_kinds,
                                text_len=len(text),
                            )
                            # 拒稿不上屏（用户拍板：不可接受错误结果）；原稿随帧
                            # 带往前端逃生舱（作者可裁决「仍以疑点提示上屏」）
                            yield build_sse_event(
                                "GHOST_REJECT",
                                "这次没能写出合格的续写（检出设定硬伤且自动修正未通过）",
                                code="quality_reject",
                                mode=request.mode,
                                text=text,
                                warnings=[w for w in _precheck if not w.get("local_only")],
                            )
                            return
            except Exception as e:
                # 返修环自身故障绝不阻塞生成——原稿照走后续通道（终检仍提示）
                logger.debug(f"[adaptive/stitch-ghost] 返修环失败（不阻塞生成）: {e}")
            # ============================================================
            # deai 小模型抛光（预留接口，docs/deai-integration.md；deai/ 子项目）：
            # 呈现平面的模型层——自训「去AI味」小模型对最终短稿做只改质感的
            # 改写（卡舱幽灵 ≤100 字契约窗内才生效，burst/outline 长稿自动跳过）。
            # 位置在字数闸后、快检前：ghost_guard 扫的是抛光后的文本（死者开口
            # 等疑点以最终上屏稿为准）。未配置/超长/任何失败 = 原样通过，
            # 逐字节零变化（零变化契约，同 embedding 未配置短路纪律）。
            # ============================================================
            deai_payload: Dict = {"applied": False, "reason": "", "warnings": []}
            # 微镜头旁路（2026-09-13 B1 深水区批）：≤60 字单镜头出字竞速优先
            # ——微镜头截断封顶 96 字恒进 deai ≤100 契约窗，一次往返常态 1-3s
            # 对「按 Space 即出字」是纯延迟；模型层洗味让位确定性 P1 洗层
            # （有替代表照换）+ 终检 cliche_hit（live 进 warnings 帧），兜底链不缺。
            _micro_lens = _is_micro_lens(request.mode, request.target_chars)
            if _micro_lens:
                deai_payload["reason"] = "micro_lens_bypass"
            try:
                from backend.services.deai import is_deai_configured, polish_fragment
                from backend.services.style.events import append_style_event

                if is_deai_configured() and not _micro_lens:
                    # 保名闸素材（导师审 P1-1）：契约专名闸只护引文/书名与
                    # 拉丁 token，中文名不在其内——用 kg 在场/死者名单给
                    # 抛光稿加一道「原文出现的实体名必须逐字保留」的加护
                    _deai_names = {
                        n for n in (
                            *(getattr(kg, "present_names", None) or []),
                            *(getattr(kg, "dead_names", None) or []),
                        ) if n
                    }
                    deai_res = await polish_fragment(
                        text, protected_names=_deai_names
                    )
                    if deai_res.applied:
                        text = deai_res.text
                    deai_payload = {
                        "applied": deai_res.applied,
                        "reason": deai_res.reason,
                        "warnings": deai_res.warnings,
                    }
                    trace_event(
                        "deai_polish",
                        mode=request.mode,
                        applied=int(deai_res.applied),
                        skipped=int(deai_res.skipped),
                        reason=(deai_res.reason[:120] if deai_res.reason else ""),
                        warnings=len(deai_res.warnings),
                        names=len(_deai_names),
                        tokens_in=deai_res.tokens_in,
                        tokens_out=deai_res.tokens_out,
                        text_len=len(text),
                    )
                    append_style_event(
                        str(_bundle_book_id or ""), "deai_polish",
                        f"applied={int(deai_res.applied)};skipped={int(deai_res.skipped)};"
                        f"mode={request.mode};reason={deai_res.reason[:80]}",
                    )
            except Exception as e:
                logger.debug(f"[adaptive/stitch-ghost] deai 抛光失败（不阻塞生成）: {e}")

            # C1 上屏前快检已迁移（约束治理二期）：预检随返修环提前到字数闸后，
            # 终检移到 wash P2 之后（见下方「终检」段）——P2 修补稿同样必须过检。
            ghost_warnings: List[Dict] = []
            # ============================================================
            # 呈现平面（三平面分权，2026-08-29，docs/style-paradigm.md）：
            # P1 确定性洗（blocker+alternative 精确替换）→ P2 单次句级修补
            # （残留 blocker，冷却/在飞纪律）→ P4 语义 shadow（只落事件不改文）。
            # 作用域 = 采纳线前的 AI 提案；warning 档永不动手；失败不阻塞生成。
            # ============================================================
            wash_payload: Dict = {"hits": [], "original_text": ""}
            ghost_token = uuid.uuid4().hex[:12]  # P5 回流：采纳/蒸发事件据此对齐
            sample_ids = list(getattr(ctx, "sample_ids", []) or [])
            repaired_flag = False
            try:
                from backend.models import Book as _BookM
                from backend.services.style.prohibitions import ProhibitionSet, load_prohibition_set
                from backend.services.style.ghost_wash import wash_ghost_text, build_repair_prompt
                from backend.services.style.events import append_style_event
                from backend.services.style.semantic_match import semantic_scan_text
                from backend.services.style.texture_contracts import texture_enforcement_entries

                _prohibitions = None
                if bundle.book_id:
                    _prohibitions = await load_prohibition_set(
                        db,
                        book=await db.get(_BookM, bundle.book_id),
                        style_card=getattr(bundle, "style_card", None),
                    )
                # 质感契约执法词表旁路合并（2026-09 收编批）：病灶词不进四源合并
                # （保零变化契约与挂件防线），洗层/P2 重洗/语义扫描前在此并集——
                # 契约是系统级护栏，本书无配置（甚至禁忌面加载失败）也生效。
                _tex_entries = texture_enforcement_entries()
                if _tex_entries:
                    _base_entries = _prohibitions.entries if _prohibitions is not None else ()
                    _prohibitions = ProhibitionSet(tuple(_base_entries) + _tex_entries)
                wash_result = wash_ghost_text(text, _prohibitions)
                text = wash_result.text

                # P2：残留 blocker（无替代词，洗层只记录未替换）→ 单次句级修补。
                # 严格验收：修补稿重洗后零残留才采纳，否则维持洗层结果带 chip。
                # 微镜头旁路（2026-09-13 B1）：单次 LLM 往返与竞速冲突——
                # 残余禁词由 chip「已标记」+ 终检 cliche_hit warnings 保底呈现，
                # 作者裁决链完整（红队 Q4 核查：消失的只是自动修补，不是提示）。
                if wash_result.residual_hits and not _micro_lens:
                    cid = str(chapter_id)
                    now = time.time()
                    if (
                        now - _GHOST_REPAIR_TS.get(cid, 0.0) >= _GHOST_REPAIR_COOLDOWN_S
                        and cid not in _GHOST_REPAIR_INFLIGHT
                    ):
                        _GHOST_REPAIR_INFLIGHT.add(cid)
                        try:
                            rep = await call_llm_with_usage(
                                system_prompt=system_prompt,
                                user_prompt=build_repair_prompt(text, wash_result.residual_hits),
                                model_type="creative",
                                temperature=0.3,
                                max_tokens=max(STITCH_MAX_TOKENS_FLOOR, len(text) * 2 + 800),
                                reasoning_config=REASONING_DISABLED,
                            )
                            cand = (rep.content or "").strip()
                            if cand:
                                recheck = wash_ghost_text(cand, _prohibitions)
                                if not recheck.residual_hits:
                                    text = cand
                                    wash_result = recheck
                                    repaired_flag = True
                        finally:
                            _GHOST_REPAIR_INFLIGHT.discard(cid)
                            _GHOST_REPAIR_TS[cid] = time.time()

                if wash_result.hits:
                    wash_payload = {
                        "hits": [
                            {
                                "pattern": h.pattern, "span": h.span,
                                "replaced": h.replaced, "alternative": h.alternative,
                            }
                            for h in wash_result.hits
                        ],
                        "original_text": wash_result.original_text,
                    }
                    append_style_event(
                        str(_bundle_book_id or ""), "ghost_wash",
                        f"hits={len(wash_result.hits)};"
                        f"replaced={len(wash_result.replaced_hits)};"
                        f"repaired={int(repaired_flag)};mode={request.mode}",
                    )

                # P4 语义 shadow：blocker 模式向量 × 幽灵文本，抓「换字逃逸」。
                # shadow 纪律——只落事件（trace + style_events）不改文不弹 chip，
                # 与 finish 扫描对拍攒校准数据；未配置 embedding 内部零调用短路。
                try:
                    sem_hits = await semantic_scan_text(text, _prohibitions)
                    if sem_hits:
                        trace_event(
                            "ghost_semantic_shadow",
                            hits=len(sem_hits),
                            top=round(float(sem_hits[0].get("similarity") or 0), 3),
                            mode=request.mode, ghost_token=ghost_token,
                        )
                        append_style_event(
                            str(_bundle_book_id or ""), "ghost_semantic_shadow",
                            f"hits={len(sem_hits)};top={sem_hits[0].get('similarity')};mode={request.mode}",
                        )
                except Exception as sem_e:
                    logger.debug(f"[adaptive/stitch-ghost] 语义 shadow 失败（静默）: {sem_e}")
            except Exception as e:
                logger.debug(f"[adaptive/stitch-ghost] 洗层失败（不阻塞生成）: {e}")

            # ============================================================
            # 终检（约束治理二期移位）：GHOST_DONE 帧前的最后一道——wash P2
            # 修补稿/deai 抛光稿都必须过检（旧链 P2 修补稿不重检，是「拒稿时代」
            # 的承重墙裂缝）。台账回调与预检同一去重包装（同一命中不记两次）；
            # local_only（shadow 约束）由登记册 status 驱动，过滤后不进帧。
            # ============================================================
            try:
                ghost_warnings = check_ghost_text(
                    text, bundle, canon_node_ids_by_label=_label_map,
                    # ⚠ 不传 all_names：候选宇宙走 bundle 内省路径
                    # （_bundle_all_names 只收 character/asset——势力是组织不是
                    # 物件；显式传 proper_nouns() 会混入全类型名，语料库口径分叉）
                    visible_names=list(proper_nouns or []),
                    off_scene_locations=_off_scene_loc_names,
                    outline_beats=_rush_beats_guard,
                    written_tail=_written_tail_guard,
                    present_names=_present_names_guard,
                    unknown_canon_phrases=_unknown_canon_phrases,
                    on_event=_on_guard_event,
                )
                ghost_warnings = [w for w in ghost_warnings if not w.get("local_only")]
            except Exception as e:
                logger.debug(f"[adaptive/stitch-ghost] 快检失败（不阻塞生成）: {e}")
            if breaker_open:
                # 熔断降级指示（感知带可见）：自动修正已连续失败，转为仅提示
                ghost_warnings.append({
                    "kind": "quality_breaker",
                    "span_text": "",
                    "message": "自动修正连续失败，已暂时转为仅提示（不再拦截）",
                })
            # 知识平面 v3.1 join 埋点（§10 在线召回证据，只记录不 retry）：
            # 死者开口类 warning 命中时回查对应条目是否在当次选择集内——
            # 缺席即选择器漏召的直接证据，攒够样本后再决策自动补选重发
            for w in ghost_warnings:
                if (w.get("kind") or "") != "dead_speak":
                    continue
                _name = str(w.get("span_text") or "")
                _sel_titles = set(kg.present_names) | set(kg.dead_names) | {
                    k.split(":", 1)[1] for k in kg.selected_keys
                    if k.startswith(("entity:", "asset:"))
                }
                trace_event(
                    "kg_join_dead_speak",
                    name=_name,
                    entry_selected=_name in _sel_titles,
                )
            # stitch 语义抢拍闸（二期 shadow）：幽灵全文 vs 大纲就近节拍的语义
            # 重合——字面闸（dock ≥4 字重叠）抓不住的改写式抢拍由向量补位。
            # shadow 纪律：只落台账/trace 攒校准数据，不返修不切除不提示；
            # 未配置 embedding API 内部零调用短路（SQLite 存储门控不挡纯 API
            # 比对——is_embedding_api_configured 窄判定）。
            try:
                from backend.services.validation.semantic_overlap import (
                    BEAT_RUSH_SHADOW_THRESHOLD,
                    semantic_overlap_hits,
                )

                _rush_beats = outline_nearby(
                    bundle.outline_text or "",
                    (request.rolling_prefix or "") + "\n" + (request.fragment or ""),
                )
                if _rush_beats:
                    _rush_hits = await semantic_overlap_hits(
                        text, _rush_beats, threshold=BEAT_RUSH_SHADOW_THRESHOLD)
                    if _rush_hits:
                        _log_constraint_event(
                            str(_bundle_book_id or ""), str(chapter_id),
                            "stitch-beat-rush-semantic", "hit", reason="shadow",
                            detail={
                                "top": _rush_hits[0].get("similarity"),
                                "segment": str(_rush_hits[0].get("segment") or "")[:40],
                                "mode": request.mode,
                            },
                        )
                        trace_event(
                            "stitch_beat_rush_shadow",
                            mode=request.mode, hits=len(_rush_hits),
                            top=_rush_hits[0].get("similarity"),
                        )
            except Exception as e:
                logger.debug(f"[adaptive/stitch-ghost] 语义抢拍 shadow 失败（静默）: {e}")

            # B5 人称漂移（约束治理一期 report-only）：叙述段第一人称密度超阈值
            # 落台账（signal-only——每发都记会污染 hit 语义），不上屏不进帧；
            # 密度本身进 adaptive_stitch_complete trace（P2-2：校准需要分布
            # 而不只是尾部信号）。
            _persona_density = None
            try:
                from backend.services.constraints.persona_drift import narrative_first_person_density

                _pd = narrative_first_person_density(text)
                _persona_density = _pd.get("density")
                if _pd.get("sufficient") and _pd.get("density", 0) >= 2.0:
                    _log_constraint_event(
                        str(_bundle_book_id or ""), str(chapter_id), "persona-drift",
                        "hit", reason="report_only_above_threshold",
                        detail={"density": _pd.get("density"), "mode": request.mode},
                    )
            except Exception as e:
                logger.debug(f"[adaptive/stitch-ghost] 人称漂移埋点失败（静默）: {e}")

            # 幽灵半角标点归一（呈现平面末站，2026-09-09）：所有闸门已过、
            # text 即将分块播出——在此之后的所有消费方（GHOST_CHUNK 播放/
            # GHOST_DONE 全文/word_count/trace）看到同一份归一后文本
            text = _normalize_ghost_punctuation(text)

            yield build_sse_event("GHOST_START", "", mode=request.mode)
            # burst/open/outline 文本长 → 更大步长更快节奏（700 字约 2.3s 播完），短档保持原速
            chunk_size = 12 if request.mode in ("burst", "open", "outline") else 6
            frame_delay = 0.04 if request.mode in ("burst", "open", "outline") else 0.09
            for pos in range(0, len(text), chunk_size):
                yield build_sse_event("GHOST_CHUNK", "", delta=text[pos: pos + chunk_size])
                await asyncio.sleep(frame_delay)
            # warnings/wash/deai/repaired/breaker_open 均为向后兼容增量字段
            # （无命中/旧前端缺省均为空/忽略）
            yield build_sse_event(
                "GHOST_DONE", "", text=text, word_count=len(text),
                warnings=ghost_warnings,
                wash=wash_payload,
                deai=deai_payload,
                ghost_token=ghost_token,
                sample_ids=sample_ids,
                repaired=repaired_payload,
                breaker_open=breaker_open,
            )
            trace_event(
                "adaptive_stitch_complete",
                mode=request.mode,
                # F2d 全局 prompt 版本：归因本次生成用的 prompt 措辞版
                # （快照对拍 scripts/prompt_snapshot.py 的对照锚点）
                prompt_version=PROMPT_VERSION,
                target_chars=request.target_chars,
                actual_chars=len(text),
                warnings=len(ghost_warnings),
                wash_hits=len(wash_payload.get("hits") or []),
                wash_repaired=int(repaired_flag),
                deai_applied=int(deai_payload.get("applied", False)),
                ghost_token=ghost_token,
                sample_ids=sample_ids,
                persona_density=_persona_density,
                # 约束治理二期：返修环结果与熔断状态进 trace（校准与事故诊断面）
                repair_action=str(repaired_payload.get("action") or ""),
                repaired_count=int(repaired_payload.get("count") or 0),
                breaker_open=int(breaker_open),
                # P1-3（C1）短窗观测：原始上送 vs 截窗后实际进 prompt 的长度
                rolling_prefix_raw_len=len(request.rolling_prefix or ""),
                rolling_prefix_used_len=len(rolling_windowed),
            )
        except Exception as e:
            logger.warning(f"[adaptive/stitch-ghost] 失败: {e}")
            yield build_sse_error(f"续写失败: {e}")
        finally:
            # SSE 流结束（正常/异常/客户端断连）统一冲账——stitch 是请求内直接调 LLM，
            # 不冲就没人冲（下一个心跳也能兜底，但那要等作者继续打字）
            await flush_adaptive_records(chapter_id)

    return StreamingResponse(_stream(), media_type="text/event-stream")
