# Velluma 后端文章生成全流程技术文档

## 版本信息
- **版本**: v2.5 Cognitive Streaming
- **更新日期**: 2026-03-19
- **架构**: Agentic Workflow + 双模型路由 + 冰山模型

---

## 目录

1. [架构概览](#1-架构概览)
2. [核心数据模型](#2-核心数据模型)
3. [完整生成流程](#3-完整生成流程)
4. [各阶段详细说明](#4-各阶段详细说明)
5. [参数全解](#5-参数全解)
6. [错误处理与重试机制](#6-错误处理与重试机制)
7. [性能与成本优化](#7-性能与成本优化)

---

## 1. 架构概览

### 1.1 系统架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Velluma 文章生成系统                               │
│                           (v2.5 Cognitive Streaming)                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │   Frontend   │───▶│   FastAPI    │───▶│   Workflow   │                  │
│  │  (Vue3)      │◀───│   Backend    │◀───│   Engine     │                  │
│  └──────────────┘    └──────────────┘    └──────┬───────┘                  │
│                                                  │                          │
│                           ┌──────────────────────┼──────────────────────┐   │
│                           ▼                      ▼                      ▼   │
│                    ┌────────────┐        ┌────────────┐        ┌─────────┐ │
│                    │ Reasoning  │        │  Creative  │        │  RAG    │ │
│                    │   Model    │        │   Model    │        │ Engine  │ │
│                    │(Scene/Sub) │        │  (Prose)   │        │(Memory) │ │
│                    └────────────┘        └────────────┘        └─────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 双模型架构

| 模型类型 | 职责 | 典型模型 | 成本特点 |
|---------|------|---------|---------|
| **Reasoning Model** | 逻辑推理、规划、审查、断言 | GPT-4o, Claude 3.5 Sonnet | 高逻辑、中等成本 |
| **Creative Model** | 创意生成、正文撰写、润色 | GPT-4o-mini, Gemini Flash | 高创意、低成本 |

**成本公式**: 
```
Total Cost = (C_reasoning × Token_reasoning) + (C_creative × Token_creative)
```

### 1.3 核心设计哲学

1. **冰山模型**: 将逻辑规划（水下）与创意生成（水面）解耦
2. **Cognitive Streaming**: 模拟人类写作的连续认知流
3. **Fail-Fast**: 即时断言，早期拦截错误
4. **Rolling Prefix**: 滑动窗口上下文，保证语气连贯

---

## 2. 核心数据模型

### 2.1 请求模型 (GenerateChapterAgenticRequest)

```python
class GenerateChapterAgenticRequest(BaseModel):
    # ===== 基础配置 =====
    chapter_id: UUID                          # 章节唯一标识
    api_key: str                              # LLM API Key
    base_url: Optional[str] = None            # 自定义 API 端点
    model: str = "gpt-4o-mini"                # 默认模型（向后兼容）
    
    # ===== 双模型配置 (v2.0+) =====
    reasoning_model: Optional[str] = None     # 高逻辑模型
    creative_model: Optional[str] = None      # 高创意模型
    
    # ===== 生成控制 =====
    word_count: int = 2000                    # 目标字数
    author_intent: Optional[str] = None       # 作者创作意图
    max_iterations: int = 2                   # 最大重写次数 (1-5)
    fast_mode: bool = False                   # 快速模式（跳过重写）
    skip_minor_refine: bool = True            # 轻微问题跳过重写
    tension_level: Optional[int] = None       # 剧情张力等级 (1-10)
    pacing_style: Optional[str] = None        # 叙事节奏偏好
    
    # ===== RAG 配置 =====
    rag_top_k: int = 3                        # 检索记忆数量
    rag_alpha: float = 0.6                    # 语义相似度权重
    rag_beta: float = 0.2                     # 时间衰减权重
    rag_gamma: float = 0.2                    # 剧情伏笔权重
    rag_lambda: float = 0.1                   # 时间衰减系数
    
    # ===== v2.5 功能开关 =====
    feature_flags: Optional[DraftingFeatureFlags] = None
```

### 2.2 功能开关 (DraftingFeatureFlags)

```python
class DraftingFeatureFlags(BaseModel):
    # Feature A: Fail-Fast 断言与回溯
    enable_fail_fast: bool = True
    fail_fast_max_attempts: int = 2           # 最大重试次数 (1-3)
    fail_fast_temperature_step: float = 0.2   # 每次重试温度增量
    
    # Feature B: 情绪暂存器
    enable_emotional_scratchpad: bool = True
    
    # Feature C: RAG 记忆暂存（预留）
    enable_whisper_memory: bool = False
```

### 2.3 动态上下文 (DynamicContext)

```python
class DynamicContext(BaseModel):
    previous_tail: str = ""                   # Rolling Prefix (上一 Beat 末尾 300 字)
    current_emotional_state: str = "初始状态：未知"  # 当前心理状态
    physical_state_lock: str = ""             # 物理状态锁定（防幻觉）
    active_whispers: Dict[str, str] = {}      # 激活的 RAG 记忆（预留）
```

### 2.4 Story Beat 模型

```python
class ConfirmedStoryBeat(BaseModel):
    position: int                             # Beat 位置索引 (从1开始)
    beat_id: Optional[str] = None             # Beat 唯一标识
    summary: str                              # 剧情概述（核心）
    location: Optional[str] = None            # 场景地点
    pov_character: Optional[str] = None       # 视角角色
    action_summary: Optional[str] = None      # 动作化执行摘要
    worldbuilding_instruction: Optional[str] = None  # 世界观指令
    entry_state: Optional[str] = None         # 切入状态（物理+心理）
    exit_state: Optional[str] = None          # 收束状态
    red_lines: List[str] = []                 # 红线约束
    word_count_target: int = 0                # 目标字数
    target_words: int = 0                     # 兼容字段
    hook_ids: List[str] = []                  # 关联伏笔 ID
    pacing_type: Optional[str] = None         # 节奏类型 (Fast/Medium/Slow)
    weight: int = 1                           # 权重 (1-5)
```

### 2.5 生成结果 (BeatDraftResult)

```python
class BeatDraftResult(BaseModel):
    beat_id: str                              # Beat 标识
    beat_index: int                           # Beat 索引
    scene_intent: dict                        # Scene Intent 分析结果
    subconscious_thought: str                 # 潜意识独白 (50-100字)
    draft_chunk: str                          # 生成的正文
    prompts: List[dict] = []                  # 调试用的 Prompt 历史
```

---

## 3. 完整生成流程

### 3.1 主流程图

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                           execute_agentic_workflow()                            │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  [INIT] 初始化阶段                                                               │
│    ├── 加载章节、书籍、角色、关系数据                                              │
│    ├── 确定双模型配置 (reasoning_model / creative_model)                         │
│    └── 初始化 PerformanceMetrics                                                 │
│                                                                                 │
│  [PLANNING] 规划阶段 ( reasoning_model )                                         │
│    ├── 构建 Planner Prompt                                                       │
│    ├── 调用 LLM 生成 Story Beats                                                 │
│    └── 解析并验证 Beats 结构                                                     │
│                                                                                 │
│  [ENTITY_SNAPSHOT] 实体快照 ( reasoning_model )                                  │
│    ├── 为每个 Beat 分配 POV 角色                                                 │
│    └── 生成实体状态摘要                                                          │
│                                                                                 │
│  [RAG_MEMORY] 记忆检索                                                           │
│    ├── 计算 Beat 向量表示                                                        │
│    ├── 检索相关记忆 (Top-K)                                                      │
│    └── 按权重排序 (alpha/beta/gamma/lambda)                                      │
│                                                                                 │
│  [DRAFTING] 起草阶段 ( 双模型协作 )                                               │
│    ├── 步骤 A: 并行生成 Scene Intent (reasoning_model)                          │
│    ├── 步骤 A: 并行生成 Subconscious (reasoning_model)                          │
│    └── 步骤 B: 串行生成 Prose (creative_model + DynamicContext)                 │
│         ├── 初始化 DynamicContext                                               │
│         ├── For each Beat:                                                      │
│         │    ├── Fail-Fast 重试循环 (while attempts < max)                      │
│         │    │    ├── 构建 V25 Prompt (物理锁 + 情绪暂存器)                      │
│         │    │    ├── 调用 Creative Model 生成正文                               │
│         │    │    └── 微审查断言 (reasoning_model)                              │
│         │    ├── QC 质检与修复 (可选)                                            │
│         │    ├── 更新 DynamicContext                                            │
│         │    │    ├── 提取 Tail → previous_tail                                │
│         │    │    └── 更新情绪 → emotional_state                               │
│         │    └── 收集结果                                                       │
│         └── 返回 BeatDraftResult 列表                                           │
│                                                                                 │
│  [STITCHING] 统稿阶段 ( creative_model )                                         │
│    ├── 合并所有 Beat 的正文片段                                                  │
│    ├── 构建统稿 Prompt (处理过渡与衔接)                                          │
│    └── 调用 LLM 生成连贯章节                                                     │
│                                                                                 │
│  [REVIEWING] 审阅阶段 ( reasoning_model )                                        │
│    ├── 构建审阅 Prompt                                                           │
│    ├── 调用 LLM 评估质量                                                         │
│    └── 解析 ReviewResult                                                         │
│                                                                                 │
│  [DECISION] 决策节点                                                             │
│    ├── IF passed: 进入 FORMATTING                                               │
│    ├── IF minor issues AND skip_minor_refine: 进入 FORMATTING                   │
│    └── IF major issues AND iteration < max_iterations: 进入 REFINING            │
│                                                                                 │
│  [REFINING] 精炼阶段 ( creative_model )                                          │
│    ├── 构建精炼 Prompt                                                           │
│    ├── 调用 LLM 重写问题段落                                                     │
│    └── 返回精炼后的正文                                                          │
│        └── Loop back to REVIEWING                                               │
│                                                                                 │
│  [FORMATTING] 格式化阶段 ( creative_model )                                      │
│    ├── 构建格式化 Prompt                                                         │
│    ├── 调用 LLM 整理排版                                                         │
│    └── 输出最终章节                                                              │
│                                                                                 │
│  [PERSISTENCE] 持久化阶段                                                        │
│    ├── 保存 draft_text 到数据库                                                  │
│    ├── 更新 chapter 状态                                                         │
│    └── 记录迭代历史                                                              │
│                                                                                 │
└────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 流程状态机

```
                    ┌─────────────┐
                    │    INIT     │
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │  PLANNING   │
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │   ENTITY    │
                    │  SNAPSHOT   │
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │  RAG_MEMORY │
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐     ┌──────────┐
                    │   DRAFTING  │────▶│  Failed  │
                    └──────┬──────┘     └──────────┘
                           ▼
                    ┌─────────────┐
                    │  STITCHING  │
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │  REVIEWING  │
                    └──────┬──────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌────────────┐  ┌────────────┐  ┌────────────┐
    │   PASSED   │  │   MINOR    │  │   MAJOR    │
    └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
          │               │               │
          │    ┌──────────┘               │
          │    ▼                          ▼
          │  ┌────────────┐        ┌────────────┐
          │  │  FORMAT-   │        │  REFINING  │◀────┐
          │  │   TING     │        └─────┬──────┘     │
          │  └─────┬──────┘              │            │
          │        ▼                     │ max_iter   │
          │   ┌──────────┐               │ exceeded   │
          └──▶│  DONE    │◀──────────────┴────────────┘
              └──────────┘
```

---

## 4. 各阶段详细说明

### 4.1 [INIT] 初始化阶段

**函数**: `execute_agentic_workflow()` 入口

**参数读取**:
```python
# 从请求中提取
chapter_id = request.chapter_id
api_key = request.api_key
base_url = request.base_url

# 双模型路由
reasoning_model = request.reasoning_model or request.model  # 默认回退
creative_model = request.creative_model or reasoning_model

# 功能开关
feature_flags = request.feature_flags or DraftingFeatureFlags()

# RAG 参数
rag_top_k = request.rag_top_k
rag_weights = {alpha, beta, gamma, lambda}
```

**数据库查询**:
```sql
-- 章节信息
SELECT * FROM chapters WHERE id = :chapter_id

-- 书籍信息
SELECT * FROM books WHERE id = :book_id

-- 关联角色
SELECT c.* FROM characters c
JOIN chapter_entities ce ON c.id = ce.entity_id
WHERE ce.chapter_id = :chapter_id

-- 角色关系
SELECT * FROM character_relationships
WHERE book_id = :book_id AND is_public = true

-- 开放伏笔
SELECT * FROM plot_ledgers
WHERE book_id = :book_id AND status = 'open'

-- 地图地点
SELECT l.* FROM map_locations l
JOIN chapter_map_locations cml ON l.id = cml.location_id
WHERE cml.chapter_id = :chapter_id
```

---

### 4.2 [PLANNING] 规划阶段

**函数**: `_run_planner_agent()`

**输入参数**:
| 参数 | 来源 | 作用 |
|-----|------|------|
| `chapter` | DB | 提供章节大纲、标题、基调 |
| `book` | DB | 提供世界观设定、全局系统提示 |
| `entities` | DB | 角色静态/动态状态 |
| `relationships` | DB | 角色互动约束 |
| `word_count` | Request | 目标字数 |
| `author_intent` | Request | 作者创作意图 |

**Prompt 构建** (`build_planner_agent_prompt`):
```
System Prompt:
├── 全局系统提示 (book.global_sys_prompt)
├── 世界观设定 (book.worldview_settings)
├── 角色静态设定 (entities.static_prompt)
├── 角色动态状态 (entities.dynamic_state)
└── 角色关系约束 (relationships.interaction_prompt)

User Prompt:
├── 章节名与标题
├── 章节大纲 (outline_text)
├── 作者意图 (author_intent)
├── 目标字数 (word_count)
└── 张力等级与节奏偏好
```

**输出**:
```python
{
    "beats": [
        {
            "position": 1,
            "beat_id": "beat-001",
            "summary": "剧情概述...",
            "location": "场景地点",
            "pov_character": "视角角色",
            "action_summary": "动作摘要",
            "entry_state": "切入状态",
            "exit_state": "收束状态",
            "red_lines": ["红线1", "红线2"],
            "word_count_target": 400,
            "hook_ids": ["hook-001"]
        }
    ]
}
```

---

### 4.3 [ENTITY_SNAPSHOT] 实体快照

**函数**: `assign_pov_to_beats()`

**处理逻辑**:
1. 分析每个 Beat 的剧情需求
2. 从 `entities` 中选择最合适的 POV 角色
3. 考虑因素:
   - 角色在场性 (Beat 中是否涉及该角色)
   - 角色重要性 (importance_level)
   - 视角连续性 (与前/后 Beat 的连贯性)

**输出**: 每个 Beat 附加 `pov_character` 字段

---

### 4.4 [RAG_MEMORY] 记忆检索

**函数**: `MemoryRepository.search_memories()`

**参数**:
| 参数 | 默认值 | 说明 |
|-----|--------|------|
| `query_embedding` | - | Beat 的向量表示 |
| `top_k` | 3 | 返回记忆数量 |
| `alpha` | 0.6 | 语义相似度权重 |
| `beta` | 0.2 | 时间衰减权重 |
| `gamma` | 0.2 | 剧情伏笔权重 |
| `lambda` | 0.1 | 时间衰减系数 |

**评分公式**:
```
Score = alpha × semantic_score + 
        beta × time_decay_score + 
        gamma × plot_relevance_score
```

**输出**: `List[MemoryChunk]`

---

### 4.5 [DRAFTING] 起草阶段 (核心)

**主函数**: `execute_draft_stage()`

#### 4.5.1 步骤 A: 并行轻量级思考层

**A-1: Scene Intent 生成**

**函数**: `_generate_scene_intent_batch()`

**Prompt 构建** (`build_scene_intent_prompt`):
```python
{
    "intent_label": "意图标签",      # 如"说服"、"追逐"
    "goal": "场景目标",              # 角色要达成的目标
    "obstacle": "障碍",              # 需要克服的困难
    "tactic": "策略",                # 达成目标的手段
    "stakes": "风险",                # 失败的后果
    "constraints": ["约束1", "约束2"], # 额外约束
    "sensory_translation_rule": "感官转化规则"  # 可选
}
```

**参数**:
| 参数 | 值 |
|-----|-----|
| Model | `reasoning_model` |
| Temperature | 0.2 (低，确定性) |
| Max Tokens | 600 |
| Response Format | JSON Object |

**并发控制**: 所有 Beat 同时发起请求

**A-2: Subconscious 生成**

**函数**: `_generate_subconscious_batch()`

**Prompt 构建** (`build_subconscious_prompt`):
- **系统角色**: "你是角色的潜意识"
- **任务**: 生成 50-100 字第一人称内心独白
- **核心问题**:
  1. "我现在感觉如何？"
  2. "环境里最刺眼的是什么？"
  3. "我接下来的本能反应是什么？"

**参数**:
| 参数 | 值 |
|-----|-----|
| Model | `reasoning_model` |
| Temperature | 0.6 (中等，允许情感波动) |
| Max Tokens | 200 |

**输出示例**:
```
心脏跳得厉害。空气中有一股焦糊味。我得快点离开这里。
```

#### 4.5.2 步骤 B-V25: 串行正文生成

**函数**: `_generate_prose_serial_v25()`

**DynamicContext 初始化**:
```python
dynamic_context = DynamicContext(
    previous_tail="",                              # 初始为空
    current_emotional_state=beats[0].entry_state,  # 从 entry_state 提取
    physical_state_lock=physical_state_lock,       # 外部传入或从 entry_state 提取
    active_whispers={}
)
```

**Beat 循环处理**:

```python
for i, beat in enumerate(beats):
    # ===== Fail-Fast 重试循环 =====
    max_attempts = flags.fail_fast_max_attempts if flags.enable_fail_fast else 1
    attempt = 0
    current_temp = 0.75
    
    while attempt < max_attempts:
        attempt += 1
        
        # 1. 构建 V25 增强 Prompt
        system_prompt, user_prompt = build_prose_draft_prompt_v25(
            chapter=chapter,
            book=book,
            beat=beat,
            scene_intent=scene_intent_results[i],
            subconscious_thought=subconscious_results[i],
            previous_tail=dynamic_context.previous_tail,
            target_words=target_words,
            physical_state_lock=dynamic_context.physical_state_lock,      # Feature A
            current_emotional_state=dynamic_context.current_emotional_state  # Feature B
        )
        
        # 2. 调用 Creative Model 生成正文
        response = await call_llm(
            model=creative_model,
            temperature=current_temp,
            ...
        )
        chunk_text = clean_llm_output(response)
        
        # 3. Fail-Fast 断言检查 (Feature A)
        if flags.enable_fail_fast and attempt < max_attempts:
            is_valid, fail_reason = await _micro_review_assertion(
                chunk_text=chunk_text,
                dynamic_context=dynamic_context,
                pov_character=pov_character,
                api_key=api_key,
                base_url=base_url,
                model=reasoning_model  # 使用 reasoning model 做断言
            )
            
            if not is_valid:
                print(f"[Fail-Fast] Beat {beat_index} 断言失败: {fail_reason}")
                current_temp = min(1.0, current_temp + flags.fail_fast_temperature_step)
                continue  # 重试
            else:
                break  # 通过，退出重试循环
    
    # ===== 更新 DynamicContext =====
    # 1. 更新 Rolling Prefix
    dynamic_context.previous_tail = _extract_tail(chunk_text, max_chars=300)
    
    # 2. 更新情绪暂存器 (Feature B)
    if flags.enable_emotional_scratchpad:
        new_emotion = await _update_emotional_state(
            chunk_text=chunk_text,
            current_emotional_state=dynamic_context.current_emotional_state,
            pov_character=pov_character,
            api_key=api_key,
            base_url=base_url,
            model=reasoning_model
        )
        dynamic_context.current_emotional_state = new_emotion
```

**Prompt 结构** (`build_prose_draft_prompt_v25`):

```
System Prompt:
├── 【核心任务】将潜意识独白转化为具象化描写
├── 【叙事原则】
│    ├── 单一视角锁定
│    ├── 动作即性格
│    ├── 环境即情绪
│    └── 对话即冲突
├── 【物理边界锁定 (Physical State Lock) - 最高优先级】  # Feature A
│    ├── 当前物理状态: {physical_state_lock}
│    ├── 禁止行为清单
│    └── 检查清单
├── 【当前心理状态 (Emotional Scratchpad)】  # Feature B
│    ├── 当前心境: {current_emotional_state}
│    └── 情绪连贯性要求
├── 【节奏控制】
│    └── 根据 pacing_type (Fast/Medium/Slow) 调整
├── 【反AI味协议】
│    ├── 禁止设定倾倒
│    ├── 禁止预告片旁白
│    ├── 禁止形容词堆砌
│    ├── Show, Don't Tell
│    └── 短句制造紧张
└── 【文风控制】
     ├── 黄金锚点 (golden_snippets)
     └── 黑名单 (style_blacklist)

User Prompt:
├── 【POV角色】{pov_character}
├── 【当前场景】{location}
├── 【场景目标】{intent_goal}
├── 【角色潜意识独白 - 情感锚点】{subconscious_thought}
├── 【前文尾巴 - 必须无缝衔接】{previous_tail}  # Rolling Prefix
└── 【约束条件】{intent_constraints}
```

**Fail-Fast 断言** (`_micro_review_assertion`):

```python
# Prompt: build_micro_review_prompt
{
    "role": "无情的物理与逻辑断言机",
    "task": "检查文本是否存在物理/逻辑硬伤",
    "check_items": [
        "物理状态冲突: 肉身喷火、徒手举重物等",
        "装备/能力幻觉: 凭空使用不存在的装备",
        "实体混淆: 已摧毁物体重现、不存在角色说话",
        "时空错乱: 无逻辑的时间跳跃"
    ],
    "output_format": {
        "pass_check": bool,
        "reason": "失败原因（一句话）"
    }
}
```

**参数**:
| 参数 | 值 |
|-----|-----|
| Model | `reasoning_model` |
| Temperature | 0.0 (完全确定) |
| Max Tokens | 200 |
| Response Format | JSON Object |

**情绪更新** (`_update_emotional_state`):

```python
# Prompt: build_emotional_update_prompt
{
    "role": "心理学观察员",
    "task": "总结角色心理状态的微小演变",
    "requirements": [
        "20字以内",
        "聚焦演变而非状态",
        "体现因果关联"
    ],
    "examples": [
        "从惊恐万分转变为肾上腺素飙升的疯狂求生欲",
        "挫败感被冷静计算取代，开始寻找反击机会"
    ]
}
```

**参数**:
| 参数 | 值 |
|-----|-----|
| Model | `reasoning_model` (轻量级即可) |
| Temperature | 0.3 |
| Max Tokens | 100 |

---

### 4.6 [STITCHING] 统稿阶段

**函数**: `_run_stitching()`

**输入**:
- `draft_chunks`: List[str] - 所有 Beat 的正文片段
- `beats`: List[dict] - Beat 元数据

**Prompt 构建** (`build_stitch_prompt`):
```
任务: 将多个 Beat 的正文片段拼接成连贯章节
输入:
├── Beat 1: [正文片段1]
├── Beat 2: [正文片段2]
└── ...

处理要求:
├── 消除段落间的重复内容
├── 平滑过渡 Beat 边界
├── 统一叙事时态和人称
└── 保持整体文风一致
```

**输出**: 完整的章节正文

---

### 4.7 [REVIEWING] 审阅阶段

**函数**: `_run_review_agent()`

**输入**:
- `stitched_text`: str - 统稿后的完整正文
- `beats`: List[dict] - 原始 Beat 计划

**Prompt 构建** (`build_review_agent_prompt`):
```
角色: 资深小说编辑

评估维度:
├── 红线检查 (red_lines)
│   └── 是否违反任何红线约束
├── OOC检查 (out_of_character)
│   └── 角色行为是否符合设定
├── 剧情连贯性 (coherence)
│   └── Beat 间过渡是否自然
├── 完整性 (completeness)
│   └── 是否覆盖所有计划剧情
└── 文风一致性 (style)
    └── 是否符合书籍文风

输出格式:
{
    "passed": bool,
    "score": int,  # 0-100
    "issues": [
        {
            "category": "红线/OOC/连贯性/完整性/文风",
            "severity": "致命/严重/轻微",
            "description": "问题描述",
            "location": "问题位置（段落/句子）"
        }
    ],
    "revision_instruction": "重写指令"
}
```

**输出**: `ReviewResult`

---

### 4.8 [REFINING] 精炼阶段

**函数**: `_run_refine_agent()`

**触发条件**:
- Review 未通过
- `iteration < max_iterations`
- 问题严重程度为"致命"或"严重"

**输入**:
- `current_text`: str - 当前正文
- `issues`: List[dict] - Review 发现的问题
- `revision_instruction`: str - 重写指令

**Prompt 构建** (`build_refine_agent_prompt`):
```
任务: 根据审阅意见重写问题段落

输入:
├── 当前正文
├── 问题列表
└── 重写指令

要求:
├── 仅修改问题段落，保持其他部分不变
├── 保留原有文风
└── 确保修改后的段落与其他部分自然衔接
```

**输出**: 精炼后的正文

---

### 4.9 [FORMATTING] 格式化阶段

**函数**: `_run_formatting()`

**输入**:
- `final_text`: str - 最终正文

**处理内容**:
1. 段落规范化（统一换行符）
2. 标点符号规范化
3. 去除多余空格
4. 对话格式统一
5. 章节标题格式化

**输出**: 格式化后的最终正文

---

## 5. 参数全解

### 5.1 请求参数

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| `chapter_id` | UUID | ✅ | - | 章节唯一标识 |
| `api_key` | str | ✅ | - | LLM API Key |
| `base_url` | str | ❌ | null | 自定义 API 端点 |
| `model` | str | ❌ | "gpt-4o-mini" | 默认模型 |
| `reasoning_model` | str | ❌ | null | 高逻辑模型 |
| `creative_model` | str | ❌ | null | 高创意模型 |
| `word_count` | int | ❌ | 2000 | 目标字数 |
| `author_intent` | str | ❌ | null | 作者意图 |
| `max_iterations` | int | ❌ | 2 | 最大重写次数 (1-5) |
| `fast_mode` | bool | ❌ | false | 快速模式 |
| `skip_minor_refine` | bool | ❌ | true | 跳过轻微问题重写 |
| `tension_level` | int | ❌ | null | 张力等级 (1-10) |
| `pacing_style` | str | ❌ | null | 节奏偏好 |
| `rag_top_k` | int | ❌ | 3 | 记忆检索数量 |
| `rag_alpha` | float | ❌ | 0.6 | 语义权重 |
| `rag_beta` | float | ❌ | 0.2 | 时间权重 |
| `rag_gamma` | float | ❌ | 0.2 | 伏笔权重 |
| `rag_lambda` | float | ❌ | 0.1 | 衰减系数 |
| `feature_flags` | object | ❌ | {} | 功能开关 |

### 5.2 FeatureFlags 参数

| 参数名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_fail_fast` | bool | true | 启用断言检查 |
| `fail_fast_max_attempts` | int | 2 | 最大重试次数 |
| `fail_fast_temperature_step` | float | 0.2 | 重试温度增量 |
| `enable_emotional_scratchpad` | bool | true | 启用情绪暂存器 |
| `enable_whisper_memory` | bool | false | 启用记忆暂存 |

### 5.3 环境变量参数

| 变量名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `AGENTIC_ENABLE_ICEBERG` | bool | true | 启用冰山模型 |
| `AGENTIC_ENABLE_SUBCONSCIOUS` | bool | true | 启用潜意识层 |
| `AGENTIC_ENABLE_ROLLING_PREFIX` | bool | true | 启用滑动窗口 |
| `AGENTIC_ENABLE_FAIL_FAST` | bool | true | 启用断言检查 |
| `AGENTIC_ENABLE_EMOTIONAL_SCRATCHPAD` | bool | true | 启用情绪暂存器 |
| `AGENTIC_BEAT_CONCURRENCY` | int | 6 | Beat 并行度 |

---

## 6. 错误处理与重试机制

### 6.1 分层错误处理

```
Level 1: LLM 调用层 (call_llm)
├── 网络超时 → 指数退避重试 (max 3次)
├── Rate Limit → 等待后重试
└── 4xx 错误 → 直接抛出

Level 2: 阶段层 (各 Stage)
├── 单次失败 → 记录日志，返回默认值
└── 全部失败 → 进入降级模式

Level 3: 工作流层 (execute_agentic_workflow)
├── 可恢复错误 → 重试当前 Stage
└── 不可恢复错误 → 返回错误响应
```

### 6.2 Fail-Fast 重试策略

```python
attempt = 0
current_temp = 0.75

while attempt < max_attempts:
    attempt += 1
    
    # 生成正文
    text = await generate_prose(temperature=current_temp)
    
    # 断言检查
    is_valid, reason = await micro_review(text)
    
    if is_valid:
        break  # 通过，使用当前结果
    else:
        # 失败，准备重试
        current_temp += temperature_step  # 增加随机性
        log.warning(f"Attempt {attempt} failed: {reason}")
        
# 如果所有尝试都失败，使用最后一次结果
return text
```

### 6.3 降级策略

| 场景 | 降级行为 |
|------|----------|
| Reasoning Model 不可用 | 使用默认 model 替代 |
| Creative Model 不可用 | 使用 reasoning_model 替代 |
| Fail-Fast 断言失败 | 使用最后一次生成结果 |
| RAG 检索失败 | 继续生成，不使用记忆 |
| QC 修复失败 | 返回原始文本 |

---

## 7. 性能与成本优化

### 7.1 时间复杂度分析

| 阶段 | 复杂度 | 说明 |
|------|--------|------|
| PLANNING | O(1) | 单次调用 |
| ENTITY_SNAPSHOT | O(N) | N = Beat 数量 |
| RAG_MEMORY | O(N × M) | M = 记忆检索时间 |
| DRAFTING | O(N × K) | K = 平均重试次数 |
| STITCHING | O(1) | 单次调用 |
| REVIEWING | O(I) | I = 迭代次数 |
| REFINING | O(I) | 每次迭代一次 |

**总时间**: `T_total = T_planning + N×T_entity + N×M×T_rag + N×K×T_draft + T_stitch + I×(T_review + T_refine)`

### 7.2 Token 消耗估算

| 阶段 | 输入 Token | 输出 Token | 模型 |
|------|-----------|-----------|------|
| PLANNING | ~2k | ~1k | Reasoning |
| Scene Intent (×N) | ~500 × N | ~200 × N | Reasoning |
| Subconscious (×N) | ~300 × N | ~100 × N | Reasoning |
| Prose Draft (×N) | ~800 × N | ~600 × N | Creative |
| Fail-Fast (×N×K) | ~400 × N × K | ~50 × N × K | Reasoning |
| Emotional Update (×N) | ~300 × N | ~30 × N | Reasoning |
| STITCHING | ~3k | ~2k | Creative |
| REVIEWING | ~3k | ~800 | Reasoning |
| REFINING | ~2k | ~1.5k | Creative |

**估算公式** (N=4 Beats, K=1.2 平均重试):
```
Reasoning Tokens = 2k + 4×(500+300+400×0.2+300) + 800 + 800 = ~8.5k
Creative Tokens = 4×600 + 2k + 1.5k = ~5.9k
```

### 7.3 成本对比

| 架构 | Reasoning Cost | Creative Cost | Total | 质量 |
|------|---------------|---------------|-------|------|
| v1.0 单模型 | - | $C × 100% | 100% | ⭐⭐ |
| v2.0 冰山模型 | $C_r × 30% | $C_c × 70% | 75% | ⭐⭐⭐⭐ |
| v2.5 Cognitive | $C_r × 35% | $C_c × 65% | 70% | ⭐⭐⭐⭐⭐ |

**成本降低**: 相比纯 GPT-4o 生成，成本降低约 45%

---

## 附录 A: 完整调用链

```
POST /api/chapters/{chapter_id}/generate-agentic
└── generate_chapter_agentic()
    └── execute_agentic_workflow()
        ├── [INIT]
        │   └── 数据库查询
        ├── [PLANNING]
        │   ├── build_planner_agent_prompt()
        │   ├── call_llm(reasoning_model)
        │   └── parse_planner_result()
        ├── [ENTITY_SNAPSHOT]
        │   └── assign_pov_to_beats()
        ├── [RAG_MEMORY]
        │   └── MemoryRepository.search_memories()
        ├── [DRAFTING]
        │   └── execute_draft_stage()
        │       ├── _generate_scene_intent_batch()
        │       │   ├── build_scene_intent_prompt()
        │       │   ├── call_llm(reasoning_model)
        │       │   └── parse_scene_intent_result()
        │       ├── _generate_subconscious_batch()
        │       │   ├── build_subconscious_prompt()
        │       │   └── call_llm(reasoning_model)
        │       └── _generate_prose_serial_v25()
        │           ├── For each beat:
        │           │   ├── build_prose_draft_prompt_v25()
        │           │   ├── call_llm(creative_model)
        │           │   ├── _micro_review_assertion()
        │           │   │   ├── build_micro_review_prompt()
        │           │   │   └── call_llm(reasoning_model)
        │           │   └── _update_emotional_state()
        │           │       ├── build_emotional_update_prompt()
        │           │       └── call_llm(reasoning_model)
        │           └── Return BeatDraftResult[]
        ├── [STITCHING]
        │   ├── build_stitch_prompt()
        │   └── call_llm(creative_model)
        ├── [REVIEWING]
        │   ├── build_review_agent_prompt()
        │   ├── call_llm(reasoning_model)
        │   └── parse_review_result()
        ├── [REFINING] (Conditional)
        │   ├── build_refine_agent_prompt()
        │   └── call_llm(creative_model)
        ├── [FORMATTING]
        │   ├── build_formatting_prompt()
        │   └── call_llm(creative_model)
        └── [PERSISTENCE]
            └── 数据库更新
```

---

## 附录 B: 错误码与状态

| 状态码 | 含义 | 处理建议 |
|--------|------|----------|
| `PLANNING_FAILED` | 规划阶段失败 | 检查大纲是否清晰 |
| `DRAFTING_FAILED` | 起草阶段失败 | 检查角色设定完整性 |
| `REVIEW_REJECTED` | 审阅未通过 | 查看具体 issue 列表 |
| `MAX_ITERATIONS` | 达到最大迭代 | 降低质量要求或增加预算 |
| `LLM_ERROR` | LLM 调用错误 | 检查 API Key 和网络 |
| `TIMEOUT` | 超时 | 增加超时时间或减少 Beats |

---

*文档版本: v2.5.0 | 最后更新: 2026-03-19*
