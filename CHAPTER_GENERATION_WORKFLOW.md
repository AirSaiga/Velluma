# Velluma 章节生成工作流 - 完整逻辑链文档

## 概述

Velluma 的章节生成采用 **Agentic Workflow（智能体工作流）** 架构，通过多轮迭代和多个专业化 Agent 的协作，生成高质量的小说章节内容。

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        章节生成完整流程图                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐       │
│  │  ASSEMBLING_    │────▶│    PLANNING     │────▶│  POV_ASSIGNMENT │       │
│  │    CONTEXT      │     │  (Planner Agent)│     │  (Anchor POV)   │       │
│  └─────────────────┘     └─────────────────┘     └─────────────────┘       │
│         │                      │                      │                     │
│         ▼                      ▼                      ▼                     │
│    加载角色卡               拆分 Story Beats        确定核心主角              │
│    检索记忆                 计算字数分配            统一 POV                  │
│    提取伏笔                 分配场景地点                                  │
│                                                                             │
│                              ┌─────────────────┐                            │
│                              │    DRAFTING     │                            │
│                              │  (Draft Agent)  │                            │
│                              └─────────────────┘                            │
│                                     │                                       │
│                    ┌────────────────┼────────────────┐                      │
│                    ▼                ▼                ▼                      │
│              ┌──────────┐    ┌──────────┐    ┌──────────┐                   │
│              │ Beat 1   │    │ Beat 2   │    │ Beat N   │  (并行生成)        │
│              │ Scene    │    │ Scene    │    │ Scene    │                   │
│              │ Intent   │    │ Intent   │    │ Intent   │                   │
│              │ Chunk QC │    │ Chunk QC │    │ Chunk QC │                   │
│              └──────────┘    └──────────┘    └──────────┘                   │
│                    │                │                │                      │
│                    └────────────────┼────────────────┘                      │
│                                     ▼                                       │
│                              ┌─────────────────┐                            │
│                              │    STITCHING    │                            │
│                              │ (Stitch Agent)  │                            │
│                              └─────────────────┘                            │
│                                     │                                       │
│                                     ▼                                       │
│                              ┌─────────────────┐                            │
│                              │   REVIEWING     │◀────────────────┐         │
│                              │ (Review Agent)  │                 │         │
│                              └─────────────────┘                 │         │
│                                     │                            │         │
│                         ┌───────────┴───────────┐                │         │
│                         ▼                       ▼                │         │
│                   ┌──────────┐           ┌──────────┐            │         │
│                   │  通过    │           │  未通过  │────────────┘         │
│                   │ pass=true│           │ pass=false                        │
│                   └──────────┘           └──────────┘                       │
│                         │                       │                           │
│                         ▼                       ▼                           │
│                   ┌──────────┐           ┌──────────┐                       │
│                   │FORMATTING│           │ REFINING │                       │
│                   │ 排版优化  │           │ 局部精修  │                       │
│                   └──────────┘           └──────────┘                       │
│                         │                       │                           │
│                         └───────────┬───────────┘                           │
│                                     ▼                                       │
│                              ┌─────────────────┐                            │
│                              │  FINAL OUTPUT   │                            │
│                              │   最终输出      │                            │
│                              └─────────────────┘                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 一、上下文组装阶段 (ASSEMBLING_CONTEXT)

### 1.1 功能说明
该阶段负责从数据库加载章节生成所需的全部上下文信息，为后续 Agent 提供完整的工作材料。

### 1.2 数据来源

| 数据类型 | 来源表 | 用途 |
|---------|--------|------|
| 章节信息 | `Chapter` | 章节大纲、张力等级、节奏偏好 |
| 书籍设定 | `Book` | 世界观设定、全局系统提示词 |
| 角色卡 | `Character` + `ChapterEntity` | 静态设定、动态状态 |
| 角色关系 | `CharacterRelationship` | 互动约束 |
| 开放伏笔 | `PlotLedger` | 待回收的剧情线索 |
| 前文摘要 | `Chapter.summary` (上一章) | 上下文连贯性 |
| 相关记忆 | `MemoryChunk` (RAG检索) | 跨章节记忆回溯 |
| 地图地点 | `MapLocation` + `ChapterMapLocation` | 场景地点信息 |

