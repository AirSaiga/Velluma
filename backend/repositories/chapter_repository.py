from uuid import UUID

from sqlalchemy.orm import selectinload

from backend.models import Chapter, ChapterEntity
from backend.repositories.base import BaseRepository, QuerySpec


class ChapterRepository(BaseRepository[Chapter]):
    """
    章节仓储：管理章节实体及章节与角色的关联关系。

    核心概念：ChapterEntity 是多态关联表，同一表可关联不同类型实体（character/location 等）。
    设计意图：通过 entity_type 字段实现"一对多"灵活关联，避免为每种实体单独建关联表。
    """
    model = Chapter

    async def list_entities(self, chapter_id: UUID):
        """
        查询章节关联的所有实体：用于章节详情页展示关联角色。

        数据流：chapter_id → WHERE chapter_id = ? → List[ChapterEntity]
        注意：仅返回关联表数据，不包含实体详情（需要二次查询或使用 with_character 变体）。
        """
        spec = QuerySpec.create(ChapterEntity).where(ChapterEntity.chapter_id == chapter_id)
        return await self.find_all(
            spec=spec
        )

    async def list_entities_with_character(self, chapter_id: UUID):
        """
        查询章节关联实体并预加载角色详情：避免 N+1 查询问题。

        副作用：selectinload 会生成额外的 SELECT 语句，但避免了循环查询。
        权衡：适用于"章节详情页同时展示所有关联角色"的场景；若仅需关联ID，list_entities 更轻量。
        """
        spec = (
            QuerySpec.create(ChapterEntity)
            .where(ChapterEntity.chapter_id == chapter_id)
            .with_options(selectinload(ChapterEntity.character))
        )
        return await self.find_all(
            spec=spec
        )

    async def add_entity(self, chapter_id: UUID, entity_id: UUID, entity_type: str = "character"):
        """
        为章节添加实体关联：创建 ChapterEntity 记录。

        事务边界：单条插入 + 提交，独立事务。
        副作用：插入前不检查重复性，可能产生重复关联（业务层需自行去重）。
        警示：若需"添加前检查是否存在"，应先调用 list_entities 验证。
        """
        chapter_entity = ChapterEntity(chapter_id=chapter_id, entity_id=entity_id, entity_type=entity_type)
        self.db.add(chapter_entity)
        await self.db.commit()

    async def delete_entity(self, entity: ChapterEntity):
        """
        删除章节实体关联：用于章节编辑时移除某个角色关联。

        事务边界：单条删除 + 提交。
        警示：这是物理删除，关联移除后无法直接恢复（需重新调用 add_entity）。
        """
        await self.db.delete(entity)
        await self.db.commit()

    async def list_locations(self, chapter_id: UUID):
        """
        查询章节关联的所有地点
        """
        from backend.models import ChapterMapLocation
        spec = QuerySpec.create(ChapterMapLocation).where(ChapterMapLocation.chapter_id == chapter_id)
        return await self.find_all(spec=spec)

    async def list_locations_with_details(self, chapter_id: UUID):
        """
        查询章节关联地点并预加载详情
        """
        from backend.models import ChapterMapLocation
        spec = (
            QuerySpec.create(ChapterMapLocation)
            .where(ChapterMapLocation.chapter_id == chapter_id)
            .with_options(selectinload(ChapterMapLocation.location))
        )
        return await self.find_all(spec=spec)

    async def add_location(self, chapter_id: UUID, location_id: UUID):
        """
        为章节添加地点关联
        """
        from backend.models import ChapterMapLocation
        chapter_location = ChapterMapLocation(chapter_id=chapter_id, location_id=location_id)
        self.db.add(chapter_location)
        await self.db.commit()

    async def delete_location(self, location: "ChapterMapLocation"):
        """
        删除章节地点关联
        """
        await self.db.delete(location)
        await self.db.commit()

    async def remove_location_by_ids(self, chapter_id: UUID, location_id: UUID):
        """
        直接通过 chapter_id 和 location_id 删除关联
        """
        from backend.models import ChapterMapLocation
        from sqlalchemy import delete

        stmt = delete(ChapterMapLocation).where(
            ChapterMapLocation.chapter_id == chapter_id,
            ChapterMapLocation.location_id == location_id
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount > 0
