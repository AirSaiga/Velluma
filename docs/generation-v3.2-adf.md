# Velluma 生成引擎 V3.2 — ADF（Anchor-Driven Flow）设计文档

> **版本**：V3.2（Anchor-Driven Flow，锚点驱动正向流）
> **状态**：当前默认（且唯一保留的）生成引擎；V3.0/V3.1/V4.0 已废弃归档
> **日期**：2026-07-21
> **前置**：V3.1 统一引擎（`docs/generation-v3.1-unified.md`，已废弃）
> **关系**：原计划与 V3.1 并存；经 2026-07-24 引擎剥离后，V3.1/V3.0/V4.0 端点均已移除，V3.2 ADF（`POST /api/chapters/{id}/generate-adf`）成为唯一保留的生成引擎

---

## 0. 设计动机

### 0.1 V3.1 的根本病灶

V3.1 引爆链的 `chain_grower` 是**纯因果回溯**：从高潮倒推铺垫节点，按 `reading_order` 线性拼接正文。
这种"预先设计完整铺垫树 + 线性化拼接"在叙事上有三个致命缺陷：

1. **节点是功能性的，不是场景性的** —— 节点为服务高潮而存在，彼此间无自然场景过渡，导致角色/场景切换突兀
2. **节点是树关系，不是流关系** —— 多个铺垫朝 PAYLOAD 收敛，横向关系（场景共用/角色交接/时间先后）未被建模
3. **章节当孤岛** —— 逆向推到根部就是章节入口，但入口状态应由前章出口决定，逆向链无此建模

### 0.2 双轨为什么流畅但高潮弱

双轨是**纯正向**：每段从前段尾部 500 字涌现，呼吸连续；但每段"自我完满"，情绪势能累积不起来。

### 0.3 矛盾本质

```
正向（双轨）：流畅 ∩ 高潮弱
逆向（引爆）：高潮强 ∩ 流畅弱
```

V3.2 ADF 的目标是 **流畅 ∩ 高潮强**。这不可能通过调参实现，因为它是因果方向的根本矛盾。
ADF 用一个新范式解决：**设计要逆向（知道要去哪），执行要正向（顺势流出），约束要全局（符合脉络）**。

---

## 1. 核心思想

> **只设计高潮和必要锚点，不设计铺垫树；铺垫由正向写作时从前文涌现。**

把"设计高潮"和"执行正文"彻底解耦：

- **设计时（逆向，轻量）**：只设定 1 个高潮 + 3-5 个必要前置条件 + 全局脉络轨
- **执行时（正向，重执行）**：从章节入口逐段写作，每段受三方约束（前文衔接 / 脉络轨 / 远端锚牵引）
- **铺垫是 emergent 的**：写作时实时扫描"哪些前置条件还没埋"，软提示 LLM 在自然场景中埋下

### 1.1 关键转变：从"节点"到"条件"

V3.1 输出 `SetupNode` 列表（每个节点对应正文一段），正文按 `reading_order` 拼接。
V3.2 输出 `Precondition` 列表（每个条件是"高潮落地前必须满足的状态"，不对应特定段落），正文正向写作时**路过即埋**，埋设位置由前文自然涌现决定。

```
V3.1: 高潮 ← Node4 ← Node3 ← Node2 ← Node1     （树线性化）
V3.2: 高潮 ← {Cond A, Cond B, Cond C}            （条件集合，无序）
      正文正向流：seg1 → seg2 → seg3 → seg4 → seg5
      每段后扫描：哪些 Cond 还没埋？下一段软提示埋设
```

### 1.2 人类作家隐喻

人类作家写一章时脑子里有三样东西：

1. **远端目标**（这章高潮是什么）—— 逆向的
2. **入口状态**（上一章结尾，角色在哪/情绪在哪/伏笔在哪）—— 全局的
3. **当下场景流**（接下来这个场景自然会发生什么）—— 正向的

**人类作家不预先设计完整铺垫树。** 他只知道高潮和几个锚点，中间的铺垫是写作过程中**凭直觉涌现**的——写到第 3 段时凭直觉知道"这里该埋一笔了"。

ADF 把这种"凭直觉"变成"运行时扫描 + 软提示"。

---

## 2. 三层架构

