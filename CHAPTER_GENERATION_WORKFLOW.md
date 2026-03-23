# Velluma 文章生成全流程逻辑链文档

## 一、整体架构概览

Velluma 采用 **Agentic Workflow（智能体工作流）** 架构，通过多轮迭代生成高质量小说章节。系统使用 **双模型架构（冰山模型）**：
- **reasoning_model**: 高逻辑模型，用于 Scene Intent、Subconscious、Review 阶段
- **creative_model**: 高创意模型，用于 Prose Draft 阶段

### V3.0 智能路由架构

基于 `tension_level`（剧情张力等级 1-5）自动选择执行路径，实现算力资源的智能分配：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         文章生成主流程 (最多5轮迭代)                      │
├─────────────────────────────────────────────────────────────────────────┤
│  ASSEMBLING_CONTEXT → PLANNING → POV_ASSIGNMENT → DRAFTING → STITCHING │
│                                                               ↓ 未通过  │
│  FORMATTING ←──────────────────────────────────────────── REFINING      │
│      ↓                                                                  │
│  FINAL_TEXT_STREAM                                                      │
└─────────────────────────────────────────────────────────────────────────┘

V3.0 智能路由三档执行路径：
┌─────────────────┬─────────────────┬─────────────────────────────────────┐
│   TIER_1_FAST   │ TIER_2_STANDARD │        TIER_3_FORTRESS              │
│    (疾速流)      │    (均衡流)      │         (堡垒流)                    │
├─────────────────┼─────────────────┼─────────────────────────────────────┤
│ tension: 1-2    │ tension: 3      │ tension: 4-5                        │
│ Scene Intent: ✗ │ Scene Intent: ✓ │ Scene Intent: ✓                     │
│ Subconscious: ✗ │ Subconscious: ✓ │ Subconscious: ✓ (MCTS三分支)         │
│ DynamicContext: │ CoreDC only     │ Full 5D DynamicContext              │
│   Rolling Prefix│                 │                                     │
│ Fail-Fast: ✗    │ Fail-Fast: ✓    │ Fail-Fast: ✓                        │
│ Stitching: ✗    │ Stitching: ✓    │ Stitching: ✓                        │
│ Reviewing: 简版 │ Reviewing: 标准 │ Reviewing: 完整                     │
└─────────────────┴─────────────────┴─────────────────────────────────────┘

核心特性：
- 双模型架构：reasoning_model（高逻辑）+ creative_model（高创意）
- V2.5 认知流式生成：Scene Intent + Subconscious 并行，Prose 串行 Rolling Prefix
- DynamicContext：跨 Beat 流转的五维认知状态容器
- Fail-Fast 机制：即时断言检查与回溯重试
- V3.0 四重锁：Asset Schema + Perception Masking + Tonality + Red Lines

### V3.5 双轨对抗架构 (Dual Track)

为解决**并行生成连贯性差**与**串行生成耗时长**的矛盾，引入双轨架构：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     V3.5 双轨对抗架构 (推荐用于多节拍章节)                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Phase 1: 节拍生成 (PLANNING)                                            │
│       ↓                                                                 │
│  Phase 2: 双轨并行生成 (DUAL TRACK GENERATION)                           │
│       ├─ Track A: 节拍扩写 (Drafting) ──────────────────────────────┐   │
│       │   Beat[1] → Text[1], Beat[2] → Text[2], ...                 │   │
│       │                                                             │   │
│       └─ Track B: 短文生成 (Sketch) ────────────────────────────────┤   │
│           基于 Beats 生成连贯速写 (40-50% 字数)                     │   │
│           输出: Sketch + 转折点映射 + 情绪曲线                       │   │
│                                                                    ↓   │
│  Phase 3: 节拍统稿 (STITCHING) ─────→ Draft_A                       │   │
│                                                                    ↓   │
│  Phase 4: 对抗校对 (ADVERSARIAL ALIGNMENT)                          │   │
│           对比 Draft_A vs Sketch                                   │   │
│           - 结构对齐: 转折点位置偏移检测                            │   │
│           - 情绪对齐: 情绪曲线一致性                                │   │
│           - 信息对齐: 关键信息揭示时机                              │   │
│           - 归因分析: beat_design / expansion_drift / segment_boundary │
│                                                                    ↓   │
│  Phase 5: 融合精修 (FUSION REFINEMENT) ─────────────────────────────┘   │
│           基于 Alignment Plan 修复 Draft_A                              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**双轨架构 vs 传统方案：**

| 维度 | 串行生成 | 纯并行 | 双轨对抗 |
|------|---------|--------|---------|
| 时间复杂度 | N × T | T | T (并行+轻量校对) |
| 连贯性 | ⭐⭐⭐ | ⭐ | ⭐⭐⭐ |
| 跨节拍过渡 | ⭐⭐⭐ | ⭐ | ⭐⭐⭐ |
| 算力消耗 | 中 | 低 | 中 (+1次 Sketch 调用) |

**核心组件：**

1. **SketchGenerator** (`workflows/sketch_generator.py`)
   - 职责：生成连贯速写短文（Track B）
   - 特点：连续叙述流，不标记节拍边界，记录转折点映射
   - 字数：正文字数的 40-50%（默认 45%）
   - 输出：`SketchResult` (sketch_text, turn_markers, emotion_arc)

2. **AdversarialAligner** (`workflows/adversarial_aligner.py`)
   - 职责：对比 Draft_A 和 Sketch，检测差异
   - 检测维度：结构对齐、情绪对齐、信息对齐、首尾对齐
   - 归因分析：判断问题根源（beat_design/expansion_drift/segment_boundary/sketch_hallucination）
   - 输出：`AdjustmentPlan` (alignment_score, gaps, beat_adjustments)

3. **DualTrackWorkflow** (`workflows/dual_track.py`)
   - 职责：整合双轨流程，提供统一入口
   - 使用：`execute_dual_track_generation()` 便捷函数
   - 配置：`DualTrackConfig` (enable_sketch_track, alignment_threshold, ...)

**使用方式：**

```python
from backend.services.workflows.dual_track import (
    DualTrackWorkflow, DualTrackConfig
)

workflow = DualTrackWorkflow(
    api_key=api_key,
    base_url=base_url,
    reasoning_model=reasoning_model,
    creative_model=creative_model,
    config=DualTrackConfig(
        enable_sketch_track=True,
        enable_adversarial_alignment=True,
        alignment_threshold=70.0,
    ),
)

result = await workflow.execute(
    chapter=chapter,
    book=book,
    beats=beats,
    entities=entities,
    relationships=relationships,
    word_count=word_count,
)

# result.final_text: 最终正文
# result.sketch_result: 速写结果
# result.adjustment_plan: 对抗校对结果（含 alignment_score）
```

