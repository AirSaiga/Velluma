# Velluma - 世界折叠唯一入口（Fold API · B1，docs/world-kernel-foundation.md §3）
# AGPL-3.0
"""
四域世界模型的统一查询面：fold(t, perspective_set, domains, tx_head)。

**唯一入口纪律（不变量 4）**：一切世界状态的消费（world_bridge / 场景切片 /
知识平面 / 未来的 digest 编译）必须经本函数，不得旁路直调仓储折叠——
四域（truth/belief/intent/reader）的模态封闭（不变量 3）只有收口才能保证。

域语义（docs/world-kernel-foundation.md §0 四域存在论）：
- truth：发生了什么（world_events append-only 真值日志的折叠）——B1 起；
- belief：各角色以为发生了什么（认知事件曝光级折叠）——B3 接入；
- intent：打算发生什么（Intent 统一存储查询）——B2 接入；
- reader：读者已知什么（Depiction 呈现关系折叠）——B4 接入。

折叠纯度（不变量 2，决策 5）：本函数与底层 compute_world_state_from_events
均为纯函数式消费——零 LLM、零 NLP、零时钟、零随机；同输入同输出。
tx_head=None 语义 =「链头（最新真相）」；传事件 id 即时间旅行到该修订点
之前（as-of 查询，双时态库语义）。

认知事件类型家族（B1 落 schema、B3 落折叠语义；payload 契约）：
- told{subject: entity_id, object_event: event_id | proposition_ref: canon_node_id}
- discover{subject, evidence_of: event_id}
- misbelieve{subject, proposition_ref, false_content: str}  # 误信首日进 schema（决策 2）
- witness{subject, object_event}  # 非在场获知（远处目击/传闻），在场获知由 participants 推导
副作用：无（纯查询）。
"""
from __future__ import annotations

from typing import Any, Dict, FrozenSet, Iterable, Sequence, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

# 认知事件类型家族（B1 登记；fold 的 belief 域在 B3 消费）
EPISTEMIC_EVENT_TYPES: FrozenSet[str] = frozenset({"told", "discover", "misbelieve", "witness"})

# 合法域集合（模态封闭的边界）
FOLD_DOMAINS: Tuple[str, ...] = ("truth", "belief", "intent", "reader")


async def fold(
    db: AsyncSession,
    book_id: str,
    *,
    t: int,
    domains: Sequence[str],
    perspective_set: Iterable[str],
    tx_head: Any = None,
) -> Dict[str, Any]:
    """四域世界状态的唯一查询入口。

    Args:
        db: 异步会话。
        book_id: 书 id。
        t: 叙事时刻（valid time 轴，必填无默认——不变量 4）。
        domains: 请求的域集合（必填无默认；非法域名抛 ValueError——模态封闭）。
        perspective_set: 视角角色 id 集合（belief 域的配给边界；truth 域忽略；
            空集合法=不按视角过滤）。
        tx_head: 修订链头（None=最新真相；传事件 id=as-of 该修订点）。

    Returns:
        {domain: state_dict}——未接入的域返回空 dict（诚实降级，不猜）。
    """
    domain_set = set(domains)
    if not domain_set:
        raise ValueError("fold: domains 不能为空（模态封闭——查询必须显式声明域）")
    unknown = domain_set - set(FOLD_DOMAINS)
    if unknown:
        raise ValueError(f"fold: 未知域 {sorted(unknown)}（合法域：{FOLD_DOMAINS}）")

    result: Dict[str, Any] = {}
    if "truth" in domain_set:
        from backend.repositories.world_repository import WorldRepository

        # 修订传播（决策 1 tx 轴）：链头查询=排除被 supersede 的旧事件；
        # as-of 查询=只取 tx_head 之前创建的链（B5 的信封校验消费同口径）
        repo = WorldRepository(db)
        state = await repo.compute_world_state(book_id, t)
        result["truth"] = state
        if tx_head is not None:
            result["truth_tx_note"] = f"as-of {tx_head}（修订时间旅行由 B5 信封校验消费）"
    if "belief" in domain_set:
        # B3 接入：曝光级折叠（认知事件 + 参与者在场推导），纯函数
        from sqlalchemy import select as _sa_select

        from backend.models import WorldEvent as _WE
        from backend.services.world.belief import fold_belief

        _bid = UUID(str(book_id))
        _evs = (await db.execute(
            _sa_select(_WE).where(
                _WE.book_id == _bid,
                _WE.event_type.in_(EPISTEMIC_EVENT_TYPES),
                _WE.time_start <= t,
            ).order_by(_WE.sequence_num)
        )).scalars().all()
        _belief = fold_belief(list(_evs), t)
        # 视角配给视图：perspective_set 内各成员的命题 clearance（四值）
        from backend.services.world.belief import proposition_status

        result["belief"] = {
            "states": _belief,
            "perspective": {
                str(pid): {
                    "knows_propositions": (_belief.get(str(pid)) or {}).get("knows_propositions", []),
                    "believes_false": (_belief.get(str(pid)) or {}).get("believes_false", []),
                }
                for pid in perspective_set
            },
            "proposition_status": {
                # 全部被引用命题 × 视角集的四值（B9 反讽机会/负空间消费）
                ref: proposition_status(ref, perspective_set, _belief)
                for ref in {
                    str(p)
                    for slot in _belief.values()
                    for p in (slot.get("knows_propositions") or [])
                    + [b.get("proposition_ref") for b in slot.get("believes_false") or []]
                }
            },
        }
    if "intent" in domain_set:
        from backend.repositories.intent_repository import IntentRepository

        repo_i = IntentRepository(db)
        result["intent"] = {
            "hooks": await repo_i.read_merge_hooks(UUID(str(book_id))),
            "reveals": await repo_i.read_merge_reveals(UUID(str(book_id))),
        }
    if "reader" in domain_set:
        # B4 接入：Depiction 折叠（confirmed 呈现 → 读者认知；未回填=unknown）
        from sqlalchemy import select as _rs

        from backend.models import WorldDepiction as _WD
        from backend.services.world.negative_space import fold_reader

        _deps = (await db.execute(
            _rs(_WD).where(
                _WD.book_id == UUID(str(book_id)),
                _WD.status == "confirmed",
            )
        )).scalars().all()
        result["reader"] = fold_reader(list(_deps))
    return result
