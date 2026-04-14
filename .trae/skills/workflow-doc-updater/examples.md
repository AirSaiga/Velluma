# Workflow Doc Updater - 使用示例

## 示例 1: 新增双轨架构

当用户完成了双轨架构的代码实现，需要更新文档：

**输入**:
```json
{
  "changed_files": [
    "backend/services/workflows/sketch_generator.py",
    "backend/services/workflows/adversarial_aligner.py",
    "backend/services/workflows/dual_track.py"
  ],
  "change_type": "new_phase",
  "change_description": "新增双轨对抗架构，包括短文生成器 (SketchGenerator) 和对抗校对器 (AdversarialAligner)",
  "affected_phases": ["4.5", "5.5"],
  "new_functions": [
    {
      "name": "SketchGenerator.generate",
      "line_start": 80,
      "line_end": 180,
      "description": "生成连贯速写短文，作为连贯性锚点"
    },
    {
      "name": "AdversarialAligner.align",
      "line_start": 70,
      "line_end": 180,
      "description": "对比 Draft 和 Sketch，检测差异并生成修复方案"
    }
  ],
  "new_config_options": [
    {
      "name": "enable_sketch_track",
      "type": "bool",
      "default": true,
      "description": "启用 Track B (短文生成)"
    },
    {
      "name": "alignment_threshold",
      "type": "float",
      "default": 70.0,
      "description": "对齐度阈值，低于此值触发精修"
    }
  ],
  "version_bump": "minor"
}
```

**Skill 执行操作**:
1. 在整体架构概览中添加 V4.0 双轨架构说明
2. 在 Phase 4 后插入 Phase 4.5: 双轨并行生成
3. 在 Phase 5 后插入 Phase 5.5: 对抗校对
4. 在 Prompt 汇总表添加 SKETCH_GEN 和 ADV_ALIGNMENT 行
5. 添加 V4.0 双轨配置表格
6. 更新版本号为 V4.0

---

## 示例 2: 修改 Drafting Prompt

当用户修改了 prose draft 的 prompt 构建函数：

**输入**:
```json
{
  "changed_files": [
    "backend/services/prompts/draft_prompts.py"
  ],
  "change_type": "modified_prompt",
  "change_description": "build_prose_draft_prompt_v25 新增 pov_perception_state 参数",
  "affected_phases": ["4"],
  "modified_functions": [
    {
      "name": "build_prose_draft_prompt_v25",
      "line_start": 749,
      "line_end": 999,
      "changes": "新增 pov_perception_state 参数，用于控制角色知觉状态"
    }
  ],
  "version_bump": "none"
}
```

**Skill 执行操作**:
1. 在 Phase 4: DRAFTING 章节更新 Prompt 构建说明
2. 更新关键变量表格，添加 pov_perception_state
3. 在 Prompt 汇总表更新 PROSE_DRAFT 行的关键变量列
4. 更新代码行号引用

---

## 示例 3: 修改配置参数

当用户修改了功能开关的默认值：

**输入**:
```json
{
  "changed_files": [
    "backend/schemas.py",
    "backend/services/workflows/drafting.py"
  ],
  "change_type": "modified_config",
  "change_description": "DraftingFeatureFlags 修改 fail_fast_max_attempts 默认值为 3",
  "affected_phases": ["4"],
  "modified_functions": [],
  "version_bump": "none"
}
```

**Skill 执行操作**:
1. 在 V4.0 功能开关配置表格中更新 fail_fast_max_attempts 的默认值
2. 在 Phase 4: DRAFTING 的 Fail-Fast 部分更新说明

---

## 使用提示词模板

当需要调用此 skill 时，可以使用以下提示词模板：

### 模板 1: 新增功能

```
我新增了 [功能名称]，请使用 workflow-doc-updater skill 更新 CHAPTER_GENERATION_WORKFLOW.md 文档。

变更文件：
- [文件1]
- [文件2]

新增函数：
- [函数名] (行 [start]-[end]): [描述]

影响阶段：[Phase X, Phase Y]

版本更新：[major/minor/none]
```

### 模板 2: 修改现有功能

```
我修改了 [功能名称]，请使用 workflow-doc-updater skill 更新文档。

变更文件：
- [文件]

修改内容：
- [函数名]: [变更描述]

需要更新的文档位置：
- [Phase X] 的 [具体章节]
```

### 模板 3: 自动检测（推荐）

```
我修改了以下工作流相关文件，请使用 workflow-doc-updater skill 分析变更并更新 CHAPTER_GENERATION_WORKFLOW.md 文档：

[列出修改的文件]

请：
1. 分析每个文件的变更内容
2. 确定需要更新的文档章节
3. 执行文档更新
4. 必要时更新版本号
```
