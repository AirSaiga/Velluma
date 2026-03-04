from dataclasses import dataclass
from typing import Any, Generic, Optional, Sequence, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

ModelType = TypeVar("ModelType")


@dataclass
class JoinSpec:
    target: Any
    onclause: Optional[Any] = None
    isouter: bool = False
    full: bool = False


@dataclass
class QuerySpec:
    model: Optional[type[Any]] = None
    conditions: Optional[Sequence[Any]] = None
    order_by: Optional[Any] = None
    options: Optional[Sequence[Any]] = None
    joins: Optional[Sequence[JoinSpec]] = None
    skip: Optional[int] = None
    limit: Optional[int] = None

    @classmethod
    def create(cls, model: Optional[type[Any]] = None):
        return cls(model=model)

    def with_model(self, model: type[Any]):
        self.model = model
        return self

    def where(self, *conditions: Any):
        merged = list(self.conditions or [])
        merged.extend(conditions)
        self.conditions = merged
        return self

    def order(self, *order_by: Any):
        if not order_by:
            return self
        if len(order_by) == 1:
            self.order_by = order_by[0]
        else:
            self.order_by = list(order_by)
        return self

    def with_options(self, *options: Any):
        merged = list(self.options or [])
        merged.extend(options)
        self.options = merged
        return self

    def join(self, target: Any):
        merged = list(self.joins or [])
        merged.append(JoinSpec(target=target))
        self.joins = merged
        return self

    def join_on(
        self,
        target: Any,
        onclause: Any,
        *,
        isouter: bool = False,
        full: bool = False,
    ):
        merged = list(self.joins or [])
        merged.append(JoinSpec(target=target, onclause=onclause, isouter=isouter, full=full))
        self.joins = merged
        return self

    def join_outer(self, target: Any, onclause: Optional[Any] = None):
        merged = list(self.joins or [])
        merged.append(JoinSpec(target=target, onclause=onclause, isouter=True))
        self.joins = merged
        return self

    def paginate(self, skip: Optional[int] = None, limit: Optional[int] = None):
        self.skip = skip
        self.limit = limit
        return self


class BaseRepository(Generic[ModelType]):
    model: type[ModelType]

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(self, skip: int = 0, limit: int = 100):
        return await self.find_all(skip=skip, limit=limit)

    async def get_by_id(self, item_id: Any) -> Optional[ModelType]:
        return await self.find_one(conditions=[getattr(self.model, "id") == item_id])

    async def create(self, payload: dict[str, Any]) -> ModelType:
        item = self.model(**payload)
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def update(self, item: ModelType, payload: dict[str, Any]) -> ModelType:
        for key, value in payload.items():
            setattr(item, key, value)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def delete(self, item: ModelType):
        await self.db.delete(item)
        await self.db.commit()

    async def execute_scalar_all(self, query: Select):
        result = await self.db.execute(query)
        return result.scalars().all()

    async def execute_scalar_one_or_none(self, query: Select):
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def commit(self):
        await self.db.commit()

    async def refresh(self, item: ModelType):
        await self.db.refresh(item)

    def build_query(
        self,
        *,
        spec: Optional[QuerySpec] = None,
        model: Optional[type[Any]] = None,
        conditions: Optional[Sequence[Any]] = None,
        order_by: Optional[Any] = None,
        options: Optional[Sequence[Any]] = None,
        joins: Optional[Sequence[Any]] = None,
        skip: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> Select:
        spec = spec or QuerySpec(
            model=model,
            conditions=conditions,
            order_by=order_by,
            options=options,
            skip=skip,
            limit=limit,
        )
        query: Select = select(spec.model or self.model)
        if spec.joins:
            for join_spec in spec.joins:
                query = query.join(
                    join_spec.target,
                    join_spec.onclause,
                    isouter=join_spec.isouter,
                    full=join_spec.full,
                )
        if joins:
            for join_target in joins:
                if isinstance(join_target, tuple):
                    query = query.join(*join_target)
                else:
                    query = query.join(join_target)
        if spec.options:
            query = query.options(*spec.options)
        if spec.conditions:
            query = query.where(*spec.conditions)
        if spec.order_by is not None:
            if isinstance(spec.order_by, (list, tuple)):
                query = query.order_by(*spec.order_by)
            else:
                query = query.order_by(spec.order_by)
        if spec.skip is not None:
            query = query.offset(spec.skip)
        if spec.limit is not None:
            query = query.limit(spec.limit)
        return query

    async def find_all(
        self,
        *,
        spec: Optional[QuerySpec] = None,
        model: Optional[type[Any]] = None,
        conditions: Optional[Sequence[Any]] = None,
        order_by: Optional[Any] = None,
        options: Optional[Sequence[Any]] = None,
        joins: Optional[Sequence[Any]] = None,
        skip: Optional[int] = None,
        limit: Optional[int] = None,
    ):
        query = self.build_query(
            spec=spec,
            model=model,
            conditions=conditions,
            order_by=order_by,
            options=options,
            joins=joins,
            skip=skip,
            limit=limit,
        )
        return await self.execute_scalar_all(query)

    async def find_one(
        self,
        *,
        spec: Optional[QuerySpec] = None,
        model: Optional[type[Any]] = None,
        conditions: Optional[Sequence[Any]] = None,
        options: Optional[Sequence[Any]] = None,
        joins: Optional[Sequence[Any]] = None,
    ):
        query = self.build_query(
            spec=spec,
            model=model,
            conditions=conditions,
            options=options,
            joins=joins,
        )
        return await self.execute_scalar_one_or_none(query)
