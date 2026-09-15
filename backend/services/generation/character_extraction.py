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
智能人物提取与关系推断服务

职责：
- 从章节内容中提取出现的人物（包括已有角色和新角色）
- 自动创建新角色卡片
- 推断人物之间的关系
- 自动建立章节与角色的关联

业务场景：
- 章节发布时自动识别所有涉及的人物
- 新人物首次登场时自动创建角色档案
- 根据互动内容自动更新角色关系

设计原则：
- 与现有发布流程解耦，可独立调用
- 提供清晰的提取结果和降级策略
- 支持人工审核和自动模式
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any, Set
from uuid import UUID

from backend.services.utils.logging import ServiceLogger, LOG_PREFIX_WORKFLOW
from backend.services.utils.timeout import TimeoutManager

logger = logging.getLogger(__name__)
svc_logger = ServiceLogger(logger, LOG_PREFIX_WORKFLOW)
_timeout_manager = TimeoutManager()


def _log_to_file(message: str):
    """将调试信息写入日志文件"""
    try:
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "character_extraction_debug.log")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass  # 如果日志写入失败，不要影响主流程


@dataclass
class ExtractedCharacter:
    """提取出的人物信息"""
    name: str
    is_new: bool  # True = 新人物, False = 已有角色
    existing_id: Optional[str] = None  # 如果是已有角色，记录ID
    description: str = ""  # 人物描述/特征
    role_type: str = ""  # 角色类型: protagonist, antagonist, supporting, minor
    aliases: List[str] = field(default_factory=list)  # 别名/称呼
    first_appearance: bool = False  # 是否首次登场
    importance_level: int = 3  # 重要性等级 1-10


@dataclass
class InferredRelationship:
    """推断出的人物关系"""
    source_name: str  # 关系发起方
    target_name: str  # 关系目标方
    relation_type: str  # 关系类型
    description: str = ""  # 关系描述
    affinity_score: int = 0  # 亲密度 -100~100
    interaction_prompt: str = ""  # 互动提示
    is_new: bool = True  # 是否是新关系
    existing_id: Optional[str] = None  # 已有关系的ID


