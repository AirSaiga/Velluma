# 全局资产（Asset）管理功能详细设计规格说明书 (Spec)

## 1. 概述
当前系统中，用户仅能在“高级设置”中通过 `chapter_assets_schema` 字段定义**仅对当前章节有效**的资产/道具。为了支持跨章节的道具连续性（如道具的获取、消耗、损坏、升级等），我们需要引入**全局资产（Asset）管理**功能。
该功能允许用户在全局层面创建和管理小说中的关键道具、法宝、装备等，并在生成特定章节时，将这些全局资产关联到章节中，供 LLM 在规划和起草时作为上下文约束。

## 2. 数据库设计 (Database Schema)

在 `backend/models.py` 中新增以下模型：

### 2.1 `Asset` (全局资产模型)
对标 `Character` 模型，管理全局道具设定。
- `id`: UUID (主键)
- `book_id`: UUID (外键 -> `books.id`)
- `name`: String(200) (资产名称，如“霜之哀伤”)
- `aliases`: JSONB (别名列表)
- `static_description`: Text (静态设定，如外观、基础功能、历史渊源)
- `current_state`: Text (此刻状态，如“轻微破损”、“充能中”，可由世界快照提取更新)
- `importance_level`: Integer (重要性等级 1-5，用于控制上下文注入优先级)
- `created_at`: DateTime

### 2.2 `ChapterAsset` (章节-资产关联模型)
对标 `ChapterEntity` 和 `ChapterMapLocation`，管理章节中出场的资产。
- `id`: UUID (主键)
- `chapter_id`: UUID (外键 -> `chapters.id`)
- `asset_id`: UUID (外键 -> `assets.id`)
- (无需额外类型字段，专表专用更清晰)

## 3. 后端 API 层 (Backend API)

### 3.1 Schemas (`backend/schemas/assets.py`)
定义 Pydantic 模型：
- `AssetBase`, `AssetCreate`, `AssetUpdate`, `AssetResponse`

### 3.2 Repositories (`backend/repositories/asset_repository.py`)
实现数据访问层，提供基础的 CRUD 方法：
- `get_by_id`, `list_by_book`, `create`, `update`, `delete`

### 3.3 Routes (`backend/routes/assets.py`)
提供 RESTful API 接口：
- `GET /books/{book_id}/assets`: 获取某本书的所有资产
- `POST /books/{book_id}/assets`: 创建新资产
- `GET /assets/{asset_id}`: 获取资产详情
- `PUT /assets/{asset_id}`: 更新资产信息
- `DELETE /assets/{asset_id}`: 删除资产

### 3.4 章节路由修改 (`backend/routes/chapters.py`)
- `GET /chapters/{chapter_id}/assets`: 获取章节关联的资产
- `PUT /chapters/{chapter_id}/assets`: 更新章节关联的资产（全量覆盖）

## 4. 章节生成工作流集成 (Agentic Workflow)

### 4.1 上下文加载 (`backend/routes/chapter_generation/__init__.py` 等)
在加载章节完整上下文时（如 `load_full_chapter_context`），增加对关联资产的查询：
- 获取当前章节关联的所有 `Asset` 实例。

### 4.2 Prompt 注入 (`backend/services/prompts/`)
修改 Planner 和 Drafter 的 Prompt 构建逻辑（如 `planner_prompts.py`, `draft_prompts.py`），注入资产上下文：
```xml
<chapter_assets>
  <!-- 当章节有关联资产时渲染 -->
  <asset name="霜之哀伤" state="轻微破损">
    基础设定：这是一把受诅咒的符文剑...
  </asset>
</chapter_assets>
```
在系统提示词中增加约束指令：
- “若情节涉及上述关键道具，必须严格遵循其基础设定和当前状态，不可凭空赋予设定外的新功能，并合理推演其状态变化。”

### 4.3 状态更新 (WorldTerminalState)
在章节发布阶段（`backend/routes/chapter_publishing.py`）调用 `SnapshotExtractorAgent` 时，将关联的资产列表传入。
- 让大模型分析本章剧情后，提取资产的最新状态（如耐久度下降、形态改变）。
- 更新 `Asset.current_state` 字段，实现跨章状态连续性。

## 5. 前端界面设计 (Frontend UI)

### 5.1 侧边栏资产管理 (`frontend/src/features/asset-panel/`)
在应用侧边栏（与角色面板 `CharacterPanel` 并列或作为独立 Tab）增加全局资产管理：
- 资产列表：展示当前书籍的所有资产。
- 资产表单：支持创建和编辑资产（名称、静态设定、当前状态、重要性）。

### 5.2 章节编辑器资产选择 (`frontend/src/features/chapter-editor/`)
在 `ChapterEditorView.vue` 的生成配置区（刚刚我们优化的面板中）：
- 对标现有的“人物选择”组件，增加“本章关键道具”的选择组件。
- 允许用户从全局资产列表中勾选本章可能用到的关键道具。

### 5.3 移除旧的 `chapter_assets_schema` (可选或并存)
- 原有的“高级设置 -> 本章专属设定（Asset Schema）”是基于文本框的单章临时设定。
- 引入全局资产后，该文本框可以：
  a) 保留，作为对全局资产的临时补充说明。
  b) 逐步废弃，引导用户使用全局资产管理。
  (建议：暂时保留，并在 UI 上区分“全局资产”和“本章临时设定”)

## 6. 实施步骤与顺序

1. **Phase 1: 数据库与基础 API**
   - 定义模型、Schemas、Repositories、Routes，完成迁移。
2. **Phase 2: 前端基础管理功能**
   - 实现侧边栏的全局资产增删改查。
3. **Phase 3: 章节关联与编辑器 UI**
   - 实现章节与资产的关联 API，在 `ChapterEditorView.vue` 中增加选择组件。
4. **Phase 4: LLM Prompt 集成与状态更新**
   - 将资产信息注入到规划和生成的 Prompt 中，并集成到章节发布的快照提取流程中。