**推荐场景：**
- ✅ 节拍数 > 3 的章节
- ✅ 对连贯性要求高的场景（情感文、悬疑文）
- ✅ 可以接受 10-20% 时间增加换取更高连贯性
- ❌ 单节拍章节（没必要）
- ❌ 极致速度要求（使用 TIER_1_FAST）
```

---

## 二、各阶段详细逻辑链

### Phase 1: ASSEMBLING_CONTEXT（上下文组装）

**文件**: `backend/services/agentic_workflow.py` (行 600-750)

**职责**: 从数据库加载所有必要的上下文信息

**关键变量**:

| 变量 | 类型 | 用途 |
|------|------|------|
| `chapter` | Chapter | 当前章节实体（大纲、标题、张力等级、节奏偏好等） |
| `book` | Book | 书籍实体（全局系统提示、世界观设定、核心母题禁忌） |
| `entities` | List[ChapterEntity] | 章节关联的角色列表 |
| `relationships` | List[CharacterRelationship] | 角色间关系列表 |
| `open_hooks` | List[dict] | 开放的伏笔/情节点列表 |
| `previous_summary` | str | 上一章摘要（用于上下文连贯性） |
| `relevant_memories` | List | RAG 检索的相关记忆 |
| `locations` | List[ChapterMapLocation] | 章节关联的地图地点 |

**处理流程**:
1. 查询 Chapter、Book 实体
2. 加载章节关联的角色（ChapterEntity → Character）
3. 查询角色间关系（CharacterRelationship）
4. RAG 检索相关记忆（使用 alpha/beta/gamma 权重混合语义相似度、时间衰减、剧情伏笔）
5. 获取上一章摘要或最后 1000 字作为前文参考
6. 加载开放的 PlotLedger（伏笔）

---

### Phase 2: PLANNING（规划节拍）

**文件**: `backend/services/prompts/planner_prompts.py`

**核心函数**: `build_planner_agent_prompt()` (行 32-234)

**职责**: 将章节大纲拆分为可执行的 **Story Beats（剧情节拍）**，并自动计算工作流层级

**V3.0 新增特性**:
- **workflow_tier 自动计算**：基于 `tension_level` 自动输出工作流层级
  - tension_level 1-2 → "TIER_1_FAST"
  - tension_level 3 → "TIER_2_STANDARD"
  - tension_level 4-5 → "TIER_3_FORTRESS"

**Prompt 设计**:

**System Prompt 关键内容**:
```python
# 输出 JSON 结构定义
{
  "beats": [
    {
      "position": 1,
      "beat_id": "beat-1",
      "summary": "本段剧情概述",
      "location": "场景地点",
      "pov_character": "视角角色",
      "pov_perception_state": "正常",  # 角色意识清醒程度与物理行动力
      "action_summary": "动作化执行摘要",
      "worldbuilding_instruction": "本段生效的世界构建约束",
      "entry_state": "本段切入时的起始状态",
      "exit_state": "本段必须停住的收束状态",
      "red_lines": ["禁止发生1", "禁止发生2"],
      "word_count_target": 600,
      "hook_ids": ["hk-1"],
      "pacing_type": "Medium",  # Fast/Medium/Slow
      "weight": 3  # 1-5 权重，用于字数分配
    }
  ],
  "workflow_tier": "TIER_2_STANDARD"  # V3.0 新增
}
```

**约束条件**:
- beats 数量: 1-6 个
- 每个 beat 必须有 entry_state、exit_state、red_lines
- exit_state 是硬停点，不能把后续 beat 事件提前
- **跨章接缝绝对定标**：第一个 beat 的 `entry_state` 必须与上一章结尾的物理空间、视角角色保持 100% 连续性
- **跨 Beat 状态过渡动作强制规则**：角色物理形态突变时，必须显式包含过渡动作

**V3.0 低张力规则**（tension_level <= 2）：
- 自动注入红线: `["禁止发生任何武力冲突或战斗升级", "避免正面冲突"]`
- 禁止设计直接爆发式冲突，剧情推进以铺垫与悬停为主

**字数分配算法** (`_calculate_beat_word_counts`):
```python
# Multipliers: Fast=0.8, Medium=1.0, Slow=1.2
# Formula: score = weight * multiplier
# Result: (score / total_score) * total_chapter_words
```

**输出解析**: `parse_planner_result()` (行 237-392)
- 容错解析: 直接解析 → Markdown代码块 → 首尾大括号
- 失败回退: 使用大纲生成单个 fallback beat

**双轨模式快速路径 (confirmed_beats fast path)**:

当前端用户在 Beat 预览弹窗中手动确认节拍后，后端可跳过 LLM PLANNING 调用，直接使用用户确认的 beats：

```python
# chapter_generation_dual_track.py
if request.beats and len(request.beats) > 0:
    # 快速路径：直接使用用户确认的节拍，0秒完成 PLANNING
    beats = [b.model_dump() for b in request.beats]
    # log: fast_path=true, source="confirmed_beats_from_frontend"
else:
    # 标准路径：调用 LLM 重新规划
    beats, _ = await generate_beats(...)
```

- **触发条件**: `DualTrackGenerationRequest.beats` 字段非空
- **日志标记**: `fast_path=true, source="confirmed_beats_from_frontend"`
- **注意事项**: `_save_story_beats()` 在保存前会先 DELETE 旧记录，防止多次生成重复累积

---

### Phase 3: POV_ASSIGNMENT（视角分配）- Anchor POV 机制

**文件**: `backend/services/workflows/planning.py`

**核心函数**: `assign_pov_to_beats()` (行 111-233), `determine_chapter_anchor_pov()` (行 236-307)

**职责**: 为章节确定统一的锚定视角角色（Anchor POV），确保全文视角一致性

**Anchor POV 机制**:
- 由 `determine_chapter_anchor_pov()` 分析章节内容，选定最适合的主视角角色
- 所有 Beat 的 `pov_character` 统一设置为 anchor_pov
- 保留原始角色到 `original_actor` 字段，用于感官转化法则

**关键设计**:
```python
for beat in beats:
    beat["original_actor"] = original_pov  # 保留原始执行者
    beat["pov_character"] = anchor_pov      # 统一锚定视角
    beat["anchor_pov"] = anchor_pov         # 标记锚定角色
