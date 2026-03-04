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
    """
    泛型仓储基类 - 为所有数据模型提供统一的 CRUD 操作入口。

    设计意图：
    - 统一数据访问层接口，消除业务代码与 SQLAlchemy 的直接耦合
    - 通过泛型确保类型安全，IDE 可在子类中提供完整的自动补全
    - 封装异步会话管理，确保所有数据库操作在正确的上下文中执行

    事务策略：
    - 每个 CRUD 方法独立管理事务（自动 commit），这是最简单的模式
    - 副作用：如果业务需要"查询-修改-再提交"的原子操作，需在调用方手动控制事务
    """
    model: type[ModelType]

    def __init__(self, db: AsyncSession):
        """
        依赖注入点：db session 由外层框架（如 FastAPI Depends）管理，
        确保同一请求生命周期内复用同一会话，避免连接泄漏。
        """
        self.db = db

    async def list(self, skip: int = 0, limit: int = 100):
        """
        默认分页查询：限制单次返回数量防止内存溢出。
        100 是经验值，兼顾响应速度和数据集大小。
        """
        return await self.find_all(skip=skip, limit=limit)

    async def get_by_id(self, item_id: Any) -> Optional[ModelType]:
        """
        按主键查询：假设所有模型都有 'id' 字段。
        数据流：item_id (UUID/Int) → SQL WHERE id = ? → ORM 对象
        """
        return await self.find_one(conditions=[getattr(self.model, "id") == item_id])

    async def create(self, payload: dict[str, Any]) -> ModelType:
        """
        创建并返回完整对象：commit 后执行 refresh 以同步数据库生成的值
        （如自增 ID、默认时间戳、server-generated UUID）。

        副作用：refresh 会触发一次额外的 SELECT 语句。
        权衡：如果不需要返回最新状态，可省略 refresh 提升性能。
        """
        item = self.model(**payload)
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def update(self, item: ModelType, payload: dict[str, Any]) -> ModelType:
        """
        原地更新：setattr 修改对象属性，ORM dirty tracking 会在 commit 时生成 UPDATE SQL。
        数据流：payload (dict) → ORM 对象属性 → DB row update

        警示：item 必须是当前 session 绑定的对象，否则需先 merge。
        """
        for key, value in payload.items():
            setattr(item, key, value)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def delete(self, item: ModelType):
        """
        物理删除：直接执行 DELETE 语句（非软删除）。
        警示：级联删除由模型关系定义决定，需确认外键约束避免数据库报错。
        """
        await self.db.delete(item)
        await self.db.commit()

    async def execute_scalar_all(self, query: Select):
        """
        底层执行接口：返回标量列表，用于自定义复杂查询。
        数据流：Select 对象 → DB → scalar 列表
        """
        result = await self.db.execute(query)
        return result.scalars().all()

    async def execute_scalar_one_or_none(self, query: Select):
        """
        返回单条或空：用于 "查询一条记录" 场景。
        与 execute_scalar_all 的区别：多用于唯一性查询（by ID, by unique constraint）。
        """
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def commit(self):
        """
        手动提交点：用于跨多个操作的显式事务控制。
        使用场景：批量操作需要全部成功或全部回滚时。
        """
        await self.db.commit()

    async def refresh(self, item: ModelType):
        """
        刷新对象状态：从数据库重新加载最新值。
        典型用途：确认其他进程/触发器对同一行的修改。
        """
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
        """
        核心查询构建器：将声明式配置转换为 SQLAlchemy Select 语句。

        逻辑分块：
        1. 初始化 QuerySpec（合并传入参数与默认值）
        2. 构建基础 SELECT 语句
        3. 依次应用 JOIN → OPTIONS → WHERE → ORDER BY → OFFSET → LIMIT

        关键数据流：
        - spec.model 或 self.model → FROM 子句
        - joins → JOIN 子句（支持链式多表关联）
        - conditions → WHERE 子句
        - options → 加载策略（如 selectinload 预加载关系）
        - skip/limit → 分页控制
        """
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
        """
        查询多条记录：构建查询并执行，返回标量列表。
        数据流：QuerySpec → Select → execute_scalar_all() → List[ModelType]
        """
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
        """
        查询单条记录：用于唯一性约束查询或 "查不到则创建" 场景。
        警示：如果查询条件不唯一，可能返回任意一条而非报错，需业务层确保唯一性。
        """
        query = self.build_query(
            spec=spec,
            model=model,
            conditions=conditions,
            options=options,
            joins=joins,
        )
        return await self.execute_scalar_one_or_none(query)
