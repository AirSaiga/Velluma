# Velluma V4.1 — 精修流水线 + 对话式协同（Refinery + Conversational Co-Creation）

> ⚠️ **【已整体拔除 2026-09-12】**Refinery 引擎随写后检查收敛批退役（docs/reports/post-writing-checks-audit.md）：
> 手术原语（planner/surgeon）迁 `backend/services/text_surgery/`（ADF 一致性守卫消费）；
> 读者反馈收编 `POST /adaptive/reader-feedback`；前端问题清单/进度/手术历史 UI 删除。
> 本文档转为历史设计档案，运行事实以 AGENTS.md 为准。文中「事后可回滚」承诺从未实现（拔除原因之一）。

> **版本**：V4.1（Refinery，精修厂）
> **状态**：设计完成，进入实施
> **日期**：2026-07-21
> **前置**：V4.0 Canon（作者脑中世界图谱）
> **核心**：多工序精修（读-诊断-局部手术-回读-抛光）+ 对话式介入点 2（诊断后确认问题清单）

---

## 0. 设计动机

### V4.0 解决了什么

V4.0 Canon 解决了**正确性**问题（Q1 钩子丢失 / Q2 设定词缺失 / Q5 信息泄露）——通过把作者脑中世界作为强约束注入生成 prompt。

### V4.0 没解决什么

V4.0 单工序生成（V3.2 ADF）仍有**流畅性**问题：
- Q3 场景切换突兀
- Q4 段间拼接错位（第 301-303 行断裂）
- Q6 节奏拖沓（某段占比过重）
- Q7 直陈句太多（"她控制得很好"）

这些问题是**单工序生成的根本病灶**——LLM 一次成稿的质量上限。解法是多工序流水线：把人类作家的改稿流程（读→找问题→手术→回读→抛光）外化为独立的 LLM 工序。

### 为什么需要对话式

多工序流水线本身有 bug：**LLM 自己诊断自己生成的内容，会陷入"自我合理化"**——它倾向于认为自己的输出没问题。解法是让作者介入诊断环节，把人类的判断力注入精修流程。

这就是**对话式介入点 2（诊断后确认）**的价值：系统诊断出问题清单后，**不直接手术**，而是先让作者确认哪些是真问题、哪些是有意为之。这避免了：
- 系统把"有意为之的留白"当成"漏洞"去修补
- 系统把"刻板的网文套路"当成"正常"放过

---

## 1. 范式：读-诊断-局部手术-回读-抛光（DORS-P）

```
Phase 4.5: 精修流水线（Refinery）

4.5.1 诊断（Diagnostic）
       LLM 读全文 → 输出结构化问题清单
       ↓
4.5.2 对话式介入点 2（★ 质量分水岭）
       系统呈现问题清单 → 作者逐条确认
       - 确认 → 加入手术队列
       - 否决（"有意的"）→ 标记 ignored，不影响
       - 补充 → 作者加新问题（"我读着觉得 X 不顺"）
       - Canon 更新 → 作者现场改 Canon（加 private 设定等）
       ↓
4.5.3 手术规划（Operation Planning，纯算法）
       按确认的问题排序 + 冲突检测 + 影响半径合并
       ↓
4.5.4 局部手术（Targeted Surgery）
       每个问题 1 次 LLM 调用，最小侵入式修改
       ★ 关键：prompt 注入"全文上下文摘要"（让 LLM 改局部时有整体感）
       ↓
4.5.5 整体回读（Holistic Re-read）
       1 次 LLM 调用，检查手术之间是否冲突
       ↓
4.5.6 抛光（Polish）
       1 次 LLM 调用，文风统一 + 句式去重 + 章末钩子强化
```

### 为什么这个范式能解决问题

| 问题 | 解法 | 工序 |
|---|---|---|
| Q3 场景切换突兀 | 诊断（scene_jump）+ 手术（重写过渡） | 4.5.1 + 4.5.4 |
| Q4 段间拼接错位 | 诊断（pacing_break）+ 手术（修复接缝） | 4.5.1 + 4.5.4 |
| Q6 节奏拖沓 | 诊断（pacing_drag）+ 手术（合并删减） | 4.5.1 + 4.5.4 |
| Q7 直陈句 | 诊断（tell_not_show）+ 手术（改动作暗示） | 4.5.1 + 4.5.4 |
| 自我合理化 | 对话式介入点 2（作者确认） | 4.5.2 |

---

## 2. 数据结构

### 2.1 Issue（诊断产出的问题）

