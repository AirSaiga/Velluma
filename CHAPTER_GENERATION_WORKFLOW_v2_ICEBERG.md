# Velluma 章节生成工作流 v2.0 - 冰山模型架构

## 概述

Velluma 的章节生成已升级至 **Iceberg Model（冰山模型/潜意识写作）** 架构，采用**双模型路由**策略，将"重度逻辑规划"与"沉浸式感官生成"解耦。

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    冰山模型架构 - 双模型路由                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   高逻辑模型 (Reasoning Model)        高创意模型 (Creative Model)            │
│   ├─ Scene Intent 分析                 └─ Prose Draft 正文起草              │
│   ├─ Subconscious 潜意识生成                                                │
│   ├─ Review 审阅                                                            │
│   └─ Refine 精修                                                            │
│                                                                             │
│   Cost = C_reasoning × Token_subconscious + C_creative × Token_prose        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 核心架构变更

### 1. 双模型路由 (Dual-Model Routing)

| 阶段 | 使用模型 | 说明 |
|-----|---------|------|
| **PLANNING** | Reasoning Model | Story Beats 拆分、POV 分配 |
| **SCENE_INTENT** | Reasoning Model | 场景意图分析（目标/风险/约束） |
| **SUBCONSCIOUS** | Reasoning Model | 生成角色内心独白（50-100字） |
| **DRAFTING_PROSE** | Creative Model | 基于潜意识的正文创作 |
| **REVIEWING** | Reasoning Model | OOC/逻辑/边界检查 |
| **REFINING** | Reasoning Model | 精准裁剪修复 |

**成本公式**：
```
总成本 = C_reasoning × (Token_scene_intent + Token_subconscious + Token_review)
       + C_creative × Token_prose
```

### 2. 冰山模型两层架构

```
水面之上（显性层）                    水面之下（隐性层）
┌─────────────────────┐              ┌─────────────────────────────┐
│  DRAFTING_PROSE     │              │  SUBCONSCIOUS               │
│  正文草稿           │◄─────────────│  角色内心独白（50-100字）      │
│                     │   驱动创作    │  - 我现在感觉如何？           │
│  - 动作描写         │              │  - 环境里最刺眼的是什么？      │
│  - 对话             │              │  - 我的本能反应是什么？        │
│  - 环境渲染         │              │                             │
└─────────────────────┘              └─────────────────────────────┘
            ▲                                      ▲
            │                                      │
            └────────── 极简输入 ──────────────────┘
            严禁传入：red_lines, exit_state, 庞大世界观
```

### 3. 混合流水线 (Rolling Prefix)

```
旧的并行模型：                        新的串行流水线：
┌─────────┐ ┌─────────┐              Beat 1: Subconscious₁ → Prose₁ → Tail₃₀₀
│  Beat 1 │ │  Beat 2 │ ─────►      Beat 2: Subconscious₂ + Tail₁ → Prose₂ → Tail₃₀₀
│  Draft  │ │  Draft  │   语气断裂   Beat 3: Subconscious₃ + Tail₂ → Prose₃ → Tail₃₀₀
└─────────┘ └─────────┘              
                                        公式: Contextₙ = Subconsciousₙ + LastTailₙ₋₁
```

**Rolling Prefix 机制**：
- Beat 1: 基于 `Subconscious_1` 生成 `Prose_1`，提取末尾 300 字符作为 `Tail_1`
- Beat 2: 基于 `Subconscious_2 + Tail_1` 生成 `Prose_2`，提取 `Tail_2`
- Beat N: 基于 `Subconscious_N + Tail_(N-1)` 生成 `Prose_N`

---

