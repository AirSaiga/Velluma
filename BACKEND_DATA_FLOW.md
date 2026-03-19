# 数据流向详解

## 1. 请求生命周期

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────────────────────────────┐
│   Frontend  │────▶│  FastAPI    │────▶│  GenerateChapterAgenticRequest          │
│   (Vue3)    │     │  Endpoint   │     │                                         │
└─────────────┘     └─────────────┘     │  - chapter_id                           │
                                        │  - api_key                              │
                                        │  - reasoning_model / creative_model     │
                                        │  - feature_flags                        │
                                        │  - beats[]                              │
                                        └─────────────────┬───────────────────────┘
                                                          │
                                                          ▼
                                        ┌─────────────────────────────────────────┐
                                        │   execute_agentic_workflow()           │
                                        │   (Orchestrator)                        │
                                        └─────────────────┬───────────────────────┘
                                                          │
                    ┌─────────────────────────────────────┼─────────────────────────────────────┐
                    │                                     │                                     │
                    ▼                                     ▼                                     ▼
          ┌──────────────────┐              ┌──────────────────┐              ┌──────────────────┐
          │  Database Layer  │              │   LLM Client     │              │   RAG Engine     │
          │                  │              │                  │              │                  │
          │ - Chapter        │              │ - call_llm()     │              │ - get_embedding()│
          │ - Book           │              │ - Streaming      │              │ - search_memories│
          │ - Character      │              │ - Retry Logic    │              │                  │
          │ - Relationship   │              │                  │              │                  │
          └──────────────────┘              └──────────────────┘              └──────────────────┘
```

## 2. DynamicContext 流转

```
Beat 1: Init
┌────────────────────────────────────────────────────────────────┐
│ DynamicContext                                                 │
│ ├── previous_tail: ""                                          │
│ ├── physical_state_lock: "楚言，肉身，手无寸铁"                 │
│ └── current_emotional_state: "初始状态：刚从昏迷中醒来，头晕目眩"│
└────────────────────────────────────────────────────────────────┘
         │
         │ build_prose_draft_prompt_v25()
         ▼
    ┌──────────────┐
    │ Creative Model│
    └──────┬───────┘
           │ generated_text
           ▼
    ┌───────────────────────────────────────┐
    │ "楚言睁开眼，头顶是陌生的金属天花板..." │
    └─────────────────┬─────────────────────┘
                      │
                      ├──▶ _extract_tail() ──▶ previous_tail (for Beat 2)
                      │
                      └──▶ _update_emotional_state()
                               │
                               ▼
                    "从昏迷的混沌中逐渐清醒，开始警惕地观察四周"
                               │
                               └──▶ current_emotional_state (for Beat 2)

Beat 2: Use Beat 1's Context
┌────────────────────────────────────────────────────────────────┐
│ DynamicContext                                                 │
│ ├── previous_tail: "楚言睁开眼，头顶是陌生的金属天花板..."      │
│ ├── physical_state_lock: "楚言，肉身，手无寸铁"                 │
│ └── current_emotional_state: "从昏迷的混沌中逐渐清醒..."        │
└────────────────────────────────────────────────────────────────┘
         │
         │ build_prose_draft_prompt_v25()  
         │ (包含 previous_tail + emotional_state)
         ▼
    ┌──────────────┐
    │ Creative Model│
    └──────┬───────┘
           │ (无缝衔接 Beat 1 的结尾)
           ▼
    ... and so on
