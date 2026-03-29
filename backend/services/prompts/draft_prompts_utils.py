from typing import Optional, List

from backend.models import Book


def _normalize_text(value, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _normalize_text_list(value) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _render_boundary_constraints(entry_state: str, exit_state: str, red_lines: list[str]) -> str:
    red_line_text = "；".join(red_lines) if red_lines else "无"
    return (
        "## 【边界约束与剧情完整性 - 最高优先级】\n"
        "1. 本区块优先级高于其他所有写作建议。\n"
        f"2. 切入状态（entry_state）：{entry_state}\n"
        f"3. 目标收束状态（exit_state）：{exit_state}\n"
        f"4. 绝对禁忌（red_lines）：{red_line_text}\n"
        "5. 请确保本节拍的核心冲突和情感铺垫得到充分演绎，再自然收束于 exit_state。切勿为了赶进度而在高潮处突然中断！"
    )


def _render_scene_intent_prompt(scene_intent_data) -> Optional[str]:
    if isinstance(scene_intent_data, dict):
        constraints = _normalize_text_list(scene_intent_data.get("constraints"))
        return (
            "## SceneIntent\n"
            f"标签：{_normalize_text(scene_intent_data.get('intent_label'), '推进剧情')}\n"
            f"目标：{_normalize_text(scene_intent_data.get('goal'), '推进剧情')}\n"
            f"风险：{_normalize_text(scene_intent_data.get('stakes'), '无')}\n"
            f"约束：{', '.join(constraints) if constraints else '无'}"
        )
    if isinstance(scene_intent_data, list) and scene_intent_data:
        latest_intent = scene_intent_data[-1]
        if isinstance(latest_intent, dict):
            constraints = _normalize_text_list(latest_intent.get("constraints"))
            return (
                "## SceneIntent\n"
                f"标签：{_normalize_text(latest_intent.get('intent_label'), '推进剧情')}\n"
                f"目标：{_normalize_text(latest_intent.get('goal'), '推进剧情')}\n"
                f"风险：{_normalize_text(latest_intent.get('stakes'), '无')}\n"
                f"约束：{', '.join(constraints) if constraints else '无'}"
            )
        normalized_latest_intent = _normalize_text(latest_intent)
        return f"## SceneIntent\n{normalized_latest_intent}" if normalized_latest_intent else None
    normalized_scene_intent = _normalize_text(scene_intent_data)
    return f"## SceneIntent\n{normalized_scene_intent}" if normalized_scene_intent else None


def _render_style_control_prompt(book: Book) -> Optional[str]:
    golden_snippets = getattr(book, 'golden_snippets', None) or []
    style_blacklist = getattr(book, 'style_blacklist', None) or []

    if isinstance(golden_snippets, list):
        golden_snippets = [s for s in golden_snippets if s]
    else:
        golden_snippets = []

    if isinstance(style_blacklist, list):
        style_blacklist = [s for s in style_blacklist if s]
    else:
        style_blacklist = []

    if not golden_snippets and not style_blacklist:
        return None

    sections = []

    if golden_snippets:
        snippets_text = "\n\n".join(golden_snippets)
        sections.append(
            "### [表情] 必须模仿的文风基准（黄金锚点）：\n"
            "请仔细分析以下片段的**句式长短、信息密度、克制的情绪张力以及修辞手法**。\n"
            "你接下来的扩写，必须在咬字和语感上无限逼近这段文字的质感：\n"
            f"{snippets_text}"
        )

    if style_blacklist:
        blacklist_text = "、".join(style_blacklist)
        sections.append(
            "### [表情] 绝对禁止触发的黑名单词库（通电铁丝网）：\n"
            "由于 LLM 存在滥用烂俗网文词汇的倾向，以下词汇/句式已被原作者拉入黑名单。\n"
            "**若在生成文本中触发以下任意一词，系统将判定生成彻底失败：**\n"
            f"{blacklist_text}"
        )

    if sections:
        return (
            "[特级文风走廊协议：防御大模型均值回归]\n"
            "为了防止文风漂移，你必须绝对服从以下\"一正一反\"的文风控制准则：\n\n"
            + "\n\n".join(sections)
        )
    return None


def _format_entity_spatial_ledger(ledger: dict) -> str:
    if not ledger:
        return ""
    lines = []
    for char_name, state in ledger.items():
        parts = [f"【{char_name}】"]
        if state.is_in_vehicle and state.vehicle_or_mech_name:
            parts.append(f"当前处于【{state.vehicle_or_mech_name}】内部（封闭状态）")
        elif state.is_in_vehicle:
            parts.append("当前处于载具/机甲内部（封闭状态）")
        else:
            parts.append("当前为肉身状态")
        if state.equipped_weapons:
            parts.append(f"装备：{', '.join(state.equipped_weapons)}")
        if state.movement_constraints and state.movement_constraints != "无特殊限制":
            parts.append(f"⚠ 限制：{state.movement_constraints}")
        lines.append(" → ".join(parts))
    return "\n".join(lines)