```

**感官转化法则**: 当 Beat 的 original_actor ≠ anchor_pov 时，需将该事件转化为 anchor_pov 能感知的物理异象（如远处的爆炸声、地面的震动等）

---

### Phase 4: DRAFTING（起草）- V3.0 智能路由生成

**文件**: `backend/services/workflows/drafting.py`

**核心函数**: `execute_draft_stage()` (行 167-313)

**输出数据结构** `BeatDraftResult`:
```python
class BeatDraftResult(BaseModel):
    beat_id: str                    # Beat 唯一标识
    beat_index: int                 # Beat 位置索引（从1开始）
    scene_intent: dict              # Scene Intent 分析结果
    subconscious_thought: str       # 角色潜意识/内心独白（50-100字）
    draft_chunk: str                # 生成的小说正文
    prompts: List[dict]             # 全流程提示词历史
    mcts_rollout: Optional[list]    # MCTS 三分支推演记录（可观测性）
```

**架构**: **混合流水线** - 并行思考层 + 串行正文层

```
┌────────────────────────────────────────────────────────────┐
│                    DRAFTING 混合流水线                      │
├────────────────────────────────────────────────────────────┤
│  步骤 A: 并行生成轻量级思考层（无文本依赖）                   │
│    ├── A-1: 批量并行生成 Scene Intent (所有 beats 同时)    │
│    └── A-2: 批量并行生成 Subconscious (依赖 Scene Intent)  │
├────────────────────────────────────────────────────────────┤
│  步骤 B-V25: 串行滑动窗口生成正文                            │
│    ├── Rolling Prefix: Beat n 接收 Beat n-1 末尾 300 字符   │
│    ├── DynamicContext: 跨 Beat 流转的动态上下文              │
│    ├── Fail-Fast: 即时断言检查与回溯重试                     │
│    └── Emotional Scratchpad: 动态情绪状态更新                │
└────────────────────────────────────────────────────────────┘
```

#### V3.0 三档执行路径

**TIER_1_FAST (疾速流)** - `execute_fast_path()`:
- 跳过 Scene Intent 和 Subconscious
- 单次调用 creative_model 生成正文
- 仅保留 previous_tail 作为上下文
- 跳过 Stitching（直接拼接）

**TIER_2_STANDARD (均衡流)** - `execute_standard_path()`:
- 轻量级 Scene Intent
- 轻量级 Subconscious（无 MCTS）
- CoreDynamicContext（previous_tail + physical_state_lock）
- 标准 Reviewing

**TIER_3_FORTRESS (堡垒流)** - `execute_fortress_path()`:
- 完整 V2.5 实现
- MCTS 三分支 Subconscious
- 全部 5 维 DynamicContext
- Fail-Fast 断言检查
- 完整 STITCHING → REVIEWING → REFINING 闭环

#### 4.1 Scene Intent 生成

**文件**: `backend/services/prompts/scene_intent_prompts.py`

**函数**: `build_scene_intent_prompt()` (行 26-110)

**输出结构**:
```json
{
  "intent_label": "场景标签",
  "goal": "本场景目标",
  "stakes": "失败代价或风险",
  "constraints": ["约束1", "约束2"]
}
```

**节奏微观指令** (PACING_MICRO_INSTRUCTIONS):
- **slow_burn**: 单段只推进一个小动作，冲突表达以试探、停顿为主
- **fast_paced**: 每段至少一个可见动作变化，句式更短更直接
- **balanced**: 动作推进与情绪描写保持均衡

#### 4.2 Subconscious 生成（MCTS 潜意识树搜索）

**文件**: `backend/services/prompts/draft_prompts.py` (行 123-231)

**函数**: `build_subconscious_prompt()`

**MCTS (Monte Carlo Tree Search) 设计**:
```python
# 展开 3 条潜意识分支
分支A：基于本能反抗或冲动的思维（可能极易违背红线）
分支B：基于当前知觉受限条件下的无力感、痛觉或冷酷本能
分支C：结合特定性格设定的战术/极端环境思维

# 评估与剪枝
- 任何有一丝可能导致违背【红线】的分支，直接打分为 0
- 任何违背【动机连贯性】（与前一时刻核心动机矛盾）的分支，打分为 0
- 任何违背【物理知觉状态】的分支，打分为 0
- 选出得分最高且绝对安全的分支