```

## 3. Token 流向图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           单次请求 Token 消耗                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PLANNING (Reasoning)                                                       │
│  ┌────────────────┐         ┌──────────────┐         ┌────────────────┐   │
│  │  System: 2000  │────────▶│  User: 1500  │────────▶│ Output: 1000   │   │
│  └────────────────┘         └──────────────┘         └────────────────┘   │
│         ~4.5K Tokens                                                        │
│                                                                             │
│  DRAFTING (Mixed) - N=4 Beats                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Scene Intent × 4  (Reasoning)                                      │   │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │   │
│  │  │ 500 × 4 = 2K │───▶│ 500 × 4 = 2K │───▶│ 200 × 4 = 800│          │   │
│  │  └──────────────┘    └──────────────┘    └──────────────┘          │   │
│  │  ~4.8K Tokens                                                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Subconscious × 4  (Reasoning)                                      │   │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │   │
│  │  │ 300 × 4 = 1.2K│───▶│ 300 × 4 = 1.2K│───▶│ 100 × 4 = 400│          │   │
│  │  └──────────────┘    └──────────────┘    └──────────────┘          │   │
│  │  ~2.8K Tokens                                                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Prose Draft × 4  (Creative) - w/ Fail-Fast (K=1.2 avg)             │   │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │   │
│  │  │ 800 × 4 = 3.2K│───▶│ 800 × 4 = 3.2K│───▶│ 600 × 4 = 2.4K│         │   │
│  │  └──────────────┘    └──────────────┘    └──────────────┘          │   │
│  │  ~8.8K Tokens                                                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Fail-Fast Review × 0.8  (Reasoning) - 20% 触发重试                  │   │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │   │
│  │  │ 400 × 0.8 = 320│──▶│ 400 × 0.8 = 320│──▶│  50 × 0.8 = 40 │        │   │
│  │  └──────────────┘    └──────────────┘    └──────────────┘          │   │
│  │  ~680 Tokens                                                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Emotional Update × 4  (Reasoning)                                  │   │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │   │
│  │  │ 300 × 4 = 1.2K│───▶│ 300 × 4 = 1.2K│───▶│  30 × 4 = 120 │        │   │
│  │  └──────────────┘    └──────────────┘    └──────────────┘          │   │
│  │  ~2.5K Tokens                                                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  STITCHING (Creative)                                                       │
│  ┌────────────────┐         ┌──────────────┐         ┌────────────────┐   │
│  │  System: 1000  │────────▶│  User: 2000  │────────▶│ Output: 2000   │   │
│  └────────────────┘         └──────────────┘         └────────────────┘   │
│         ~5K Tokens                                                          │
│                                                                             │
│  REVIEWING (Reasoning)                                                      │
│  ┌────────────────┐         ┌──────────────┐         ┌────────────────┐   │
│  │  System: 1500  │────────▶│  User: 2000  │────────▶│ Output: 800    │   │
│  └────────────────┘         └──────────────┘         └────────────────┘   │
│         ~4.3K Tokens                                                        │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  Total Estimation                                                           │
│  ├── Reasoning: ~15K Tokens  (~$0.075 with GPT-4o-mini)                    │
│  ├── Creative:  ~14K Tokens  (~$0.007 with GPT-4o-mini)                    │
│  └── Total:     ~29K Tokens  (~$0.082 per chapter)                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 4. Prompt 层级结构

```
build_prose_draft_prompt_v25()
│
├── System Prompt (构建)
│   │
│   ├── Base Instructions
│   │   ├── 核心任务说明
│   │   └── 叙事原则 (4条)
│   │
│   ├── Pacing Control
│   │   └── 根据 pacing_type 选择指令
│   │       ├── Fast: 短句、动词、紧张
│   │       ├── Medium: 平衡长短句
│   │       └── Slow: 长句、感官细节
│   │
│   ├── Physical State Lock  [V2.5 Feature A]
│   │   ├── 当前状态: {physical_state_lock}
│   │   ├── 禁止行为清单
│   │   └── 检查清单提醒
│   │
│   ├── Emotional Scratchpad  [V2.5 Feature B]
│   │   ├── 当前心境: {current_emotional_state}
│   │   └── 情绪连贯性要求
│   │
│   ├── Anti-AI Protocol
│   │   ├── 禁止设定倾倒
│   │   ├── 禁止预告片旁白
│   │   ├── 禁止形容词堆砌
│   │   ├── Show Don't Tell
│   │   └── 短句制造紧张
│   │
│   ├── Style Control (可选)
│   │   ├── 黄金锚点 (golden_snippets)
│   │   └── 黑名单 (style_blacklist)
│   │
│   └── Output Requirements
│       ├── 字数要求
│       ├── 段落格式
│       └── 禁止 Markdown
│
└── User Prompt (构建)
    │
    ├── Context Info
    │   ├── POV角色: {pov_character}
    │   └── 当前场景: {location}
    │
    ├── Story Intent
    │   └── 场景目标: {intent_goal}
    │
    ├── Emotional Anchor
    │   └── 潜意识独白: {subconscious_thought}
    │
    ├── Rolling Prefix  [V2.0 Iceberg]
    │   └── 前文尾巴: {previous_tail}
    │       └── 无缝衔接要求
    │
    └── Constraints
        └── 约束条件: {intent_constraints}
