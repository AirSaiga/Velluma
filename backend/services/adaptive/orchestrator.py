# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - NLE-ADF 3.0 动态调度器
"""
自适应写作伙伴的大脑——消费作者状态 + 世界模型快照 + 变化信号，
决定激活哪些能力组件、以什么粒度、花多少 Token。

设计：状态驱动的规则表（非 if-else 瀑布）。改规则即可调整系统行为。
所有组件异步激活（asyncio.create_task），心跳请求不阻塞——前端不等组件完成，
下次心跳拿到的快照已含组件产出。

Token 预算：心跳组件侧无全局汇总闸——每次激活带独立 budget_tokens（下发为
该组件本次 LLM 调用的 max_tokens），调度器不做跨组件求和与超支拦截。
真正的预算器在 services/context/budget.py（P5 批次 3）：管 stitch 注入侧
的上下文剂量与跨块分配，不覆盖心跳组件。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from backend.services.observability.run_trace import trace_event
from backend.services.adaptive.change_detector import (
    AuthorState, ChangeSignal, detect, aggregate_severity,
)

logger = logging.getLogger(__name__)

# 反推最小间隔（秒）——即使信号很强，也太频繁会烧 Token
INFERENCE_MIN_INTERVAL_S = 30.0
# 信号严重度阈值——低于此值不触发反推
INFERENCE_SEVERITY_THRESHOLD = 0.5
# 停顿档同步组件的单个等待上限（秒）（2026-08-27）：慢端点实测推测 70s/挂件
# 104s——停顿心跳响应被拖到几分钟，前端自动弹舱守卫（响应落地时作者须未动笔）
# 永不满足，卡片舱「只有 Tab 活着」。超时即放弃本轮产出（下次停顿重算），
# 把自动唤醒的最坏等待钉死。正常端点（推测 4s+挂件 3s）远够用。
SYNC_COMPONENT_TIMEOUT_S = 12.0


@dataclass
class Activation:
    """一次组件激活指令。"""
    component: str   # intent_inference | future_projection | dock_generator | sediment | post_process | canon_watch | event_scout
    priority: str    # high | medium | low
    budget_tokens: int


class AdaptiveOrchestrator:
    """动态调度器。

    生命周期：每个章节一个实例（或按 chapter_id 缓存）。前端心跳到达时调
    on_heartbeat，调度器内部决定是否激活组件，组件异步跑、写回世界模型。
    """

    def __init__(self, db_factory: Callable, chapter_id: str):
        """
        Args:
            db_factory: 返回新 AsyncSession 的工厂（异步任务需独立 session）
            chapter_id: 当前章节
        """
        self.db_factory = db_factory
        self.chapter_id = chapter_id
        # 每 chapter 的瞬态缓存（防并发重复激活 + 大纲签名）
        self._last_inference_ts: float = 0.0
        self._prev_outline_sig: str = ""
        # 打算一句话签名（2026-09-03 意图入舱）：变更即触发层 2 转化 + 舱换向
        self._prev_spine_sig: str = ""
        self._active_tasks: Dict[str, asyncio.Task] = {}  # component → running task
        # P3-2（C4）双跑去重：异步激活的入参签名（recent_text 签名 + budget 档）
        self._active_task_sigs: Dict[str, str] = {}
        # P3-1（C5）组件失败可见化：component → {"ts": 秒级时间戳, "error": 一行摘要}。
        # 成功即清（「最近一次失败」语义，非历史账）；per-orchestrator 内存态
        self._last_component_errors: Dict[str, Dict[str, Any]] = {}
        # 谋篇进度判定的增量基准（P1.4 M2）：上次心跳时的正文长度，-1=首次（判全文）
        self._last_content_len: int = -1
        # dock 缓存：段落文本 + projection 签名未变则复用上次碎片，省 ~90% dock 成本
        self._sync_inflight: set = set()  # 停顿档同步组件在飞标记（跨心跳去重，防慢端点下并发双烧 LLM）
        self._last_dock_text_sig: str = ""
        self._last_dock_proj_sig: str = ""
        # dock 缓存低频在场键（2026-09-08 红队 R2）：钉 id + 叙事锚——换景/换锚
        # 才失效；dynamic_state 与全章提及集禁入键（防沉淀抖动与他段打字风暴）
        self._last_dock_stage_sig: str = ""
        # B7 已退役并删除字段：方向权重引擎 +「被采纳的方向」缝合降权
        # （尸检与信号转世见 docs/world-kernel-foundation.md）
        # canon 感知缓存：recent_text 签名未变则复用上次 hints（纯算法但省 DB 查询）
        self._last_canon_text_sig: str = ""
        # 缓存签名待定账（2026-09-04 审计修复）：签名在 _decide 决策时算出，但
        # 落账推迟到 _activate_sync **成功后**——此前决策即落账，12s 超时后旧
        # 签名已就位，下一轮同文本直接判缓存命中，「超时下轮重算」承诺失效，
        # 首次停顿即超时则挂件舱整章为空。失败/超时弃账（旧签名保留=下轮重算）
        self._pending_sigs: Dict[str, Dict[str, str]] = {}
        # 完稿在飞标记（2026-09-04 审计修复）：原「post_process in _active_tasks」
        # 守卫恒假（post_process 从不进 _active_tasks），连点完稿=全管线并发双跑
        self._finish_in_flight: bool = False
        # 组件注册（延迟 import 避免循环）
        self._components: Dict[str, Callable] = {}

    def register_component(self, name: str, runner: Callable):
        """注册能力组件（runner 签名：async def(chapter_id, db, model_snapshot, budget) -> result）。"""
        self._components[name] = runner

    def _commit_pending_sig(self, component: str) -> None:
        """把待定缓存签名落账（_activate_sync 成功路径调用；失败/超时弃账）。"""
        pending = self._pending_sigs.pop(component, None)
        if not pending:
            return
        if component == "dock_generator":
            self._last_dock_text_sig = pending.get("text", self._last_dock_text_sig)
            self._last_dock_proj_sig = pending.get("proj", self._last_dock_proj_sig)
            self._last_dock_stage_sig = pending.get("stage", self._last_dock_stage_sig)
        elif component == "canon_watch":
            self._last_canon_text_sig = pending.get("text", self._last_canon_text_sig)

    # ============================================================
    # P3-1（C5）组件失败可见化 + P3-2（C4）入参签名
    # ============================================================

    def _note_component_error(self, component: str, exc: BaseException) -> None:
        """记录组件最近一次失败（秒级时间戳 + 一行摘要，不带堆栈）。

        此前异步组件失败只有后台 log，前端「辅助层偶尔什么都不出」完全不可
        分辨原因。经心跳响应 / /adaptive/model 透出（副驾「AI 视角」调试区），
        堆栈不给作者看。
        """
        summary = " ".join(str(exc).split())[:120] or exc.__class__.__name__
        self._last_component_errors[component] = {
            "ts": int(time.time()),
            "error": summary,
        }

    def _clear_component_error(self, component: str) -> None:
        """成功即清该组件的失败记录（最近一次失败语义）。"""
        self._last_component_errors.pop(component, None)

    def last_component_errors(self) -> Dict[str, Dict[str, Any]]:
        """最近失败组件快照（浅拷贝防外部改动内存态；空 dict = 一切正常）。"""
        return {k: dict(v) for k, v in self._last_component_errors.items()}

    @staticmethod
    def _component_input_sig(recent_text: str, budget: int) -> str:
        """P3-2（C4）组件入参签名：recent_text 签名 + budget 档。

        等效 = 同段落文本 + 同预算档——await 完的在跑异步任务产出可直接复用；
        签名不等效时维持重跑（现状兜底：异步任务可能用的旧参数，产出无效）。
        """
        from backend.services.adaptive.change_detector import _text_sig
        return f"{_text_sig(recent_text)}:{int(budget)}"

    async def on_heartbeat(self, state: AuthorState) -> Dict[str, Any]:
        """前端心跳到达。返回当前世界模型快照 + 本次激活的组件列表。

        调度器决定激活哪些组件，异步启动它们（不等待完成）。
        前端下次心跳会拿到组件产出（已写入世界模型）。
        """
        from backend.services.adaptive.world_model import WorldModelRepository

        async with self.db_factory() as db:
            repo = WorldModelRepository(db)
            snapshot = await repo.snapshot(self.chapter_id)

            # ---- 变化检测 ----
            signals = detect(state, snapshot, self._prev_outline_sig)
            # 缓存大纲签名（下次对比）
            if state.has_outline:
                from backend.services.adaptive.change_detector import _text_sig
                self._prev_outline_sig = _text_sig(state.outline_text)
            # 打算变更信号（2026-09-03 意图入舱）：作者写/改/纠正打算一句话 →
            # severity 0.6 过反推阈值——层 2 走 spine 短路转化（0 LLM），
            # intent_version 递增连带 bust dock 缓存，舱随纠正换向
            from backend.services.adaptive.change_detector import _text_sig
            spine_sig = _text_sig(state.spine_intent or "")
            if spine_sig != self._prev_spine_sig:
                self._prev_spine_sig = spine_sig
                signals.append(ChangeSignal(
                    kind="spine_updated", evidence="打算一句话变更", severity=0.6,
                ))

            # ---- 热层影子（B7 · 方向权重葬礼后的转世）----
            # 力学模型已删（尸检：18 次恒常量输出）；有价值的信号（未兑现伏笔/
            # 期待张力/先验重要度）由 salience 三族信号承接。此处 log-only：
            # 算而不注，攒影子数据过 A/B 闸后才供 dock 单车道
            try:
                from backend.services.adaptive.salience import compute_salience
                from backend.services.context.settings_bundle import load_chapter_settings_bundle

                _bundle = await load_chapter_settings_bundle(self.chapter_id, db)
                _names = {
                    str(getattr(getattr(e, "character", None), "name", "") or ""): [
                        str(getattr(getattr(e, "character", None), "name", "") or "")
                    ] + [str(a) for a in (getattr(getattr(e, "character", None), "aliases", None) or [])]
                    for e in (_bundle.entities or [])
                }
                _names = {k: v for k, v in _names.items() if k}
                _priors = {
                    k: int(getattr(getattr(e, "world_entity", None), "importance", 5) or 5)
                    for e in (_bundle.entities or [])
                    for k in [str(getattr(getattr(e, "character", None), "name", "") or "")]
                    if k
                }
                _loops = [str(getattr(h, "content", "") or "") if not isinstance(h, dict)
                          else str(h.get("content", "") or "") for h in (_bundle.open_hooks or [])]
                _hot = compute_salience(
                    canvas_text=_bundle.content_text or "",
                    entity_names=_names,
                    priors=_priors,
                    open_loops=_loops,
                )
                trace_event(
                    "salience_shadow",
                    hot=[{"title": e.title, "slot": e.slot, "score": e.score} for e in _hot],
                )
            except Exception as e:
                logger.debug(f"[orchestrator] 热层影子失败（不阻塞心跳）: {e}")

            # ---- 决策：哪些组件该激活 ----
            # 在场低频键（2026-09-08 红队 R2）：Chapter 行单主键取（开销结论同
            # _spine_intent——可忽略）；异常静默空串=恒定键，零失效增量
            stage_sig = ""
            try:
                from backend.models import Chapter as _Chapter
                _ch = await db.get(_Chapter, self.chapter_id)
                if _ch is not None:
                    from backend.services.adaptive.components.dock_generator import presence_fingerprint
                    stage_sig = presence_fingerprint(
                        getattr(_ch, "scene_location_id", None),
                        getattr(_ch, "narrative_time", None),
                    )
            except Exception:
                stage_sig = ""

            activations = self._decide(state, snapshot, signals, stage_sig)

            # 停顿心跳（paused_ms 够长）→ 同步等待 dock_generator 完成，
            # 让本次心跳响应直接带回挂件（避免"首次心跳返回空、要等下次"的时序问题）。
            # 活跃心跳 → 全部异步（不阻塞，下次心跳拿产出）。
            is_pause_heartbeat = state.paused_ms >= 4000
            sync_components = {"dock_generator", "future_projection", "canon_watch"} if is_pause_heartbeat else set()

            for act in activations:
                if act.component in sync_components:
                    # 停顿档在飞去重（2026-08-27）：上一停顿的同名组件仍在跑
                    #（慢端点下 60s+）时本轮不重复花 LLM——trace 实证两次停顿
                    # 间隔 23s 会并发双跑推测。产出落地后下轮心跳自然取走
                    if act.component in self._sync_inflight:
                        continue
                    # 停顿心跳同步组件统一透传实时段落（前端光标段纯文本）——
                    # dock_generator/canon_watch 据此锚定「作者当前段落」；
                    # dock 另可带 salience 具名提示行（B7 单车道注入，取代旧方向权重）
                    # 停顿心跳同步组件统一透传实时段 + 全书字数（意图衰老判定
                    # 原料，2026-09-09）+ 后文锚（中插桥接/FIM，2026-09-09）
                    extra: Dict[str, Any] = {
                        "recent_text": state.recent_text or "",
                        "word_count": state.word_count,
                        "suffix_anchor": state.suffix_anchor or "",
                    }
                    self._sync_inflight.add(act.component)
                    try:
                        await self._activate_sync(act, db, extra_context=extra)
                    finally:
                        self._sync_inflight.discard(act.component)
                else:
                    # 意图加固（2026-09-03）：细纲胶囊速记透传给反推组件——
                    # 胶囊会话级不落库，是作者最稀疏最真实的意图信号
                    extra = (
                        {"outline_notes": list(state.outline_notes or [])}
                        if act.component == "intent_inference" else None
                    )
                    await self._activate(act, recent_text=state.recent_text or "", extra=extra)

            await db.commit()
            # 同步执行后重新拉快照（挂件已写入）
            if sync_components & {a.component for a in activations}:
                snapshot = await repo.snapshot(self.chapter_id)

        return {
            "snapshot": snapshot,
            "activated": [a.component for a in activations],
            "signals": [s.kind for s in signals],
        }

    def _decide(
        self,
        state: AuthorState,
        snapshot: Dict[str, Any],
        signals: List[ChangeSignal],
        stage_sig: str = "",
    ) -> List[Activation]:
        """规则表决策。返回需激活的组件列表。"""
        activations: List[Activation] = []
        intent = snapshot.get("intent", {})
        intent_source = intent.get("source", "none")
        fact_count = snapshot.get("fact_count", 0)
        # 有效字数 = 层1沉淀字数 + 作者当前画布字数（含未沉淀的）
        # 关键：不能只看层1——作者刚开始写还没沉淀时层1是空的，但画布已有正文
        effective_words = max(snapshot.get("total_words", 0), state.word_count)

        # ---- 规则 1：意图反推（Token 主战场，最严格节流）----
        sev = aggregate_severity(signals)
        should_infer = False
        if intent_source == "none" and effective_words >= 200:
            # 无意图 + 有足够正文（含未沉淀的）→ 首次反推
            should_infer = True
        elif sev >= INFERENCE_SEVERITY_THRESHOLD:
            # 有强变化信号 → 重算
            should_infer = True
        # 节流：距上次反推不足 30s 则不触发（即使信号强）。
        # 例外（2026-09-03 核实轮修复）：spine_updated 且打算非空 → 豁免——
        # 打算转化的 spine 路径 0 LLM，节流（为省 token 而设）对它无意义；
        # 且 spine 信号被吞后 _prev_spine_sig 已更新、不会重发，纠正会在层 2
        # 滞留到下个变化信号（前端乐观更新被旧猜测回写覆盖，表现为「纠正
        # 被无视」）。打算清空的 spine_updated 不豁免（那条路可能走 LLM）。
        spine_hot = bool((state.spine_intent or "").strip()) and any(
            s.kind == "spine_updated" for s in signals
        )
        if (should_infer and not spine_hot
                and (time.time() - self._last_inference_ts) < INFERENCE_MIN_INTERVAL_S):
            should_infer = False
        if should_infer:
            activations.append(Activation(
                component="intent_inference",
                priority="medium",
                budget_tokens=1500,
            ))

        # ---- 规则 2：挂件生发（停顿 4s + 段尾 + 有意图或正文足够）----
        # 句子级闸门（2026-08-25）：段落停在半句（无句末标点）时挂件闭嘴——
        # 此刻作者要的是把句子写完（Space 续写的活），推新画面全是噪音；
        # 空段=段界不判半句（写完一段回车进新段是挂件黄金时机）；
        # Tab 显式点名（summoned）豁免，作者主权优先
        from backend.services.adaptive.paragraph_source import ends_mid_sentence
        if (state.paused_ms >= 4000
            and state.cursor_at_paragraph_end
            and (state.summoned or not ends_mid_sentence(state.recent_text or ""))
            and (intent_source != "none" or effective_words >= 300)):
            # projection 是否过期？（懒加载：没 projection 或 intent 刚变）
            # ⚠ 只看真实推测——layer3 混装着 __dock__/__canon_watch__ 缓存标记项，
            # 不滤掉的话首次停顿后缓存项占位、not projections 永假，走向卡
            # 整章不刷新（无意图时停顿过一次即整章缺席）
            real_projs = [
                p for p in (snapshot.get("projections") or [])
                if isinstance(p, dict) and not p.get("__dock__") and not p.get("__canon_watch__")
            ]
            # 意图版本比对：意图重算后旧推测过期（缺键=修复前的旧推测，刷新一次）
            intent_ver = snapshot.get("intent_version", 0)
            proj_stale = bool(real_projs) and real_projs[0].get("intent_version") != intent_ver
            need_proj = (
                intent_source != "none"
                and (not real_projs or intent.get("confidence", 0) < 0.5 or proj_stale)
            )
            if need_proj:
                activations.append(Activation(
                    component="future_projection",
                    priority="low",
                    budget_tokens=1500,
                ))
            # dock 缓存命中判断：段落文本签名 + projection 签名都没变 → 复用上次碎片
            # 省 ~90% dock 调用（作者没沉淀新段落时，碎片本来就不该变）
            from backend.services.adaptive.change_detector import _text_sig
            # 文本签名并入打算一句话（2026-09-03 意图入舱）：作者纠正打算的瞬间
            # 段落文本没变，但 dock 的 spine_intent 行该换料了——纠正即换向。
            # 并入全书字数（2026-09-09 实测拍板「上下文变即重算」）：段落签名只
            # 盯当前段，盯不住全章上下文——他段增删/幽灵采纳推进/就近节拍前移
            # 都改 word_count 而不改当前段前 100 字。激活只在停顿档（规则 2 的
            # paused_ms≥4000 门），放宽签名不会增加活跃档调用；纯停顿不写字
            # 仍命中缓存（省 ~90% 的承诺保持）。
            cur_text_sig = _text_sig(
                f"{state.recent_text or ''}|{state.spine_intent or ''}|wc{state.word_count}"
            )
            # projection 签名基于**接缝裁剪后**集合（2026-08-27）：过滤是 dock 产出
            # 的实际取材池——stage 变化导致 kept 集合变化时必须触发重算，否则
            # 缓存命中会端出旧取材池的碎片
            from backend.services.adaptive.components.dock_generator import (
                DOCK_PIPELINE_VERSION, _prebeat_projections,
            )
            kept_projs = _prebeat_projections(real_projs)
            # 签名 = 过滤后数量 + 首项 event（简化 hash，沿用旧口径）
            cur_proj_sig = ""
            for p in kept_projs:
                ev = p.get("possible_beats", [{}])[0].get("event", "") if p.get("possible_beats") else ""
                cur_proj_sig = f"{len(kept_projs)}:{ev[:30]}"
                break
            # 意图版本入签名（2026-09-03 意图入舱）：反推重算/作者纠正后
            # 意图版本递增——猜测方向变了舱里 toward_beat 必须换料，不 bust
            # 会把旧方向的碎片端给已纠正的作者（纠正手势「舱就换向」的兑现点）
            cur_proj_sig = f"{cur_proj_sig}:v{intent_ver}"
            # 版本盐值入签名（2026-09-08 僵尸缓存修复）：缓存持久化在
            # layer3_projections 跨进程存活，签名不含流水线版本时——代码
            # 重构后历史章节文本未变即命中库中旧零件。规则大改递增
            # DOCK_PIPELINE_VERSION 即全量安全失效（读取侧 _extract_dock_parts
            # 同源过滤兜底活跃心跳）
            stage_sig = f"{stage_sig}|{DOCK_PIPELINE_VERSION}"
            # 在场键入签（2026-09-08 红队 R2）：换景/换锚（两个人工节奏事件）
            # 后旧在册投影的碎片不再复用——签名三键全同才命中；无钉书恒定
            # 空串=零失效增量（零变化契约）
            dock_cache_hit = (
                cur_text_sig == self._last_dock_text_sig
                and cur_proj_sig == self._last_dock_proj_sig
                and stage_sig == self._last_dock_stage_sig
                and cur_text_sig != ""  # 空文本不缓存
            )
            # 强制刷新（2026-09-08）：心跳带 force_refresh（用户主动连续触发）
            # 时跳过命中判断强行重算并覆盖旧缓存——半句门禁/在飞去重照常生效
            if not dock_cache_hit or state.force_refresh:
                activations.append(Activation(
                    component="dock_generator",
                    priority="low",
                    budget_tokens=1500,
                ))
                # 签名待定账（成功落账/失败弃账，见 __init__ _pending_sigs）
                self._pending_sigs["dock_generator"] = {
                    "text": cur_text_sig, "proj": cur_proj_sig, "stage": stage_sig,
                }
            # 缓存命中：__dock__ 项仍在 layer3_projections，前端 heartbeat 照常取到

        # ---- 规则 4：Canon 感知（停顿 4s + 有正文；hint 主体纯算法 + contradiction 低频 LLM，与 dock 同档同步返回）----
        # 产 Canon 感知 hints（角色出场/伏笔回收/private 泄露/揭示临近），写 __canon_watch__ 缓存项
        # 与 dock 区别：不要求 cursor_at_paragraph_end（写到相关词就该提醒，不限段尾）
        if state.paused_ms >= 4000 and (state.recent_text or "").strip():
            from backend.services.adaptive.change_detector import _text_sig
            canon_text_sig = _text_sig(state.recent_text or "")
            canon_cache_hit = (
                canon_text_sig == self._last_canon_text_sig
                and canon_text_sig != ""
            )
            if not canon_cache_hit:
                activations.append(Activation(
                    component="canon_watch",
                    priority="low",
                    budget_tokens=0,  # appearance/callback/leak 纯算法；contradiction 分支的 1×LLM 由组件内 ≥30s/章 节流自控，不走此预算
                ))
                # 签名待定账（成功落账/失败弃账，见 __init__ _pending_sigs）
                self._pending_sigs["canon_watch"] = {"text": canon_text_sig}
            # 缓存命中：__canon_watch__ 项仍在 layer3_projections，前端 heartbeat 照常取到

        # ---- 规则 3：去重（同组件不重复激活）----
        seen = set()
        unique = []
        for a in activations:
            if a.component not in seen and a.component not in self._active_tasks:
                seen.add(a.component)
                unique.append(a)
        return unique

    async def _activate(self, act: Activation, recent_text: str = "", extra: Optional[Dict] = None):
        """异步激活组件（后台 task，不阻塞心跳）。

        extra：透传给 runner 的组件专属入参（**kw 展开——如反推的细纲胶囊
        速记 outline_notes）；None 时调用形态与旧版一致。
        """
        runner = self._components.get(act.component)
        if not runner:
            logger.warning(f"[orchestrator] 未注册组件: {act.component}")
            return
        # 若该组件已有 task 在跑，跳过（防并发重复）
        existing = self._active_tasks.get(act.component)
        if existing and not existing.done():
            return
        # P3-2（C4）：记录入参签名——_activate_sync await 到本任务后比对等效性，
        # 等效则直接复用产出不再重跑（同参数 LLM 双调用消除）
        self._active_task_sigs[act.component] = self._component_input_sig(
            recent_text, act.budget_tokens,
        )

        async def _run():
            try:
                async with self.db_factory() as db:
                    from backend.services.adaptive.world_model import WorldModelRepository
                    repo = WorldModelRepository(db)
                    snapshot = await repo.snapshot(self.chapter_id)
                    await runner(self.chapter_id, db, snapshot, act.budget_tokens, **(extra or {}))
                    await db.commit()
                if act.component == "intent_inference":
                    self._last_inference_ts = time.time()
                self._clear_component_error(act.component)  # P3-1：成功即清
            except Exception as e:
                logger.warning(f"[orchestrator] 组件 {act.component} 失败: {e}", exc_info=True)
                self._note_component_error(act.component, e)  # P3-1
            finally:
                self._active_tasks.pop(act.component, None)
                self._active_task_sigs.pop(act.component, None)

        self._active_tasks[act.component] = asyncio.create_task(_run())

    async def _activate_sync(self, act: Activation, db, extra_context: Dict = None):
        """同步激活组件（在调用方的 db session 里执行，阻塞等待完成）。

        用于停顿心跳：让 dock_generator/future_projection 在心跳返回前跑完，
        本次心跳响应直接带回挂件。~1-2s 可接受（停顿心跳低频）。

        extra_context：透传给 runner 的额外上下文（如 direction_weights），
        runner 在 **kw 里取。
        """
        runner = self._components.get(act.component)
        if not runner:
            return
        # 若已有异步 task 在跑，等它完成（避免并发写冲突）——
        # P3-2（C4）：await 完成后入参签名与本次等效（同段落签名 + 同 budget 档）
        # → 直接复用其产出不再重跑（任务已把产出写进世界模型）；不等效才维持
        # 重跑（旧行为兜底：异步 task 可能用的旧 budget/旧参数，产出可能无效）
        existing = self._active_tasks.get(act.component)
        if existing and not existing.done():
            prior_sig = self._active_task_sigs.get(act.component, "")
            try:
                await existing
            except Exception:
                pass
            finally:
                self._active_tasks.pop(act.component, None)
                self._active_task_sigs.pop(act.component, None)
            cur_sig = self._component_input_sig(
                str((extra_context or {}).get("recent_text") or ""), act.budget_tokens,
            )
            if prior_sig and prior_sig == cur_sig:
                return
        try:
            from backend.services.adaptive.world_model import WorldModelRepository
            repo = WorldModelRepository(db)
            snapshot = await repo.snapshot(self.chapter_id)
            # 同步超时钳制（2026-08-27）：wait_for 超时即放弃本轮产出——组件
            # 不落库、下次停顿重算。取消落在 LLM HTTP await 上（耗时所在），
            # DB 写全部在其后，无半写状态
            await asyncio.wait_for(
                runner(self.chapter_id, db, snapshot, act.budget_tokens, **(extra_context or {})),
                timeout=SYNC_COMPONENT_TIMEOUT_S,
            )
            # 不在此 commit（由 on_heartbeat 统一 commit）
            if act.component == "intent_inference":
                self._last_inference_ts = time.time()
            # 缓存签名成功落账（2026-09-04 审计修复：决策即落账会让超时后
            # 下一轮误判缓存命中——「超时下轮重算」承诺的兑现点）
            self._commit_pending_sig(act.component)
            self._clear_component_error(act.component)  # P3-1：成功即清
        except asyncio.TimeoutError:
            # 超时/失败弃账：待定签名丢弃，旧缓存签名保留 → 下一轮同文本仍判
            # 未命中并重新激活（「本轮产出放弃，下轮重算」成立）
            self._pending_sigs.pop(act.component, None)
            logger.warning(
                f"[orchestrator] 同步组件 {act.component} 超时（>{SYNC_COMPONENT_TIMEOUT_S}s），本轮产出放弃"
            )
            self._note_component_error(
                act.component,
                TimeoutError(f"同步超时 >{SYNC_COMPONENT_TIMEOUT_S}s（端点缓慢，本轮产出放弃，下轮停顿重算）"),
            )
        except Exception as e:
            self._pending_sigs.pop(act.component, None)
            logger.warning(f"[orchestrator] 同步组件 {act.component} 失败: {e}", exc_info=True)
            self._note_component_error(act.component, e)  # P3-1

    async def on_settle(self, segment_text: str, entities: List[Dict], commit: bool = False) -> Dict[str, Any]:
        """段落锁死事件：追加层 1 + 同步触发沉淀（抽涌现实体 + 冲突检测）+ 节拍力权重重算。

        sediment 同步等待——让前端 settle 响应直接带回涌现实体/冲突，
        作者立即看到抽取结果（作者主权：冲突不自动改，浮给作者确认）。
        """
        from backend.services.adaptive.world_model import WorldModelRepository, SettledSegment

        async with self.db_factory() as db:
            repo = WorldModelRepository(db)
            seg = SettledSegment(
                text=segment_text,
                entities=entities,
                word_count=len(segment_text),
            )
            await repo.append_fact(self.chapter_id, seg)
            await db.commit()

        # B7：沉淀节拍力（方向权重重算）已随力学模型退役——新段新节拍的
        # 注意力刷新由热层 salience 的段距衰减天然承担（纯函数无需事件触发）

        # ---- 同步触发沉淀（抽涌现实体 + 冲突检测）----
        sediment_result = {}
        sediment_runner = self._components.get("sediment")
        if sediment_runner and "sediment" not in self._active_tasks:
            try:
                async with self.db_factory() as db:
                    snapshot = await WorldModelRepository(db).snapshot(self.chapter_id)
                    sediment_result = await sediment_runner(self.chapter_id, db, snapshot, 1500, commit=commit)
                    await db.commit()
                self._clear_component_error("sediment")  # P3-1
            except Exception as e:
                logger.warning(f"[orchestrator] sediment 失败: {e}", exc_info=True)
                self._note_component_error("sediment", e)  # P3-1

        # ---- W4 候选事件抽取（本段 → 待确认池；失败不影响沉淀结果）----
        candidates_created = 0
        scout_skipped = None
        scout_runner = self._components.get("event_scout")
        if scout_runner:
            try:
                async with self.db_factory() as db:
                    scout_result = await scout_runner(
                        self.chapter_id, db, {}, 1500, source="settle", text=segment_text
                    )
                    candidates_created = int(scout_result.get("created", 0))
                    # P3-4（C6）：无候选产出且带跳过原因（无实体/正文不足）→ 透出给
                    # 前端收件箱空态（有候选产出时缺省不出，零变化契约）
                    if not candidates_created:
                        scout_skipped = scout_result.get("skipped")
                    await db.commit()
                self._clear_component_error("event_scout")  # P3-1
            except Exception as e:
                logger.warning(f"[orchestrator] event_scout 失败: {e}", exc_info=True)
                self._note_component_error("event_scout", e)  # P3-1

        result = {
            "settled": True,
            "fact_count": (await self._fact_count()),
            "emergent_facts": sediment_result.get("emergent_facts") if sediment_result else None,
            "conflicts": sediment_result.get("conflicts") if sediment_result else None,
            "candidates_created": candidates_created,
        }
        if scout_skipped:
            result["scout_skipped"] = scout_skipped
        return result

    async def on_finish(self) -> Dict[str, Any]:
        """作者完稿：同步触发后处理（审计/一致性/残句/覆盖率），返回完整报告。

        同步等待（不 fire-and-forget）——完稿是低频操作，~3-8s 可接受，
        让前端直接拿到审计结果展示。
        """
        post_runner = self._components.get("post_process")
        if not post_runner:
            return {"finished": False, "reason": "post_process 未注册"}
        # 并发守卫（2026-09-04 审计修复）：原「post_process in _active_tasks」
        # 恒假（post_process 走同步路径从不注册后台 task）——连点完稿=审计
        # +event_scout+记忆重索引全管线并发双跑双烧 token。改用真实在飞标记。
        if self._finish_in_flight:
            return {"finished": False, "reason": "后处理已在进行中"}
        self._finish_in_flight = True

        # 存量缺陷修复：on_finish 缺此导入 → NameError → /adaptive/finish 一直 500
        # （本文件各方法惯用局部导入防循环依赖，on_settle 有、on_finish 漏了）
        from backend.services.adaptive.world_model import WorldModelRepository

        try:
            async with self.db_factory() as db:
                snapshot = await WorldModelRepository(db).snapshot(self.chapter_id)
                report = await post_runner(self.chapter_id, db, snapshot, 8000)
                await db.commit()
            self._clear_component_error("post_process")  # P3-1
            # ---- W4 候选事件抽取（整章 → 待确认池；失败不影响审计结果）----
            candidates_created = 0
            scout_skipped = None
            scout_runner = self._components.get("event_scout")
            if scout_runner:
                try:
                    async with self.db_factory() as db:
                        scout_result = await scout_runner(
                            self.chapter_id, db, {}, 2500, source="finish"
                        )
                        candidates_created = int(scout_result.get("created", 0))
                        # P3-4（C6）：无候选产出且带跳过原因 → 透出（增量字段，零变化）
                        if not candidates_created:
                            scout_skipped = scout_result.get("skipped")
                        await db.commit()
                    self._clear_component_error("event_scout")  # P3-1
                except Exception as e:
                    logger.warning(f"[orchestrator] event_scout(finish) 失败: {e}", exc_info=True)
                    self._note_component_error("event_scout", e)  # P3-1
            result = {"finished": True, "report": report or {}}
            if candidates_created:
                result["candidates_created"] = candidates_created
            if scout_skipped:
                result["scout_skipped"] = scout_skipped
            return result
        except Exception as e:
            logger.warning(f"[orchestrator] post_process 失败: {e}", exc_info=True)
            self._note_component_error("post_process", e)  # P3-1
            return {"finished": False, "reason": str(e)}
        finally:
            self._finish_in_flight = False

    async def _fact_count(self) -> int:
        async with self.db_factory() as db:
            from backend.services.adaptive.world_model import WorldModelRepository
            snap = await WorldModelRepository(db).snapshot(self.chapter_id)
            return snap.get("fact_count", 0)


# ============================================================
# 全局 orchestrator 注册表（按 chapter_id 缓存实例）
# ============================================================

_ORCHESTRATORS: Dict[str, AdaptiveOrchestrator] = {}


def get_orchestrator(chapter_id: str, db_factory: Callable) -> AdaptiveOrchestrator:
    """获取或创建章节的调度器实例（每章一个，带组件注册）。"""
    if chapter_id not in _ORCHESTRATORS:
        orch = AdaptiveOrchestrator(db_factory, chapter_id)
        # 注册所有组件（延迟 import 避免循环依赖）
        from backend.services.adaptive.components import (
            intent_inference, future_projection, dock_generator,
            sediment, post_process, canon_watch,
        )
        from backend.services.world import event_scout
        orch.register_component("intent_inference", intent_inference.run)
        orch.register_component("future_projection", future_projection.run)
        orch.register_component("dock_generator", dock_generator.run)
        orch.register_component("sediment", sediment.run)
        orch.register_component("post_process", post_process.run)
        orch.register_component("canon_watch", canon_watch.run)
        orch.register_component("event_scout", event_scout.run)
        _ORCHESTRATORS[chapter_id] = orch
    return _ORCHESTRATORS[chapter_id]


def drop_orchestrator(chapter_id: str):
    """章节卸载时清理（防内存泄漏）。"""
    _ORCHESTRATORS.pop(chapter_id, None)