# 输出格式
{
  "mcts_rollout": [
    {"branch_id": "A", "thought": "...", "score": 0, "reason": "..."},
    {"branch_id": "B", "thought": "...", "score": 95, "reason": "..."}
  ],
  "best_subconscious": "获胜分支的 thought 内文"
}
```

**关键变量**:
| 变量 | 用途 |
|------|------|
| `pov_perception_state` | POV 角色当前物理知觉状态（三级优先级链） |
| `red_lines` | 红线约束列表，用于评估分支安全性 |
| `previous_tail` | 伪前文（前一 beat 的 exit_state + 当前 entry_state） |

#### 4.3 Prose Draft 生成（V3.0 串行滑动窗口 + 四重锁）

**文件**: `backend/services/workflows/drafting.py` (行 552-850)

**函数**: `_generate_prose_serial_v25()`

**核心机制**:

1. **Rolling Prefix**: 
   - Beat 1: 基于 Subconscious_1 + DynamicContext_0 生成 Prose_1
   - Beat 2: 基于 Subconscious_2 + DynamicContext_1 生成 Prose_2
   - 传递: `previous_tail = _extract_tail(chunk_text, max_chars=300)`

2. **DynamicContext 动态上下文** (V2.5+):
   ```python
   class DynamicContext(BaseModel):
       previous_tail: str = ""                    # Rolling Prefix（上文尾部300字符）
       current_emotional_state: str = "初始状态：未知"  # 主角当前心理状态
       physical_state_lock: str = ""              # 绝对物理状态约束（防幻觉边界）
       pov_perception_state: str = ""             # POV角色清醒程度与物理行动力
       accumulated_summary: str = ""              # 宏观剧情累加器（≤500字符）
       relational_state_lock: str = ""            # 在场角色动态关系锁
       active_whispers: dict = {}                 # 激活的RAG记忆片段
       entity_spatial_ledger: Dict[str, CharacterPhysicalState]  # 角色物理形态与空间从属
   ```

3. **V3.0 四重锁机制** (Prose Draft Prompt):
   ```python
   【锁1：核心资产体积锁 (Asset Schema Lock) - P0级特权】
   严禁把重型机甲写成"钻入体内的纳米神经"、"吸附在皮肤上的液体战甲"或"外骨骼"
   
   【锁2：知觉与感官遮罩层 (Perception Masking)】
   如果状态包含"昏迷/重伤/失去控制"，绝对禁止描写该角色做出清醒、精准的主动战术动作
   
   【锁3：世界观基调锁 (Tonality Lock)】
   严禁题材污染（如科幻文出现修仙魔法）
   
   【锁4：大纲红线 (Red Lines) - 撞线即判废】
   触碰红线的生成内容将被立即判定为无效
   ```

4. **Fail-Fast 断言检查** (行 852-968):
   ```python
   async def _micro_review_assertion():
       # 断言决策树
       IF Violate(red_lines): RETURN (False, "触碰红线约束", ["红线"])
       IF Physical_Hallucination: RETURN (False, "物理状态冲突", ["物理幻觉"])
       IF OOC_Behavior: RETURN (False, "角色行为偏离设定", ["OOC"])
       IF Relationship_Jump: RETURN (False, "人物关系无逻辑突变", ["关系"])
       IF Style_Issue: RETURN (False, "文风问题", ["文风"])
       RETURN (True, "", [])
   ```
   
   **智能温度调整策略**:
   - 文风问题 → 提高温度重新采样
   - 逻辑错误 → 降低温度，注入错误提示

5. **Emotional Scratchpad 状态更新** (行 1443-1524):
   - 基于刚生成的剧情，总结新的角色内心状态
   - 更新关系状态锁、宏观剧情累加器

**Prompt 构建**: `build_prose_draft_prompt_v25()` (行 749-999)

**关键约束**:
- **单一视角锁定**: 绝对锁定在 POV 角色的感官范围内
- **反AI味协议**: 禁止设定倾倒、预告片旁白、形容词堆砌
- **危机递进法则**: 禁止从 0 直接跳到 100，必须使用三段式危机爬升

---

### Phase 5: STITCHING（统稿）

**文件**: `backend/services/prompts/stitch_prompts.py`, `backend/services/workflows/stitching.py`

**核心函数**: 
- `build_stitch_prompt()` - 构建统稿提示词
- `stitch_chunks()` - 执行统稿

**职责**: 将多个 Beat 生成的 chunks 融合成连贯的章节正文

**V3.5.3 新增参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `sketch_text` | Optional[str] | 连贯速写文本，作为连贯性参考（双轨模式） |
| `book` | Optional[Book] | 书籍实体，用于文风控制 |

**统稿规则**:
1. **重点修复**: 检查各 Chunk 之间的连接点，消除突兀的场景转换
2. **抹除劣质胶水词**: 强制删去"与此同时"、"视角回到"、"在这关键时刻"
3. **收束去AI味**: 去除段落末尾拔高立意的"旁白说教"
4. **黑名单词库约束**: 避免使用 style_blacklist 中的词汇
5. **单一连续时间线**: 抹去非主视角的描写，合并为主视角的背景板感知流
6. **反蒙太奇剪辑**: 当使用 anchor_pov 时，拥有最高剪辑权

**V3.5.3 连贯性参考机制**:

当双轨模式启用时，统稿器会接收 Sketch 文本作为连贯性参考：

```
## 连贯性参考（来自连贯速写）
以下是一段连续生成的速写文本，展示了自然流畅的场景过渡方式...

**参考要点**：
- 学习上述文本中场景转换的自然方式
- 注意情绪流动的平滑性
- 你的统稿正文应比速写更详细、更丰富，但过渡方式可借鉴
- 不要照搬速写内容，只借鉴其过渡技巧
```

**设计意图**: 让统稿器主动学习 Sketch 的过渡技巧，预防式改善节拍间的衔接问题。

**温度设置**: `temperature=0.4`（较低，保持稳定性）

---

### Phase 4.5: 双轨并行生成 (V3.5 可选增强)

**文件**: `backend/services/workflows/dual_track.py`, `sketch_generator.py`

**核心函数**: 
- `DualTrackWorkflow.execute()` (行 148-345)
- `SketchGenerator.generate()` (行 109-218)

**职责**: 在单轨 Drafting 基础上，并行生成连贯速写短文，作为连贯性锚点。

**触发条件**:
- `DualTrackConfig.enable_sketch_track = True`
- 推荐用于节拍数 > 3 的章节

**双轨架构**:
```
Track A: 节拍扩写 (execute_draft_stage)     Track B: 短文生成 (SketchGenerator)
├─ Beat[1] → Text[1]                         ├─ 连续叙述，不标记节拍边界
├─ Beat[2] → Text[2]                         ├─ 强连贯性，情绪一气呵成
└─ Beat[N] → Text[N]                         └─ 输出转折点映射 + 情绪曲线
         │                                              │
         └──────────────────┬───────────────────────────┘
                            ↓
                    同时完成，耗时 ≈ max(Time_A, Time_B)
```

**Track B (Sketch) 详细设计**:

```python
class SketchResult(BaseModel):
    sketch_text: str              # 速写正文（正文字数的 40-50%）
    turn_markers: List[TurnMarker]  # 转折点位置映射
    emotion_arc: List[dict]       # 情绪曲线
    word_count: int
    generation_time: float