```

## 5. 状态持久化

```
Memory / Database Updates
│
├── Chapter Entity
│   ├── draft_text = 生成的正文
│   ├── summary = 自动生成的摘要
│   ├── review_feedback = 审阅反馈
│   └── revision_count += 1
│
├── Character Entities (Per POV Character)
│   └── dynamic_state = 最后一幕的情绪状态
│       └── 用于下一章的 entry_state
│
├── Plot Ledger (伏笔)
│   ├── 已回收的伏笔 → status = "closed"
│   └── 新创建的伏笔 → INSERT
│
└── Memory Chunks (RAG)
    └── 本章关键情节 → embedding → INSERT
        └── 用于后续章节的记忆检索

PerformanceMetrics (Logging)
│
├── 各阶段耗时
│   ├── planning_duration_ms
│   ├── drafting_duration_ms
│   ├── reviewing_duration_ms
│   └── total_duration_ms
│
├── Token 消耗
│   ├── reasoning_tokens
│   ├── creative_tokens
│   └── total_tokens
│
└── 成本估算
    └── estimated_cost_usd
```

## 6. 并发模型

```
AsyncIO Concurrency Model
│
├── Level 1: Stage Sequential
│   │
│   │  PLANNING ──▶ ENTITY ──▶ RAG ──▶ DRAFTING ──▶ STITCHING
│   │     (等待)     (等待)    (等待)     (等待)       (等待)
│   │
│   └── 每个 Stage 必须等待前一个完成
│
├── Level 2: Drafting Parallel (Within Stage)
│   │
│   │  Step A: Scene Intent
│   │   ┌─────┬─────┬─────┬─────┐
│   │   │Beat1│Beat2│Beat3│Beat4│  ← 同时发起
│   │   └─────┴─────┴─────┴─────┘
│   │        (等待全部完成)
│   │
│   │  Step A: Subconscious
│   │   ┌─────┬─────┬─────┬─────┐
│   │   │Beat1│Beat2│Beat3│Beat4│  ← 同时发起
│   │   └─────┴─────┴─────┴─────┘
│   │        (等待全部完成)
│   │
│   │  Step B: Prose Draft (Serial w/ Rolling Prefix)
│   │   Beat1 ──▶ Beat2 ──▶ Beat3 ──▶ Beat4
│   │   (等待)    (等待)    (等待)    (等待)
│   │
│   └── 混合并发：A步骤并行，B步骤串行
│
└── Level 3: Fail-Fast Retry (Within Beat)
    │
    │  Attempt 1 ──▶ Review ──▶ (Failed?) ──▶ Attempt 2
    │    Temp=0.75    ↓            ↓            Temp=0.95
    │              (Passed?)  (Yes) │
    │                 ↓              │
    │              Use Result ◀──────┘
    │
    └── 单个 Beat 内可能多次重试
```

## 7. 错误传播

```
Error Handling Flow
│
├── LLM Level (call_llm)
│   │
│   ├── Network Error
│   │   ├── Timeout ──▶ Exponential Backoff Retry (×3)
│   │   └── Connection Error ──▶ Same
│   │
│   ├── Rate Limit
│   │   └── 429 ──▶ Wait (retry-after) ──▶ Retry
│   │
│   └── 4xx Client Error
│       └── 400/401/403 ──▶ Raise immediately
│
├── Stage Level (execute_draft_stage)
│   │
│   ├── Single Beat Failure
│   │   └── Return empty string ──▶ Log warning ──▶ Continue
│   │
│   └── All Beats Failed
│       └── Raise DraftingError
│
└── Workflow Level (execute_agentic_workflow)
    │
    ├── Recoverable Error
    │   └── Retry current stage (max 2 times)
    │
    └── Unrecoverable Error
        └── Return error response with details

Error Response Format
{
    "status": "error",
    "stage": "DRAFTING",
    "error_code": "BEAT_GENERATION_FAILED",
    "message": "Beat 3 generation failed after 3 retries",
    "details": {
        "beat_id": "beat-003",
        "attempts": 3,
        "last_error": "Timeout after 30s"
    }
}
```

---

*与 BACKEND_GENERATION_WORKFLOW_COMPLETE.md 配套使用*
