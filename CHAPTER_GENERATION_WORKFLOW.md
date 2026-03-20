# Velluma 文章生成全流程逻辑链文档

## 一、整体架构概览

Velluma 采用 **Agentic Workflow（智能体工作流）** 架构，通过多轮迭代生成高质量小说章节。系统使用 **双模型架构（冰山模型）**：
- **reasoning_model**: 高逻辑模型，用于 Scene Intent、Subconscious、Review 阶段
- **creative_model**: 高创意模型，用于 Prose Draft 阶段

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

核心特性：
- 双模型架构：reasoning_model（高逻辑）+ creative_model（高创意）
- V2.5 认知流式生成：Scene Intent + Subconscious 并行，Prose 串行 Rolling Prefix
- DynamicContext：跨 Beat 流转的五维认知状态容器
- Fail-Fast 机制：即时断言检查与回溯重试
```

---

## 二、各阶段详细逻辑链

### Phase 1: ASSEMBLING_CONTEXT（上下文组装）

**文件**: `backend/services/agentic_workflow.py` (行 600-713)

**职责**: 从数据库加载所有必要的上下文信息

**关键变量**:

| 变量 | 类型 | 用途 |
|------|------|------|
| `chapter` | Chapter | 当前章节实体（大纲、标题、张力等级等） |
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

**核心函数**: `build_planner_agent_prompt()` (行 32-220)

**职责**: 将章节大纲拆分为可执行的 **Story Beats（剧情节拍）**

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
      "pov_perception_state": "正常",  # 角色意识清醒程度
      "action_summary": "动作化执行摘要",
      "entry_state": "本段切入时的起始状态",
      "exit_state": "本段必须停住的收束状态",
      "red_lines": ["禁止发生1", "禁止发生2"],  # 红线约束
      "word_count_target": 600,
      "hook_ids": ["hk-1"],  # 绑定的伏笔
      "pacing_type": "Medium",  # Fast/Medium/Slow
      "weight": 3  # 1-5 权重
    }
  ]
}
```

**约束条件**:
- beats 数量: 1-6 个
- 每个 beat 必须有 entry_state、exit_state、red_lines
- exit_state 是硬停点，不能把后续 beat 事件提前
- 低张力章节(tension_level<=3)自动注入红线: `["避免正面冲突", "避免战斗升级"]`

**User Prompt 结构**:
```
## 0. 绝对最高优先级指令 (Absolute Highest Priority)
【全局禁忌/核心母题】{global_taboos}
【作者创作意图】{author_intent} (优先级高于大纲)

【章节名】{chapter_name}
【剧情张力等级】{tension_level}
【叙事节奏偏好】{pacing_style}
【上一章情节概要】{previous_chapter_summary}
【章节大纲】{outline_text}
【目标字数】{word_count}
【角色设定】...
【关系约束】...
【开放伏笔】...
```

**输出解析**: `parse_planner_result()` (行 223-366)
- 容错解析: 直接解析 → Markdown代码块 → 首尾大括号
- 失败回退: 使用大纲生成单个 fallback beat

---

### Phase 3: POV_ASSIGNMENT（视角分配）- Anchor POV 机制

**文件**: `backend/services/workflows/planning.py`

**核心函数**: `assign_pov_to_beats()` (行 95-210)

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

### Phase 4: DRAFTING（起草）- V2.5 认知流式生成

**文件**: `backend/services/workflows/drafting.py`

**核心函数**: `execute_draft_stage()` (行 76-230)

**输出数据结构** `BeatDraftResult`:
```python
class BeatDraftResult(BaseModel):
    beat_id: str                    # Beat 唯一标识
    beat_index: int                 # Beat 位置索引（从1开始）
    scene_intent: dict              # Scene Intent 分析结果
    subconscious_thought: str       # 角色潜意识/内心独白（50-100字）
    draft_chunk: str                # 生成的小说正文
    prompts: List[dict]             # 全流程提示词历史（Scene Intent + Subconscious + Prose）
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

#### 3.1 Scene Intent 生成

**文件**: `backend/services/prompts/scene_intent_prompts.py`

**函数**: `build_scene_intent_prompt()` (行 26-110)

**输出结构**:
```json
{
  "intent_label": "场景标签",
  "goal": "本场景目标",
  "stakes": "失败代价或风险",
  "constraints": ["约束1", "约束2"],
  "sensory_translation_rule": "感官转化规则（非主视角事件）"
}
```

**节奏微观指令** (PACING_MICRO_INSTRUCTIONS):
- **slow_burn**: 单段只推进一个小动作，冲突表达以试探、停顿为主
- **fast_paced**: 每段至少一个可见动作变化，句式更短更直接
- **balanced**: 动作推进与情绪描写保持均衡

#### 3.2 Subconscious 生成（MCTS 潜意识树搜索）

**文件**: `backend/services/prompts/draft_prompts.py` (行 107-207)

**函数**: `build_subconscious_prompt()`

**MCTS (Monte Carlo Tree Search) 设计**:
```python
# 展开 3 条潜意识分支
分支A：基于本能反抗或冲动的思维（可能极易违背红线）
分支B：基于当前知觉受限条件下的无力感、痛觉或冷酷本能
分支C：结合特定性格设定的战术/极端环境思维