```

**Sketch Prompt 核心要求**:
1. **连续叙述流**: 禁止标记节拍边界，用自然过渡句连接
2. **强连贯性**: 情绪、节奏、信息传递一气呵成
3. **首尾呼应**: 开头承接上文，结尾形成情感闭环
4. **转折点映射**: 记录每个关键转折点的位置（百分比）

**与 Track A 的关系**:
- Track A 和 Track B 完全并行，互不等待
- 两者基于同一组 Beats 生成
- Track B 的结果用于 Phase 5.5 的对抗校对

**性能指标**（基于实测日志）:
- Sketch 生成耗时: ~15-20% of Track A（实测 11-15s vs Track A 86-102s）
- 额外 Token 消耗: ~50-55% of 正文（Sketch 实际字数常超目标 30-60%）
- Sketch 字数超出警告: 模型(Gemini Flash Lite)倾向超量生成，实测达目标字数 150-163%
- 对齐度得分 (alignment_score):
  - **V3.5.3 改进后**: 实测 84+（大幅提升）
  - **V3.5.2 及之前**: 实测范围 36-62
  - 改进原因：统稿阶段学习 Sketch 连贯性 + 对抗校对分段采样
- 融合精修触发后字数净变化: 约 +200 至 +300 字（补充内容为主）

---

### Phase 5.5: 对抗校对 (Adversarial Alignment) - V3.5

**文件**: `backend/services/workflows/adversarial_aligner.py`

**核心函数**: `AdversarialAligner.align()` (行 114-166)

**职责**: 对比节拍统稿 (Draft_A) 和连贯速写 (Sketch)，检测差异并生成修复方案。

**核心问题**: 解决并行生成导致的节拍间连贯性问题

**检测维度**:

| 维度 | 检测内容 | 实现函数 | 输出 |
|------|---------|---------|------|
| **结构对齐** | 转折点位置偏移 | `_detect_structural_gaps()` | 每个 beat 的预期 vs 实际位置 |
| **情绪对齐** | 情绪曲线一致性 | `_detect_emotional_gaps()` (行 214-297) | 情绪跳跃、情绪断层、情绪基调错位 |
| **信息对齐** | 关键信息揭示时机 | `_detect_information_gaps()` | 信息揭示的位置和方式差异 |
| **首尾对齐** | 开头结尾呼应 | `_detect_boundary_gaps()` (行 389-475) | 开头风格、结尾收束感 |

**情绪对齐检测详细逻辑** (`_detect_emotional_gaps`):
1. 遍历 Sketch 的 `emotion_arc`，检测相邻情绪点的强度变化
2. 若强度差超过 `emotion_diff_threshold` (默认 2.0)，记录为情绪跳跃
3. 检测开头情绪是否过于强烈（强度 > 8 可能显得突兀）
4. 通过 `_estimate_beat_from_position()` 将位置描述映射到 beat 索引

**信息对齐检测 `_is_key_beat` 过滤规则**:

`_detect_information_gaps()` 在将 beats 送入 LLM 前会过滤出"关键节拍"：

```python
key_beats = [b for b in beats if self._is_key_beat(b)]
# 关键词: ["发现", "转折", "决定", "冲突", "高潮"]

# 修复后的 fallback 规则（v3.5.1+）：
# 如果命中关键词的节拍 < min(3, total_beats)，则扩展为全部节拍
min_required = min(3, len(beats))
if len(key_beats) < min_required:
    key_beats = beats[:6]  # 最多取 6 个，避免 token 过长
```

- **背景**: 旧版仅当 `key_beats == []` 时才 fallback，导致只有 1/5 个 beat 被分析（如含"发现"的 beat）
- **现行规则**: 命中数 < `min(3, len(beats))` 即触发扩展
- **LLM prompt 可观测性**: `INFO_ALIGNMENT_ANALYSIS` prompt 现在通过 `prompt_logger.log_prompts()` 记录，label 为 `INFO_ALIGNMENT_ANALYSIS`

**V3.5.3 分段采样机制**:

解决旧版只分析前 2000 字符遗漏过渡问题的问题：

```python
def _sample_text_segments(self, text: str, max_total: int = 3000) -> str:
    """
    分段采样文本，覆盖开头、中间、结尾。
    过渡问题通常发生在节拍边界，即文章的中间部分。
    """
    head_len = int(max_total * 0.4)  # 开头 40%
    tail_len = int(max_total * 0.4)  # 结尾 40%
    mid_len = max_total - head_len - tail_len  # 中间 20%
    
    return f"【开头部分】\n{head}\n\n【中间部分】\n{mid}\n\n【结尾部分】\n{tail}"
```

| 改进前 | 改进后 |
|--------|--------|
| 只分析前 2000 字符 | 分段采样覆盖全文 |
| 遗漏中间过渡问题 | 开头 40% + 中间 20% + 结尾 40% |
| 对齐度得分 ~61 | 实测对齐度得分 84+ |

**首尾对齐检测详细逻辑** (`_detect_boundary_gaps`):
1. **开头风格检测**: 对比 Draft 和 Sketch 开头是否都有场景描写
2. **结尾收束检测**: 检测 Draft 结尾是否有叙事收束感（句号、省略号、收束关键词）
3. **突兀结尾检测**: 检测是否以对话或省略号中断结束

**归因分析 (Gap Source)**:

```python
class GapSource(str, Enum):
    BEAT_DESIGN = "beat_design"          # 节拍设计缺陷（entry/exit state 问题）
    EXPANSION_DRIFT = "expansion_drift"  # 扩写偏离（Track A 执行问题）
    SEGMENT_BOUNDARY = "segment_boundary"  # 衔接断裂（节拍间过渡问题）
    SKETCH_HALLUCINATION = "sketch_hallucination"  # 短文幻觉（Sketch 过度发挥）
```

**AdjustmentPlan 结构**:

```python
@dataclass
class AdjustmentPlan:
    alignment_score: float           # 0-100 整体对齐度得分
    needs_adjustment: bool           # 是否需要修复（< threshold）
    gaps: List[AlignmentGap]         # 差异列表
    beat_adjustments: Dict[int, List[str]]  # 按节拍的修复指令
    global_adjustments: List[str]    # 全局修复指令
```

**修复策略**:

| 问题类型 | 修复方式 | 实现函数 | 说明 |
|---------|---------|---------|------|
| beat_design | 调整 entry/exit state | `_execute_fusion_refinement()` | 修改节拍框架 |
| expansion_drift | 局部重扩 | `refine_single_beat()` | 重生成特定节拍 |
| segment_boundary | 过渡重织 | `_build_revision_guide()` | 用 Sketch 的过渡方式重写边界 |
| sketch_hallucination | 忽略或评估 | - | Sketch 可能更好，需人工判断 |

**融合精修详细实现** (`_execute_fusion_refinement`, 行 492-720):

```python
# 核心修复流程
1. 根据 adjustment_plan.beat_adjustments 定位问题 Beat
2. 调用 _segment_draft_by_beats() 按字数比例将统稿分段
3. 对每个问题 Beat 调用 refine_single_beat() 进行局部重写
4. 构建修复指导 (_build_revision_guide):
   - 问题描述列表
   - 特殊处理建议（SEGMENT_BOUNDARY/BEAT_DESIGN）
   - Sketch 参考片段 (_extract_sketch_reference)
5. 合并精修后的片段

