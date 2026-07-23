"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
铺垫/铺陈段写作器（V3.0 新建，V3.1 统一引擎演进）。

职责（设计文档 §5 Phase 4 + §7.3 + D3 距离即指令 + 3.1 §4 分区写作）：
按 reading_order 串行写作每个非高潮节点（PAYLOAD 除外），朝已成文的高潮写。

V3.1 分区工艺（规格 §4）：
- development 区（铺陈段）：双轨工艺，前向滚动扩写，【不施加"压抑"约束】
  离高潮远，无需压着写——双轨"每拍自我完满"的病灶在这个距离上不发作
- buildup 区（蓄势段）：高潮倒推工艺，朝高潮写，带高潮距离标注与压抑约束
- climax 区（高潮段）：由 payload_writer 单独写（本模块不处理）

核心约束：
- 串行 Rolling Prefix 链（呼吸连续性要求；human-flavor §7：分段生成在接缝处无法呼吸）
- 每段输入：文风卡 + 章节卡 + 本段节点（含 distance/assignment/question/restraint/subtext）
            + 高潮成文锚 + 前段尾巴 500 字
- 距离指令模板（§7.3）直接进 prompt（仅 buildup 区注入；development 区去约束）
- 即时校验（fail-fast）：禁词/句长/红线 → 带反馈重试 ≤2

分段策略（按铺垫总长）：
- ≤2500 字单段一次写
- 2500~5000 字分 2-3 段（后段可见高潮 + 前段全文尾巴 500 字）
- >5000 字退回分段扩写 fallback（Slice C 接管）