### 1.3 RAG 记忆检索
使用 DashScope Embedding API 生成向量，基于以下权重公式检索：

```
score = alpha * 语义相似度 + beta * 时间衰减 + gamma * 位置接近度
```

- **alpha** (默认 0.6): 向量相似度权重
- **beta** (默认 0.2): 时间衰减权重
- **gamma** (默认 0.2): 剧情伏笔权重

**约束条件**：只检索当前章节之前的内容，避免未来信息泄露。

---

## 二、规划阶段 (PLANNING)

### 2.1 Planner Agent
将章节大纲拆分为可执行的 **Story Beats（剧情节拍）**。

### 2.2 Beat 结构
每个 Beat 包含以下字段：

```json
{
  "position": 1,                    // 节拍位置序号
  "beat_id": "beat-1",              // 唯一标识
  "summary": "剧情概述",             // 本段核心内容
  "location": "场景地点",            // 发生地点
  "pov_character": "视角角色",       // POV角色
  "action_summary": "动作化摘要",    // 可执行的剧情指令
  "worldbuilding_instruction": "世界构建约束",
  "entry_state": "进入状态",         // 切入时的角色状态
  "exit_state": "退出状态",          // 必须停住的收束状态
  "red_lines": ["红线约束1", "红线约束2"],
  "word_count_target": 600,         // 目标字数
  "hook_ids": ["伏笔ID"],           // 关联的伏笔
  "pacing_type": "Medium",          // 节奏类型：Fast/Medium/Slow
  "weight": 3                       // 重要性权重 (1-5)
}
```

### 2.3 字数分配算法
基于 pacing_type 和 weight 计算每个 Beat 的目标字数：

```python
multipliers = {
    "Fast": 0.8,      # 快节奏段落字数减少
    "Medium": 1.0,    # 正常节奏
    "Slow": 1.2       # 慢节奏段落字数增加
}

score = weight * multiplier
word_count = (score / total_score) * total_chapter_words
```

### 2.4 低张力模式
当 `tension_level <= 3` 时，自动注入红线约束：
- "避免正面冲突"
- "避免战斗升级"

---

## 三、POV 分配阶段 (POV_ASSIGNMENT)

### 3.1 Anchor POV 机制
采用**单一核心主角视角**策略（而非每 Beat 切换 POV）：

1. 通过 LLM 分析章节大纲和角色列表
2. 确定本章的 **Anchor POV（核心视角角色）**
3. 将所有 Beat 的 `pov_character` 统一设置为 Anchor POV
4. 保留 `original_actor` 字段记录原始动作执行者

### 3.2 Anchor POV 选择标准
- 与章节核心冲突的相关性
- 角色在剧情中的重要性
- 上一章的 POV 延续性

---

## 四、起草阶段 (DRAFTING)

### 4.1 并行生成架构
每个 Beat 独立生成，通过 `asyncio.Semaphore` 控制并发数（默认 6，可通过 `AGENTIC_BEAT_CONCURRENCY` 环境变量调整）。

### 4.2 单 Beat 生成流程

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Scene Intent │────▶│ Chunk Draft  │────▶│  Chunk QC    │
│   构建       │     │   生成正文    │     │  质量检查    │
└──────────────┘     └──────────────┘     └──────────────┘
      │                     │                     │
      ▼                     ▼                     ▼
  生成场景意图           根据意图扩写         异常检测与修复
  (目标/风险/约束)       节奏控制            (可选，最多1轮)