# 评估与剪枝
- 任何有一丝可能导致后续动作违背【红线】的分支，直接打分为 0
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
| `pov_perception_state` | POV 角色当前物理知觉状态（"正常"/"半昏迷"/"重伤行动受限"等） |
| `red_lines` | 红线约束列表，用于评估分支安全性 |
| `previous_tail` | 伪前文（前一 beat 的 exit_state + 当前 entry_state） |

#### 3.3 Prose Draft 生成（V2.5 串行滑动窗口）

**文件**: `backend/services/workflows/drafting.py` (行 424-698)

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
       current_emotional_state: str = "初始状态：未知"  # 主角当前心理状态（随剧情演变）
       physical_state_lock: str = ""              # 绝对物理状态约束（防幻觉边界）
       pov_perception_state: str = ""             # POV角色清醒程度与物理行动力
       accumulated_summary: str = ""              # 宏观剧情累加器（跨Beat剧情摘要，≤500字符）
       relational_state_lock: str = ""            # 在场角色动态关系锁（防止关系错乱）
       active_whispers: dict = {}                 # 激活的RAG记忆片段（预留）
       entity_spatial_ledger: Dict[str, CharacterPhysicalState] = {}  # 角色物理形态与空间从属
   ```
   
   **CharacterPhysicalState 字段**:
   - `is_in_vehicle`: 是否处于载具/机甲内部
   - `vehicle_or_mech_name`: 所在载具/机甲名称
   - `equipped_weapons`: 当前装备的武器列表
   - `movement_constraints`: 移动限制说明（如"深度昏迷，无法自主移动"）

3. **Fail-Fast 断言检查** (行 700-801):
   ```python
   async def _micro_review_assertion():
       # 断言决策树
       IF Violate(red_lines): RETURN (False, "触碰红线约束")
       IF Physical_Hallucination: RETURN (False, "物理状态冲突")
       IF OOC_Behavior: RETURN (False, "角色行为偏离设定")
       IF Relationship_Jump: RETURN (False, "人物关系无逻辑突变")
       RETURN (True, "")
   ```

4. **Emotional Scratchpad 状态更新** (行 803-868):
   - 基于刚生成的剧情，总结新的角色内心状态
   - 更新关系状态锁、宏观剧情累加器

**Prompt 构建**: `build_prose_draft_prompt_v25()` (行 540+)

**关键约束**:
- **单一视角锁定**: 绝对锁定在 POV 角色的感官范围内
- **反AI味协议**: 禁止设定倾倒、预告片旁白、形容词堆砌
- **危机递进法则**: 禁止从 0 直接跳到 100，必须使用三段式危机爬升

---

### Phase 4: STITCHING（统稿）

**文件**: `backend/services/prompts/stitch_prompts.py`

**函数**: `build_stitch_prompt()` (行 20-106)

**职责**: 将多个 Beat 生成的 chunks 融合成连贯的章节正文

**统稿规则**:
1. **重点修复**: 检查各 Chunk 之间的连接点，消除突兀的场景转换
2. **抹除劣质胶水词**: 强制删去"与此同时"、"视角回到"、"在这关键时刻"
3. **收束去AI味**: 去除段落末尾拔高立意的"旁白说教"
4. **黑名单词库约束**: 避免使用 style_blacklist 中的词汇
5. **单一连续时间线**: 抹去非主视角的描写，合并为主视角的背景板感知流

**温度设置**: `temperature=0.4`（较低，保持稳定性）

---

### Phase 5: REVIEWING（审阅）

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

### Phase 6: REFINING（精修）- 局部精修模式

**文件**: `backend/services/workflows/refining.py`

**函数**: `refine_single_beat()` (行 114+)

**触发条件**:
- Review 未通过 (`pass: false`)
- 存在 `target_beat_ids` 定位问题 Beat
- `iteration < max_iterations`

**局部精修流程**:
1. 根据 `target_beat_ids` 提取需要精修的 Beat chunks
2. 提取该 Beat 对应的 issue descriptions
3. 获取前一个 Beat 的尾部文本 (`previous_tail`) 用于语气衔接
4. 对每个问题 Beat 调用 `refine_single_beat()`
5. 精修后重新进行 **STITCHING_AFTER_REFINE**

**纠偏机制**:
```python
def _is_refine_output_suspiciously_short():
    # 如果精修后文本长度 < 原文的 55%(越界) 或 70%(普通)
    # 触发 retry，要求重新完整重写