```
┌─────────────────────────────────────────────────┐
│  Layer 1: 远端锚（Distal Anchor）— 逆向，轻量    │
│  1 个高潮点 + 3-5 个必要前置条件（不是节点）      │
└─────────────────────────────────────────────────┘
                        ↓ 牵引（不强制路径）
┌─────────────────────────────────────────────────┐
│  Layer 2: 脉络轨（Spine Track）— 全局，新增       │
│  入口状态（前章出口）+ 出口预期 + 本章位置 +       │
│  必须推进的角色弧/伏笔                            │
└─────────────────────────────────────────────────┘
                        ↓ 约束（强约束）
┌─────────────────────────────────────────────────┐
│  Layer 3: 正向流（Forward Flow）— 正向，重执行    │
│  从入口逐段写作，每段三方约束：                   │
│  (a) 前文衔接（rolling prefix 500 字）            │
│  (b) 脉络轨（场景/角色弧约束）                    │
│  (c) 远端锚牵引（情绪曲线进度条）                  │
└─────────────────────────────────────────────────┘
```

---

## 3. 数据结构

### 3.1 `DistalAnchor`（远端锚，Layer 1 产出）

```python
@dataclass
class DistalAnchor:
    """远端锚：本章高潮 + 必要前置条件集合。"""
    # 高潮点（1 个）
    climax: "ClimaxSpec"                # 见下
    # 必要前置条件（3-5 个，无序，不对应特定段落）
    preconditions: List["Precondition"]
    # 情绪曲线（连续，非整数距离）
    emotion_curve: "EmotionCurve"
```

### 3.2 `ClimaxSpec`（高潮规格）

```python
@dataclass
class ClimaxSpec:
    description: str                   # 高潮场景描述
    emotional_target: str              # 目标情绪（如：屈辱到爆发的临界点）
    payoff_question: str               # 本章回收的悬念
    open_question: str                 # 本章打开的新悬念（钩子）
    intensity: int                     # 1-10 强度自评（供 tier 决策）
```

### 3.3 `Precondition`（前置条件，核心创新）

```python
@dataclass
class Precondition:
    """高潮落地前必须满足的状态条件（不预设埋设位置）。"""
    id: str                            # 如 "PC_ROLE_HINT"
    category: str                      # "role" | "worldbuilding" | "foreshadow" | "motivation" | "relationship"
    description: str                   # 条件描述（如："建立兰星暗元素/弦月巅峰的真实实力暗示"）
    must_use_terms: List[str]          # 必须出现的设定词（如 ["暗元素", "弦月巅峰"]）
    min_landing_offset: int            # 距高潮至少多少字之前埋下（避免临高潮才补）
    # 运行时状态（由 ForwardFlowWriter 更新）
    landed: bool = False
    landed_segment: Optional[int] = None
    landed_evidence: Optional[str] = None  # 引文
```

### 3.4 `EmotionCurve`（情绪曲线，连续约束）

```python
@dataclass
class EmotionCurve:
    """章节情绪势能曲线（连续，替代 V3.1 的整数 distance_to_climax）。"""
    # 锚点采样（0.0=入口，1.0=高潮）
    samples: List["CurveSample"]       # 按 progress 排序

@dataclass
class CurveSample:
    progress: float                    # 0.0 ~ 1.0
    register: str                      # 情绪基调（如 "压抑隐忍" / "临界" / "爆发"）
    energy: int                        # 1-10 势能
```

典型 climax 档曲线：`[(0.0, 入口, 2), (0.3, 日常压抑, 3), (0.6, 临界, 6), (0.85, 一触即发, 8), (1.0, 爆发, 10)]`

### 3.5 `SpineTrack`（脉络轨，Layer 2）

```python
@dataclass
class SpineTrack:
    """全局脉络轨：把章节从孤岛接回全书脉络。"""
    # 入口状态（从前章继承）
    entry_state: "EntryState"
    # 出口预期（通往后章）
    exit_expectation: "ExitExpectation"
    # 本章在卷中的位置
    chapter_position: "ChapterPosition"
    # 必须埋的钩子（与 Precondition 互补，钩子是"为后章埋"，Precondition 是"为高潮埋"）
    must_plant_hooks: List[str]
    # 必须回收的伏笔
    must_resolve_hooks: List[str]
    # 角色弧推进要求
    character_arc_advances: Dict[str, str]  # {角色名: 本章弧线推进到}
```

```python
@dataclass
class EntryState:
    character_positions: Dict[str, str]   # {角色名: 位置}
    emotional_register: str               # 情绪基调
    open_hooks: List[str]                 # 悬挂的伏笔
    last_scene_image: str                 # 上一章结尾画面（≤200 字）
    time_of_day: Optional[str]            # 时间

@dataclass
class ExitExpectation:
    next_chapter_setup: str               # 为下章铺设什么
    open_question_to_keep: List[str]      # 故意留开的悬念

@dataclass
class ChapterPosition:
    volume_arc: str                       # 本卷主题
    offset_from_volume_climax: int        # 距卷高潮的章数（负=已过）
    pacing_tempo: str                     # "slow_burn" | "balanced" | "fast_paced"
```