# 辅助方法
- _segment_draft_by_beats(): 按 beat 字数比例分段
- _build_revision_guide(): 构建包含 Sketch 参考的修复指导
- _extract_sketch_reference(): 从 Sketch 提取对应位置的参考文本（±5%范围）
- _execute_global_refinement(): 处理无法定位到具体 beat 的全局问题
```

**完整 Stage 日志 (v3.5.1+)**:

FUSION_REFINEMENT 阶段现有完整的 `prompt_logger` 埋点：

```python
# stage inputs（对齐结果摘要）
{
  "alignment_score": 62.0,
  "gaps_count": 3,
  "beats_to_refine": [2, 3],        # 实际触发精修的 beat 索引
  "has_global_adjustments": true
}

# stage outputs（精修前后对比）
{
  "final_word_count": 3357,
  "stitched_word_count": 3111,
  "word_diff": 246                   # 正数=补充内容，负数=删减
}
```

`refine_single_beat()` 内部 LLM 调用现在也记录到 FUSION_REFINEMENT 阶段的 prompts 列表：
- **label 格式**: `FUSION_REFINE_BEAT_{beat_id}`（如 `FUSION_REFINE_BEAT_beat-2`）
- **文件**: `backend/services/workflows/refining.py`（新增 `prompt_logger: Optional[PromptLogger]` 参数）

**阈值配置**:
- `alignment_threshold`: 70.0 (默认)
- 低于阈值触发自动精修
- 高于阈值跳过精修，直接使用 Draft_A

**与 Phase 6 (Reviewing) 的区别**:

| | Phase 5.5 对抗校对 | Phase 6 审阅 |
|--|-------------------|-------------|
| **对比对象** | Draft_A vs Sketch | Draft vs 大纲/角色设定 |
| **关注点** | 连贯性、过渡自然 | 逻辑正确性、OOC |
| **修复粒度** | 节拍级/句子级 | 节拍级 |
| **触发条件** | 双轨模式启用 | 所有模式 |

---

### Phase 6: REVIEWING（审阅）

**文件**: `backend/services/prompts/review_prompts.py`

**函数**: `build_review_agent_prompt()` (行 110-245)

**职责**: 对章节初稿进行质量检查

**检查项目**:
1. 是否遵循章节大纲要求
2. 角色是否出现 OOC (Out Of Character，人设崩塌)
3. 是否有逻辑硬伤或情节漏洞
4. 是否遗漏了应该有的剧情点
5. **Boundary & Pacing 越界检查**: 是否越过 exit_state 或触发 red_lines
6. **完整性缺失检查**: 是否大幅删段导致关键段落缺失

**输出 JSON 结构**:
```json
{
  "pass": true/false,
  "issues": [
    {
      "type": "OOC/剧情遗漏/逻辑硬伤/PACING_OVERFLOW/完整性缺失",
      "severity": "high/medium/low",
      "description": "详细描述问题",
      "target_beat_ids": ["beat_01", "beat_02"]
    }
  ],
  "revision_plan": "具体的重写建议"
}
```

**精修策略指导**:
- **精准裁剪原则**: 不要要求全部重写，只微调越过边界的具体句子
- **示例**: 原文"推开门，发现敌人" → 修改为"手搭在门把上，心跳如鼓"

**温度设置**: `temperature=0.1`（极低，保证判断一致性）

---

### Phase 7: REFINING（精修）- 局部精修模式

**文件**: `backend/services/workflows/refining.py`

**函数**: `refine_single_beat()` (行 71-221)

**触发条件**:
- Review 未通过 (`pass: false`)
- 存在 `target_beat_ids` 定位问题 Beat
- `iteration < max_iterations`

**V3.0 广播式切片精修** (Broadcast Iterative Refine):

当 Review 返回的 beat_ids 无效时（如幻觉的 beat-13），触发广播式精修：
1. 将 revision_plan 广播给所有 active beats
2. 逐一调用 `refine_single_beat()` 进行局部重写
3. 精修后重新进行 **STITCHING_AFTER_BROADCAST**

**精准制导打点精修** (Bug 1 修复):
```python
# 算法：I_k = { i ∈ I | k ∈ i.target_beat_ids }
# 只将 target_beat_ids 包含当前 beat_id 的 issues 传入该 beat 的精修
targeted_issues = []
for issue in all_issues:
    target_beat_ids = issue.get("target_beat_ids", [])
    if not target_beat_ids or current_beat_id in target_beat_ids:
        targeted_issues.append(issue.get("description", ""))
```

**纠偏机制**:
```python
def _is_refine_output_suspiciously_short():
    # 如果精修后文本长度 < 原文的 55%(越界) 或 70%(普通)
    # 触发 retry，要求重新完整重写