```

---

### Phase 7: FORMATTING（格式化）

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
| PLANNING | `planner_prompts.py` | `build_planner_agent_prompt` | 0.2 | `chapter`, `book`, `entities`, `relationships`, `word_count`, `open_hooks`, `global_taboos`, `author_intent` |
| POV_ASSIGNMENT | `planning.py` | `assign_pov_to_beats` | 0.3 | `beats`, `characters`, `story_premise`, `previous_chapter_summary` |
| SCENE_INTENT | `scene_intent_prompts.py` | `build_scene_intent_prompt` | 0.2 | `chapter`, `beat`, `open_hooks`, `pacing_style`, `anchor_pov` |
| SUBCONSCIOUS | `draft_prompts.py` | `build_subconscious_prompt` | 0.4 | `chapter`, `beat`, `scene_intent`, `entities`, `pov_perception_state`, `red_lines`, `previous_tail` |
| PROSE_DRAFT | `draft_prompts.py` | `build_prose_draft_prompt_v25` | 0.75 | `chapter`, `book`, `beat`, `scene_intent`, `subconscious_thought`, `previous_tail`, `target_words`, `dynamic_context` |
| STITCHING | `stitch_prompts.py` | `build_stitch_prompt` | 0.4 | `chapter`, `beats`, `chunks`, `word_count`, `anchor_pov` |
| REVIEWING | `review_prompts.py` | `build_review_agent_prompt` | 0.1 | `chapter`, `book`, `entities`, `relationships`, `chapter_outline`, `draft_text`, `beats` |
| REFINING | `review_prompts.py` | `build_refine_agent_prompt` | 0.7 | `chapter`, `book`, `entities`, `relationships`, `draft_text`, `revision_plan`, `word_count` |
| CHUNK_REFINE | `review_prompts.py` | `build_chunk_refine_prompt` | 0.7 | `chapter`, `book`, `entities`, `relationships`, `beat_summary`, `chunk_text`, `revision_instruction` |
| FORMATTING | `format_prompts.py` | `build_formatting_prompt` | 0.1 | `draft_text` |

### V2.5 功能开关配置 (DraftingFeatureFlags)

**定义**: `backend/schemas.py` (行 715-732)

| 开关 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enable_fail_fast` | bool | True | 启用 Fail-Fast 断言检查与回溯重试 |
| `enable_emotional_scratchpad` | bool | True | 启用动态情绪暂存器更新 |
| `enable_whisper_memory` | bool | False | 启用 RAG 记忆暂存（预留接口） |
| `fail_fast_max_attempts` | int | 2 | Fail-Fast 最大重试次数（范围 1-3） |
| `fail_fast_temperature_step` | float | 0.2 | 每次重试温度增量（范围 0.0-0.5） |

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
              └─────────────────┘
                          ↓
              ┌─────────────────┐
              │ POV_ASSIGNMENT  │
              │ (Anchor POV分配)│
              └─────────────────┘
                          ↓
       ┌──────────────────┼──────────────────┐
       ↓                  ↓                  ↓
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ SceneIntent │   │ SceneIntent │   │ SceneIntent │  ← 并行生成
│  (Beat 1)   │   │  (Beat 2)   │   │  (Beat n)   │
└─────────────┘   └─────────────┘   └─────────────┘
       ↓                  ↓                  ↓
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ Subconscious│   │ Subconscious│   │ Subconscious│  ← 并行生成 (MCTS)
│  (Beat 1)   │   │  (Beat 2)   │   │  (Beat n)   │
└─────────────┘   └─────────────┘   └─────────────┘
       ↓                  ↓                  ↓
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ Prose Draft │──→│ Prose Draft │──→│ Prose Draft │  ← 串行 Rolling
│  (Beat 1)   │   │  (Beat 2)   │   │  (Beat n)   │     Prefix + 
└─────────────┘   └─────────────┘   └─────────────┘     DynamicContext
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
              │  target_beat_ids│
              │  (定位问题Beat)  │
              └─────────────────┘
                          ↓
              ┌─────────────────┐
              │ CHUNK_REFINE    │
              │ (局部精修)       │
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

系统的核心设计思想是**分层生成 + 迭代精修 + 认知状态流转**：

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

**评估与剪枝**: 任何可能导致违背红线或物理状态的分支，直接打分为 0 并淘汰

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

### 5. Fail-Fast 防错机制
**触发条件**: `enable_fail_fast=True`（默认开启）

**断言检查项**:
- 是否触碰 red_lines（红线约束）
- 是否存在 Physical Hallucination（物理状态冲突）
- 是否存在 OOC Behavior（角色行为偏离设定）
- 是否存在 Relationship Jump（人物关系无逻辑突变）

**回溯策略**: 断言失败时提高温度（`+fail_fast_temperature_step`）并重试，最多 `fail_fast_max_attempts` 次

### 6. Anchor POV 视角统一机制
- 由 LLM 分析章节内容，选定最适合的 **单一主视角角色**
- 所有 Beat 的 `pov_character` 统一设置为 anchor_pov
- 保留原始角色到 `original_actor`，用于**感官转化法则**
- **感官转化法则**: 非主视角事件必须转化为主视角能感知的物理异象

### 7. 局部精修闭环
Review 发现问题后：
1. 通过 `target_beat_ids` 定位问题 Beat
2. 仅对问题 Beat 调用 `refine_single_beat()`
3. 使用 `previous_tail` 保持语气衔接
4. 精修后重新 Stitching，而非整章重写
5. **纠偏机制**: 检测精修后文本是否过度缩短，触发 retry