业务场景：
- DetonationWorkflow.execute 内部调用（3.0 旧路径：所有节点统一处理）
- UnifiedWorkflow.execute 内部调用（3.1 新路径：按 zone 分流，development 区走双轨工艺）
- 每个 FuseSegment 通过 SSE FUSE_PROGRESS 事件上浮进度
"""

import logging
from typing import Any, Dict, List, Optional

from backend.services.llm import call_llm_with_usage
from backend.services.prompts.detonation_prompts import (
    build_fuse_write_prompt,
    build_development_write_prompt,
)
from backend.services.workflows.detonation.types import FuseSegment

logger = logging.getLogger(__name__)


# 铺垫写作参数（设计文档 §5 Phase 4 + §7.3）
FUSE_TEMPERATURE = 0.8
FUSE_MAX_TOKENS = 4096
FUSE_RETRY_MAX = 2  # 即时校验失败后带反馈重试次数
TAIL_WINDOW = 500   # 前段尾巴窗口（字符）

# 字数目标分配（按章节总字数 - payload 长度，按节点 distance 与 assignment 加权）
DEFAULT_TOTAL_FUSE_WORDS = 3500  # 若无章节卡字数，默认铺垫总字数


async def write_fuse_segments(
    nodes: List[Dict[str, Any]],
    reading_order: List[str],
    payload_text: str,
    chapter: Any,
    chapter_card: Any,
    entities: List[Any],
    style_card: Any = None,
    author_samples: Optional[List[str]] = None,
    target_total_words: Optional[int] = None,
    fail_fast_validator: Optional[Any] = None,
    recorder: Optional[Any] = None,
    progress_callback: Optional[Any] = None,
    zones: Optional[Dict[str, List[str]]] = None,
) -> List[FuseSegment]:
    """按 reading_order 串行写作所有铺垫/铺陈段。

    Args:
        nodes: SetupNode dict 列表
        reading_order: 节点 id 序（末位 PAYLOAD，本函数不写它）
        payload_text: 高潮段成文（锚注入每段 prompt）
        chapter: Chapter ORM 对象
        chapter_card: ChapterCard ORM 对象
        entities: 本章关联角色列表
        style_card: 可选 StyleCard ORM
        author_samples: 可选作者样本列表
        target_total_words: 铺垫总字数目标（None 则按章节卡 word_target 推断）
        fail_fast_validator: 可选校验闭包 (chunk) -> (is_valid, fail_reason, categories)
        recorder: 可选 RunRecorder
        progress_callback: 可选回调 (segment_index, total_segments, segment) -> None
        zones: V3.1 三分区映射 {development/buildup/climax: [node_id...]}
            传入时按 zone 分流：development 区用去约束的铺陈工艺，buildup 区用压抑约束的铺垫工艺。
            None 时（3.0 旧路径）所有节点统一走铺垫工艺（压抑约束）。

    Returns:
        List[FuseSegment]：按 reading_order 排列（不含 PAYLOAD）
    """
    # 铺垫节点 = reading_order 中除 PAYLOAD 外的、且在 nodes 中存在的
    node_by_id = {str(n.get("id", "")): n for n in nodes if n.get("id")}
    fuse_node_ids = [nid for nid in reading_order if nid != "PAYLOAD" and nid in node_by_id]
    total_segments = len(fuse_node_ids)

    if total_segments == 0:
        logger.info("[FuseWriter] 无铺垫节点（纯高潮章），跳过铺垫写作")
        return []

    # V3.1：构建 node_id → zone 查找表
    node_zone_map: Dict[str, str] = {}
    if zones:
        for zone_name, node_ids in zones.items():
            for nid in node_ids or []:
                node_zone_map[str(nid)] = zone_name

    # 字数分配
    word_targets = _allocate_word_targets(
        fuse_node_ids=[node_by_id[nid] for nid in fuse_node_ids],
        target_total=target_total_words or _infer_total_words(chapter_card, chapter),
        payload_text=payload_text,
    )

    segments: List[FuseSegment] = []
    rolling_tail = ""  # 前段尾巴（首段为空）

    # V3.1：统计分区分布（日志透明化）
    if zones:
        zone_counts = {"development": 0, "buildup": 0}
        for nid in fuse_node_ids:
            z = node_zone_map.get(nid, "buildup")
            zone_counts[z] = zone_counts.get(z, 0) + 1
        logger.info(
            f"[FuseWriter] V3.1 分区写作：{total_segments} 段 "
            f"(development={zone_counts.get('development', 0)} / "
            f"buildup={zone_counts.get('buildup', 0)})，"
            f"总目标 {sum(word_targets)} 字，payload 锚 {len(payload_text)} 字"
        )
    else:
        logger.info(
            f"[FuseWriter] 开始铺垫写作：{total_segments} 段，"
            f"总目标 {sum(word_targets)} 字，payload 锚 {len(payload_text)} 字"
        )

    for idx, nid in enumerate(fuse_node_ids):
        node = node_by_id[nid]
        target_words = word_targets[idx]
        # V3.1：查询本节点所属 zone（无 zones 时默认 buildup，走旧铺垫工艺）
        zone = node_zone_map.get(nid, "buildup") if zones else "buildup"

        segment = await _write_single_fuse(
            node=node,
            distance=idx + 1,  # 距高潮的节点数（reading_order 中 PAYLOAD 在末位，所以距离 = total - idx）
            payload_text=payload_text,
            tail_500=rolling_tail,
            target_words=target_words,
            chapter=chapter,
            entities=entities,
            style_card=style_card,
            author_samples=author_samples,
            fail_fast_validator=fail_fast_validator,
            recorder=recorder,
            segment_index=idx,
            zone=zone,
        )
        segments.append(segment)

        # 更新 rolling tail（取本段末尾 TAIL_WINDOW 字符）
        rolling_tail = segment.text[-TAIL_WINDOW:] if segment.text else rolling_tail

        # 进度回调
        if progress_callback is not None:
            try:
                await progress_callback(idx + 1, total_segments, segment)
            except Exception as e:
                logger.warning(f"[FuseWriter] progress_callback 异常: {e}")

    logger.info(f"[FuseWriter] 写作完成：{len(segments)} 段，总 {sum(s.word_count for s in segments)} 字")
    return segments


async def _write_single_fuse(
    node: Dict[str, Any],
    distance: int,
    payload_text: str,
    tail_500: str,
    target_words: int,
    chapter: Any,
    entities: List[Any],
    style_card: Any,
    author_samples: Optional[List[str]],
    fail_fast_validator: Optional[Any],
    recorder: Optional[Any],
    segment_index: int,
    zone: str = "buildup",
) -> FuseSegment:
    """写单个铺垫/铺陈段（含 fail-fast 重试）。

    Args:
        zone: V3.1 分区（development=铺陈段去约束 / buildup=蓄势段带压抑约束）
    """
    # V3.1：按 zone 分流选择 prompt 模板
    if zone == "development":
        # 铺陈段（双轨工艺，去压抑约束）——规格 §4.3
        system_prompt, user_prompt = build_development_write_prompt(
            payload_text=payload_text,
            node=node,
            tail_500=tail_500,
            target_words=target_words,
            style_card=style_card,
            author_samples=author_samples,
        )
        stage_suffix = "development"
    else:
        # 蓄势段（高潮倒推工艺，带压抑约束）——规格 §4.2
        system_prompt, user_prompt = build_fuse_write_prompt(
            payload_text=payload_text,
            node=node,
            tail_500=tail_500,
            target_words=target_words,
            style_card=style_card,
            author_samples=author_samples,
        )
        stage_suffix = "buildup"

    prompts_history = {"system": system_prompt, "user": user_prompt, "zone": zone}
    last_fail_reason = ""

    for attempt in range(FUSE_RETRY_MAX + 1):
        current_user = user_prompt
        if attempt > 0 and last_fail_reason:
            current_user = user_prompt + f"\n\n## 上次写作的问题（请修正）\n{last_fail_reason}"

        try:
            if recorder is not None:
                async with recorder.record_call(
                    stage=f"detonation.fuse_write.{stage_suffix}.segment_{segment_index}.attempt_{attempt}",
                    model_slot="creative",
                ) as ctx:
                    result = await call_llm_with_usage(
                        system_prompt=system_prompt,
                        user_prompt=current_user,
                        model_type="creative",
                        temperature=FUSE_TEMPERATURE,
                        max_tokens=FUSE_MAX_TOKENS,
                    )
                    ctx.set_result(result)
            else:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=current_user,
                    model_type="creative",
                    temperature=FUSE_TEMPERATURE,
                    max_tokens=FUSE_MAX_TOKENS,
                )
        except Exception as e:
            logger.warning(f"[FuseWriter] segment_{segment_index}({zone}) LLM 调用失败 attempt={attempt}: {e}")
            prompts_history[f"attempt_{attempt}_error"] = str(e)[:200]
            if attempt >= FUSE_RETRY_MAX:
                # 重试耗尽：返回空段，标记降级
                return FuseSegment(
                    node_id=str(node.get("id", "")),
                    text="",
                    word_count=0,
                    prompts=prompts_history,
                )
            last_fail_reason = f"LLM 调用异常：{type(e).__name__}"
            continue

        text = (result.content or "").strip()
        if not text:
            last_fail_reason = "生成内容为空"
            if attempt >= FUSE_RETRY_MAX:
                return FuseSegment(
                    node_id=str(node.get("id", "")),
                    text="",
                    word_count=0,
                    prompts=prompts_history,
                )
            continue

        # fail-fast 校验（可选）
        if fail_fast_validator is not None:
            try:
                is_valid, fail_reason, _cats = await fail_fast_validator(text)
                if not is_valid:
                    last_fail_reason = fail_reason or "fail-fast 校验失败"
                    logger.info(
                        f"[FuseWriter] segment_{segment_index}({zone}) 校验失败 attempt={attempt}: {last_fail_reason[:80]}"
                    )
                    if attempt >= FUSE_RETRY_MAX:
                        # 重试耗尽：仍返回文本（带降级标记），由 workflow 层决策
                        logger.warning(
                            f"[FuseWriter] segment_{segment_index}({zone}) 校验重试耗尽，返回未通过文本"
                        )
                        word_count = len(text.replace(" ", ""))
                        return FuseSegment(
                            node_id=str(node.get("id", "")),
                            text=text,
                            word_count=word_count,
                            prompts=prompts_history,
                        )
                    continue
            except Exception as e:
                logger.warning(f"[FuseWriter] validator 异常，放行: {e}")

        # 成功
        word_count = len(text.replace(" ", ""))
        return FuseSegment(
            node_id=str(node.get("id", "")),
            text=text,
            word_count=word_count,
            prompts=prompts_history,
        )

    # 理论上不会到达
    return FuseSegment(
        node_id=str(node.get("id", "")),
        text="",
        word_count=0,
        prompts=prompts_history,
    )


def _allocate_word_targets(
    fuse_node_ids: List[Dict[str, Any]],
    target_total: int,
    payload_text: str,
) -> List[int]:
    """按节点 distance 与 assignment 加权分配字数。

    简单策略（Slice A）：
    - 等分 baseline = target_total / N
    - tighten/release_partial 段 +20%（情绪密度高，需要篇幅）
    - texture 段 -30%（闲笔呼吸段，短）
    - suppress 段 +10%（压抑需要铺垫空间）
    - payload 字数从章节卡 word_target 扣除（已在外部处理，这里只管铺垫总长）
    """
    n = len(fuse_node_ids)
    if n == 0:
        return []
    baseline = max(200, target_total // n)
    weights = []
    for node in fuse_node_ids:
        assignment = str(node.get("assignment", "tighten"))
        if assignment == "texture":
            weights.append(0.7)
        elif assignment == "suppress":
            weights.append(1.1)
        elif assignment == "release_partial":
            weights.append(1.2)
        else:  # tighten
            weights.append(1.2)
    # 归一化到 target_total
    total_weight = sum(weights)
    targets = [max(150, int(baseline * w * n / total_weight)) for w in weights]
    return targets


def _infer_total_words(chapter_card: Any, chapter: Any) -> int:
    """从章节卡或章节推断铺垫总字数。"""
    if chapter_card is not None:
        wt = getattr(chapter_card, "word_target", 0) or 0
        if wt > 0:
            # 章节总字数 - 爆发段（约 15-25%）= 铺垫总字数
            return int(wt * 0.80)
    return DEFAULT_TOTAL_FUSE_WORDS
