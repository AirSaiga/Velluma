# Workflow Document Updater Skill

## 用途

当后端生成流程代码发生变更时，自动同步更新 `CHAPTER_GENERATION_WORKFLOW.md` 文档，确保文档与代码实现保持一致。

## 触发条件

以下文件发生修改时，应调用此 Skill：
- `backend/services/workflows/*.py` (drafting.py, stitching.py, reviewing.py, refining.py, planning.py, dual_track.py, sketch_generator.py, adversarial_aligner.py)
- `backend/services/prompts/*.py`
- `backend/services/agentic_workflow.py`

## 工作流程

### 1. 分析代码变更

读取修改的文件，识别以下变更类型：
- **新增阶段/模块**: 新增的工作流阶段
- **修改 Prompt**: Prompt 模板、变量、结构的变更
- **修改配置**: 功能开关、阈值、参数的变更
- **修改输出格式**: 返回数据结构的变化
- **修改调用链**: 阶段间的依赖关系变化

### 2. 定位文档对应位置

根据文件路径定位文档中的对应章节：

| 代码文件 | 文档章节 |
|---------|---------|
| `planning.py` | Phase 2: PLANNING |
| `drafting.py` | Phase 4: DRAFTING |
| `stitching.py` | Phase 5: STITCHING |
| `sketch_generator.py` | Phase 4.5: 双轨并行生成 |
| `adversarial_aligner.py` | Phase 5.5: 对抗校对 |
| `reviewing.py` | Phase 6: REVIEWING |
| `refining.py` | Phase 7: REFINING |

### 3. 更新文档内容

根据变更类型执行对应的更新操作：

#### 新增阶段
```markdown
### Phase X: [阶段名]

**文件**: `backend/services/workflows/[file].py`

**核心函数**: `[function_name]()` (行 [start]-[end])

**职责**: [一句话描述]

**详细说明**: [关键实现细节]

**输入/输出**: [数据结构]
```

#### 修改 Prompt
- 更新 Prompt 模板引用
- 更新关键变量列表
- 更新温度等参数

#### 修改配置
- 更新功能开关表格
- 更新配置项说明

### 4. 检查关联更新

变更可能影响的其他文档部分：
- 整体架构概览图
- 数据流向图
- Prompt 汇总表
- 版本号

### 5. 更新版本号

文档版本格式: `V[主版本].[子版本]`

版本号递增规则：
- 重大架构变更: 主版本 +1 (如 V4.0 → V4.0)
- 新增阶段/功能: 子版本 +1 (如 V4.0 → V4.0)
- 细节修正: 不递增，只更新日期

## 文档结构规范

### Phase 章节模板

```markdown
### Phase N: [英文名（中文名）]

**文件**: `backend/services/workflows/[file].py`

**核心函数**: `[function_name]()` (行 [start]-[end])

**职责**: [一句话描述核心职责]

**详细说明**:
[实现细节、算法、关键逻辑]

**关键变量**:
| 变量 | 类型 | 用途 |
|------|------|------|
| `var_name` | type | description |

**输入/输出**:
- 输入: [输入数据结构]
- 输出: [输出数据结构]

**依赖**: [前置阶段]
```

### 表格更新规范

Prompt 汇总表列：阶段、Prompt 文件、核心函数、温度、关键变量

配置表格列：配置项、类型、默认值、说明

## 检查清单

更新完成后，确认以下项目：

- [ ] 新增/修改的 Phase 章节已更新
- [ ] Prompt 汇总表已同步
- [ ] 配置表格已同步
- [ ] 整体架构概览图已检查
- [ ] 数据流向图已检查
- [ ] 版本号和日期已更新
- [ ] 代码行号引用准确
- [ ] 文件路径引用准确

## 示例

### 示例 1: 新增双轨架构

**代码变更**: 新增 `sketch_generator.py` 和 `adversarial_aligner.py`

**文档更新**:
1. 在整体架构概览添加 V4.0 双轨架构说明
2. 在 Phase 4 和 Phase 5 之间插入 Phase 4.5
3. 在 Phase 5 和 Phase 6 之间插入 Phase 5.5
4. 在 Prompt 汇总表添加新行
5. 添加 V4.0 配置表格
6. 更新版本号为 V4.0

### 示例 2: 修改 Prompt 变量

**代码变更**: `build_prose_draft_prompt_v25()` 新增 `new_param` 参数

**文档更新**:
1. 在 Phase 4: DRAFTING 的"关键变量"表格添加新行
2. 在 Prompt 汇总表更新 PROSE_DRAFT 行的"关键变量"列
3. 更新代码行号引用

## 注意事项

1. **不要过度文档**: 只记录架构设计和关键逻辑，不要复制代码实现细节
2. **保持简洁**: 使用表格、列表、代码块提高可读性
3. **版本一致**: 确保文档版本与代码版本对应
4. **关联更新**: 检查变更对其他章节的影响
5. **行号准确**: 函数行号引用应与代码实际位置一致