```

---

### Phase 8: FORMATTING（格式化）

**文件**: `backend/services/prompts/format_prompts.py`

**触发条件**: `_needs_formatting()` 检测到需要格式化
- 文本长度 >= 800 字符
- 无段落分隔 (`\n\n`)
- 存在长行 (>= 180 字符) >= 2 处

**处理内容**:
1. 段落规范化（统一换行符）
2. 标点符号规范化
3. 去除多余空格
4. 对话格式统一

---

## 三、迭代控制与状态流转

### 状态变量

| 变量 | 初始值 | 用途 |
|------|--------|------|
| `iteration` | 0 | 当前迭代轮次（最多 max_iterations） |
| `current_draft` | "" | 当前版本的正文 |
| `revision_plan` | "" | 来自 Review Agent 的修改建议 |
| `review_passed` | False | 审查是否通过 |
| `skip_drafting_stitching` | False | 局部精修后跳过完整的 DRAFTING |

### 迭代退出条件

1. **正常通过**: `review_result.get("pass") == True`
2. **轻微问题跳过**: `skip_minor_refine=True` 且所有 issues 的 severity 为 low/minor
3. **达到最大迭代次数**: `iteration >= max_iterations`（默认 2，最大 5）

---

## 四、Prompt 与关键变量汇总表

| 阶段 | Prompt 文件 | 核心函数 | 温度 | 关键变量 |
|------|-------------|----------|------|----------|
| PLANNING | `planner_prompts.py` | `build_planner_agent_prompt` | 0.2 | `chapter`, `book`, `entities`, `relationships`, `word_count`, `open_hooks`, `global_taboos`, `author_intent`, `tension_level` |
| POV_ASSIGNMENT | `planning.py` | `assign_pov_to_beats` | - | `beats`, `characters`, `story_premise`, `previous_chapter_summary` |
| SCENE_INTENT | `scene_intent_prompts.py` | `build_scene_intent_prompt` | 0.2 | `chapter`, `beat`, `open_hooks`, `pacing_style`, `anchor_pov` |
| SUBCONSCIOUS | `draft_prompts.py` | `build_subconscious_prompt` | 0.4 | `chapter`, `beat`, `scene_intent`, `entities`, `pov_perception_state`, `red_lines`, `previous_tail` |
| PROSE_DRAFT | `draft_prompts.py` | `build_prose_draft_prompt_v25` | 0.75 | `chapter`, `book`, `beat`, `scene_intent`, `subconscious_thought`, `previous_tail`, `target_words`, `dynamic_context`, `chapter_assets_schema`, `pov_perception_state` |
| STITCHING | `stitch_prompts.py` + `stitching.py` | `build_stitch_prompt` / `stitch_chunks` | 0.4 | `chapter`, `beats`, `chunks`, `word_count`, `anchor_pov`, `sketch_text`, `book` |
| SKETCH_GEN | `sketch_generator.py` | `SketchGenerator.generate()` | 0.8 | `chapter`, `book`, `beats`, `entities`, `relationships`, `target_words`, `previous_summary`, `anchor_pov` |
| ADV_ALIGNMENT | `adversarial_aligner.py` | `AdversarialAligner.align()` | 0.1 | `draft_text`, `sketch_result`, `beats`, `chapter`, `book` |
| FUSION_REFINE | `dual_track.py` + `refining.py` | `_execute_fusion_refinement()` + `refine_single_beat()` | 0.7 | `stitched_draft`, `sketch_result`, `adjustment_plan`, `beats`, `chapter`, `book`; prompt label: `FUSION_REFINE_BEAT_{beat_id}` |
| REVIEWING | `review_prompts.py` | `build_review_agent_prompt` | 0.1 | `chapter`, `book`, `entities`, `relationships`, `chapter_outline`, `draft_text`, `beats` |
| REFINING | `refining.py` | `refine_single_beat` | 0.7 | `beat`, `original_chunk`, `revision_guide`, `all_issues`, `chapter`, `book` |
| CHUNK_REFINE | `review_prompts.py` | `build_chunk_refine_prompt` | 0.7 | `chapter`, `book`, `entities`, `relationships`, `beat_summary`, `chunk_text`, `revision_instruction` |
| FORMATTING | `format_prompts.py` | `build_formatting_prompt` | 0.1 | `draft_text` |

### V3.0 功能开关配置 (DraftingFeatureFlags)

**定义**: `backend/schemas.py` (行 762-783)

| 开关 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enable_fail_fast` | bool | True | 启用 Fail-Fast 断言检查与回溯重试 |
| `enable_emotional_scratchpad` | bool | True | 启用动态情绪暂存器更新 |
| `enable_whisper_memory` | bool | False | 启用 RAG 记忆暂存（预留接口） |
| `fail_fast_max_attempts` | int | 2 | Fail-Fast 最大重试次数（范围 1-3） |
| `fail_fast_temperature_step` | float | 0.2 | 每次重试温度增量（范围 0.0-0.5） |
| `workflow_tier` | WorkflowTier | TIER_2_STANDARD | 智能路由工作流层级 |

### V3.5 双轨配置 (DualTrackConfig)

**定义**: `backend/services/workflows/dual_track.py` (行 30-60)

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_sketch_track` | bool | True | 启用 Track B (短文生成) |
| `enable_adversarial_alignment` | bool | True | 启用对抗校对 |
| `use_sketch_for_refinement` | bool | True | 使用 Sketch 指导精修 |
| `alignment_threshold` | float | 70.0 | 对齐度阈值，低于此值触发精修 |
| `sketch_ratio` | float | 0.45 | Sketch 字数 / 正文字数 |

### WorkflowTier 映射规则

```python
def map_tension_to_workflow_tier(tension_level: int) -> WorkflowTier:
    if tension_level <= 2:
        return "TIER_1_FAST"      # 疾速流
    elif tension_level == 3:
        return "TIER_2_STANDARD"  # 均衡流
    else:
        return "TIER_3_FORTRESS"  # 堡垒流
```

---

## 五、数据流向图

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Chapter   │───→│    Book     │───→│  Character  │
│  (章节信息)  │    │  (书籍设定)  │    │   (角色卡)   │
└─────────────┘    └─────────────┘    └─────────────┘
       │                  │                  │
       └──────────────────┴──────────────────┘
                          ↓
              ┌─────────────────┐
              │ ASSEMBLING_CTX  │
              │  (上下文组装)    │
              └─────────────────┘
                          ↓
              ┌─────────────────┐
              │    PLANNING     │
              │ (生成 beats 列表)│
              │ (含 workflow_tier)│
              └─────────────────┘
                          ↓
              ┌─────────────────┐
              │ POV_ASSIGNMENT  │
              │ (Anchor POV分配)│
              └─────────────────┘
                          ↓
       ┌──────────────────┼──────────────────┐
       │                  │                  │
       ↓                  ↓                  ↓
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  TIER_1_FAST│   │TIER_2_STAND │   │TIER_3_FORT  │
│  (疾速流)    │   │  (均衡流)    │   │  (堡垒流)    │
├─────────────┤   ├─────────────┤   ├─────────────┤
│跳过Scene/Sub│   │轻量级Scene  │   │完整Scene    │
│单次生成     │   │轻量级Sub    │   │MCTS三分支   │
│直接拼接     │   │CoreDynamicC │   │Full 5D DC   │
└─────────────┘   └─────────────┘   └─────────────┘
       │                  │                  │
       └──────────────────┼──────────────────┘
                          ↓
              ┌─────────────────┐
              │    STITCHING    │
              │  (统稿拼接)      │
              └─────────────────┘
                          ↓
              ┌─────────────────┐
              │    REVIEWING    │
              │  (质量审查)      │
              └─────────────────┘
                          ↓
              ┌─────────────────┐
              │  pass? ──→ YES ─┼──→ FORMATTING → DONE
              │        └──→ NO  │
              └─────────────────┘
                          ↓
              ┌─────────────────┐
              │  target_beat_ids?│
              │  (定位问题Beat)  │
              └─────────────────┘
                          ↓
              ┌─────────────────┐
              │ 有效? → 精准制导 │
              │ 无效? → 广播精修 │
              └─────────────────┘
                          ↓
              ┌─────────────────┐
              │ STITCHING_AFTER │
              │   _REFINE       │
              └─────────────────┘
                          ↓
                    (返回 REVIEWING)
```

