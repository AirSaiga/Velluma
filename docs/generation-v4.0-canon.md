# Velluma V4.0 — 涌泉架构（Canon + 一致性引擎 + 图谱可视化）

> **版本**：V4.0（Spring，涌泉）
> **状态**：全量开发中
> **日期**：2026-07-21
> **前置**：V3.2 ADF 引擎
> **核心定位转变**：从"基于已生成文本的生成器" → "维护作者脑中世界与已发布文本一致性的协同系统"

---

## 0. 设计动机的根本转变

### V3.x 的根本病灶

V3.0/V3.1/V3.2 所有版本都基于一个隐性假设：**"作者脑中的意图可以从已生成文本推断"**。这是错的。

经过多轮讨论确定的四个事实：
1. **作者有大量未写出的设定**（真相在脑中，不在文本里）
2. **作者高频即兴修改**（即兴是创作的核心，不是异常）
3. **作者愿意深度编辑，但平时看一眼就够**（双层 UI）
4. **作者需要主动提醒**（写作时实时一致性检查）

### V4.0 的核心定位

```
┌──────────────────────────────────────────┐
│  作者脑中的世界（The Author's Canon）★ 最高权威 │
│  作者随时编辑，AI 强制遵循                    │
└──────────────────────────────────────────┘
                   ↕
        ╔═══════════════════════════════╗
        ║  一致性维护层（系统核心）       ║
        ╚═══════════════════════════════╝
                   ↕
┌──────────────────────────────────────────┐
│  已发布文本（Published Text）              │
│  读者看到的，但未必是真相                   │
└──────────────────────────────────────────┘
```

**核心职责转变**：从"生成文本" → "维护两个世界的一致性"。生成是手段，一致性是目的。

---

## 1. 五大核心模块

| 模块 | 职责 | 核心原则 |
|---|---|---|
| **Canon** | 存作者脑子里的真相 | private 字段绝不泄露到正文 |
| **Reader Mirror** | 推断读者状态（期待/信息差/张力） | 纯推断，纯建议，无强制 |
| **Consistency Engine** | 维护 Canon ↔ Published Text 一致性 | 实时检查 + 即兴变更连锁分析 |
| **Generation Pipeline** | 把 Canon + 当前意图转化为正文 | 多工序（粗坯→精修→抛光） |
| **Author Interface** | 作者高效维护 Canon 和审阅 | 平时轻量默认，深度可展开 |

---

## 2. Canon 数据模型

### 2.1 设计哲学

- **图谱结构**（非扁平表单），节点 + 边
- **双层 visibility**（public = 已在正文写出 / private = 仅作者知道）
- **可追溯**（每个节点知道自己在哪些章节出现）
- **可规划**（每个 private 节点可标揭示计划）

### 2.2 节点（CanonNode）

```python
class CanonNode:
    id: UUID
    book_id: UUID
    type: NodeType  # CHARACTER | EVENT | OBJECT | PLACE | HOOK
    label: str       # 显示名（如"兰星"）
    
    # 内容（双层）
    canon_text: str       # 作者脑中的真相（完整）
    public_text: str      # 读者目前看到的描述（可能截断/伪装）
    
    # 可见性
    visibility: str       # public | private | partial
    
    # 章节追溯
    appeared_in: [int]    # 出现在哪些 chapter_number
    revealed_in: [int]    # 在哪些章被部分/全部揭示
    
    # 揭示计划
    reveal_plan: str      # 作者计划的揭示策略（自由文本）
    expected_reveal_chapter: int  # 预期揭示章节
    
    # 元数据
    tags: [str]
    confidence: str       # confirmed | tentative | draft
    source: str           # author | auto_extracted | mixed
    metadata: JSONB       # 自由扩展（角色字段/事件字段等）
    
    created_at, updated_at
```

**type 语义**：
- `CHARACTER`：角色（metadata 含 identity/power/motivation/arc_position）
- `EVENT`：事件（metadata 含 when/where/who/consequence）
- `OBJECT`：物件（metadata 含 owner/ability/origin）
- `PLACE`：地点（metadata 含 description/inhabitants）
- `HOOK`：伏笔节点（metadata 含 strength/bury_style/payoff_style/status）

### 2.3 边（CanonEdge）

```python
class CanonEdge:
    id: UUID
    book_id: UUID
    source_id: UUID  # CanonNode.id
    target_id: UUID  # CanonNode.id
    type: EdgeType   # 见下
    strength: int    # 1-10
    visibility: str  # public | private
    note: str        # 作者备注
    established_in: [int]  # 在哪些章建立
    metadata: JSONB
    created_at, updated_at
```

