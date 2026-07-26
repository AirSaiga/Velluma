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
段级状态追踪器（State Tracker）—— Agent Loop 1：剧情状态卡。

职责：
- 每段写完用 1 次小 creative 调用抽取结构化"剧情状态卡"（谁在场/谁死亡或
  离场/各角色一句话状态/关键物品归属/剧情进展/POV/地点）
- 状态卡注入下一段 prompt（硬约束区块第 4 组件），让模型写新段时知道
  "世界现在是什么样"
- 代码侧校验新段与状态卡的矛盾（0 LLM 闸门）：死亡/离场角色不应再行动

设计意图：
- 真实故障：老周已死亡，后续段却"老周喊了一嗓子"；流光机甲内/外混乱。
  根因是段间连续性只靠 500 字 rolling_prefix——模型看不到 3 段前谁死了。
- 自纠正设计：每次抽取都输出"完整新卡"（上一张卡 + 刚写完的段 → 新卡），
  不做增量合并——单段抽取错误不会沿链累积。
- 降级哲学：任何异常/解析失败 → 保留旧卡继续，绝不阻塞主流程。
- 误报控制（宁漏勿误）：departed 角色名出现且所在段落无回忆标记词才报警
  （"他想起老周"不触发，"老周喊了一嗓子"触发）；误报代价是 1 次重写 +
  可能弃段，漏报由 Phase 7 一致性审计兜底。

业务场景：
- segment_writer.py Phase 4 正向流写作：段定稿后抽取（末段不抽），
  下一段硬约束注入 + 统一闸门校验

使用方式：
    state_card = SceneStateCard()
    ...写完一段...
    state_card = await extract_state_card(state_card, segment_text, registry, recorder, i)
    block = card_to_prompt_block(state_card)          # 注入下段 prompt
    violations = check_segment_against_card(new_text, state_card)  # 闸门

依赖项：
- workflows.adf.name_registry（角色名规范化：别名→规范名，表外名丢弃）
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.services.llm import call_llm_with_usage
from backend.services.observability.run_recorder import RunRecorder
from backend.services.prompts.adf_prompts import build_state_extraction_prompt
from backend.services.workflows.adf.name_registry import NameRegistry

logger = logging.getLogger(__name__)

# 状态卡 prompt 渲染上限（紧凑，防 token 膨胀）
MAX_CARD_BLOCK_CHARS = 250

# 回忆标记词：departed 角色名出现在含这些词的段落里 → 视为回忆/遗体相关描写，
# 不算"复活行动"（豁免，防误报）
RECALL_MARKERS = (
    "想起", "回忆", "梦到", "梦见", "尸体", "遗体",
    "遗像", "坟", "遗言", "临死", "生前",
)


@dataclass
class SceneStateCard:
    """剧情状态卡（截至某一段的世界状态快照）。"""

    pov: str = ""                          # 视角角色
    location: str = ""                     # 当前地点
    present: List[str] = field(default_factory=list)   # 在场角色（规范名）
    departed: List[str] = field(default_factory=list)  # 死亡/离场（下一段不应再行动）
    states: Dict[str, str] = field(default_factory=dict)  # 角色 → 一句话状态
    items: Dict[str, str] = field(default_factory=dict)   # 关键物品 → 持有者/位置
    progress: str = ""                     # 剧情进展一句话

    def is_empty(self) -> bool:
        """空卡（首段之前）：不渲染、不校验。"""
        return not (
            self.pov or self.location or self.present or self.departed
            or self.states or self.items or self.progress
        )


def _norm_name(name: Any, registry: Optional[NameRegistry]) -> Optional[str]:
    """角色名过 registry 规范化：别名→规范名；表外名丢弃（返回 None）。

    registry 为空（无注册名）时无法校验，原样保留（降级宽松）。
    """
    name = (str(name).strip() if name else "")
    if not name:
        return None
    if registry is None or not registry.all_surface_forms:
        return name
    if name in registry.all_surface_forms:
        return registry.alias_to_canonical.get(name, name)
    return None


def validate_card(
    data: Any,
    registry: Optional[NameRegistry] = None,
) -> Optional[SceneStateCard]:
    """把 LLM 输出的 JSON dict 校验为 SceneStateCard。

    容错规则：字段缺失/类型错 → 填充默认；角色名过 registry 规范化
    （别名→规范名，表外名丢弃）；data 不是 dict → None（调用方降级旧卡）。

    Args:
        data: LLM JSON 解析结果
        registry: 专名注册表（角色名规范化用）

    Returns:
        SceneStateCard；data 非 dict 时返回 None
    """
    if not isinstance(data, dict):
        return None

    def _str_field(key: str) -> str:
        val = data.get(key)
        return str(val).strip() if isinstance(val, (str, int, float)) else ""

    def _name_list(key: str) -> List[str]:
        val = data.get(key)
        if not isinstance(val, list):
            return []
        names = []
        for item in val:
            normed = _norm_name(item, registry)
            if normed and normed not in names:
                names.append(normed)
        return names

    def _name_state_dict(key: str, normalize_keys: bool) -> Dict[str, str]:
        val = data.get(key)
        if not isinstance(val, dict):
            return {}
        out: Dict[str, str] = {}
        for k, v in val.items():
            if not isinstance(v, str) or not v.strip():
                continue
            if normalize_keys:
                normed = _norm_name(k, registry)
                if normed is None:
                    continue
                out[normed] = v.strip()[:60]
            else:
                k = str(k).strip()
                if k:
                    out[k] = v.strip()[:60]
        return out

    return SceneStateCard(
        pov=_str_field("pov")[:30],
        location=_str_field("location")[:30],
        present=_name_list("present"),
        departed=_name_list("departed"),
        states=_name_state_dict("states", normalize_keys=True),
        items=_name_state_dict("items", normalize_keys=False),
        progress=_str_field("progress")[:80],
    )