## 完整工作流

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         章节生成完整流程图 v2.0                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐                                                        │
│  │ ASSEMBLING_CTX  │  加载角色卡、关系网、RAG记忆、开放伏笔                   │
│  └────────┬────────┘                                                        │
│           ▼                                                                 │
│  ┌─────────────────┐     ┌─────────────────┐                                │
│  │    PLANNING     │────▶│  POV_ASSIGNMENT │  Anchor POV 确定              │
│  │  (Reasoning)    │     │  (Reasoning)    │                                │
│  └────────┬────────┘     └─────────────────┘                                │
│           ▼                                                                 │
│  ╔═══════════════════════════════════════════════════════════════════════╗  │
│  ║                        步骤 A: 并行生成轻量级思考                        ║  │
│  ║  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐             ║  │
│  ║  │  Beat 1        │ │  Beat 2        │ │  Beat N        │  (并行)      ║  │
│  ║  │  Scene Intent  │ │  Scene Intent  │ │  Scene Intent  │             ║  │
│  ║  │  (Reasoning)   │ │  (Reasoning)   │ │  (Reasoning)   │             ║  │
│  ║  ├────────────────┤ ├────────────────┤ ├────────────────┤             ║  │
│  ║  │  Subconscious  │ │  Subconscious  │ │  Subconscious  │             ║  │
│  ║  │  (Reasoning)   │ │  (Reasoning)   │ │  (Reasoning)   │             ║  │
│  ║  └────────────────┘ └────────────────┘ └────────────────┘             ║  │
│  ╚═══════════════════════════════════════════════════════════════════════╝  │
│                                    │                                        │
│                                    ▼                                        │
│  ╔═══════════════════════════════════════════════════════════════════════╗  │
│  ║                        步骤 B: 串行生成正文                             ║  │
│  ║                                                                       ║  │
│  ║  Beat 1:  Subconscious₁ ──▶ Prose₁ ──▶ Tail₃₀₀                       ║  │
│  ║                                    │                                  ║  │
│  ║                                    ▼                                  ║  │
│  ║  Beat 2:  Subconscious₂ + Tail₁ ──▶ Prose₂ ──▶ Tail₃₀₀               ║  │
│  ║                                    │                                  ║  │
│  ║                                    ▼                                  ║  │
│  ║  Beat 3:  Subconscious₃ + Tail₂ ──▶ Prose₃ ──▶ Tail₃₀₀               ║  │
│  ║                                                                       ║  │
│  ║  (Creative Model 驱动，Rolling Prefix 保证连贯性)                       ║  │
│  ╚═══════════════════════════════════════════════════════════════════════╝  │
│                                    │                                        │
│                                    ▼                                        │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐       │
│  │    STITCHING    │────▶│   REVIEWING     │────▶│    REFINING     │       │
│  │   (统稿合并)     │     │  (精准裁剪)      │     │  (局部修复)      │       │
│  │                 │     │  (Reasoning)    │     │  (Reasoning)    │       │
│  └─────────────────┘     └────────┬────────┘     └────────┬────────┘       │
│                                   │                       │               │
│                         ┌─────────┴─────────┐             │               │
│                         ▼                   ▼             │               │
│                      ┌────────┐       ┌────────┐         │               │
│                      │ 通过   │       │ 未通过 │─────────┘               │
│                      └────┬───┘       └────────┘                         │
│                           ▼                                               │
│  ┌───────────────────────────────────────────────────────────────────┐   │
│  │                    FINAL_TEXT_STREAM → DONE                        │   │
│  └───────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 各阶段详细说明

### 阶段 A: 并行轻量级思考

#### A-1. Scene Intent (场景意图)

**职责**：分析每个 Beat 的核心要素

**输出结构**：
```json
{
  "intent_label": "场景标签",
  "goal": "本场景目标",
  "stakes": "失败代价/风险",
  "constraints": ["约束条件1", "约束条件2"],
  "sensory_translation_rule": "感官转化法则（可选）"
}
```

**输入**：
- Beat summary
- Open hooks（关联伏笔）
- Chapter outline

**使用模型**：Reasoning Model (temperature=0.2)

#### A-2. Subconscious (潜意识)

**职责**：生成 POV 角色的内心独白，作为 Prose 的情感锚点

**约束**：
- 50-100 字
- 第一人称视角
- 回答三个核心问题：
  1. "我现在感觉如何？"（情绪、身体反应）
  2. "环境里最刺眼的是什么？"（视觉、听觉、触觉）
  3. "我接下来的本能反应是什么？"（直觉、冲动）

**示例**：
```
呼吸急促，手心出汗。那个身影在阴影中若隐若现——是敌人吗？
我必须冷静。手指不自觉地摸向腰间的配枪。
```

**使用模型**：Reasoning Model (temperature=0.6)

---

### 阶段 B: 串行正文生成 (Rolling Prefix)

#### B-1. Prose Draft (正文起草)

**职责**：基于潜意识独白和前文尾巴，沉浸式续写正文

**输入**：
- `subconscious_thought`: 50-100 字内心独白
- `previous_tail`: 上一个 Beat 的末尾 300 字符（Rolling Prefix）
- `scene_intent`: 场景意图

**严禁传入**：
- ❌ red_lines
- ❌ exit_state
- ❌ 庞大的世界观设定

