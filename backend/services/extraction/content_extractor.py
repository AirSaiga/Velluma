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
正文逆向提取编排器（统一提取 + 落库执行）。

职责：
- extract_from_chapter：纯 LLM 提取，不落库，返回 ExtractionResult
- commit_extraction：根据用户确认的子集，串行写入各结构化表

业务场景：
- 用户对导入或已有章节执行"分析正文"
- 第一阶段（analyze）：提取但不落库，结果存内存待用户确认
- 第二阶段（confirm）：用户勾选后批量落库

设计要点：
- 统一用一个 LLM 调用提取全部类型（角色/关系/地点/资产/伏笔），保证一致性与成本
- 落库时逐表查重，避免唯一约束冲突
- 正文切片+embedding 填充 MemoryChunk（RAG 向量记忆）
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.llm import call_llm_with_usage, get_embedding
from backend.services.prompts.content_extraction import (
    build_extraction_system_prompt,
    build_extraction_prompt,
)
from backend.services.utils.logging import ServiceLogger, LOG_PREFIX_WORKFLOW

logger = logging.getLogger(__name__)
svc_logger = ServiceLogger(logger, LOG_PREFIX_WORKFLOW)

# 正文截断长度（与 character_extraction 一致）
MAX_CONTENT_CHARS = 8000
# LLM 超时秒数
EXTRACTION_TIMEOUT = 120


@dataclass
class ExtractionResult:
    """
    提取结果容器。

    每个字段是该类型的 dict 列表，dict 结构与 LLM 输出 schema 一致。
    """
    characters: List[dict] = field(default_factory=list)
    relationships: List[dict] = field(default_factory=list)
    locations: List[dict] = field(default_factory=list)
    assets: List[dict] = field(default_factory=list)
    foreshadows: List[dict] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "characters": self.characters,
            "relationships": self.relationships,
            "locations": self.locations,
            "assets": self.assets,
            "foreshadows": self.foreshadows,
            "stats": {
                "characters": len(self.characters),
                "relationships": len(self.relationships),
                "locations": len(self.locations),
                "assets": len(self.assets),
                "foreshadows": len(self.foreshadows),
            },
        }


def _parse_llm_json(content: str) -> dict:
    """
    解析 LLM 返回的 JSON，剥离 markdown 代码块围栏。

    Args:
        content: LLM 原始返回文本

    Returns:
        解析后的 dict；解析失败返回空结构。
    """
    if not content:
        return {}
    text = content.strip()
    # 剥离 ```json ... ``` 围栏
    if text.startswith("```"):
        lines = text.split("\n")
        # 去掉首尾的 ``` 行
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        svc_logger.warning("Failed to parse extraction JSON", error=str(e))
        return {}


async def extract_from_chapter(
    chapter_content: str,
    chapter_number: int,
    existing_character_names: Optional[List[str]] = None,
    existing_ledger_keys: Optional[List[str]] = None,
    timeout: int = EXTRACTION_TIMEOUT,
) -> ExtractionResult:
    """
    从章节正文提取结构化数据（不落库）。

    使用 reasoning 模型 + JSON 模式，单次调用提取全部类型。

    Args:
        chapter_content: 章节正文
        chapter_number: 章节序号
        existing_character_names: 已有角色名列表（提示 LLM 避免重复）
        existing_ledger_keys: 已有伏笔 key 列表
        timeout: LLM 超时秒数

    Returns:
        ExtractionResult，异常时返回空结果（不抛异常）。
    """
    if not chapter_content or not chapter_content.strip():
        svc_logger.info("Empty content, skipping extraction")
        return ExtractionResult()

    # 截断正文
    truncated = chapter_content[:MAX_CONTENT_CHARS]

    try:
        import asyncio

        system_prompt = build_extraction_system_prompt()
        user_prompt = build_extraction_prompt(
            truncated,
            chapter_number,
            existing_character_names or [],
            existing_ledger_keys or [],
        )

        svc_logger.info(
            "Calling LLM for content extraction",
            content_length=len(truncated),
            chapter_number=chapter_number,
        )

        result = await asyncio.wait_for(
            call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="reasoning",
                temperature=0.2,
                max_tokens=4096,
                response_format={"type": "json_object"},
            ),
            timeout=timeout,
        )

        parsed = _parse_llm_json(result.content)
        return ExtractionResult(
            characters=parsed.get("characters", []),
            relationships=parsed.get("relationships", []),
            locations=parsed.get("locations", []),
            assets=parsed.get("assets", []),
            foreshadows=parsed.get("foreshadows", []),
        )
    except asyncio.TimeoutError:
        svc_logger.warning("Extraction timed out", timeout=timeout)
        return ExtractionResult()
    except Exception as e:
        svc_logger.warning("Extraction failed", error=str(e))
        return ExtractionResult()