def card_to_prompt_block(card: Optional[SceneStateCard]) -> str:
    """把状态卡渲染为紧凑 prompt 区块（≤250 字；空卡返回空串）。"""
    if card is None or card.is_empty():
        return ""
    lines = ["# 剧情状态卡（截至上一段，必须与之保持一致）"]
    if card.pov or card.location:
        parts = []
        if card.pov:
            parts.append(f"POV：{card.pov}")
        if card.location:
            parts.append(f"地点：{card.location}")
        lines.append("- " + "｜".join(parts))
    if card.present:
        lines.append(f"- 在场：{'、'.join(card.present[:8])}")
    if card.departed:
        lines.append(f"- 已死亡/离场（不应再行动或说话）：{'、'.join(card.departed[:8])}")
    if card.states:
        states_text = "；".join(f"{k}={v}" for k, v in list(card.states.items())[:6])
        lines.append(f"- 状态：{states_text}")
    if card.items:
        items_text = "；".join(f"{k}={v}" for k, v in list(card.items.items())[:4])
        lines.append(f"- 物品：{items_text}")
    if card.progress:
        lines.append(f"- 进展：{card.progress}")
    text = "\n".join(lines)
    if len(text) > MAX_CARD_BLOCK_CHARS:
        text = text[:MAX_CARD_BLOCK_CHARS] + "…"
    return text


def check_segment_against_card(
    segment_text: str,
    card: Optional[SceneStateCard],
) -> List[str]:
    """0 LLM 闸门：校验新段是否与状态卡矛盾，返回违规说明列表（空=通过）。

    规则：departed 角色名在新段出现，且出现的【段落】内无回忆标记词
    （想起/回忆/梦到/尸体/遗像等）→ "X 已死亡/离场，不应再行动或说话"。

    宁漏勿误：误报代价是 1 次重写 + 可能弃段，漏报由 Phase 7 兜底。
    """
    violations: List[str] = []
    if not segment_text or card is None or not card.departed:
        return violations
    paragraphs = [p for p in re.split(r"\n\n|\n", segment_text) if p.strip()]
    for name in card.departed:
        if not name:
            continue
        for para in paragraphs:
            if name not in para:
                continue
            if any(marker in para for marker in RECALL_MARKERS):
                continue  # 同段有回忆/遗体标记 → 豁免
            violations.append(f"{name} 已死亡/离场，不应再行动或说话")
            break  # 同名只报一次
    return violations


def _parse_json_object(content: str) -> Optional[dict]:
    """从 LLM 输出提取 JSON 对象（围栏/杂质容忍）。"""
    if not content:
        return None
    text = content.strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            pass
    return None


async def extract_state_card(
    prev_card: SceneStateCard,
    segment_text: str,
    registry: Optional[NameRegistry],
    recorder: Optional[RunRecorder],
    segment_index: int,
) -> SceneStateCard:
    """段定稿后抽取新状态卡（1×creative，自纠正：输出完整新卡）。

    降级哲学：任何异常/解析失败/校验失败 → 返回 prev_card（旧卡继续），
    绝不抛出、绝不阻塞主流程。

    Args:
        prev_card: 截至上一段的状态卡
        segment_text: 刚写完的本段正文
        registry: 专名注册表（角色名清单 + 规范化）
        recorder: RunRecorder（stage=adf.state_track.segment_{i+1}）
        segment_index: 刚写完的段序号（0-based）

    Returns:
        新状态卡；失败时返回 prev_card
    """
    if not segment_text or not segment_text.strip():
        return prev_card
    try:
        # 已知角色清单：角色规范名 + 别名（LLM 只许从这里选名字）
        known_characters: List[str] = []
        if registry is not None:
            known_characters = sorted(registry.character_names)
            known_characters += sorted(
                alias for alias, canon in registry.alias_to_canonical.items()
                if canon in registry.character_names
            )

        system_prompt, user_prompt = build_state_extraction_prompt(
            prev_card_text=card_to_prompt_block(prev_card) or "（首张卡，无历史状态）",
            segment_text=segment_text,
            known_characters="、".join(known_characters) or "（无角色清单）",
        )
        if recorder is not None:
            async with recorder.record_call(
                stage=f"adf.state_track.segment_{segment_index + 1}",
                model_slot="creative",
            ) as call_ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="creative",
                    temperature=0.2,
                    max_tokens=400,
                    response_format={"type": "json_object"},
                )
                call_ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=0.2,
                max_tokens=400,
                response_format={"type": "json_object"},
            )
        data = _parse_json_object(result.content or "")
        card = validate_card(data, registry)
        if card is None:
            logger.warning(
                f"[ADF] 第 {segment_index + 1} 段状态卡校验失败，保留旧卡"
            )
            return prev_card
        return card
    except Exception as e:
        logger.warning(f"[ADF] 第 {segment_index + 1} 段状态卡抽取失败，保留旧卡: {e}")
        return prev_card
