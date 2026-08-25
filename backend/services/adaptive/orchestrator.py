# Velluma - NLE-ADF 3.0 动态调度器
# AGPL-3.0
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

from backend.services.adaptive.change_detector import (
    AuthorState, ChangeSignal, detect, aggregate_severity,
)

logger = logging.getLogger(__name__)

# 反推最小间隔（秒）——即使信号很强，也太频繁会烧 Token
INFERENCE_MIN_INTERVAL_S = 30.0
# 信号严重度阈值——低于此值不触发反推
INFERENCE_SEVERITY_THRESHOLD = 0.5


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
        self._active_tasks: Dict[str, asyncio.Task] = {}  # component → running task
        # P3-2（C4）双跑去重：异步激活的入参签名（recent_text 签名 + budget 档）
        self._active_task_sigs: Dict[str, str] = {}
        # P3-1（C5）组件失败可见化：component → {"ts": 秒级时间戳, "error": 一行摘要}。
        # 成功即清（「最近一次失败」语义，非历史账）；per-orchestrator 内存态
        self._last_component_errors: Dict[str, Dict[str, Any]] = {}
        # 谋篇进度判定的增量基准（P1.4 M2）：上次心跳时的正文长度，-1=首次（判全文）
        self._last_content_len: int = -1
        # dock 缓存：段落文本 + projection 签名未变则复用上次碎片，省 ~90% dock 成本
        self._last_dock_text_sig: str = ""
        self._last_dock_proj_sig: str = ""
        # 方向权重（NLE-ADF 3.0）：5 叙事方向的偏好，每次心跳更新，dock_generator 据此分布生成
        self._direction_weights: Dict[str, float] = {}
        # 被采纳的方向（缝合降权用，compute 后清空）
        self._adopted_directions: List[str] = []
        # canon 感知缓存：recent_text 签名未变则复用上次 hints（纯算法但省 DB 查询）
        self._last_canon_text_sig: str = ""
        # 组件注册（延迟 import 避免循环）
        self._components: Dict[str, Callable] = {}

    def register_component(self, name: str, runner: Callable):
        """注册能力组件（runner 签名：async def(chapter_id, db, model_snapshot, budget) -> result）。"""
        self._components[name] = runner

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

            # ---- 方向权重更新（纯算法，每次心跳都跑，零 LLM）----
            # 输入：意图(must_hits/foreshadows) + 软约束 + 当前段落(惯性力) + 已写正文(推动力)
            # 产出：5 方向的归一化权重，dock_generator 据此分布生成碎片
            from backend.services.adaptive.direction_weights import compute as compute_weights
            from backend.services.adaptive.paragraph_source import written_text
            from backend.services.context.settings_bundle import load_chapter_settings_bundle
            bundle = await load_chapter_settings_bundle(self.chapter_id, db)
            intent = snapshot.get("intent", {})
            soft = bundle.soft_constraints()
            # 推动力「已达成」判定用画布全文——写到画布即已写（无论是否沉淀）；
            # 层 1 事实作者删改后过期，不再作为判定文本
            written_for_weights = written_text(bundle.content_text or "")
            self._direction_weights = compute_weights(
                intent=intent,
                soft=soft,
                recent_text=state.recent_text or "",
                facts_text=written_for_weights,
                prev_weights=self._direction_weights,
                settled_just_now=False,  # on_heartbeat 不触发节拍重置（on_settle 才触发）
                adopted_directions=self._adopted_directions,
            )
            self._adopted_directions = []  # 消费完清空

            # ---- 决策：哪些组件该激活 ----
            activations = self._decide(state, snapshot, signals)

            # 停顿心跳（paused_ms 够长）→ 同步等待 dock_generator 完成，
            # 让本次心跳响应直接带回挂件（避免"首次心跳返回空、要等下次"的时序问题）。
            # 活跃心跳 → 全部异步（不阻塞，下次心跳拿产出）。
            is_pause_heartbeat = state.paused_ms >= 4000
            sync_components = {"dock_generator", "future_projection", "canon_watch"} if is_pause_heartbeat else set()

            for act in activations:
                if act.component in sync_components:
                    # 停顿心跳同步组件统一透传实时段落（前端光标段纯文本）——
                    # dock_generator/canon_watch 据此锚定「作者当前段落」；
                    # dock 另带方向权重（LLM 据此分布生成）
                    extra: Dict[str, Any] = {"recent_text": state.recent_text or ""}
                    if act.component == "dock_generator":
                        extra["direction_weights"] = self._direction_weights
                    await self._activate_sync(act, db, extra_context=extra)
                else:
                    await self._activate(act, recent_text=state.recent_text or "")

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
        # 节流：距上次反推不足 30s 则不触发（即使信号强）
        if should_infer and (time.time() - self._last_inference_ts) < INFERENCE_MIN_INTERVAL_S:
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
            cur_text_sig = _text_sig(state.recent_text or "")
            # projection 签名 = projection 内容的 hash（简化：取数量 + 首项 event）
            cur_proj_sig = ""
            for p in real_projs:
                ev = p.get("possible_beats", [{}])[0].get("event", "") if p.get("possible_beats") else ""
                cur_proj_sig = f"{len(real_projs)}:{ev[:30]}"
                break
            dock_cache_hit = (
                cur_text_sig == self._last_dock_text_sig
                and cur_proj_sig == self._last_dock_proj_sig
                and cur_text_sig != ""  # 空文本不缓存
            )
            if not dock_cache_hit:
                activations.append(Activation(
                    component="dock_generator",
                    priority="low",
                    budget_tokens=1500,
                ))
                self._last_dock_text_sig = cur_text_sig
                self._last_dock_proj_sig = cur_proj_sig
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
                self._last_canon_text_sig = canon_text_sig
            # 缓存命中：__canon_watch__ 项仍在 layer3_projections，前端 heartbeat 照常取到

        # ---- 规则 3：去重（同组件不重复激活）----
        seen = set()
        unique = []
        for a in activations:
            if a.component not in seen and a.component not in self._active_tasks:
                seen.add(a.component)
                unique.append(a)
        return unique

    async def _activate(self, act: Activation, recent_text: str = ""):
        """异步激活组件（后台 task，不阻塞心跳）。"""
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
                    await runner(self.chapter_id, db, snapshot, act.budget_tokens)
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
            await runner(self.chapter_id, db, snapshot, act.budget_tokens, **(extra_context or {}))
            # 不在此 commit（由 on_heartbeat 统一 commit）
            if act.component == "intent_inference":
                self._last_inference_ts = time.time()
            self._clear_component_error(act.component)  # P3-1：成功即清
        except Exception as e:
            logger.warning(f"[orchestrator] 同步组件 {act.component} 失败: {e}", exc_info=True)
            self._note_component_error(act.component, e)  # P3-1

    def on_direction_adopted(self, direction: str) -> None:
        """作者缝合采纳了某方向的碎片 → 记录，下次心跳 compute 时该方向降权（负反馈）。

        由 stitch-ghost 端点调用（缝合时前端回报 adopted_direction）。
        """
        if direction and direction not in self._adopted_directions:
            self._adopted_directions.append(direction)

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

        # ---- 节拍力：沉淀触发方向权重重算（新段新节拍，刻画/环境部分重置）----
        try:
            from backend.services.adaptive.direction_weights import compute as compute_weights
            from backend.services.adaptive.paragraph_source import written_text
            from backend.services.context.settings_bundle import load_chapter_settings_bundle
            async with self.db_factory() as db:
                snapshot = await WorldModelRepository(db).snapshot(self.chapter_id)
                bundle = await load_chapter_settings_bundle(self.chapter_id, db)
                intent = snapshot.get("intent", {})
                soft = bundle.soft_constraints()
                # 推动力判定文本=画布全文；刚沉淀的段落可能尚未过存盘防抖落库，
                # 判定文本缺席会让本段 must_hit 被误判未达——补在尾部
                written_for_weights = written_text(bundle.content_text or "")
                seg = segment_text.strip()
                if seg and seg not in written_for_weights:
                    written_for_weights = written_for_weights + "\n\n" + seg
                self._direction_weights = compute_weights(
                    intent=intent, soft=soft,
                    recent_text=segment_text, facts_text=written_for_weights,
                    prev_weights=self._direction_weights,
                    settled_just_now=True,  # ← 节拍力触发
                    adopted_directions=self._adopted_directions,
                )
                self._adopted_directions = []
        except Exception as e:
            logger.warning(f"[orchestrator] 沉淀节拍力重算失败: {e}")

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
        if "post_process" in self._active_tasks:
            return {"finished": False, "reason": "后处理已在进行中"}

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
            self._active_tasks.pop("post_process", None)

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