**type 六类**（来自网文叙事结构分析）：
- `CAUSES`：因果（A 导致 B）
- `BEFORE`：时序（A 在 B 之前）
- `HINTS`：弱伏笔暗示
- `SETUPS`：强伏笔铺设
- `CALLBACKS`：回收
- `ECHOES`：呼应（已回收后的二次呼应）

### 2.4 数据库表结构

两张新表（不改动现有表）：

```sql
CREATE TABLE canon_nodes (
    id UUID PRIMARY KEY,
    book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    type VARCHAR(20) NOT NULL,
    label VARCHAR(200) NOT NULL,
    canon_text TEXT DEFAULT '',
    public_text TEXT DEFAULT '',
    visibility VARCHAR(20) DEFAULT 'public',
    appeared_in JSONB DEFAULT '[]',
    revealed_in JSONB DEFAULT '[]',
    reveal_plan TEXT DEFAULT '',
    expected_reveal_chapter INTEGER,
    tags JSONB DEFAULT '[]',
    confidence VARCHAR(20) DEFAULT 'confirmed',
    source VARCHAR(20) DEFAULT 'author',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_canon_nodes_book ON canon_nodes(book_id);
CREATE INDEX idx_canon_nodes_type ON canon_nodes(book_id, type);

CREATE TABLE canon_edges (
    id UUID PRIMARY KEY,
    book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES canon_nodes(id) ON DELETE CASCADE,
    target_id UUID NOT NULL REFERENCES canon_nodes(id) ON DELETE CASCADE,
    type VARCHAR(20) NOT NULL,
    strength INTEGER DEFAULT 5,
    visibility VARCHAR(20) DEFAULT 'public',
    note TEXT DEFAULT '',
    established_in JSONB DEFAULT '[]',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_canon_edges_book ON canon_edges(book_id);
CREATE INDEX idx_canon_edges_source ON canon_edges(source_id);
CREATE INDEX idx_canon_edges_target ON canon_edges(target_id);
```

---

## 3. 一致性引擎（Consistency Engine）

### 3.1 三类检查

**类型 A：Private 字段泄露检测**（生成时 + 写作时）

扫描新章节正文，对照所有 `visibility=private` 的 CanonNode：
- 如果正文中出现 canon_text 的关键短语 → 警告"private 信息泄露"
- 如果正文中角色行为与 canon_text 矛盾（如撒谎但无铺垫）→ 警告"需要铺垫"

**类型 B：事实矛盾检测**（写作时实时）

检查新写入的文本是否与已建立的 public 事实矛盾：
- "兰星从来没伤害过人" vs Canon 里"兰星曾失手杀人"（public）
- 给出三种解释选项：角色撒谎 / 角色失忆 / 作者忘了

**类型 C：变更连锁分析**（即兴修改时）

作者改 Canon 一个节点/边，触发 N 跳邻居扫描：
- 找出所有受影响的节点
- 标注每个影响类型（直接矛盾 / 性质反转 / 需要铺垫）
- 给出处理建议

### 3.2 自动提取（写完一章后）

每章发布后，用 1 次 LLM 调用从正文提取候选节点和边：
- 候选节点进入"待确认队列"（不直接进 Canon）
- 作者审阅后一键确认 / 编辑 / 拒绝
- 已确认的节点 source 标记为 `auto_extracted` 或 `mixed`

---

## 4. Generation Pipeline 集成

### 4.1 Phase 0 增强

V3.2 ADF 的 Phase 0（CONTEXT_ASSEMBLING）增加 Canon 加载：

```
ctx = await _load_adf_context(...)
ctx["canon_nodes"] = await canon_repo.get_relevant_nodes(book_id, chapter_number)
ctx["canon_edges"] = await canon_repo.get_relevant_edges(book_id, chapter_number)
ctx["private_canon"] = filter_private(ctx["canon_nodes"])  # private 节点单独传
```

### 4.2 Prompt 注入

每个 prompt 增加 Canon 段落：