### 3.6 `SegmentResult`（正向流写作产出）

```python
@dataclass
class SegmentResult:
    """正向流的一段产出。"""
    index: int                        # 段序号（0-based）
    text: str                         # 本段正文
    scene_summary: str                # 本段场景摘要（供下段 rolling prefix 用）
    emotion_register: str             # 本段情绪基调
    landed_preconditions: List[str]   # 本段埋下的 Precondition id
    planted_hooks: List[str]          # 本段埋下的钩子 id
```

### 3.7 `ADFResult`（总结果）

```python
@dataclass
class ADFResult:
    distal_anchor: DistalAnchor
    spine_track: SpineTrack
    segments: List[SegmentResult]
    final_text: str                   # 拼接后的完整正文
    audit: "ADFAudit"                 # 审校结论
    stats: Dict[str, Any]
    degraded: List[Dict[str, Any]]
```

---

## 4. 工作流阶段（七 Phase）

```
Phase 0: CONTEXT_ASSEMBLING     上下文加载（复用 V3.1）
Phase 1: SPINE_BUILDING         脉络轨构建（0-1 次 LLM，纯算法为主）
Phase 2: ANCHOR_DESIGN          远端锚设计（1 次 reasoning：高潮+条件+曲线）
Phase 3: TIER_DECIDE            定档（复用 V3.1 tier_classifier，0 LLM）
Phase 4: FORWARD_FLOW           正向流写作（核心，N 次 creative）
Phase 5: ANCHOR_AUDIT           锚点审计（1 次 reasoning：条件落地+情绪曲线+脉络符合）
Phase 6: REFINE                 条件补埋（0-K 次 creative，仅未落地条件）
```

### 4.1 Phase 1: SPINE_BUILDING（脉络轨构建）

- **目的**：把章节从孤岛接回全书脉络
- **方法**：纯算法为主，必要时 1 次 reasoning LLM
  - `entry_state`：从前章 `summary` + `chapter.rolling_summary` + `open_hooks` 抽取
  - `exit_expectation`：从 chapter_card `must_hit_events` + 后章 outline 推断
  - `chapter_position`：从 `chapter.chapter_number` + 卷信息计算
  - `must_plant_hooks` / `must_resolve_hooks`：从 PlotLedger 表读取
  - `character_arc_advances`：从 chapter_card + 角色静态卡推断
- **LLM**：仅当 `entry_state.last_scene_image` 缺失时调 1 次 reasoning（小模型）补全
- **降级**：失败时空值填充，不阻塞

### 4.2 Phase 2: ANCHOR_DESIGN（远端锚设计，核心创新 #1）

- **目的**：设计高潮 + 3-5 个前置条件 + 情绪曲线
- **方法**：1 次 reasoning LLM 调用
- **输入 prompt**：
  - 章节大纲 / 章节卡
  - 脉络轨（Phase 1 产出，强约束：必须埋的钩子要成为某些 Precondition）
  - 前文摘要 / 开放伏笔
- **输出 JSON**：
  ```json
  {
    "climax": {
      "description": "...",
      "emotional_target": "...",
      "payoff_question": "...",
      "open_question": "...",
      "intensity": 8
    },
    "preconditions": [
      {
        "id": "PC_REAL_POWER",
        "category": "role",
        "description": "建立主角暗元素/弦月巅峰的真实实力暗示",
        "must_use_terms": ["暗元素", "弦月巅峰"],
        "min_landing_offset": 500
      }
    ],
    "emotion_curve": {
      "samples": [
        {"progress": 0.0, "register": "入口", "energy": 2},
        {"progress": 0.6, "register": "临界", "energy": 6},
        {"progress": 1.0, "register": "爆发", "energy": 10}
      ]
    }
  }
  ```
- **max_tokens**：4096
- **关键约束**：必须为 `spine_track.must_plant_hooks` 中的每个钩子生成对应 Precondition（强制关联，防钩子丢失）

### 4.3 Phase 3: TIER_DECIDE（定档）

- **复用 V3.1** `tier_classifier.classify_tier`（纯算法，0 LLM）
- **依据**：`anchor.climax.intensity` + `chapter_position.offset_from_volume_climax` + `user_tier_hint`
- **产出**：`tier` + `max_depth` + `target_word_count` + `target_segment_count`