```python
class Issue:
    id: str                          # "I001"
    location: IssueLocation          # 位置
    type: IssueType                  # 问题类型
    severity: str                    # high | medium | low
    diagnosis: str                   # 诊断说明
    suggestion: str                  # 建议处理方式
    impact_radius: str               # local | multi_paragraph | global
    # 运行时状态（由对话式介入点更新）
    status: str                      # pending | confirmed | ignored | custom
```

```python
class IssueLocation:
    paragraph: Optional[int]         # 单段
    paragraph_range: Optional[Tuple[int, int]]  # 多段
    quote: str                       # 引文（精确锚定）
    char_offset: Optional[Tuple[int, int]]      # 字符偏移（精确定位）
```

```python
class IssueType(str, Enum):
    TELL_NOT_SHOW = "tell_not_show"          # 直陈该用动作
    PACING_DRAG = "pacing_drag"              # 节奏拖沓
    PACING_BREAK = "pacing_break"            # 节奏断裂（拼接错位）
    SCENE_JUMP = "scene_jump"                # 场景切换突兀
    INFO_LEAK = "info_leak"                  # 信息泄露（Canon 补充）
    CHARACTER_OFF = "character_off"          # 角色行为不符
    REDUNDANCY = "redundancy"                # 冗余重复
    WEAK_HOOK = "weak_hook"                  # 章末钩子弱
    EMOTION_MISMATCH = "emotion_mismatch"    # 情绪与曲线不符
    CUSTOM = "custom"                        # 作者补充的问题
```

### 2.2 Operation（手术计划）

```python
class Operation:
    id: str                          # "OP001"
    issue_ids: List[str]             # 处理哪些问题（多个可合并）
    operation_type: str              # rewrite | merge | delete | insert
    target_paragraphs: List[int]     # 操作目标段
    context_summary: str             # 全文上下文摘要（注入手术 prompt）
    canon_constraints: str           # Canon 约束（private 不许泄露等）
```

### 2.3 SurgeryResult（手术结果）

```python
class SurgeryResult:
    operation_id: str
    original_text: str               # 原文
    revised_text: str                # 修改后
    diff_summary: str                # 改了什么
    applied: bool                    # 是否应用
```

### 2.4 RefineryResult（总结果）

```python
class RefineryResult:
    raw_text: str                    # 原始粗坯
    issues: List[Issue]              # 诊断出的问题
    confirmed_issues: List[Issue]    # 作者确认的问题
    operations: List[Operation]      # 手术计划
    surgeries: List[SurgeryResult]   # 手术结果
    holistic_verdict: str            # pass | needs_final_touch
    polished_text: str               # 最终抛光后正文
    stats: Dict[str, Any]
```

---

## 3. 工序详细设计

### 3.1 工序 4.5.1：诊断（Diagnostic）

**1 次 reasoning LLM 调用**，读全文，输出 JSON 问题清单。

prompt 关键设计：
- system：你是资深小说编辑
- user：章节主旨 + 情绪曲线 + Canon 摘要 + 完整正文
- 输出严格 JSON（issues 数组）

诊断的问题类型（10 种，见 IssueType）覆盖了今晚讨论的所有生成质量问题。

max_tokens=6144，温度=0.2（找问题要冷静）。

**输出后立刻做一次"作者补充"**：
- 系统问作者："诊断发现 N 个问题。你读粗坯时有没有别的觉得不对的地方？"
- 作者可补充 CUSTOM 类型 issue

### 3.2 工序 4.5.2：对话式介入点 2（核心创新）

**这是 V4.1 的灵魂。**

系统呈现问题清单，作者逐条决策：

```
┌─────────────────────────────────────────┐
│ 精修诊断（共 7 个问题）                   │
│                                          │
│ 🔴 I001 [high] tell_not_show             │
│   "她控制得很好"                          │
│   → 建议改为动作暗示                      │
│   [确认手术] [否决（有意为之）] [编辑]    │
│                                          │
│ 🟡 I002 [medium] pacing_drag             │
│   第 12-18 段                            │
│   → 建议合并为 3 段                       │
│   [确认手术] [否决] [编辑]                │
│                                          │
│ ...                                      │
│                                          │
│ + 添加你发现的问题                        │
│ + 现场编辑 Canon                          │
│                                          │
│ [全部确认] [全部否决] [开始手术]          │
└─────────────────────────────────────────┘
```

**作者的三种操作**：
1. **确认**：加入手术队列
2. **否决**：标记 ignored（系统学习：这类"问题"以后不报）
3. **编辑**：作者改 issue 描述或建议