```
[作者脑中的真相 - ★ private 字段绝不许在正文直接写出]

## 角色真相
- 兰星 [private]：真实实力=弦月巅峰之上还有暗月 / 动机=为母亲复仇 / 已知=暗元素弦月巅峰
  → 你可以写她受辱时的隐忍，但绝不许直接写"她为母亲复仇"
- 老人 [public]：协会高层 / 实力深不可测
- 老人 [private]：与兰星是失散祖孙 / 计划 ch45 揭示
  → 绝不许让两人直接认出对方

## 必须埋设的伏笔（来自 Canon HOOK 节点）
- [HOOK_DARK_ELEMENT] strength=8 status=open：本章继续铺垫
- [HOOK_NEEDLE_STITCH] strength=6 status=open：可在这章回收

## 必须遵守的事实（来自 Canon public 节点）
- 兰星袖口有三毫米歪斜的针脚（第1章已建立）
- 老人在第1章已察觉弦月波纹（第1章已建立）
```

### 4.3 生成后的回写

每章生成后：
- 新出现的 public 事实 → 写入 CanonNode（source=auto_extracted，进待确认队列）
- 新埋的伏笔 → 写入 CanonNode（type=HOOK）
- 新建立的关系 → 写入 CanonEdge

---

## 5. 作者界面（前端）

### 5.1 三层视图

```
Layer 1: 章节生成面板（默认）
  - 章节生成时，侧栏显示"涉及 Canon 节点"
  - 一致性提醒实时显示
  
Layer 2: Canon 编辑器（深度编辑）
  - 角色卡（结构化表单 + 自由文本）
  - 关系列表（A → B：[类型][强度][可见性]）
  - 伏笔列表（status/strength/expected_reveal_chapter）
  
Layer 3: 图谱可视化（Cytoscape.js）
  - force-directed 布局（默认）
  - 多布局切换（时间线/角色分组/关系密度）
  - 节点点击编辑、边右键改类型
  - 过滤器（只看 private/只看悬空 HOOK/只看某角色）
  - 高亮某节点邻居、其他变灰
```

### 5.2 关键交互

**章节生成时的实时提示**：
```
作者正在写："兰星说：我从来没伤害过人"
→ 侧栏立即显示：
   ⚠ Canon 检查
   - 兰星有 [private] 设定："曾失手杀死平民"
   - 这可能是：
     a) 兰星撒谎（OK，角色可以撒谎）
     b) 兰星失忆（需要前文铺垫）
     c) 你忘了（建议改成"我没主动伤害过人"）
```

**即兴变更的连锁分析**：
```
作者在 Canon 加了"配角 A 背叛"
→ 弹窗显示：
   检测到 4 个受影响节点：
   1. [第2章兄弟情] 矛盾（建议加铺垫）
   2. [A送的礼物] 性质反转
   3. [主角独白×3] 需要修改
   4. [A背景故事] 不矛盾
   [逐个处理] [全部接受] [取消]
```

---

## 6. 实施清单（本会话全量完成）

### 后端
- [x] 设计文档（本文）
- [ ] `backend/models.py` 增加 `CanonNode` + `CanonEdge` ORM
- [ ] `backend/database.py` MIGRATIONS 加建表（首次启动自动创建）
- [ ] `backend/repositories/canon_repository.py` 节点/边 CRUD + 图查询
- [ ] `backend/repositories/__init__.py` 导出
- [ ] `backend/services/canon/extractor.py` 自动提取
- [ ] `backend/services/canon/consistency.py` 一致性检查
- [ ] `backend/services/canon/impact.py` 变更连锁分析
- [ ] `backend/routes/canon.py` REST API
- [ ] `backend/main.py` 注册路由
- [ ] V3.2 ADF 集成：`_load_adf_context` 加载 Canon

### 前端
- [ ] `frontend/src/services/api/domain/canon.api.ts` API 绑定
- [ ] `frontend/src/features/canon/` Canon feature 模块
  - `containers/CanonEditor.vue`（深度编辑容器）
  - `containers/CanonGraph.vue`（可视化容器）
  - `presentation/CharacterCardForm.vue`（角色卡表单）
  - `presentation/NodeEditModal.vue`（节点编辑弹窗）
  - `presentation/EdgeEditModal.vue`（边编辑弹窗）
  - `presentation/ConsistencyAlert.vue`（一致性提醒）
  - `presentation/PendingQueue.vue`（待确认队列）
  - `composables/useCanon.ts`（状态管理）
- [ ] `frontend/src/router/index.ts` 加 `/canon/:bookId` 路由
- [ ] `frontend/src/features/app/containers/AppRail.vue` 加导航项
- [ ] 集成到工作台（生成面板的侧栏）

### 依赖
- [ ] `frontend/package.json` 加 `cytoscape` + `cytoscape-fcose`

### 验证
- [ ] 后端 Python import 冒烟
- [ ] 前端 TS 类型检查
- [ ] Canon CRUD 端到端流程