### 4.4 Phase 4: FORWARD_FLOW（正向流写作，核心创新 #2）

这是 ADF 的灵魂。**串行逐段写作，每段三方约束 + 运行时条件扫描。**

#### 4.4.1 段数规划

- 由 tier 决定：`target_segment_count = max(3, min(8, word_count // 600))`
- climax 档倾向多段（情绪累积需要节拍），transition 档倾向少段

#### 4.4.2 每段写作流程

```
对每段 i（0 到 N-1）：
  1. 计算 progress = (i + 1) / N
  2. 查情绪曲线：得到当前 register + energy
  3. 取 rolling_prefix = 前段末尾 500 字（首段用 entry_state.last_scene_image）
  4. 扫描未落地 Precondition：找出"建议在本段埋设"的条件
     - 优先级：min_landing_offset 即将违反的 > 尚未落地的
     - 软提示（非强制）："下段建议自然融入 PC_REAL_POWER 的埋设"
  5. 构造 prompt，包含：
     - 系统层：文风契约 + 作者样本 + 写作原则
     - 用户层：章节主旨 + 角色 + rolling_prefix + 情绪曲线位置 + 远端锚描述（牵引） + 软提示
  6. 调用 1 次 creative LLM（model_type="creative"）
  7. 解析返回，更新 Precondition.landed 状态（关键词检测）
  8. 推送 ZONE_PROGRESS SSE 事件
```

#### 4.4.3 关键设计

- **rolling_prefix 保证呼吸连续**：继承双轨优点
- **情绪曲线进度条代替整数距离**：每段知道自己在情绪弧中的精确位置
- **远端锚作为牵引而非强制路径**：高潮描述每段都注入，但不强制"现在必须写什么"
- **软提示而非硬指令**：告诉 LLM "建议下段埋 X"，但场景选择由前文涌现
- **关键词检测验证 Precondition 落地**：`must_use_terms` 出现即标记 landed

#### 4.4.4 max_tokens

- 单段 max_tokens：`max(2048, min(8192, target_words_per_segment * 4))`

### 4.5 Phase 5: ANCHOR_AUDIT（锚点审计）

- **目的**：合并校验所有维度（1 次 reasoning，复用 V3.1 合并审计思想）
- **校验内容**：
  1. Precondition 落地验证（代码先扫 must_use_terms，未落地的交给 LLM 判断是否语义落地）
  2. 情绪曲线符合度（开头/中段/高潮 的情绪是否对齐曲线）
  3. 脉络符合度（角色弧推进了吗？钩子埋了吗？前章衔接自然吗？）
  4. 高潮验收（高潮段是否真的达到 climax.emotional_target）
- **输出 JSON**：
  ```json
  {
    "verdict": "pass" | "needs_refinement" | "fail",
    "missing_preconditions": ["PC_REAL_POWER"],
    "emotion_mismatch": [...],
    "spine_violations": [...],
    "climax_score": 7,
    "refinement_targets": ["PC_REAL_POWER"]
  }
  ```
- **max_tokens**：6144

### 4.6 Phase 6: REFINE（条件补埋）

- **触发**：`verdict == "needs_refinement"` 且有 `refinement_targets`
- **方法**：对每个未落地的 Precondition，**定位最自然的段落**重写插入
- **策略**：
  - 优先在已有段落中"内嵌式补写"（避免新开段落破坏流畅性）
  - 选择 emotion_curve 上最接近"日常"的段落（develop 区），插入最不打断流畅
- **单条件 1 次** creative LLM（max_tokens=3072）

---

## 5. LLM 调用次数对比

| 场景 | V3.1 引爆链 | **V3.2 ADF** |
|---|---|---|
| Phase 1 脉络轨 | 0 | 0-1 |
| Phase 2 锚点设计 | (V3.1 候选) 1 | 1 |
| Phase 3 定档 | 0 | 0 |
| Phase 4 写作主体 | 2(双候选高潮)+N(fuse)+2(速写对照)+1(接缝)=N+5 | **N（纯正向逐段）** |
| Phase 5 审计 | 1(图校验)+1(锚定审计)=1 | 1 |
| Phase 6 精修 | 0-2 | 0-K（K=未落地条件数，通常 0-2） |
| **典型合计** | N+8 ~ N+11 | **N+3 ~ N+6** |

