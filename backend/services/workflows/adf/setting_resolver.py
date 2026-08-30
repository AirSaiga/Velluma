# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
V3.5 设定解析器（Setting Resolver）—— 场景触发式设定召回。

职责：
- 从用户章级显式指定的角色/地点/资产（ChapterEntity/ChapterMapLocation/ChapterAsset）
  召回每项的结构化设定文本
- 召回在场角色之间的关系网
- 拼装为 SceneSetting 文本块，供 forward_flow_writer 注入 prompt

设计意图（方向 A：场景触发式设定召回）：
- 模仿人类作家的"场景触发联想"——只调取本章相关的设定，不灌入全书全量
- 零额外 LLM 调用（纯代码 + DB 查询已加载的 ORM 对象）
- 按需召回：用户在侧边栏勾选了哪些角色/地点/资产，就召回哪些
- 可降级：任何设定缺失都不阻塞生成

设定堆砌防御（反 info-dump）：
- 召回的设定文本不直接写进正文，而是作为"角色行为/环境描写的背景知识"
- prompt 注入时附带明确指令：设定影响行为选择，但不许复述设定文本

业务场景：
- ADFWorkflow Phase 4 正向流写作：每段 prompt 注入 # 场景设定 区块
- ADFWorkflow Phase 2 远端锚设计：注入角色设定辅助锚点设计
"""

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# 设定文本截断上限（每项），防 token 爆炸
MAX_STATIC_PROMPT_CHARS = 300       # 角色永恒设定
MAX_DYNAMIC_STATE_CHARS = 150       # 角色瞬时状态
MAX_LOCATION_DESC_CHARS = 200       # 地点描述
MAX_LOCATION_STATE_CHARS = 100      # 地点当前状态
MAX_ASSET_DESC_CHARS = 200          # 资产描述
MAX_ASSET_STATE_CHARS = 100         # 资产当前状态
MAX_RELATIONSHIP_PROMPT_CHARS = 150 # 关系互动提示
MAX_WORLDVIEW_CHARS = 500           # 世界观设定总文本上限（与双轨 ContextEngine 的 400 对齐，略宽松）
MAX_GLOBAL_SYS_PROMPT_CHARS = 300   # global_sys_prompt 行为基线上限
MAX_CHARACTERS = 8                  # 最多召回角色数
MAX_LOCATIONS = 5                   # 最多召回地点数
MAX_ASSETS = 5                      # 最多召回资产数
MAX_RELATIONSHIPS = 10             # 最多召回关系数


def _get_field(obj: Any, attr: str, dict_key: str = None) -> Any:
    """从 ORM 对象或 dict 安全取字段。"""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(dict_key or attr)
    return getattr(obj, attr, None)


def _truncate(text: Any, max_chars: int) -> str:
    """截断文本到指定长度，超长加省略号。"""
    if not text:
        return ""
    text = str(text).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


def resolve_characters(entities: List[Any]) -> List[dict]:
    """召回本章角色的结构化设定。

    每个 entity 关联一个 character，取 name + static_prompt + dynamic_state。
    修复 V3.2 bug：Phase 4 正文写作丢失 static_prompt（只有 dynamic_state）。

    Returns:
        角色设定列表，每项 {name, static_prompt, dynamic_state, aliases}
    """
    result = []
    for ent in (entities or [])[:MAX_CHARACTERS]:
        char = _get_field(ent, "character")
        if char is None:
            continue
        name = _get_field(char, "name") or "未命名"
        static = _truncate(_get_field(char, "static_prompt"), MAX_STATIC_PROMPT_CHARS)
        dynamic = _truncate(_get_field(char, "dynamic_state"), MAX_DYNAMIC_STATE_CHARS)
        result.append({
            "name": name,
            "static_prompt": static,
            "dynamic_state": dynamic,
            "aliases": _get_field(char, "aliases") or [],
        })
    return result


def resolve_locations(chapter_locations: List[Any]) -> List[dict]:
    """召回本章地点的结构化设定。

    chapter_locations 是 ChapterMapLocation 关联表条目，每条关联一个 MapLocation。
    取 name + description + current_state。

    Returns:
        地点设定列表，每项 {name, description, current_state, aliases}
    """
    result = []
    for cl in (chapter_locations or [])[:MAX_LOCATIONS]:
        try:
            # ChapterMapLocation 有 .location 关联，也可能直接是 MapLocation
            loc = _get_field(cl, "location") or cl
            if loc is None:
                continue
            name = _get_field(loc, "name") or "未命名地点"
            desc = _truncate(_get_field(loc, "description"), MAX_LOCATION_DESC_CHARS)
            state = _truncate(_get_field(loc, "current_state"), MAX_LOCATION_STATE_CHARS)
            result.append({
                "name": name,
                "description": desc,
                "current_state": state,
                "aliases": _get_field(loc, "aliases") or [],
            })
        except Exception:
            # 防御：lazy load 触发 MissingGreenlet 时跳过该项，不阻塞生成
            logger.warning(f"[SettingResolver] 地点设定解析失败，跳过: {type(cl).__name__}")
    return result


def resolve_assets(chapter_assets: List[Any]) -> List[dict]:
    """召回本章资产的结构化设定。

    chapter_assets 是 ChapterAsset 关联表条目，每条关联一个 Asset。
    取 name + static_description + current_state。

    Returns:
        资产设定列表，每项 {name, description, current_state, aliases}
    """
    result = []
    for ca in (chapter_assets or [])[:MAX_ASSETS]:
        asset = _get_field(ca, "asset") or ca
        if asset is None:
            continue
        name = _get_field(asset, "name") or "未命名资产"
        desc = _truncate(_get_field(asset, "static_description"), MAX_ASSET_DESC_CHARS)
        state = _truncate(_get_field(asset, "current_state"), MAX_ASSET_STATE_CHARS)
        result.append({
            "name": name,
            "description": desc,
            "current_state": state,
            "aliases": _get_field(asset, "aliases") or [],
        })
    return result


def resolve_relationships(
    relationships: List[Any],
    characters: List[dict],
) -> List[dict]:
    """召回在场角色之间的关系网。

    只召回 source/target 都在 characters 列表中的关系（在场角色之间的关系）。
    取 relation_type + affinity_score + interaction_prompt。

    ⚠ is_public=False 的关系（隐藏关系）不进返回列表——直接喂给生成会把
    秘密关系泄露到正文。隐藏关系走 resolve_hidden_constraints 的否定约束通道。

    Args:
        relationships: 全部角色关系（CharacterRelationship ORM 列表）
        characters: resolve_characters 的返回值（本章在场角色）

    Returns:
        关系列表，每项 {source, target, relation_type, affinity, interaction}
    """
    if not relationships or not characters:
        return []

    # 构建在场角色名→id 映射（用于匹配关系的 source/target）
    char_names = {c["name"] for c in characters}
    char_ids = set()
    # 从 entities 反查 id（relationships 用的是 char_id）
    # 这里用名称匹配作为兜底（relationships 的 source_character/target_character 可能为 None/lazy）
    result = []
    for rel in relationships[:MAX_RELATIONSHIPS * 2]:  # 多取一些再过滤
        try:
            # 隐藏关系不召回进 prompt（泄露防护）；is_public 缺失（None）视为公开
            if _get_field(rel, "is_public") is False:
                continue
            source_char = _get_field(rel, "source_character")
            target_char = _get_field(rel, "target_character")
            source_name = _get_field(source_char, "name") if source_char else None
            target_name = _get_field(target_char, "name") if target_char else None

            # 只保留在场角色之间的关系
            if source_name and target_name and source_name in char_names and target_name in char_names:
                relation_type = _get_field(rel, "relation_type") or "未知关系"
                affinity = _get_field(rel, "affinity_score")
                interaction = _truncate(
                    _get_field(rel, "interaction_prompt"), MAX_RELATIONSHIP_PROMPT_CHARS
                )
                result.append({
                    "source": source_name,
                    "target": target_name,
                    "relation_type": relation_type,
                    "affinity": affinity,
                    "interaction": interaction,
                })
        except Exception:
            # 防御：lazy load 触发 MissingGreenlet 时跳过该关系，不阻塞生成
            logger.warning(f"[SettingResolver] 关系设定解析失败，跳过: {type(rel).__name__}")
        if len(result) >= MAX_RELATIONSHIPS:
            break
    return result


def resolve_hidden_constraints(
    relationships: List[Any],
    characters: List[dict],
) -> List[str]:
    """把 is_public=False 的隐藏关系转为否定约束行（知识边界通道）。

    设计意图：
    - 隐藏关系（如"白霆与林尘是兄弟，不为外人所知"）不能直接喂给生成——
      LLM 看到"他们是兄弟"就会让角色表现出来，秘密关系就此泄露。
    - 正确做法是只给否定约束："这段关系不为外人所知，其他角色不得表现出知情"。
      LLM 不知道关系细节（除非该角色本人），但知道"不许点破"。

    Args:
        relationships: 全部角色关系（CharacterRelationship ORM 列表）
        characters: resolve_characters 的返回值（本章在场角色）

    Returns:
        否定约束行列表；无隐藏关系时返回空列表
    """
    if not relationships or not characters:
        return []

    char_names = {c["name"] for c in characters}
    constraints: List[str] = []
    for rel in relationships[:MAX_RELATIONSHIPS * 2]:
        try:
            # 只处理明确标记为隐藏的关系（None 视为公开，跳过）
            if _get_field(rel, "is_public") is not False:
                continue
            source_char = _get_field(rel, "source_character")
            target_char = _get_field(rel, "target_character")
            source_name = _get_field(source_char, "name") if source_char else None
            target_name = _get_field(target_char, "name") if target_char else None
            # 两端都在场才需要约束（不在场的关系本章不会被写出）
            if source_name and target_name and source_name in char_names and target_name in char_names:
                relation_type = _get_field(rel, "relation_type") or "未知关系"
                constraints.append(
                    f"{source_name}与{target_name}的关系（{relation_type}）不为外人所知："
                    f"其他角色不得表现出知情，正文不得直接点破"
                )
        except Exception:
            logger.warning(f"[SettingResolver] 隐藏关系约束解析失败，跳过: {type(rel).__name__}")
    return constraints


def build_scene_setting_text(
    entities: List[Any],
    chapter_locations: List[Any],
    chapter_assets: List[Any],
    relationships: List[Any],
) -> str:
    """构建 # 场景设定 prompt 文本块（V3.5 核心输出）。

    把用户章级指定的角色/地点/资产/关系召回为结构化文本，
    供 forward_flow_writer 注入 system prompt。

    设计原则：
    - 只召回用户指定的（不是全书全量）→ token 经济
    - 附带设定堆砌防御指令 → 防止 AI 把设定说明书式写进正文
    - 全部缺失时返回空串（不阻塞，prompt 里不出现该区块）

    Args:
        entities: ChapterEntity 列表（本章关联角色）
        chapter_locations: ChapterMapLocation 列表（本章关联地点）
        chapter_assets: ChapterAsset 列表（本章关联资产）
        relationships: CharacterRelationship 列表（角色关系网）

    Returns:
        场景设定文本块；全部为空时返回空串

    使用方式（forward_flow_writer）：
        scene_text = build_scene_setting_text(entities, locations, assets, relationships)
        if scene_text:
            system_prompt = f"\\n# 场景设定\\n\\n{scene_text}\\n\\n{system_prompt}"
    """
    characters = resolve_characters(entities)
    locations = resolve_locations(chapter_locations)
    assets = resolve_assets(chapter_assets)
    rels = resolve_relationships(relationships, characters)
    hidden_constraints = resolve_hidden_constraints(relationships, characters)

    if not characters and not locations and not assets:
        return ""

    parts = []

    # 角色设定（永恒设定 + 瞬时状态）
    if characters:
        parts.append("## 本章角色（永恒设定 + 此刻状态）")
        for c in characters:
            line = f"- **{c['name']}**"
            if c["static_prompt"]:
                line += f"：{c['static_prompt']}"
            if c["dynamic_state"]:
                line += f"（此刻：{c['dynamic_state']}）"
            parts.append(line)

    # 地点设定
    if locations:
        parts.append("\n## 本章场景地点")
        for loc in locations:
            line = f"- **{loc['name']}**"
            if loc["description"]:
                line += f"：{loc['description']}"
            if loc["current_state"]:
                line += f"（当前状态：{loc['current_state']}）"
            parts.append(line)

    # 资产设定
    if assets:
        parts.append("\n## 本章关键资产")
        for a in assets:
            line = f"- **{a['name']}**"
            if a["description"]:
                line += f"：{a['description']}"
            if a["current_state"]:
                line += f"（当前状态：{a['current_state']}）"
            parts.append(line)

    # 角色关系网
    if rels:
        parts.append("\n## 在场角色关系")
        for r in rels:
            affinity_str = ""
            if r["affinity"] is not None:
                affinity_str = f"（亲和度 {r['affinity']}）"
            line = f"- {r['source']} → {r['target']}：{r['relation_type']}{affinity_str}"
            if r["interaction"]:
                line += f"｜{r['interaction']}"
            parts.append(line)

    # 隐藏信息约束（is_public=False 关系的否定约束，防泄露）
    if hidden_constraints:
        parts.append("\n## 隐藏信息约束（绝不许泄露）")
        for c in hidden_constraints:
            parts.append(f"- {c}")

    # 设定堆砌防御指令（反 info-dump）
    parts.append(
        "\n--- ⚠ 设定使用约束：以上是你的背景知识，不是要写进正文的说明文。"
        "让设定影响角色的行为选择、对话语气、环境感知，但**绝不许直接复述设定文本**。"
        "读者应该通过角色的行动『自然感受到』这些设定，而不是读到设定说明书。---"
    )

    return "\n".join(parts)


def build_worldview_text(book: Any) -> str:
    """构建世界观设定 prompt 文本块。

    从 book 对象读取两个字段：
    - global_sys_prompt：LLM 行为基线（如"你是专写硬核科幻的作家"），作开头角色定位
    - worldview_settings：JSONB {version:1, items:[{title, content}]}，转可读列表

    与双轨 ContextEngine._build_p0 的区别（改进点）：
    - 双轨直接 json.dumps 原始 JSON 注入（LLM 看到 {version:1,...} 结构化数据）
    - 本函数把 items 转成 "- 标题：内容" 的自然语言列表，LLM 更易理解
    - 总文本截断到 MAX_WORLDVIEW_CHARS，防 token 爆炸

    Args:
        book: Book ORM 对象（读 global_sys_prompt / worldview_settings）

    Returns:
        世界观文本块；全空时返回空串

    使用方式（forward_flow_writer，在 Canon prepend 之前）：
        worldview_text = build_worldview_text(book)
        if worldview_text:
            system_prompt = f"# 世界观设定\\n\\n{worldview_text}\\n\\n{system_prompt}"
    """
    if book is None:
        return ""

    parts = []

    # 1. global_sys_prompt：LLLM 行为基线（角色定位）
    global_sys = (getattr(book, "global_sys_prompt", "") or "").strip()
    if global_sys:
        parts.append(_truncate(global_sys, MAX_GLOBAL_SYS_PROMPT_CHARS))

    # 2. worldview_settings：结构化世界观 → 自然语言列表
    worldview = getattr(book, "worldview_settings", None)
    if worldview:
        worldview_lines = _worldview_to_lines(worldview)
        if worldview_lines:
            worldview_body = "\n".join(worldview_lines)
            parts.append(worldview_body)

    if not parts:
        return ""

    text = "\n\n".join(parts)
    if len(text) > MAX_WORLDVIEW_CHARS:
        text = text[:MAX_WORLDVIEW_CHARS] + "…"

    # 设定堆砌防御
    text += (
        "\n\n--- 以上世界观是你的创作背景，影响世界规则、物理法则、社会制度的描写。"
        "不许在正文里直接复述设定文本，让读者通过故事自然感受到。---"
    )
    return text


def _worldview_to_lines(worldview: Any) -> List[str]:
    """把 worldview_settings（JSONB）转为可读文本行列表。

    支持的结构：
    - {version:1, items:[{title, content}]} → 标准结构化格式
    - {key: value, ...} → 旧格式，key 当标题
    - str → 当作单条无标题内容
    """
    if not worldview:
        return []

    # 字符串：可能是 JSON 或纯文本
    if isinstance(worldview, str):
        s = worldview.strip()
        if not s:
            return []
        # 尝试 JSON 解析
        try:
            import json
            return _worldview_to_lines(json.loads(s))
        except (json.JSONDecodeError, ValueError):
            return [f"- {s[:MAX_WORLDVIEW_CHARS]}"]

    # 标准结构：{version:1, items:[...]}
    if isinstance(worldview, dict):
        items = worldview.get("items")
        if isinstance(items, list) and items:
            lines = []
            for item in items[:12]:  # 最多 12 条，防过长
                if not isinstance(item, dict):
                    continue
                title = (item.get("title") or "").strip()
                content = (item.get("content") or "").strip()
                if not content:
                    continue
                content = _truncate(content, 80)  # 每条截断
                if title:
                    lines.append(f"- {title}：{content}")
                else:
                    lines.append(f"- {content}")
            return lines

        # 旧格式：{key: value}
        lines = []
        for k, v in list(worldview.items())[:12]:
            if k in ("version",):
                continue
            val = str(v).strip() if v else ""
            if not val:
                continue
            lines.append(f"- {k}：{_truncate(val, 80)}")
        return lines

    return []