**关键设计：现场编辑 Canon**
- 作者看到诊断时可能意识到"啊这个设定我忘了在 Canon 标"
- 可以现场跳到 Canon 加一个 private 节点
- 加完后系统重新诊断（新 Canon 可能改变某些 issue 的判断）

### 3.3 工序 4.5.3：手术规划（纯算法）

```
1. 过滤：只保留 status=confirmed 的 issue
2. 排序：severity 高的优先；同 severity 看 impact_radius
3. 冲突检测：两个 issue 的目标段重叠 → 合并为一个 Operation
4. 上下文摘要生成：为每个 Operation 构建全文摘要（章节主旨+情绪曲线+Canon+角色状态）
```

### 3.4 工序 4.5.4：局部手术（核心）

**对每个 Operation，1 次 creative LLM 调用，最小侵入式修改。**

prompt 的精髓——**全文上下文摘要**：

```
# 全文上下文摘要（让你有整体感）

本章主旨：兰星隐藏实力通过测试，老人察觉
情绪曲线：压抑 → 临界 → 爆发（当前在临界区）
角色状态：兰星（隐藏弦月巅峰，紧张）；老人（已察觉）
Canon 约束：
- [private] 兰星真实身份：暗月转世（绝不许出现"暗月"）
- [public] 老人已在第 1 章察觉波纹
活跃伏笔：针脚伏笔（strength=7，已埋）

# 当前要修改的段落

[原段落 12-18]

# 诊断与建议

问题 I002：节奏拖沓
建议：合并为 3 段，加情绪转折

# 要求

只修改上述段落。输出修改后的完整段落。
- 不动其他段落
- 保持情绪连贯
- 不许出现 private 字段
- 字数可比原文少（允许删减）
```

**为什么这样设计 prompt**：
- LLM 看到"全文摘要 + 局部段落"，既有整体感又不会重写全文
- Canon 约束确保手术不破坏正确性
- "字数可比原文少"允许手术做删减（不只是替换）

max_tokens=4096，温度=0.6（修改要稳，但不能太死板）。

### 3.5 工序 4.5.5：整体回读

**1 次 reasoning LLM 调用**，读手术后的全文。

```
你刚才对一章小说做了几处局部修改。请再读一遍，检查：

1. 修改处与前后文是否衔接自然？
2. 修改是否破坏了原有的伏笔/情绪积累？
3. 是否引入了新的矛盾？
4. 整体节奏是否改善？

输出 JSON：{ verdict, remaining_issues, final_touch_suggestion }
```

如果 `verdict=needs_final_touch`，再做一次最小修改（最多 1 次）。

### 3.6 工序 4.5.6：抛光

**1 次 creative LLM 调用**，做最后的文风统一。

```
请对以下章节做最后的抛光：

1. 文风统一（对照作者样本，统一语感）
2. 句式去重（检测重复的句式模式，替换变体）
3. 章末钩子强化（如果末段没有强悬念，加一个）
4. 保持所有情节、伏笔、角色行为不变

输出抛光后的完整章节。
```

max_tokens=10000（全文抛光要够），温度=0.5。

**抛光不做大改**，只做"表面功夫"。情节/伏笔/角色的修改在工序 4.5.4 已经完成。

---

## 4. 对话式分级触发

介入点 2 不能每次都全开。设计两级：

### 默认模式（轻量，日常章用）

- 工序 4.5.2 简化为：**系统自动判断，只对 high severity 问作者**
- medium / low 自动手术
- 作者只看到最终的"修改对比视图"，事后可回滚

### 深度模式（关键章节，climax/turn）

- 工序 4.5.2 完整对话：所有问题逐条确认
- 作者可在诊断环节补充 CUSTOM 问题
- 作者可现场编辑 Canon

### 模式选择

- 自动判断（基于 tier）：climax/turn = 深度，progress/transition = 轻量
- 作者手动覆盖：每章生成时可指定

---

## 5. SSE 事件序列（V4.1 新增）

```
REFINERY_STAGE         阶段切换（DIAGNOSTIC/DIALOGUE/SURGERY/REREAD/POLISH）
REFINERY_ISSUES        诊断产出的问题清单（前端渲染为可确认列表）
REFINERY_OPERATION     单个手术开始（含 operation_id + 目标段）
REFINERY_SURGERY       单个手术完成（含 diff）
REFINERY_REREAD        整体回读结论
REFINERY_POLISH        抛光完成
REFINERY_COMPLETE      精修完成（含 stats）
```

**对话式介入点 2 的实现**：
- REFINERY_ISSUES 事件后，前端展示问题清单 UI
- 作者确认后，前端 POST 一个"确认请求"到后端
- 后端收到确认后，继续工序 4.5.3-4.5.6