async def commit_extraction(
    db: AsyncSession,
    book_id: UUID,
    chapter_id: UUID,
    chapter_number: int,
    confirmed: ExtractionResult,
    raw_text: str,
    progress_callback: Optional[Callable[[str, int], None]] = None,
) -> Dict[str, int]:
    """
    根据用户确认的提取结果，串行写入数据库各表。

    落库顺序：角色 → 关系 → 地点 → 资产 → 章节实体关联 → 伏笔 → 向量记忆。

    Args:
        db: 异步数据库会话
        book_id: 书籍 ID
        chapter_id: 章节 ID
        chapter_number: 章节序号
        confirmed: 用户勾选确认后的 ExtractionResult 子集
        raw_text: 章节正文（用于 MemoryChunk 切片+embedding）
        progress_callback: 可选的进度回调 (step_name, created_count)

    Returns:
        各表创建计数 dict，如 {"characters": 3, "relationships": 2, ...}
    """
    # 延迟导入仓储（避免循环依赖）
    from backend.repositories.character_repository import CharacterRepository
    from backend.repositories.relationship_repository import RelationshipRepository
    from backend.repositories.map_repository import MapLocationRepository
    from backend.repositories.asset_repository import AssetRepository
    from backend.repositories.chapter_repository import ChapterRepository
    from backend.repositories.plot_ledger_repository import PlotLedgerRepository
    from backend.repositories.memory_repository import MemoryRepository
    from backend.models import MemoryChunk

    char_repo = CharacterRepository(db)
    rel_repo = RelationshipRepository(db)
    map_repo = MapLocationRepository(db)
    asset_repo = AssetRepository(db)
    chapter_repo = ChapterRepository(db)
    ledger_repo = PlotLedgerRepository(db)
    memory_repo = MemoryRepository(db)

    created = {
        "characters": 0,
        "relationships": 0,
        "locations": 0,
        "assets": 0,
        "foreshadows": 0,
        "memories": 0,
    }

    # ---- 1. 角色：查重后新建 ----
    existing_chars = await char_repo.list_by_book(book_id)
    existing_char_names = {c.name for c in existing_chars}
    name_to_id: Dict[str, UUID] = {c.name: c.id for c in existing_chars}

    for ch in confirmed.characters:
        name = ch.get("name", "").strip()
        if not name or name in existing_char_names:
            continue
        try:
            new_char = await char_repo.create({
                "book_id": book_id,
                "name": name,
                "aliases": ch.get("aliases", []),
                "static_prompt": ch.get("description", ""),
                "dynamic_state": "首次登场，状态待观察",
                "importance_level": ch.get("importance_level", 3),
            })
            name_to_id[name] = new_char.id
            existing_char_names.add(name)
            created["characters"] += 1
        except Exception as e:
            svc_logger.warning("Failed to create character", name=name, error=str(e))

    if progress_callback:
        progress_callback("characters", created["characters"])

    # ---- 2. 关系：用 name→id 映射，去重后创建 ----
    existing_rels = await rel_repo.list_by_book(book_id)
    existing_rel_pairs = {(r.source_char_id, r.target_char_id) for r in existing_rels}

    for rel in confirmed.relationships:
        source_name = rel.get("source_name", "").strip()
        target_name = rel.get("target_name", "").strip()
        source_id = name_to_id.get(source_name)
        target_id = name_to_id.get(target_name)
        # 两端角色必须存在且不能自环
        if not source_id or not target_id or source_id == target_id:
            continue
        if (source_id, target_id) in existing_rel_pairs:
            continue
        try:
            await rel_repo.create({
                "source_char_id": source_id,
                "target_char_id": target_id,
                "relation_type": rel.get("relation_type", "unknown"),
                "affinity_score": rel.get("affinity_score", 0),
                "interaction_prompt": rel.get("description", ""),
            })
            existing_rel_pairs.add((source_id, target_id))
            created["relationships"] += 1
        except Exception as e:
            svc_logger.warning("Failed to create relationship", error=str(e))

    if progress_callback:
        progress_callback("relationships", created["relationships"])

    # ---- 3. 地点：查重后新建 ----
    existing_locations = await map_repo.list_by_book(book_id)
    existing_loc_names = {loc.name for loc in existing_locations}
    loc_ids: List[UUID] = []

    for loc in confirmed.locations:
        name = loc.get("name", "").strip()
        if not name or name in existing_loc_names:
            continue
        try:
            new_loc = await map_repo.create({
                "book_id": book_id,
                "name": name,
                "description": loc.get("description", ""),
            })
            existing_loc_names.add(name)
            loc_ids.append(new_loc.id)
            created["locations"] += 1
        except Exception as e:
            svc_logger.warning("Failed to create location", name=name, error=str(e))

    if progress_callback:
        progress_callback("locations", created["locations"])

    # ---- 4. 资产：查重后新建 ----
    existing_assets = await asset_repo.list_by_book(book_id)
    existing_asset_names = {a.name for a in existing_assets}

    for asset in confirmed.assets:
        name = asset.get("name", "").strip()
        if not name or name in existing_asset_names:
            continue
        try:
            await asset_repo.create({
                "book_id": book_id,
                "name": name,
                "static_description": asset.get("description", ""),
                "importance_level": asset.get("importance_level", 1),
            })
            existing_asset_names.add(name)
            created["assets"] += 1
        except Exception as e:
            svc_logger.warning("Failed to create asset", name=name, error=str(e))

    if progress_callback:
        progress_callback("assets", created["assets"])

    # ---- 5. 章节实体关联：把本章涉及的角色关联到章节 ----
    # ChapterRepository 无 update_entities 批量方法，逐条 add_entity（add_entity 插入前
    # 不查重，故先 list_entities 取已关联 id 去重，避免重复 ChapterEntity 记录）。
    if name_to_id:
        # 只关联本章提取到的角色（含已有+新建）
        chapter_char_ids = [
            name_to_id[ch["name"].strip()]
            for ch in confirmed.characters
            if ch.get("name", "").strip() in name_to_id
        ]
        if chapter_char_ids:
            try:
                existing_links = await chapter_repo.list_entities(chapter_id)
                linked_ids = {
                    ln.entity_id for ln in existing_links
                    if ln.entity_type == "character"
                }
                for cid in chapter_char_ids:
                    if cid not in linked_ids:
                        await chapter_repo.add_entity(chapter_id, cid, "character")
                        linked_ids.add(cid)
            except Exception as e:
                svc_logger.warning("Failed to update chapter entities", error=str(e))

    # ---- 6. 伏笔：去重 ledger_key 后创建 ----
    existing_keys = set(
        await ledger_repo.get_unresolved_ledger_keys(book_id, [chapter_id])
    )
    # 兜底：也查全书的 open 伏笔 key
    all_ledgers = await ledger_repo.get_by_book(book_id, status="open")
    existing_keys.update(lg.ledger_key for lg in all_ledgers)

    for fs in confirmed.foreshadows:
        key = fs.get("ledger_key", "").strip()
        if not key:
            # 自动生成 key
            key = f"extracted-{chapter_number}-{created['foreshadows'] + 1}"
        # 去重：冲突时加后缀
        base_key = key
        suffix = 2
        while key in existing_keys:
            key = f"{base_key}-{suffix}"
            suffix += 1
        existing_keys.add(key)
        try:
            await ledger_repo.create({
                "book_id": book_id,
                "chapter_id": chapter_id,
                "ledger_key": key,
                "entry_type": fs.get("entry_type", "foreshadow"),
                "content": fs.get("content", ""),
                "status": fs.get("status", "open"),
                "created_at_chapter": chapter_number,
                "meta": {"strength": fs.get("strength", 5), "source": "auto_extracted"},
            })
            created["foreshadows"] += 1
        except Exception as e:
            svc_logger.warning("Failed to create foreshadow", key=key, error=str(e))

    if progress_callback:
        progress_callback("foreshadows", created["foreshadows"])

    # ---- 7. 向量记忆：正文切片 + embedding → MemoryChunk ----
    if raw_text and raw_text.strip():
        chunk_size = 1000
        chunks = [
            raw_text[i:i + chunk_size]
            for i in range(0, len(raw_text), chunk_size)
            if raw_text[i:i + chunk_size].strip()
        ]
        for idx, chunk in enumerate(chunks):
            try:
                embedding = await get_embedding(chunk[:2000])
                chunk_text = f"【第{chapter_number}章 片段{idx + 1}】{chunk}"
                memory_item = MemoryChunk(
                    book_id=book_id,
                    chapter_id=chapter_id,
                    chunk_text=chunk_text,
                    embedding=embedding if embedding else None,
                )
                db.add(memory_item)
                created["memories"] += 1
            except Exception as e:
                svc_logger.warning("Failed to create memory chunk", idx=idx, error=str(e))
        # 批量提交记忆
        if created["memories"] > 0:
            try:
                await db.commit()
            except Exception as e:
                svc_logger.warning("Failed to commit memory chunks", error=str(e))

    if progress_callback:
        progress_callback("memories", created["memories"])

    return created
