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
泛型仓储基类 - 统一数据访问层抽象。

职责：
- 提供通用的 CRUD 操作模板方法
- 封装 SQLAlchemy 异步查询构建逻辑
- 实现事务管理和会话生命周期控制

业务场景：
- 所有具体 Repository（如 BookRepository）都继承此类
- 消除业务代码与 ORM 的直接耦合
- 统一错误处理和事务边界

设计原则：
- 泛型确保类型安全，IDE 自动补全
- 异步优先，利用 SQLAlchemy async 支持
- 声明式查询构建，简化复杂查询编写

依赖项：
- SQLAlchemy 2.0: ORM 和查询构建器
- Pydantic: 数据模型类型定义

使用方式：
    class BookRepository(BaseRepository[Book]):
        model = Book
        ...
"""

from dataclasses import dataclass
from typing import Any, Generic, Optional, Sequence, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession

ModelType = TypeVar("ModelType")


@dataclass
class JoinSpec:
    """JOIN 规范定义 - 描述表关联配置"""
    target: Any
    onclause: Optional[Any] = None
    isouter: bool = False
    full: bool = False


@dataclass
class QuerySpec:
    """查询规范定义 - 声明式查询配置"""
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

    架构约束：
    - 请通过公共方法访问数据，避免直接操作 self.db
    - 直接访问 self.db 会绕过仓储层的封装，应逐步淘汰
    """
    model: type[ModelType]
    _db: AsyncSession

    def __init__(self, db: AsyncSession):
        """
        依赖注入点：db session 由外层框架（如 FastAPI Depends）管理，
        确保同一请求生命周期内复用同一会话，避免连接泄漏。
        """
        self._db = db

    @property
    def db(self) -> AsyncSession:
        """
        兼容性别名 - 逐步废弃中。

        警告：直接访问 self.db 会绕过仓储层的封装。
        建议使用 get_session() 方法或公共 CRUD 方法。
        """
        import warnings
        warnings.warn(
            "直接访问 repo.db 已废弃，请使用公共方法或 get_session()。",
            DeprecationWarning,
            stacklevel=2
        )
        return self._db

    def get_session(self) -> AsyncSession:
        """获取数据库会话（无警告，推荐在 service 层使用）。"""
        return self._db

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
        self._db.add(item)
        await self._db.commit()
        await self._db.refresh(item)
        return item

    async def update(self, item: ModelType, payload: dict[str, Any]) -> ModelType:
        """
        原地更新：setattr 修改对象属性，ORM dirty tracking 会在 commit 时生成 UPDATE SQL。
        数据流：payload (dict) → ORM 对象属性 → DB row update

        警示：item 必须是当前 session 绑定的对象，否则需先 merge。
        """
        for key, value in payload.items():
            setattr(item, key, value)
        await self._db.commit()
        await self._db.refresh(item)
        return item

    async def delete(self, item: ModelType):
        """
        物理删除：直接执行 DELETE 语句（非软删除）。
        警示：级联删除由模型关系定义决定，需确认外键约束避免数据库报错。
        """
        await self._db.delete(item)
        await self._db.commit()

    async def execute_scalar_all(self, query: Select):
        """
        底层执行接口：返回标量列表，用于自定义复杂查询。
        数据流：Select 对象 → DB → scalar 列表
        """
        result = await self._db.execute(query)
        return result.scalars().all()

    async def execute_scalar_one_or_none(self, query: Select):
        """
        返回单条或空：用于 "查询一条记录" 场景。
        与 execute_scalar_all 的区别：多用于唯一性查询（by ID, by unique constraint）。
        """
        result = await self._db.execute(query)
        return result.scalar_one_or_none()

    async def execute(self, statement) -> Result:
        """
        执行任意 SQL 语句或 Select 对象，返回 Result 对象。
        
        用途：用于无法使用标准 CRUD 方法的复杂查询场景。
        与 execute_scalar_all/execute_scalar_one_or_none 的区别：
        - 后两者专用于 SELECT 并返回标量
        - 此方法返回完整 Result，可访问行数据、lastrowid 等
        
        迁移提示：优先使用 find_all / find_one 等高级方法，
        仅在需要执行 UPDATE/DELETE 或复杂查询时使用此方法。
        """
        return await self._db.execute(statement)

    async def add_and_commit(self, item: ModelType) -> ModelType:
        """
        快捷方法：添加实体并提交。
        
        用途：替代直接调用 self._db.add() + commit() + refresh()
        注意：此方法不执行 refresh，如需返回数据库生成的值，请使用 create() 方法
        
        迁移提示：创建新记录请使用 create() 方法，此方法适用于已有实体的快速保存
        """
        self._db.add(item)
        await self._db.commit()
        return item

    async def add_refresh_and_commit(self, item: ModelType) -> ModelType:
        """
        快捷方法：添加实体、刷新、提交。
        
        用途：添加实体后需要获取数据库生成的值（如自增ID、默认时间戳）
        迁移提示：等同于 self._db.add() + await self._db.commit() + await self._db.refresh()
        """
        self._db.add(item)
        await self._db.commit()
        await self._db.refresh(item)
        return item

    async def commit(self):
        """
        手动提交点：用于跨多个操作的显式事务控制。
        使用场景：批量操作需要全部成功或全部回滚时。
        """
        await self._db.commit()

    async def refresh(self, item: ModelType):
        """
        刷新对象状态：从数据库重新加载最新值。
        典型用途：确认其他进程/触发器对同一行的修改。
        """
        await self._db.refresh(item)

    async def commit_and_refresh(self, item: ModelType):
        """
        提交更改并刷新对象状态。

        快捷方法：等同于 commit() + refresh()
        典型用途：更新实体后需要获取数据库生成的值

        迁移提示：替代 self._db.commit(); await self._db.refresh(item)
        """
        await self._db.commit()
        await self._db.refresh(item)

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