```

### 4.3 Scene Intent 结构
```json
{
  "intent_label": "意图标签",
  "goal": "场景目标",
  "stakes": "风险/代价",
  "constraints": ["约束条件1", "约束条件2"]
}
```

### 4.4 节奏控制 (Pacing Control)
根据 Beat 的 `pacing_type` 应用不同的句式风格：

| 类型 | 句式特点 | 适用场景 |
|-----|---------|---------|
| **Fast** | 短句、动词、减少修饰 | 动作戏、追逐、紧张 |
| **Medium** | 长短句平衡 | 一般叙事 |
| **Slow** | 长句、感官细节、氛围渲染 | 情感戏、环境描写 |

### 4.5 自动质检 (Chunk QC)
触发条件：
- 字数异常：生成内容 < 目标字数的 50%
- 结构异常：长文本但无段落分隔

质检流程：
1. `build_chunk_review_prompt` → LLM 检查
2. 如发现问题 → `build_chunk_refine_prompt` → 重写
3. 最多重试 1 次

---

## 五、统稿阶段 (STITCHING)

### 5.1 功能说明
将多个 Beat 生成的 chunks 合并成连贯的章节正文。

### 5.2 统稿策略
使用 Stitch Agent 执行以下任务：
- 平滑段落间的过渡
- 消除重复和矛盾
- 统一语气和节奏
- 确保整体连贯性

### 5.3 容错机制
如果统稿结果为空，自动降级为简单拼接：
```python
stitched_text = "\n\n".join(chunks).strip()
```

---

## 六、审阅阶段 (REVIEWING)

### 6.1 Review Agent 职责
对统稿后的完整章节进行质量检查：

| 检查项 | 说明 |
|-------|------|
| **OOC 检测** | 角色行为是否符合性格设定 |
| **剧情合规性** | 是否遵循章节大纲 |
| **逻辑完整性** | 是否有情节漏洞 |
| **PACING_OVERFLOW** | 是否越过 exit_state 或触发 red_lines |
| **完整性缺失** | 是否大幅删段导致信息丢失 |

### 6.2 审阅结果结构
```json
{
  "pass": false,
  "issues": [
    {
      "type": "OOC/剧情遗漏/逻辑硬伤/PACING_OVERFLOW/完整性缺失",
      "severity": "high/medium/low",
      "description": "问题描述",
      "target_beat_ids": ["beat_01", "beat_02"]  // 问题定位
    }
  ],
  "revision_plan": "具体的重写建议"
}
```

### 6.3 问题定位机制
通过 Reference Beats 地图，让 LLM 推理出问题所属的 Beat ID，用于后续局部精修。

---

## 七、精修阶段 (REFINING)

### 7.1 触发条件
- Review Agent 判定 `pass = false`
- 用户未启用 `skip_minor_refine` 或问题非轻微

### 7.2 局部精修策略
如果 Review 返回了 `target_beat_ids`：
1. 仅对指定的 Beat chunks 进行重写
2. 保留其他 Beat 内容不变
3. 重新统稿

### 7.3 完整重写策略
如果未指定 Beat IDs 或局部精修后仍不通过：
1. 基于 `revision_plan` 重写完整章节
2. 执行 "回退-降速-悬停" 策略处理 PACING_OVERFLOW

### 7.4 完整性保护
精修时必须遵守：
- 不得大幅删除段落
- 必须保留关键情节节点
- 如需删除，必须以等价内容补回

---

## 八、迭代循环

### 8.1 循环控制
```
max_iterations = request.max_iterations (默认 5)
fast_mode 时: max_iterations = 1 (跳过审阅)
```

### 8.2 循环终止条件
1. Review Agent 判定 `pass = true`
2. 问题仅轻微且 `skip_minor_refine = true`
3. 达到最大迭代次数

---

## 九、排版阶段 (FORMATTING)

### 9.1 触发条件
如果最终文本满足以下条件：
- 长度 >= 800 字符
- 无段落分隔（`\n\n` 不存在）
- 存在长行（>= 180 字符的行数 >= 2）

### 9.2 排版优化
使用 Format Agent 进行：
- 合理的段落分隔
- 对话格式优化
- 章节结构整理

---

## 十、输出阶段 (FINAL_TEXT_STREAM)

### 10.1 输出事件流
```
event: FINAL_TEXT_STREAM  // 开始输出最终文本
event: TEXT_CHUNK         // 逐字符输出（模拟打字机效果）
event: DONE               // 完成信号 + 完整统计信息
```

### 10.2 统计信息
包含以下指标：
- 总耗时
- 各阶段耗时排行
- LLM 调用次数和失败次数
- 迭代次数
- Fast Mode 状态

---

## 十一、数据持久化

### 11.1 数据库存储
| 数据 | 存储位置 |
|-----|---------|
| 章节草稿 | `Chapter.draft_text` |
| 修订次数 | `Chapter.revision_count` |
| 审阅反馈 | `Chapter.review_feedback` |
| 最终内容 | `Chapter.content_text` |
| Story Beats | `StoryBeat` 表 |
| Scene Intents | `SceneIntent` 表 |

### 11.2 保存时机
- 每轮迭代统稿后：保存 `draft_text` 和 `revision_count`
- Review 完成后：保存 `review_feedback`
- 最终排版后：保存 `content_text`

---

## 十二、Prompt 调试

### 12.1 Debug 历史记录
所有发送给 LLM 的 Prompt 都会被记录到 `debug_history`，包含：
- stage: 阶段名称
- iteration: 迭代轮次
- system_prompt / user_prompt: 完整提示词

### 12.2 实时输出
通过 SSE 流实时发送 Prompt 到前端 Debug 窗口：
```
event: { "prompt": { "system_prompt": "...", "user_prompt": "..." } }
```

---

## 十三、环境变量配置

| 变量 | 说明 | 默认值 |
|-----|------|-------|
| `AGENTIC_BEAT_CONCURRENCY` | Beat 并行生成数 | 6 |
| `AGENTIC_FORCE_FAST_MODE` | 强制快速模式 | False |

### 13.1 Fast Mode
启用后：
- 仅执行 1 轮迭代
- 跳过审阅阶段
- 适合快速预览或测试

---

## 十四、核心设计原则

### 14.1 边界约束优先
每个 Beat 的 `entry_state`、`exit_state`、`red_lines` 具有最高优先级，确保：
- 剧情不会越界推进
- 各 Beat 之间的连贯性
- 悬念的合理设置

### 14.2 完整性优先于字数
当字数目标与剧情完整性冲突时，优先保证完整性，允许适度超出字数。

### 14.3 渐进式危机升级
禁止从 0 直接跳到 100 的转场，必须通过：
1. 微弱的异常（Anomaly）
2. 角色的错愕（Disconnect）
3. 彻底的爆发（Impact）

### 14.4 反 AI 味协议
- 禁止设定倾倒（Info-dumping）
- 禁止预告片式说教旁白
- 禁止形容词堆砌
- 强制使用短句制造紧张感

---

## 十五、代码文件对应关系

| 功能模块 | 代码文件 |
|---------|---------|
| 主工作流编排 | `backend/services/agentic_workflow.py` |
| 上下文加载 | `backend/services/workflows/context.py` |
| 规划阶段 | `backend/services/workflows/planning.py` |
| 起草阶段 | `backend/services/workflows/drafting.py` |
| 统稿阶段 | `backend/services/workflows/stitching.py` |
| 审阅阶段 | `backend/services/workflows/reviewing.py` |
| 精修阶段 | `backend/services/workflows/refining.py` |
| Planner Prompt | `backend/services/prompts/planner_prompts.py` |
| Draft Prompt | `backend/services/prompts/draft_prompts.py` |
| Review Prompt | `backend/services/prompts/review_prompts.py` |
| API 路由 | `backend/routes/chapter_generation.py` |

---

*文档生成时间: 2026-03-19*
