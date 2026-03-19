# 冰山模型架构升级指南

## 概述

已完成 Agentic Workflow 的核心架构升级，引入了**冰山模型（潜意识写作）**和**混合流水线（Rolling Prefix）**。

## 核心变更

### 1. 双模型路由（预留接口）

```python
# 当前：reasoning_model 和 creative_model 使用相同模型
# 后续：可通过配置切换为不同模型

execute_draft_stage(
    reasoning_model="gpt-4o",      # 高逻辑模型：Scene Intent + Subconscious
    creative_model="claude-3-haiku", # 高创意模型：Prose Draft
)
```

### 2. 混合流水线架构

```
步骤 A: 并行生成（无文本依赖）
├── Scene Intent（所有 Beats 并行）
└── Subconscious（所有 Beats 并行）

步骤 B: 串行生成（Rolling Prefix）
├── Beat 1: Subconscious_1 → Prose_1 → Tail_300
├── Beat 2: Subconscious_2 + Tail_1 → Prose_2 → Tail_300
└── Beat N: Subconscious_N + Tail_(N-1) → Prose_N
```

### 3. 新增数据结构

```python
class BeatDraftResult:
    beat_id: str
    beat_index: int
    scene_intent: dict           # 场景意图
    subconscious_thought: str    # 潜意识独白（50-100字）
    draft_chunk: str             # 生成正文
    prompts: List[dict]          # 调试历史
```

### 4. 新增 Prompt 函数

| 函数 | 职责 |
|-----|------|
| `build_subconscious_prompt()` | 生成 50-100 字第一人称内心独白 |
| `build_prose_draft_prompt()` | 极简输入，沉浸式续写正文 |

## 关键文件变更

| 文件 | 变更 |
|-----|------|
| `drafting.py` | **重写**：实现混合流水线核心逻辑 |
| `draft_prompts.py` | **扩展**：新增 subconscious 和 prose prompt |
| `agentic_workflow.py` | **修改**：集成新的 execute_draft_stage |
| `reviewing.py` | **扩展**：新增精准裁剪策略 |
| `review_prompts.py` | **扩展**：新增精修策略指导 |

## Review 精准裁剪策略

当 Draft 阶段越过 exit_state 时，Review Agent 现在采用**精准裁剪**而非**全部重写**：

### 示例

**原文结尾**：
```
他冲向门口，推开门，发现敌人已经在走廊尽头。
```

**目标 exit_state**：停在"准备开门，但未看到门外"

**精准裁剪**：
```
他冲向门口，手搭在门把上，心跳如鼓。门后的未知让他迟疑了一瞬。
```

### 优势
- 保留文本灵气和叙事节奏
- 只调整结尾边界
- 避免大幅删段导致的完整性损伤

## 回滚策略

如果新架构出现问题，可通过环境变量快速回滚：

```bash
# 创建环境变量文件
export ENABLE_LEGACY_DRAFTING=true

# 修改 agentic_workflow.py 中的条件判断
if os.getenv("ENABLE_LEGACY_DRAFTING") == "true":
    # 使用旧的并行生成
    generated_chunks = await generate_chunks_parallel(...)
else:
    # 使用新的混合流水线
    draft_results = await execute_draft_stage(...)
```

## 成本估算

新架构的成本分配：

```
Cost = C_reasoning × Token_subconscious + C_creative × Token_prose

示例（假设 GPT-4o + Claude 3 Haiku）：
- Scene Intent: ~200 tokens × $0.005 = $0.001
- Subconscious: ~150 tokens × $0.005 = $0.00075  
- Prose Draft: ~2000 tokens × $0.00025 = $0.50

单 Beat 成本: ~$0.502（比纯 GPT-4o 的 $0.60 略有下降）
```

## 测试建议

1. **语气连贯性测试**：检查 Beat 间过渡是否自然
2. **Subconscious 质量测试**：验证内心独白是否符合角色性格
3. **Prose 创意度测试**：对比新旧架构的输出质量
4. **边界合规性测试**：验证是否仍遵守 exit_state 约束

## 后续优化

1. **双模型切换**：实现 reasoning_model 和 creative_model 的配置化切换
2. **Tail 长度调优**：测试 200/300/400 字符的 Rolling Prefix 效果
3. **Subconscious 长度调优**：测试 50/100/150 字的效果
4. **并行度优化**：Scene Intent 和 Subconscious 的并发控制