### DynamicContext 跨 Beat 流转示意

```
Beat 1:  Subconscious_1 ──→ Prose_1 ──→ DynamicContext_1
                                              ↓
Beat 2:  Subconscious_2 ──→ Prose_2 ──→ DynamicContext_2
                                              ↓
                         ...
                                              ↓
Beat N:  Subconscious_N ──→ Prose_N ──→ DynamicContext_N

公式: Context_n = Subconscious_n + DynamicContext_(n-1)
```

---

## 六、核心设计思想

系统的核心设计思想是**分层生成 + 迭代精修 + 认知状态流转 + 智能路由**：

### 1. 冰山模型 (Iceberg Model)
将生成拆分为两层：
- **Subconscious（潜意识层）**: 50-100字的第一人称内心独白，为 Prose 提供情感锚点
- **Prose（正文层）**: 基于潜意识沉浸式续写，专注于动作和对话的自然流动
- **双模型路由**: reasoning_model 处理逻辑层，creative_model 处理创意层

### 2. 蒙特卡洛树搜索 (MCTS) 潜意识推演
在 Subconscious 阶段展开 3 条分支：
- **分支A**: 本能反抗/冲动思维（可能违背红线）
- **分支B**: 知觉受限条件下的无力感/痛觉思维
- **分支C**: 结合性格设定的战术/极端环境思维

**评估与剪枝**: 任何可能导致违背红线、物理状态或动机连贯性的分支，直接打分为 0 并淘汰

### 3. Rolling Prefix 连贯性机制
- Beat n 接收 Beat n-1 的末尾 **300 字符** 作为上下文
- 保证 Beat 间的语气、节奏和动作状态无缝衔接
- 禁止"与此同时"、"就在这时"等生硬转场词

### 4. DynamicContext 五维认知状态
跨 Beat 流转的动态上下文容器：
| 维度 | 字段 | 作用 |
|------|------|------|
| 物理边界 | `physical_state_lock` | 防幻觉边界锁定 |
| 情绪演化 | `current_emotional_state` | 性格微演变跟踪 |
| 上下文记忆 | `previous_tail` | Rolling Prefix 机制 |
| 剧情摘要 | `accumulated_summary` | 宏观剧情累加器（≤500字符） |
| 关系状态 | `relational_state_lock` | 在场角色动态关系锁 |
| 空间账本 | `entity_spatial_ledger` | 角色物理形态与空间从属 |

### 5. Fail-Fast 防错机制
**触发条件**: `enable_fail_fast=True`（默认开启）

**断言检查项**:
- 是否触碰 red_lines（红线约束）
- 是否存在 Physical Hallucination（物理状态冲突）
- 是否存在 OOC Behavior（角色行为偏离设定）
- 是否存在 Relationship Jump（人物关系无逻辑突变）
- 是否存在 Style Issue（文风问题）

**回溯策略**: 
- 断言失败时根据失败类别调整温度
- 文风问题：提高温度重新采样
- 逻辑错误：降低温度并注入错误提示
- 最多 `fail_fast_max_attempts` 次重试

### 6. Anchor POV 视角统一机制
- 由 LLM 分析章节内容，选定最适合的 **单一主视角角色**
- 所有 Beat 的 `pov_character` 统一设置为 anchor_pov
- 保留原始角色到 `original_actor`，用于**感官转化法则**
- **感官转化法则**: 非主视角事件必须转化为主视角能感知的物理异象

### 7. V3.0 智能路由三档执行路径
基于 `tension_level` 自动选择执行路径，实现算力资源的智能分配：

| 特性 | TIER_1_FAST | TIER_2_STANDARD | TIER_3_FORTRESS |
|------|-------------|-----------------|-----------------|
| 适用张力 | 1-2 | 3 | 4-5 |
| 场景 | 日常/过渡 | 中等冲突 | 高潮/关键剧情 |
| Scene Intent | ✗ | ✓ | ✓ |
| Subconscious | ✗ | 轻量级 | MCTS三分支 |
| DynamicContext | Rolling Prefix | Core | Full 5D |
| Fail-Fast | ✗ | ✓ | ✓ |
| 算力消耗 | 低 | 中 | 高 |

### 8. 局部精修闭环
Review 发现问题后：
1. 通过 `target_beat_ids` 定位问题 Beat
2. **精准制导**: 只传入与该 Beat 相关的 issues（算法：I_k = { i ∈ I | k ∈ i.target_beat_ids }）
3. **广播精修**: 若 beat_ids 无效，对所有 beats 进行广播式精修
4. 使用 `previous_tail` 保持语气衔接
5. 精修后重新 Stitching，而非整章重写
6. **纠偏机制**: 检测精修后文本是否过度缩短，触发 retry

### 9. 字数分配算法
基于 `pacing_type` 和 `weight` 自动计算每个 beat 的目标字数：
```python
multipliers = {"Fast": 0.8, "Medium": 1.0, "Slow": 1.2}
score = weight * multiplier
word_count = (score / total_score) * total_chapter_words
```

---

*最后更新: 2026-03-23*
*版本: V3.5.3 双轨对抗架构 - 连贯性预防式改进*

**V3.5.3 变更摘要**:
- **统稿阶段传入 Sketch 参考**: `stitch_chunks()` 新增 `sketch_text` 参数，统稿器主动学习 Sketch 的过渡技巧
- **对抗校对分段采样**: `_sample_text_segments()` 替代硬截取前 2000 字，覆盖开头 40% + 中间 20% + 结尾 40%
- **对齐度得分提升**: 实测从 ~61 提升至 84+，大幅减少融合精修触发
- **预防式改进架构**: 通过统稿阶段学习 Sketch 连贯性，而非事后修复

**V3.5.2 变更摘要**:
- PLANNING 双轨快速路径（confirmed_beats_from_frontend），0秒完成节拍规划
- `_save_story_beats` 幂等化（先 DELETE 旧记录再 INSERT）
- `_is_key_beat` fallback 阈值从 `==0` 提升为 `<min(3, len(beats))`，确保 LLM 信息对齐分析覆盖足够场景
- STITCHING / INFO_ALIGNMENT_ANALYSIS / FUSION_REFINEMENT / FUSION_REFINE_BEAT_{id} 全部接入 PromptLogger
- FUSION_REFINEMENT 阶段新增 `beats_to_refine` + `word_diff` 输出字段，实现前后字数变化可观测
