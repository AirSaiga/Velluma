# 双模型模式使用指南

## 概述

双模型架构（冰山模型）将文章生成过程分为两个阶段，使用不同的模型：
- **逻辑推理模型**：负责逻辑分析、规划、审阅
- **创意生成模型**：负责正文创作

## 模型使用范围

### 🔵 逻辑推理模型 (Reasoning Model)

用于以下功能：

| 功能 | 说明 |
|------|------|
| **Scene Intent 分析** | 分析场景目标、风险、约束 |
| **Subconscious 生成** | 生成角色内心独白 |
| **审阅/指导 (Critique)** | 检查 OOC、逻辑问题 |
| **灵感生成 (Inspiration)** | 生成剧情灵感 |
| **文本润色 (Optimize)** | 根据反馈优化文本 |
| **文本格式化 (Format)** | 段落排版整理 |
| **发布章节 (Publish)** | 生成摘要、更新角色状态 |
| **角色状态更新** | 分析角色动态变化 |

### 🟡 创意生成模型 (Creative Model)

仅用于：

| 功能 | 说明 |
|------|------|
| **Agentic 正文起草** | Prose Draft 阶段，Rolling Prefix 生成 |

### ⚪ 单模型模式（向后兼容）

当未启用双模型时，所有功能使用默认的 `model` 字段。

## 前端实现

### API 配置结构

```typescript
interface ApiConfig {
  api_key: string
  base_url: string
  model: string              // 默认模型（向后兼容）
  reasoning_model?: string   // 高逻辑模型
  creative_model?: string    // 高创意模型
  proxy_enabled?: boolean
  proxy_url?: string
}
```

### 模型选择优先级

```typescript
// 逻辑推理功能
const model = apiConfig.reasoning_model || apiConfig.model

// 创意生成功能（仅 Agentic）
const model = apiConfig.creative_model || apiConfig.reasoning_model || apiConfig.model
```

## 后端实现

### 请求模型

```python
class GenerateChapterAgenticRequest(BaseModel):
    chapter_id: UUID
    api_key: str
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")  # 默认模型
    reasoning_model: Optional[str] = Field(None, description="高逻辑模型")
    creative_model: Optional[str] = Field(None, description="高创意模型")
    # ... 其他字段
```

### 工作流分发

```python
# 双模型配置解析
reasoning_model = request.reasoning_model or request.model
creative_model = request.creative_model or reasoning_model

# 步骤 A: Scene Intent + Subconscious（并行）
scene_intent_results = await _generate_scene_intent_batch(
    model=reasoning_model
)
subconscious_results = await _generate_subconscious_batch(
    model=reasoning_model
)

# 步骤 B: Prose Draft（串行 Rolling Prefix）
prose_results = await _generate_prose_serial(
    model=creative_model  # 使用创意模型
)
```

## 推荐配置

### 高性价比方案
```javascript
{
  reasoning_model: 'gpt-4o',
  creative_model: 'claude-3-haiku-20240307'
}
```

### 高质量方案
```javascript
{
  reasoning_model: 'claude-3-5-sonnet-20241022',
  creative_model: 'claude-3-sonnet-20240229'
}
```

### 低成本方案
```javascript
{
  reasoning_model: 'google/gemini-2.0-flash-001',
  creative_model: 'google/gemini-2.0-flash-001'
}
// 实际上是单模型，但成本较低
```

## 成本估算

假设生成 2000 字章节，5 个 Beats：

| 阶段 | 模型 | Tokens | 成本 |
|------|------|--------|------|
| Scene Intent × 5 | GPT-4o | ~1000 | $0.005 |
| Subconscious × 5 | GPT-4o | ~1000 | $0.005 |
| Prose Draft × 5 | Claude 3 Haiku | ~10000 | $0.0125 |
| Review | GPT-4o | ~2000 | $0.01 |
| **总计** | - | ~14000 | **~$0.033** |

对比纯 GPT-4o：~$0.06，成本降低约 45%

## 常见问题

### Q: 为什么其他功能不使用双模型？

A: 其他功能（格式化、审阅、灵感等）通常不需要区分逻辑和创意：
- 格式化：纯规则任务
- 审阅：纯逻辑分析
- 灵感：创意为主，但不需要长文本生成

### Q: 如果只配置了 reasoning_model，creative_model 会怎样？

A: 会自动回退到 reasoning_model：
```python
creative_model = request.creative_model or reasoning_model
```

### Q: 双模型模式会增加多少延迟？

A: 不会增加延迟，因为 Scene Intent + Subconscious 是并行生成的。

### Q: 可以在生成过程中切换模型吗？

A: 不可以，模型配置在请求开始时确定，整个章节使用相同的配置。