> **V3.2 比 V3.1 调用次数少 30-50%**（因为抛弃了双候选高潮、速写对照、接缝打磨这些"工艺优化"调用，改为纯正向往前写）。

---

## 6. 代码组织

### 6.1 后端

```
backend/
├── schemas/adf.py                      新建：ADF 数据结构 Pydantic 模型
├── services/
│   ├── prompts/adf_prompts.py          新建：anchor_design / forward_flow / audit prompts
│   └── workflows/adf/                  新建包
│       ├── __init__.py
│       ├── types.py                    dataclass 定义
│       ├── spine_track_builder.py      Phase 1
│       ├── anchor_designer.py          Phase 2
│       ├── tier_decider.py             Phase 3（薄包装，调 V3.1 tier_classifier）
│       ├── forward_flow_writer.py      Phase 4 ★ 核心
│       ├── condition_scanner.py        Phase 4 的辅助：条件扫描
│       ├── emotion_curve.py            情绪曲线工具
│       ├── anchor_auditor.py           Phase 5
│       ├── refiner.py                  Phase 6
│       └── adf_workflow.py             主类 ADFWorkflow.execute()
├── routes/chapter_generation/adf.py    新建：POST /generate-adf
├── routes/chapter_generation/__init__.py 注册 adf_router
└── main.py                             无需改（路由已通过 chapter_generation 挂载）
```

### 6.2 前端

```
frontend/src/
├── services/api/domain/index.ts        新增 adfApi（绑定 /generate-adf）
├── features/generation/composables/
│   └── useGenerationSession.ts         支持 engine 参数：'v3.1' | 'v3.2'
├── components/TierSelector.vue         新增引擎选择 UI
└── features/generation/presentation/
    └── GenerationStepper.vue           支持 ADF 阶段标签
```

---

## 7. SSE 事件序列（V3.2）

```
ADF_STAGE              阶段切换（SPINE_BUILDING/ANCHOR_DESIGN/TIER_DECIDE/
                                FORWARD_FLOW/ANCHOR_AUDIT/REFINE）
ADF_SPINE_BUILT        脉络轨构建完成（含 entry/exit/position）
ADF_ANCHOR_DESIGNED    远端锚设计完成（含 climax/preconditions/emotion_curve）
TIER_DECIDED           定档通知（复用 V3.1 事件名）
ADF_PROGRESS           正向流写作进度（含 segment_index/total/register/energy）
ADF_PRECONDITION_LANDED 条件落地事件（含 precondition_id/segment/evidence）
ADF_AUDIT              锚点审计结论
TEXT_CHUNK             文本块（流式正文，复用）
COMPLETE / ERROR       完成/错误（复用）
```

---

## 8. 引擎剥离后的现状（2026-07-24 更新）

本文档原设想的"与 V3.1 并存"方案未长期保留。经引擎剥离后：

- **旧端点已移除**：`/generate`（V3.1）、`/generate-chapter`（V4.0 双轨）、`/generate-v3`（V3.0）已随对应引擎一并归档至 `backend/_deprecated/`
- **V3.2 成为唯一生成端点**：`POST /api/chapters/{id}/generate-adf`
- **数据库**：`DetonationChain` ORM 已删除（表保留存量数据）；V3.2 结果写入 `Chapter.draft_text` + `GenerationRun` 计量表
- **前端**：`useGenerationSession.start()` 的 `engine` 默认 `'v3.2'` → `adfApi.streamGenerate`

---

## 9. 成功标准

1. **流畅性**：场景切换比 V3.1 显著改善（目标：达到双轨水平）
2. **高潮强度**：保留 V3.1 水平（不退化）
3. **脉络符合度**：大纲所有点必须落地（解决"协会高层钩子丢失"类问题）
4. **成本**：单章 LLM 调用次数比 V3.1 减少 30%+
5. **可解释性**：每个段落的情绪位置、埋设的条件、审计结论全部可观测

---

## 10. 实施顺序（本会话执行）

1. ✅ 设计文档（本文）
2. 后端 schemas（`backend/schemas/adf.py`）
3. 后端 prompts（`backend/services/prompts/adf_prompts.py`）
4. 后端 workflows/adf/（types + 8 个模块 + 主类）
5. 后端 routes（`backend/routes/chapter_generation/adf.py` + 注册）
6. 前端 API 绑定（`services/api/domain/index.ts`）
7. 前端 session 支持（`useGenerationSession.ts`）
8. 前端引擎选择 UI（`TierSelector.vue`）
9. 自验证（Python import 冒烟 + TS 类型检查）
