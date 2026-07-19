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
数据访问层统一出口模块。

职责：聚合所有仓储（Repository）类，提供统一的导入入口。

设计模式：Repository Pattern，封装数据库访问逻辑。

模块组织：
- book_repository.py: 书籍数据访问
- chapter_repository.py: 章节数据访问（含关联管理）
- character_repository.py: 角色数据访问
- relationship_repository.py: 角色关系数据访问
- memory_repository.py: 记忆块数据访问（RAG 检索）
- map_repository.py: 地图/地点数据访问
- plot_ledger_repository.py: 伏笔账本数据访问（RAG 伏笔追踪）
- base.py: 泛型基类（包含 QuerySpec 构建器）

使用场景：
- routes/: 业务路由层，通过依赖注入获取仓储实例
- core/dependencies.py: 定义仓储的依赖注入函数
- services/: 业务服务层，通过仓储访问数据

业务规则：
- 所有仓储继承 BaseRepository，提供统一的 CRUD 接口
- 仓储绑定到同一个数据库会话，确保事务一致性
- 复杂查询使用 QuerySpec 构建器，避免硬编码 SQL
- 所有数据库操作必须通过 Repository 执行

迁移说明 (2026-03-30)：
- 新增 PlotLedgerRepository 用于伏笔管理
- 已完成所有 RAG 服务层的 Repository 迁移
- 所有直接访问 db 的代码已移除
- Repository 提供 execute() 方法用于复杂查询
"""

from backend.repositories.book_repository import BookRepository
from backend.repositories.chapter_repository import ChapterRepository
from backend.repositories.character_repository import CharacterRepository
from backend.repositories.relationship_repository import RelationshipRepository
from backend.repositories.memory_repository import MemoryRepository
from backend.repositories.map_repository import MapLocationRepository
from backend.repositories.plot_ledger_repository import PlotLedgerRepository
from backend.repositories.asset_repository import AssetRepository, ChapterAssetRepository
# CP2.1b 新增
from backend.repositories.chapter_card_repository import ChapterCardRepository
from backend.repositories.style_card_repository import StyleCardRepository
from backend.repositories.author_sample_repository import AuthorSampleRepository
from backend.repositories.system_cliche_repository import SystemClicheRepository
# CP3.1a 新增
from backend.repositories.quality_report_repository import QualityReportRepository