**Rolling Prefix 机制**：
```python
# 提取文本末尾 300 字符
def _extract_tail(text: str, max_chars: int = 300) -> str:
    if len(text) <= max_chars:
        return text
    
    # 尝试从段落边界截取
    paragraphs = text.split("\n\n")
    tail_parts = []
    current_length = 0
    
    for para in reversed(paragraphs):
        if current_length + len(para) > max_chars:
            break
        tail_parts.insert(0, para)
        current_length += len(para)
    
    return "\n\n".join(tail_parts)
```

**使用模型**：Creative Model (temperature=0.75)

---

## 数据结构

### BeatDraftResult

```python
class BeatDraftResult(BaseModel):
    """Beat 生成结果（冰山模型）"""
    beat_id: str
    beat_index: int
    scene_intent: dict            # Scene Intent 分析结果
    subconscious_thought: str     # 潜意识独白（50-100字）
    draft_chunk: str              # 生成的小说正文
    prompts: List[dict]           # 调试用的提示词历史
```

### 双模型配置

```python
class GenerateChapterAgenticRequest(BaseModel):
    chapter_id: UUID
    api_key: str
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")  # 默认模型（向后兼容）
    reasoning_model: Optional[str] = Field(None, description="高逻辑模型")
    creative_model: Optional[str] = Field(None, description="高创意模型")
    # ... 其他字段
```

**模型选择逻辑**：
```python
# 后端解析
reasoning_model = request.reasoning_model or request.model
creative_model = request.creative_model or reasoning_model

# 前端调用
reasoning_model = apiConfig.reasoning_model || apiConfig.model
creative_model = apiConfig.creative_model || reasoning_model
```

---

## 精准裁剪策略 (Surgical Refinement)

### 问题背景

旧策略：Review 发现越界时，要求**全部重写**
- 破坏文本灵气
- 增加 token 消耗
- 延长生成时间

### 新策略：精准裁剪

只修改最后 1-3 句话，微调动作使其停在 exit_state：

**示例**：
```
原文结尾：
"他冲向门口，推开门，发现敌人已经在走廊尽头。"

target_exit_state: "准备开门，但未看到门外"

精准裁剪：
"他冲向门口，手搭在门把上，心跳如鼓。门后的未知让他迟疑了一瞬。"
```

### 实现

```python
async def surgical_refinement(
    draft_text: str,
    target_exit_state: str,
    model: str,
) -> str:
    """
    精准裁剪修复。
    
    策略：
    1. 定位越过 exit_state 的具体句子
    2. 微调结尾动作或添加收束句
    3. 保持原有语气和风格
    """
    system_prompt = """你是一个精准裁剪编辑。

任务：对文本进行**最小化修改**，使其停在指定的 exit_state 上。

核心原则：
1. **最小干预**：只修改最后 1-3 句话
2. **保持灵气**：保留原文的语气、节奏和情感张力
3. **精准收束**：通过微调动作或添加收束句，使文本停在 exit_state"""
    
    # ... 调用 LLM 进行裁剪
```

---

## Prompt 设计

### build_subconscious_prompt

**目标**：生成第一人称内心独白

**核心指令**：
```
你是{chapter_name}中角色【{pov_character}】的潜意识。

【核心要求】
1. 第一人称视角：必须是{ pov_character }的内心独白，用"我"开头
2. 感官直觉：专注回答三个问题：
   - 我现在感觉如何？
   - 环境里最刺眼/最异常的是什么？
   - 我接下来的本能反应是什么？
3. 简洁直接：无需华丽辞藻，像_raw_的意识流
4. 长度限制：严格控制在50-100个汉字之间

【禁止事项】
- 禁止解释背景设定
- 禁止预告未来剧情
- 禁止使用第三人称描述
- 禁止超过100字
```

### build_prose_draft_prompt

**目标**：沉浸式正文续写

**核心指令**：
```
你是专业小说写手。请根据提供的潜意识独白，沉浸式续写小说正文。

## 【核心任务】
将角色的内心独白转化为具象化的动作、对话和环境描写。

## 【叙事原则】
1. 单一视角锁定：绝对锁定在【{pov_character}】的感官范围内
2. 动作即性格：通过角色的动作选择展现性格，不要直接解释
3. 环境即情绪：让环境描写映射角色的心理状态
4. 对话即冲突：对话推动剧情，每句台词都要有目的

## 【反AI味协议】
1. 禁止设定倾倒：不要在动作中打断解释世界观
2. 禁止预告片旁白：严禁"命运的齿轮"这类虚词
3. 禁止形容词堆砌：一个名词前最多一个修饰语
4. Show, Don't Tell：直接描写物理反应，不要总结情绪

## 【续写要求】
- 目标字数：约 {target_words} 字
- 只输出正文，不要解释
- 段落之间用双换行符分隔
- 禁止使用 Markdown 格式

【前文尾巴 - 必须无缝衔接】
{previous_tail}

【角色潜意识独白 - 情感锚点】
{subconscious_thought}
```