@dataclass
class CharacterExtractionResult:
    """人物提取完整结果"""
    extracted_characters: List[ExtractedCharacter] = field(default_factory=list)
    new_characters: List[ExtractedCharacter] = field(default_factory=list)
    existing_characters: List[ExtractedCharacter] = field(default_factory=list)
    inferred_relationships: List[InferredRelationship] = field(default_factory=list)
    chapter_entity_links: List[str] = field(default_factory=list)  # 需要关联的角色ID列表
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式用于API响应"""
        return {
            "extracted_characters": [
                {
                    "name": c.name,
                    "is_new": c.is_new,
                    "existing_id": c.existing_id,
                    "description": c.description,
                    "role_type": c.role_type,
                    "aliases": c.aliases,
                    "first_appearance": c.first_appearance,
                    "importance_level": c.importance_level,
                }
                for c in self.extracted_characters
            ],
            "new_characters_count": len(self.new_characters),
            "existing_characters_count": len(self.existing_characters),
            "inferred_relationships": [
                {
                    "source_name": r.source_name,
                    "target_name": r.target_name,
                    "relation_type": r.relation_type,
                    "description": r.description,
                    "affinity_score": r.affinity_score,
                    "is_new": r.is_new,
                }
                for r in self.inferred_relationships
            ],
            "chapter_entity_links": self.chapter_entity_links,
        }


async def extract_characters_from_chapter(
    chapter_content: str,
    existing_characters: List[Any],
    timeout: int = 180,
) -> CharacterExtractionResult:
    """
    从章节内容中提取人物信息
    
    职责：使用LLM分析章节内容，识别所有出现的人物，区分新旧角色
    
    Args:
        chapter_content: 章节正文内容
        existing_characters: 书籍中已有的角色列表
        timeout: 超时时间
        
    Returns:
        CharacterExtractionResult 包含提取的人物和关系
    """
    _log_to_file(f"extract_characters_from_chapter called, content length: {len(chapter_content) if chapter_content else 0}")
    
    if not chapter_content or not chapter_content.strip():
        svc_logger.warning("Empty chapter content provided")
        _log_to_file("Empty chapter content, returning empty result")
        return CharacterExtractionResult()
    
    # 构建已有角色名称映射（用于匹配）
    existing_char_map = _build_character_name_map(existing_characters)
    _log_to_file(f"Existing characters: {len(existing_characters)}, names: {list(existing_char_map.keys())[:5]}")
    svc_logger.debug(
        "Starting character extraction",
        content_length=len(chapter_content),
        existing_chars_count=len(existing_characters),
        existing_names=list(existing_char_map.keys())[:10],  # 只记录前10个避免日志过长
    )
    
    try:
        # 调用LLM提取人物
        extraction_data = await _call_llm_for_extraction(
            chapter_content=chapter_content,
            existing_character_names=list(existing_char_map.keys()),
            timeout=timeout,
        )
        
        if not extraction_data:
            svc_logger.warning("Character extraction returned no data")
            return CharacterExtractionResult()
        
        svc_logger.debug("LLM extraction raw data", data=extraction_data)
        
        # 解析提取结果
        result = _parse_extraction_result(
            extraction_data=extraction_data,
            existing_char_map=existing_char_map,
        )
        
        svc_logger.info(
            "Character extraction completed",
            total_chars=len(result.extracted_characters),
            new_chars=len(result.new_characters),
            existing_chars=len(result.existing_characters),
            relationships=len(result.inferred_relationships),
            new_char_names=[c.name for c in result.new_characters],
        )
        
        _log_to_file(f"Final extraction result: {len(result.extracted_characters)} total, {len(result.new_characters)} new, {len(result.existing_characters)} existing")
        
        return result
        
    except Exception as e:
        _log_to_file(f"Character extraction failed: {e}")
        svc_logger.error("Character extraction failed", error=str(e), exc_info=True)
        return CharacterExtractionResult()


def _normalize_importance_level(role_type: str, importance_level: int) -> int:
    """
    根据 role_type 标准化 importance_level
    """
    # 直接根据 role_type 映射到前端的 1-4 等级
    role_to_level = {
        "protagonist": 4,   # 主角
        "antagonist": 3,    # 核心
        "supporting": 2,    # 重要
        "minor": 1,         # 普通
    }
    
    result = role_to_level.get(role_type, 2)
    _log_to_file(f"_normalize_importance_level: role_type={role_type}, input_level={importance_level}, output_level={result}")
    return result


def _build_character_name_map(characters: List[Any]) -> Dict[str, Any]:
    """
    构建角色名称映射表，支持多别名匹配
    
    返回: {名称/别名(小写): 角色对象}
    """
    name_map = {}
    for char in characters:
        if not char:
            continue
        # 主名称
        if char.name:
            name_map[char.name.lower()] = char
            # 常见变体（去除称号等）
            simplified = _simplify_name(char.name)
            if simplified and simplified != char.name.lower():
                name_map[simplified] = char
        
        # 别名
        if hasattr(char, 'aliases') and char.aliases:
            for alias in char.aliases:
                if alias:
                    name_map[alias.lower()] = char
                    simplified = _simplify_name(alias)
                    if simplified and simplified != alias.lower():
                        name_map[simplified] = char
    
    return name_map


def _simplify_name(name: str) -> str:
    """
    简化名称用于模糊匹配
    - 去除常见称号（先生、小姐、大人等）
    - 去除标点
    """
    import re
    
    titles = ['先生', '小姐', '女士', '大人', '陛下', '殿下', '阁下', '师傅', '师尊', 
              '长老', '掌门', '宗主', '家主', '老爷', '夫人', '少爷', '小姐']
    
    simplified = name.lower().strip()
    
    # 去除称号
    for title in titles:
        simplified = simplified.replace(title, '')
    
    # 去除标点和空格
    import string
    # 定义要去除的标点符号（使用列表避免转义问题）
    punctuations = ['·', '•', '.', '"', "'", '"', '"', ''', ''', '(', ')', '（', '）', '【', '】', '[', ']'] + list(string.whitespace)
    for p in punctuations:
        simplified = simplified.replace(p, '')
    
    return simplified


async def _call_llm_for_extraction(
    chapter_content: str,
    existing_character_names: List[str],
    timeout: int,
) -> Optional[Dict[str, Any]]:
    """
    调用LLM进行人物提取
    """
    from backend.services.llm import call_llm
    from backend.services.prompts.character_extraction import (
        build_character_extraction_prompt,
        build_character_extraction_system_prompt,
    )
    
    user_prompt = build_character_extraction_prompt(
        chapter_content=chapter_content[:8000],  # 限制长度避免token超限
        existing_character_names=existing_character_names,
    )
    
    system_prompt = build_character_extraction_system_prompt()
    
    try:
        _log_to_file("Calling LLM for extraction, model=(default)")
        svc_logger.info("Calling LLM for character extraction", content_length=len(chapter_content))
        response = await _timeout_manager.call_with_timeout(
            call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                # 角色提取是结构化分析任务（2026-09-15 槽位显式化）
                model_type="reasoning",
                temperature=0.3,  # 低温度保证稳定性
            ),
            operation_type="character_extraction",
            custom_timeout=timeout,
        )
        
        _log_to_file(f"LLM response received, length={len(response) if response else 0}")
        _log_to_file(f"LLM raw response preview: {response[:500] if response else 'EMPTY'}")
        svc_logger.info("LLM response received", response_length=len(response) if response else 0)
        
        # 解析JSON响应
        import json
        # 提取JSON部分（处理可能的markdown代码块）
        text = response.strip()
        original_text = text  # 保存原始响应用于调试
        
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        
        svc_logger.debug("Parsed JSON text", text_preview=text[:200])
        
        data = json.loads(text)
        char_count = len(data.get("characters", []))
        _log_to_file(f"JSON parsing successful, characters found: {char_count}")
        _log_to_file(f"Parsed data keys: {list(data.keys())}")
        _log_to_file(f"Characters data: {data.get('characters', [])[:2]}")  # 只记录前2个
        svc_logger.info("JSON parsing successful", characters_count=char_count)
        return data
        
    except asyncio.TimeoutError:
        _log_to_file("LLM call timed out")
        svc_logger.warning("Character extraction LLM call timed out")
        return None
    except json.JSONDecodeError as e:
        _log_to_file(f"JSON parse error: {e}")
        svc_logger.error("Failed to parse extraction response", error=str(e), response_preview=original_text[:500] if 'original_text' in locals() else None)
        return None
    except Exception as e:
        _log_to_file(f"LLM call failed: {e}")
        svc_logger.error("LLM extraction call failed", error=str(e), exc_info=True)
        return None


def _parse_extraction_result(
    extraction_data: Dict[str, Any],
    existing_char_map: Dict[str, Any],
) -> CharacterExtractionResult:
    """
    解析LLM提取结果，区分新旧角色
    """
    result = CharacterExtractionResult()
    processed_names: Set[str] = set()  # 避免重复
    
    # 解析人物
    characters_data = extraction_data.get("characters", [])
    _log_to_file(f"Parsing {len(characters_data)} characters from LLM response")
    svc_logger.debug(f"Parsing {len(characters_data)} characters from LLM response")
    
    for char_data in characters_data:
        name = char_data.get("name", "").strip()
        if not name or name.lower() in processed_names:
            continue
        
        processed_names.add(name.lower())
        
        # 检查是否已有（支持模糊匹配）
        existing_char = _find_existing_character(name, existing_char_map)
        
        # LLM 可能返回字符串 "true"/"false" 或布尔值 True/False
        is_new_raw = char_data.get("is_new", True)
        if isinstance(is_new_raw, str):
            is_new = is_new_raw.lower() == "true"
        else:
            is_new = bool(is_new_raw)
        
        # 如果LLM认为不是新角色，但系统中找不到，仍然视为新角色
        if not is_new and existing_char is None:
            svc_logger.warning(
                "LLM marked character as existing but not found in database",
                name=name,
            )
            is_new = True
        # 如果LLM认为是新角色，但系统中已存在，以系统为准
        elif is_new and existing_char is not None:
            svc_logger.debug(
                "LLM marked character as new but found in database",
                name=name,
                existing_id=str(existing_char.id),
            )
            is_new = False
        
        # 获取 role_type 和 importance_level，并进行校验修正
        role_type = char_data.get("role_type", "supporting")
        raw_importance_level = char_data.get("importance_level", 3)
        
        # 确保 importance_level 是整数
        try:
            importance_level = int(raw_importance_level)
        except (ValueError, TypeError):
            importance_level = 3
        
        # 根据 role_type 修正 importance_level，确保一致性
        normalized_level = _normalize_importance_level(role_type, importance_level)
        importance_level = normalized_level
        
        _log_to_file(f"Character '{name}': raw_role_type={role_type}, raw_level={raw_importance_level}, final_level={importance_level}")
        
        if not is_new and existing_char:
            # 已有角色 - 使用本章分析的重要性等级，而不是数据库旧值
            # 因为角色在不同章节可能有不同定位
            extracted = ExtractedCharacter(
                name=name,
                is_new=False,
                existing_id=str(existing_char.id),
                description=char_data.get("description", ""),
                role_type=role_type,
                aliases=char_data.get("aliases", []),
                first_appearance=False,
                importance_level=importance_level,  # 使用本章分析的值
            )
            result.existing_characters.append(extracted)
            result.chapter_entity_links.append(str(existing_char.id))
            svc_logger.debug("Found existing character", name=name, id=str(existing_char.id))
        else:
            # 新角色
            extracted = ExtractedCharacter(
                name=name,
                is_new=True,
                description=char_data.get("description", ""),
                role_type=role_type,
                aliases=char_data.get("aliases", []),
                first_appearance=True,
                importance_level=importance_level,
            )
            result.new_characters.append(extracted)
            svc_logger.debug("Found new character", name=name)
        
        result.extracted_characters.append(extracted)
    
    # 解析关系
    relationships_data = extraction_data.get("relationships", [])
    for rel_data in relationships_data:
        source = rel_data.get("source", "").strip()
        target = rel_data.get("target", "").strip()
        
        if not source or not target or source == target:
            continue
        
        relationship = InferredRelationship(
            source_name=source,
            target_name=target,
            relation_type=rel_data.get("relation_type", "acquaintance"),
            description=rel_data.get("description", ""),
            affinity_score=rel_data.get("affinity_score", 0),
            interaction_prompt=rel_data.get("interaction_prompt", ""),
            is_new=True,  # 暂时标记为新，后续会检查是否已存在
        )
        result.inferred_relationships.append(relationship)
    
    _log_to_file(f"Parsing complete: {len(result.extracted_characters)} total, {len(result.new_characters)} new, {len(result.existing_characters)} existing")
    return result


def _find_existing_character(name: str, existing_char_map: Dict[str, Any]) -> Optional[Any]:
    """
    查找是否已有该角色（支持精确和模糊匹配）
    """
    name_lower = name.lower()
    
    # 精确匹配
    if name_lower in existing_char_map:
        return existing_char_map[name_lower]
    
    # 简化名称匹配
    simplified = _simplify_name(name)
    if simplified in existing_char_map:
        return existing_char_map[simplified]
    
    # 包含匹配（用于处理"张无忌" vs "无忌"）
    for key, char in existing_char_map.items():
        if name_lower in key or key in name_lower:
            # 长度差异不能太大，避免误判
            len_diff = abs(len(name_lower) - len(key))
            if len_diff <= 2:
                return char
    
    return None


async def create_new_characters(
    new_characters: List[ExtractedCharacter],
    book_id: UUID,
    character_repo: Any,
    session: Any,
) -> List[Dict[str, Any]]:
    """
    批量创建新角色
    
    Args:
        new_characters: 新角色列表
        book_id: 书籍ID
        character_repo: 角色仓库
        session: 数据库会话
        
    Returns:
        创建的角色信息列表
    """
    created_chars = []
    
    for char_data in new_characters:
        try:
            # 构建角色创建数据
            char_dict = {
                "book_id": book_id,
                "name": char_data.name,
                "aliases": char_data.aliases,
                "static_prompt": _build_initial_static_prompt(char_data),
                "dynamic_state": "首次登场，状态待观察",
                "importance_level": char_data.importance_level,
            }
            
            _log_to_file(f"Creating character '{char_data.name}': importance_level={char_data.importance_level}, role_type={char_data.role_type}")
            
            new_char = await character_repo.create(char_dict)
            await session.flush()  # 确保ID生成
            
            _log_to_file(f"Character '{char_data.name}' created: id={new_char.id}, stored_level={new_char.importance_level}")
            
            created_chars.append({
                "id": str(new_char.id),
                "name": new_char.name,
                "description": char_data.description,
            })
            
            svc_logger.debug("Created new character", name=new_char.name, id=str(new_char.id))
            
        except Exception as e:
            svc_logger.error("Failed to create character", name=char_data.name, error=str(e))
            continue
    
    return created_chars


def _build_initial_static_prompt(char_data: ExtractedCharacter) -> str:
    """
    根据提取信息构建初始静态设定
    """
    prompt_parts = [f"【{char_data.name}】"]
    
    if char_data.description:
        prompt_parts.append(f"人物特征：{char_data.description}")
    
    if char_data.role_type:
        type_map = {
            "protagonist": "主角",
            "antagonist": "反派",
            "supporting": "配角",
            "minor": "路人",
        }
        role_cn = type_map.get(char_data.role_type, char_data.role_type)
        prompt_parts.append(f"角色定位：{role_cn}")
    
    if char_data.aliases:
        prompt_parts.append(f"别名/称呼：{', '.join(char_data.aliases)}")
    
    return "\n".join(prompt_parts)


async def create_inferred_relationships(
    relationships: List[InferredRelationship],
    character_id_map: Dict[str, UUID],  # 名称 -> ID 映射
    book_id: UUID,
    existing_relationships: List[Any],
    relationship_repo: Any,
    session: Any,
) -> List[Dict[str, Any]]:
    """
    批量创建推断的关系
    
    Args:
        relationships: 推断的关系列表
        character_id_map: 角色名称到ID的映射
        book_id: 书籍ID
        existing_relationships: 已存在的关系（用于去重）
        relationship_repo: 关系仓库
        session: 数据库会话
        
    Returns:
        创建的关系信息列表
    """
    created_rels = []
    
    # 构建已有关系集合用于快速查找
    existing_set = set()
    for rel in existing_relationships:
        source_id = str(getattr(rel, 'source_char_id', ''))
        target_id = str(getattr(rel, 'target_char_id', ''))
        existing_set.add((source_id, target_id))
    
    for rel_data in relationships:
        source_name = rel_data.source_name
        target_name = rel_data.target_name
        
        # 查找角色ID
        source_id = character_id_map.get(source_name.lower())
        target_id = character_id_map.get(target_name.lower())
        
        if not source_id or not target_id:
            svc_logger.debug(
                "Skipping relationship - character not found",
                source=source_name,
                target=target_name,
            )
            continue
        
        # 检查是否已存在
        if (str(source_id), str(target_id)) in existing_set:
            svc_logger.debug("Relationship already exists", source=source_name, target=target_name)
            continue
        
        try:
            rel_dict = {
                "source_char_id": source_id,
                "target_char_id": target_id,
                "relation_type": rel_data.relation_type,
                "affinity_score": rel_data.affinity_score,
                "interaction_prompt": rel_data.interaction_prompt or rel_data.description,
            }
            
            new_rel = await relationship_repo.create(rel_dict)
            await session.flush()
            
            created_rels.append({
                "id": str(new_rel.id),
                "source_name": source_name,
                "target_name": target_name,
                "relation_type": rel_data.relation_type,
            })
            
            svc_logger.debug(
                "Created relationship",
                source=source_name,
                target=target_name,
                type=rel_data.relation_type,
            )
            
        except Exception as e:
            svc_logger.error(
                "Failed to create relationship",
                source=source_name,
                target=target_name,
                error=str(e),
            )
            continue
    
    return created_rels


async def update_chapter_entity_links(
    chapter_id: UUID,
    character_ids: List[str],
    chapter_repo: Any,
) -> None:
    """
    更新章节与角色的关联
    
    Args:
        chapter_id: 章节ID
        character_ids: 角色ID列表
        chapter_repo: 章节仓库
    """
    try:
        await chapter_repo.update_entities(chapter_id, character_ids)
        svc_logger.debug(
            "Updated chapter entity links",
            chapter_id=str(chapter_id),
            count=len(character_ids),
        )
    except Exception as e:
        svc_logger.error("Failed to update chapter entity links", error=str(e))
        # 不抛出异常，避免影响主流程


async def execute_character_extraction_workflow(
    chapter_content: str,
    chapter_id: UUID,
    book_id: UUID,
    character_repo: Any,
    relationship_repo: Any,
    chapter_repo: Any,
    timeout: int = 180,
) -> CharacterExtractionResult:
    """
    执行完整的人物提取工作流
    
    这是主入口函数，整合所有步骤：
    1. 提取人物
    2. 创建新角色
    3. 创建关系
    4. 更新章节关联
    
    Args:
        chapter_content: 章节内容
        chapter_id: 章节ID
        book_id: 书籍ID
        character_repo: 角色仓库
        relationship_repo: 关系仓库
        chapter_repo: 章节仓库
        timeout: 超时时间
        
    Returns:
        CharacterExtractionResult 完整结果
    """
    session = character_repo.get_session()
    
    # 1. 获取已有角色
    existing_chars = await character_repo.list_by_book(book_id)
    
    # 2. 提取人物
    extraction_result = await extract_characters_from_chapter(
        chapter_content=chapter_content,
        existing_characters=existing_chars,
        timeout=timeout,
    )
    
    if not extraction_result.extracted_characters:
        _log_to_file("No characters extracted from chapter (extraction_result.extracted_characters is empty)")
        svc_logger.info("No characters extracted from chapter")
        return extraction_result
    
    _log_to_file(f"Extraction successful: {len(extraction_result.extracted_characters)} characters, {len(extraction_result.new_characters)} new")
    
    # 3. 创建新角色
    created_chars = []
    if extraction_result.new_characters:
        created_chars = await create_new_characters(
            new_characters=extraction_result.new_characters,
            book_id=book_id,
            character_repo=character_repo,
            session=session,
        )
    
    # 4. 构建名称->ID映射（包含新创建的角色）
    character_id_map: Dict[str, UUID] = {}
    
    # 添加已有角色
    for char in existing_chars:
        if char.name:
            character_id_map[char.name.lower()] = char.id
        if hasattr(char, 'aliases') and char.aliases:
            for alias in char.aliases:
                character_id_map[alias.lower()] = char.id
    
    # 添加新创建的角色
    for created in created_chars:
        char_name = created["name"]
        char_id = UUID(created["id"])
        character_id_map[char_name.lower()] = char_id
        # 添加到结果中以便更新章节关联
        extraction_result.chapter_entity_links.append(created["id"])
    
    # 5. 创建关系
    created_rels = []
    if extraction_result.inferred_relationships and character_id_map:
        existing_rels = await relationship_repo.list_by_book(book_id)
        created_rels = await create_inferred_relationships(
            relationships=extraction_result.inferred_relationships,
            character_id_map=character_id_map,
            book_id=book_id,
            existing_relationships=existing_rels,
            relationship_repo=relationship_repo,
            session=session,
        )
    
    # 6. 更新章节与角色的关联
    if extraction_result.chapter_entity_links:
        await update_chapter_entity_links(
            chapter_id=chapter_id,
            character_ids=list(set(extraction_result.chapter_entity_links)),  # 去重
            chapter_repo=chapter_repo,
        )
    
    # 提交事务
    await session.commit()
    
    svc_logger.info(
        "Character extraction workflow completed",
        chapter_id=str(chapter_id),
        new_chars=len(created_chars),
        new_rels=len(created_rels),
        total_links=len(extraction_result.chapter_entity_links),
    )
    
    return extraction_result