**前端控制流**：
```
SSE: REFINERY_ISSUES
  ↓
前端：渲染问题清单 UI（等待作者操作）
  ↓
作者：[确认/否决/补充] → POST /api/chapters/{id}/refinery/confirm
  ↓
后端：继续手术规划 → 局部手术 → 回读 → 抛光
  ↓
SSE: REFINERY_OPERATION → REFINERY_SURGERY → REFINERY_REREAD → REFINERY_POLISH → REFINERY_COMPLETE
```

**关键设计**：精修不是单次 SSE 流，而是 **"两阶段 SSE"**：
- 第一阶段：诊断（SSE 流）→ 暂停在介入点 2
- 第二阶段：手术+回读+抛光（SSE 流）→ 完成

---

## 6. 代码组织

### 后端

```
backend/
├── schemas/refinery.py                 新建：Issue/Operation/SurgeryResult/RefineryResult
├── services/
│   ├── prompts/refinery_prompts.py     新建：诊断/手术/回读/抛光 4 套 prompt
│   └── refinery/                       新建包
│       ├── __init__.py
│       ├── diagnostician.py            工序 4.5.1 诊断
│       ├── planner.py                  工序 4.5.3 手术规划（纯算法）
│       ├── surgeon.py                  工序 4.5.4 局部手术
│       ├── holistic_reader.py          工序 4.5.5 整体回读
│       ├── polisher.py                 工序 4.5.6 抛光
│       └── refinery.py                 主类 Refinery orchestration
├── routes/chapter_generation/
│   ├── refinery.py                     新建：SSE 端点 + 确认端点
│   └── __init__.py                     注册 refinery_router
```

### 前端

```
frontend/src/
├── services/api/domain/index.ts        新增 refineryApi
├── features/generation/
│   ├── composables/
│   │   └── useGenerationSession.ts     处理 REFINERY_* 事件
│   └── presentation/
│       └── RefineryIssuesPanel.vue     新建：问题清单 UI（诊断后确认）
```

### 集成

```
backend/routes/chapter_generation/adf.py
  - 现有：Phase 1-4（ADF 生成）
  - 新增：Phase 4.5 触发 Refinery（先发 REFINERY_ISSUES，等作者确认）
  - 新增：Phase 4.6 完成后续精修
```

---

## 7. LLM 调用次数

| 工序 | 调用次数 | 模型 |
|---|---|---|
| 诊断 | 1 | reasoning |
| 对话式介入点 2 | 0（人工） | - |
| 手术规划 | 0（纯算法） | - |
| 局部手术 | 3-8（按确认的 issue 数） | creative |
| 整体回读 | 1 | reasoning |
| 抛光 | 1 | creative |
| **精修合计** | **5-11** | — |

加上 V3.2 ADF 的粗坯（N+3 ≈ 8），**单章总计 13-19 次调用**。

---

## 8. 成功标准

1. **Q3-Q7 流畅性问题**：诊断能发现 + 手术能修复 70%+
2. **作者主权**：所有手术都经过作者确认（深度模式）或事后可回滚（轻量模式）
3. **修改可追溯**：每个修改都有 issue 关联 + diff 记录
4. **不破坏 Canon**：手术严格遵守 private 字段约束
5. **效率**：精修阶段总耗时 < 5 分钟（不含作者思考时间）

---

## 9. 实施顺序

1. ✅ 设计文档（本文）
2. 后端 schemas（`backend/schemas/refinery.py`）
3. 后端 prompts（`backend/services/prompts/refinery_prompts.py`）
4. 后端 refinery 工作流（6 个模块）
5. 后端 routes（`refinery.py` + 注册）
6. 后端集成到 ADF（Phase 4.5/4.6 + SSE 事件）
7. 前端 useGenerationSession 支持 REFINERY_* 事件
8. 前端问题清单 UI
9. 全量验证（冒烟 + TS）

---

## 10. 第 2/3/4 期的接口预留

第 1 期实现时，要为后续留好接口：

- **Reader Mirror（第 2 期）**：诊断 prompt 的"情绪曲线"字段会从 Reader Mirror 拉取（第 1 期先从 ADF 的 emotion_curve 取）
- **对话式介入点 1（第 2 期）**：章节规划接口已存在（ADF 的 spine_track），后续加作者确认环节
- **对话式介入点 3（第 3 期）**：抛光后的"读者反馈"是未来功能
- **文风指纹（第 4 期）**：抛光 prompt 的"作者样本"字段已预留，第 4 期填入指纹数据