---

## 性能与成本

### 时间复杂度

| 阶段 | 并行度 | 时间复杂度 |
|-----|--------|-----------|
| Scene Intent | N (Beats) | O(1) 并行 |
| Subconscious | N (Beats) | O(1) 并行 |
| Prose Draft | 1 (串行) | O(N) Rolling |
| Review | 1 | O(1) |
| **总计** | - | **O(N)** |

### 成本估算（2000字章节，5 Beats）

**双模型方案**（GPT-4o + Claude 3 Haiku）：
| 阶段 | 模型 | Tokens | 成本 |
|-----|------|--------|------|
| Scene Intent ×5 | GPT-4o | ~1,000 | $0.005 |
| Subconscious ×5 | GPT-4o | ~1,000 | $0.005 |
| Prose Draft ×5 | Claude Haiku | ~10,000 | $0.0125 |
| Review | GPT-4o | ~2,000 | $0.01 |
| **总计** | - | ~14,000 | **~$0.033** |

**对比纯 GPT-4o**：~$0.06，**成本降低 45%**

---

## 代码文件对应关系

| 功能模块 | 代码文件 | 说明 |
|---------|---------|------|
| 主工作流编排 | `backend/services/agentic_workflow.py` | 双模型配置解析、工作流调度 |
| 混合流水线 | `backend/services/workflows/drafting.py` | 并行 SceneIntent/Subconscious + 串行 Prose |
| 潜意识 Prompt | `backend/services/prompts/draft_prompts.py` | `build_subconscious_prompt()` |
| 正文 Prompt | `backend/services/prompts/draft_prompts.py` | `build_prose_draft_prompt()` |
| 精准裁剪 | `backend/services/workflows/reviewing.py` | `surgical_refinement()` |
| Review Prompt | `backend/services/prompts/review_prompts.py` | 精准裁剪策略指导 |
| 前端双模型设置 | `frontend/src/components/SettingsModal.vue` | 双模型开关 + 手动输入 |
| Payload 构建 | `frontend/src/composables/useAgenticConfig.ts` | `buildAgenticPayload()` |

---

## 向后兼容性

### 单模型模式（默认）

如果未配置双模型：
```javascript
// 前端
apiConfig = {
  model: 'gpt-4o',
  reasoning_model: '',  // 空
  creative_model: ''    // 空
}

// 后端解析
reasoning_model = request.reasoning_model or request.model  // = 'gpt-4o'
creative_model = request.creative_model or reasoning_model  // = 'gpt-4o'
```

所有阶段使用同一模型，行为与 v1.0 一致。

### 数据迁移

旧版本保存的配置只有 `model` 字段，打开设置面板时：
```javascript
formData.value = {
  ...props.config,
  reasoning_model: props.config.reasoning_model || '',  // 默认为空
  creative_model: props.config.creative_model || ''     // 默认为空
}
enableDualModel.value = !!(props.config.reasoning_model || props.config.creative_model)  // = false
```

用户需要手动开启双模型并配置。

---

## 最佳实践

### 推荐双模型配置

| 场景 | Reasoning | Creative | 说明 |
|-----|-----------|----------|------|
| 高性价比 | GPT-4o | Claude 3 Haiku | 质量与成本平衡 |
| 高质量 | Claude 3.5 Sonnet | Claude 3 Sonnet | 全 Claude 生态 |
| 低成本 | Gemini Flash | Gemini Flash | 单模型低成本 |
| 全国产 | Qwen-Max | Qwen-Plus | 阿里云生态 |

### Rolling Prefix 长度调优

| 长度 | 效果 | 适用场景 |
|-----|------|---------|
| 200 字符 | 轻量衔接 | 快节奏动作戏 |
| 300 字符（默认） | 平衡 | 通用场景 |
| 400 字符 | 强连贯 | 慢节奏情感戏 |

### 字数分配

```python
# 基于 pacing_type 的字数乘数
multipliers = {
    "Fast": 0.8,    # 快节奏：减少字数，增加紧张感
    "Medium": 1.0,  # 正常节奏
    "Slow": 1.2     # 慢节奏：增加字数，强化氛围
}
```

---

*文档版本: v2.0 (Iceberg Model)*
*最后更新: 2026-03-19*
