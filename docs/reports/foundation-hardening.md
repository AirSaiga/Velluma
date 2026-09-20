> **归档说明（2026-09-19）**：P5 地基加固期执行文档（2026-08-20 立项，✅ 08-21 完成于 e44dd59）；历史施工档案，B2 预览/stitch_context/私有双轨/预算器结论仍是现行红线（同步沉淀于领域档案）。

# Velluma 地基加固期（P5）设计文档

> 状态：**✅ 施工完成（2026-08-21，代码提交 e44dd59）**——批次 1-4 全部落地 + 死者提权
> 修正 + 收尾修复三项；B4 真流式按 D8 条件未启动；实测期事项待真实写作验证。
> 详见文末「施工记录」。
> 定位：在「作者录入设定 → AI 放大设定」地基不变的前提下，修系统侧的契约违约点、
> 让录入回报可见、在现有架构内提生成效果。**不做任何「补偿无设定场景」的能力。**
> 调研依据：2026-08-20 生成流与世界数据双路代码普查（本文档所有行号为普查时工作区版本，
> 实施前以代码现状复核）。

---

## 0. 设计哲学：地基契约论

「作者录入设定，AI 放大设定」是一份双边契约：

- **作者侧**：把脑子里的世界亲手录进系统（设计前提，不补偿——没想好的设定默认
  产不出好文本，这是拍板的产品立场）；
- **系统侧**：忠实、充分、不打折地使用作者录的每一份数据。

P5 的全部事项按一把尺子排序：**凡是作者录了、但生成时没被用上 / 被用错 / 被压扁 /
被静默丢弃的地方，都是系统违约，按严重程度排队修。** 体验组的定位是「让录入的回报
可见、让履约成本趋零」，效果组的定位是「在既有架构内把单次生成质量顶到上限」。

### 已排除方案（防重复踩坑）

| 方案 | 排除理由 |
|---|---|
| 叙事时间 ③ 级只统计 `chapter_ref` 非空事件 | `chapter_ref`（models.py:1370）**全库无写入点**，此方案会把所有无锚书退化到 t=0 |
| 实体字段级私有标记（如仅 background 私有） | 复杂度与收益不成比例，实体级私有够用最清晰 |
| 恢复渲染期拦截闸门（BS-ADF 式） | 违背「作者裁决即闸门 / 柔性可忽略」定案（路线图 D3 推论） |
| E4 段落级指标制导 | 路线图 §0.4 非目标，维持不做 |

---

## 1. 决策点

| # | 决策 | 状态 |
|---|------|------|
| D5 | 「私有」语义 = **AI 知晓但绝不能直接写出**（对齐 canon `[private]`），而非从上下文删除 | ✅ 拍板（2026-08-20）：删除反而违约——作者写暗示/铺垫时 AI 需知晓秘密才能协助 |
| D6 | 叙事时间默认值问题首版**零行为变化**：只做来源可见 + 录入侧警示，不改 resolve_narrative_time 语义 | ✅ 拍板（2026-08-20）：chapter_ref 方案已排除（见 §0）；行为改变留待真实使用数据 |
| D7 | 预算管理器分两期：A3a 纯重构收敛常量（零行为变化）→ A3b 动态分配（单独实测期） | ✅ 拍板（2026-08-20）：prompt 任何变化都需实测缓冲 |
| D8 | 真流式（B4）条件排期：批次 1-2 完成后实测首字延迟，快模型体感无卡则缓行 | ✅ 拍板（2026-08-20） |

---

## 2. 批次 1：契约快赢 + 观测工具（预估 2–3 天）✅ 2026-08-21 完成

> 本批全部零/近零行为变化。**B2 必须第一个做**——它是 A2/A3b/C2/C3 所有 prompt
> 侧改造的观测手段（对照路线图 §0.2「协作体验无仪表」的教训：没有预览，prompt
> 调优就是盲调）。

### 2.1 【B2】AI 所见预览（context-preview）

**问题**：作者录的数据经五级管道注入 prompt，但全程黑盒——录入的 ROI 不可见，
作者无从学习「什么值得录」；同时 A/C 组改造缺少对照工具。

**方案**：

1. **装配逻辑抽共享**：stitch-ghost 路由（adaptive.py:578-647）的上下文装配段
   （bundle → render_style_positive → retrieve_author_samples → recall_memories →
   spatial_brief）抽为 `services/context/stitch_context.py` 的
   `assemble_stitch_context(chapter, mode, fragment, rolling_prefix, after_text, db)`
   ，stitch 路由与预览端点共用同一函数——**防漂移红线：预览必须与真实注入同源**。
2. **新端点**：`GET /api/chapters/{id}/adaptive/context-preview?mode=continue`
   ——跑装配全程，**不调 LLM 文本生成**，返回：
   ```json
   {
     "mode": "continue",
     "blocks": [{"key": "style_positive|author_samples|proper_nouns|canon|echoes|spatial",
                 "title": "文风画像", "content": "…", "chars": 0, "source": "…"}],
     "total_chars": 0,
     "world_time": 0, "world_time_source": "chapter_anchor|prev_anchor|max_event|zero",
     "world_sourced": true
   }
   ```
   块序与 adaptive_prompts 四 builder 注入序一致（画像→样本→专名→canon→回响→空间）。
   空块原样返回（前端展示「未配置」提示，这是设定体检的入口流量）。
   注：`retrieve_author_samples` 向量流有一次 embedding 调用（非 LLM），可接受；
   未配置 embedding 自动走兜底流，无需特判。
3. **前端**：副驾「章节」tab 尾部加「AI 此刻所见」折叠区（位于世界模型调试区之上），
   按块展示内容 + 字数 + 来源徽标（如「世界实体 · 在场」「canon · 私有」）。

**改动清单**：`services/context/stitch_context.py`（新）、`routes/chapter_generation/adaptive.py`
（抽装配 + 加端点）、`features/workspace/` 副驾章节 tab 组件、`services/api/domain/adaptive` API 层。

**测试与验收**：
- 后端单测：固定 bundle 下预览各块 content 与 stitch 真实 system prompt 的对应段
  逐字节一致（对照 `logs/prompt_log_*.json` 抽查）；
- 无设定书：块全空、不报 500；
- GUI：副驾展开预览，与一次真实 stitch 的 prompt log 人工对拍。

**量级**：小-中。

### 2.2 【A4】叙事时间来源可见 + 录入侧警示（零行为变化）

**问题**：`resolve_narrative_time`（world_bridge.py:48-88）③ 级取
`max(event.time_start)`——作者不锚章节时，一条远期未来事件（如结局之战）把整书
推演拉到结局态，切片与生成上下文的「此刻」全错，且**完全不可见**。

**方案**（D6：不改解析语义，把隐形变可见）：

1. **来源透传**：`load_world_overlay` 已返回 `world_time_source`（world_bridge.py:278）
   ——`GET /world/scene-slice` 响应透传该字段 + source=max_event 时附事件摘要
   （repo 查 max 事件的 note/type）。
2. **切片条展示**：`WorldSceneSlice.vue` 时刻行加来源小字（「此刻 第1240日 ·
   来自事件『结局之战』」），source≠chapter_anchor 时尾部常驻「锚定本章」轻按钮
   （复用时间轴右键锚定的同一 PATCH）。
3. **录入侧警示**：`QuickCapturePanel.vue` 建事件时，若 time_start 大于当前最大章锚
   （有锚书）或大于当前 t（无锚书），表单内联一句提示：「此事件晚于当前叙事时刻，
   未锚定章节的『此刻』将被拉到第 N 日」。只提示，不拦截。

**测试与验收**：后端单测锁 scene-slice 新字段；前端 vitest（警示显隐逻辑放
`__tests__/`）；存量书切片条除新增文案外逐像素不变。

**量级**：小。

### 2.3 【A2】在场提权

**问题**：`load_world_overlay`（world_bridge.py:241-257）角色排序键只有
「t 时刻有事态 → 重要度」，截 16——长篇后期当前场景在场的次要角色被挤出上下文，
而在场信号（char_states 的 location_id + chapter.scene_location_id）装配时**已经在手**，
只是没用。

**方案**：

1. 排序键改三元：`在场（char_states[id].location_id == chapter.scene_location_id）
   → 有事态 → 重要度降序`。仅当本章有场景钉（scene_location_id）时第一键生效，
   **无钉书排序与现状逐一致（零变化契约）**。
2. 活跃关系边提权：两端任一为在场实体的边排在其余活跃边之前（仍截 8）。
3. 资产不引入在场概念（无位置状态），维持重要度排序。
4. 切片条的多数派场景地推断（scene_slice.py `_resolve_scene_location`）**不引入**
   装配侧——v1 只认显式场景钉，行为可解释。
5. **死者不进在场集**（2026-08-21 施工期修正）：death 事件不清 location_id，
   不加 alive 判定则死亡角色会原位一直占在场名额——在场集构造带 `alive` 闸。

**改动清单**：`world_bridge.py` 排序段一处 + 单测。

**测试与验收**：新单测 `services/context/test_world_bridge_presence.py`——
低重要度在场角色击败高重要度远端角色进 16 名单；无钉/无位置数据书名单与现状一致；
prompt log 抽查一次真实章节。

**量级**：小-中。**为 A3b 提供优先级信号，必须先于预算器。**

### 2.4 【A5a】候选去重升级（回流环第一刀）

**问题**：event_scout 幂等只查 pending 池同章 `(event_type, summary)`
（event_scout.py:97-102），**不查 world_events 账本**——同一事件换措辞重复提议，
作者裁决成本随书变厚线性上升，是收件箱积压的首因。

**方案**：

1. `build_event_candidates_prompt`（prompts/world_event_prompts.py）增
   `recent_events` 参数：t 时刻之前最近 15 条事件（`time_start ≤ t` 倒序），格式
   「第N日 类型：note」，注入为排除块「以下事件已入账，勿重复提取」。
   **无事件书 prompt 零变化**。
2. 落池前加一道纯算法预筛：draft.summary 与现有事件 note 的归一化子串重合
   （去空白/标点）即跳过——挡「换皮重复」的第一道闸，宁漏勿误。
3. event_scout.run 取数路径：复用其已有的 repo（event_scout.py:59-64），
   加 `repo.events` 最近事件查询一处。

**测试与验收**：单测（重复事件不再入池 / 无事件书零变化）；上线后对照
`data/collab_events.jsonl` 的 quick_note_commit 与候选采纳率观察重复率下降。

**量级**：小。

### 2.5 【B3】用量可见

**问题**：token 消耗数据已落 `generation_runs`（P0-2，run_id=`adaptive_{chapter_id}`，
stage 按组件拆账），但没有任何面向作者的视图——自管 Key 按量付费的用户对
「这次写作花了多少」完全无感。

**方案**：

1. 端点 `GET /api/chapters/{id}/adaptive/usage`：聚合本章 generation_runs——
   total_calls、prompt/completion tokens、by_stage 拆账（heartbeat 组件/stitch/
   settle/finish/fix-sentence）。
2. 端点 `GET /api/books/{id}/adaptive/usage`：按书按日聚合趋势。
3. 前端：insights「协作」面板加两卡（本章消耗、按日趋势 + 组件分布）。
   **写作台顶栏不放**（免打扰红线）。

**测试与验收**：单测聚合正确性（mock generation_runs 行）；GUI 对拍一本真实书
的消耗数与 jsonl 手感一致。

**量级**：小。纯聚合，零风险。

---

## 3. 批次 2：私有语义 + 回流闭环（预估 3–4 天）✅ 2026-08-21 完成

### 3.1 【A1】「私有」语义统一（本批核心，信任级）

**问题**：实体 `visibility=private` 只在切片条影响展示，prompt 侧不过滤；
`props` 全字段（含几乎必含剧透的 background）经 `static_prompt_from_world_entity`
（world_bridge.py:115-130）注入正文上下文。作者最在意的秘密没有防泄底通道，
而 UI 上的「私有」字样让作者误以为已受保护——**这是静默违约，信任级**。

**方案**（D5：私有 = AI 知晓但绝不能直接写出，对齐 canon `[private]` 语义）：

1. **world_bridge**：`WorldEntityAdapter` 保持现状（内部算法消费者——sediment
   冲突检测的 `ent.character.static_prompt` 鸭子链——继续吃全量）；
   `load_world_overlay` 返回新增 `secrets: List[{name, text}]`——
   `visibility == "private"` 实体的结构化拼接文本进此通道。
2. **settings_bundle**：`_characters_text` 等 prompt 文本装配处跳过 private 实体
   （判定走 `adapter.world_entity.visibility`，**过滤发生在文本装配层，不动适配器**——
   sediment 等内部逻辑零影响）；bundle 新增 `character_secrets` 字段并暴露到
   `to_prompt_context()`。
   ⚠ 实施检查单：审计 `hard_constraints()["character_statics"]` 的全部消费方，
   规则 = **进 prompt 的文本必须排除 private props，纯算法消费者保持全量**。
3. **adaptive_prompts**：四 builder 在 canon 块后增 `_secrets_block`：
   ```
   # 作者私有设定（你知晓以下秘密以协助铺垫与暗示，但绝不能直接写出）
   - 叶轻眉：目标：……；背景：……
   ```
   **零变化契约：无私有实体的书 prompt 逐字节不变**（沿用 test_style_injection.py 同型单测）。
4. **UI 消歧**：EntityDetailDrawer「读者已知/私有」切换旁加一行说明：
   「私有 = AI 知晓但不直接写出；防泄底强制力来自真相层，敏感秘密建议建真相节点」。

**改动清单**：`world_bridge.py`、`settings_bundle.py`、`adaptive_prompts.py`、
`EntityDetailDrawer.vue`、新单测 `services/context/test_private_channel.py`。

**测试与验收**：
- 单测三件套：私有实体内容只进 secrets 块 / 公开实体不变 / 无私有零变化；
- prompt log 抽查私有实体书的 stitch 调用；
- 一次真实验证：私密角色的秘密在续写中不被直接道出，但暗示类写法仍被协助。

**量级**：中。

### 3.2 【A5b/c/d】回流闭环剩余三刀（前端为主）

目标：**让「账本与正文同步」的履约成本趋零**。

- **A5b 批量裁决**：写作页收件箱 + 世界页「待确认」分区加「全部采纳」——
  弹出逐条预览（可剔除）→ 确认后批量走既有 accept 端点；toast 6 秒可撤销
  （逐条 reopen 复合撤销，复用 world.py:415-479 现有 undo 机制）。
- **A5c 积压提醒**：finish 报告附 `candidates_pending` 计数；pending >5 时
  感知带一条柔性提示（走 canon_hints 既有通道，kind=world_inbox，不弹窗不抢焦点）。
- **A5d 沉淀直达**：settle 完成 toast 带「N 条世界变化待确认」action，
  点击直达副驾「此刻」tab 收件箱（useToast action 机制 S4 已建）。

**测试与验收**：前端 vitest（批量勾选/撤销逻辑）；GUI 全流程走一遍
settle→toast→收件箱→批量采纳→撤销；埋点沿用 collab_events（quick_note_commit 旁
增 batch_accept 计数）。

**量级**：中。

---

## 4. 批次 3：上下文预算管理器（预估约 1 周，D7 分两期）✅ 机制落地 2026-08-21（A3b 调参留实测期）

### 4.1 【A3a】截断常量收敛（纯重构，零行为变化）

**方案**：新建 `services/context/budget.py` 单文件常量表，收编全部散落的截断
魔法数字，每项附注释说明取舍理由与首版出处：

| 常量 | 现值 | 现位置 |
|---|---|---|
| 角色数上限 / 每角色文本截断 | 16 / 200 字 | world_bridge.py:253 / settings_bundle `_characters_text` |
| 资产 / 地点 / 关系上限 | 8 / 12 / 8 | world_bridge.py:257,274,269 |
| canon 表/里条数与截断 | 各 10 / 150,120 字 | canon/consistency.py:200-303 |
| 读者期待条数与描述截断 | 3 / 40 字 | settings_bundle.py:182-205 |
| RAG 回响 k / 每条截断 | 3（dock 2）/ 160 字 | rag/recall.py |
| 作者样本 k / 每条截断 | 2 / 1200 字 | style/retrieval.py:46-54 |
| spatial_brief / 画像行数 | 300 字 / 14 行 | settings_bundle.py:283-293,569-603 |

**验收**：单测锁定全部装配输出逐字节不变（这是 A3b 的安全绳）。

**量级**：小。

### 4.2 【A3b】按优先级动态分配（单独实测期）

**方案**：

1. budget.py 增 `allocate(blocks: List[Block], budget: int) -> List[Block]`：
   每块候选条目携带 `(priority, text)`，priority 来源 = A2 的在场/事态/重要度
   信号 + 新近度；按模式分档总预算：
   `continue` 轻（顺句少干扰）/ `burst` 重（连写多给养料）/ `outline` 中 /
   `open` 偏世界观与摘要。
2. 各块 builder 改造为「产候选条目 + 优先级」，裁剪统一由 allocate 执行——
   散点截断全部收口。
3. B2 预览同步显示「预算占用条」（每块实际字数 / 配额），成为调参界面。

**验收**：总注入字数有界且按模式分档；拥挤场景（20+ 角色书）在场实体不再被挤出；
**作者实测 2–3 章确认生成手感无回退**（回退即回滚分档表，结构保留）。

**量级**：中-大。A 组唯一改变生成手感的事项，单独成批留实测缓冲。

---

## 5. 批次 4：生成效果调优（滚动进行，每项配实测）✅ C1/C2/C3 施工完成 2026-08-21（效果待实测；B4 按 D8 未启动）

### 5.1 【C1】轻量前置校验（上屏前快检染色）

**方案**：新模块 `services/validation/ghost_guard.py`——stitch-ghost 完整文本生成后、
GHOST_DONE 帧前跑纯算法快检：
1. 死者开口/在场：新文本实体名（含别名）命中 × world_state `alive=False`；
2. canon 泄底：`hard_constraints()["canon_private_labels"]` 正则命中；
3. 私有实体秘密外泄：A1 的 secrets 文本关键短语命中（复用同一份抽取代码）。

命中项随 GHOST_DONE 附 `warnings: [{kind, span_text, message}]`；前端幽灵草稿
对应句染波浪线，采纳 toast 附一句提醒。**红线：只提示不拦截，不阻断采纳。**

**依赖**：A1（私有标签抽取同源）。**量级**：中。

### 5.2 【C2】样本场景匹配（few-shot 提质）

**方案**：
1. 纯算法场景判定：对 rolling_prefix 尾 300 字跑 `fingerprint.py` 现成对话占比
   统计，>0.35 判 dialogue，否则 general（v1 只分两档，不做抒情/动作细分——
   等埋点证明价值再扩）；
2. `retrieve_author_samples`（retrieval.py:71-123）：向量流对 scene_type 匹配者
   加分（+0.1 量级），兜底流同 scene_type 优先；
3. **零变化契约**：无 scene_type 标注的样本库行为不变。

**验收**：单测 + B2 预览直读「换上了哪条样本」+ 作者实测对照。**量级**：小-中。

### 5.3 【C3】分模式差异化注入（克制首版）

首版只动三处，每处独立单测 + prompt log 对照 + 实测：
1. **burst**：样本 k 2→3，走向卡文本进 user prompt（现仅 beat_guidance 间接）；
   > ✅ 施工核实（2026-08-21）：走向卡文本本就在 burst user prompt（beat_guidance
   > 通道），此半条为旧调研过时结论，跳过零改动；k=3 已落地（budget 连锁三处同步）。
2. **outline**：注入 spine 全锚点行（现仅 serves_anchor 单锚，adaptive_prompts.py:326-327）；
3. **continue**：画像块压至关键行（句长节奏 + 对话目标两行），防束缚顺句手感。

**量级**：每档小，滚动做，严禁打包一次全上。

### 5.4 【B4】真流式（D8 条件排期）

**排期条件**：批次 1–2 完成后实测 stitch 首字延迟；作者所用模型够快、体感无卡
则缓行（伪流对快模型无害）。

**方案要点**（若启动）：`generate_stream_response`（llm/client.py:154）现成；
stitch-ghost 改边生成边推 GHOST_CHUNK；outline 双层闸改流内字数监测——
超 ×1.6 中止流 + 带压缩反馈重试（前端处理「写到一半清空重来」展现）；
×1.5 句界截断在末帧前应用。**风险**：SSE 契约变化（useGhostDraft 消费方），
需 GUI 全量回归一遍幽灵生命周期。

---

## 6. 中期立项（本期不实施，登记备查）

| 项 | 内容 | 前置 |
|---|---|---|
| C4 world_bridge 换源 | 下游 `_characters_text` 等文本模板直读世界原生字段（不限 200 字、importance 1-10 原生语义），适配器退回未迁移书兜底 | A3b 之后（先有预算器才知道额度往哪花） |
| SQLite 向量补强 | sqlite-vec 或本地 embedding，把 RAG V 层带回默认路径 | 中期再议；A+B 层对非字面指代的召回短板随书变厚而放大 |

---

## 7. 依赖与排期总表

```
批次1（2-3天）: B2 → A4 → A2 → A5a → B3     全部零/近零行为变化
批次2（3-4天）: A1（→ C1 复用其私有标签抽取）→ A5b/c/d
批次3（约1周）: A3a →（实测缓冲）→ A3b      依赖 A2 的优先级信号
批次4（滚动）:   C1（依赖 A1）→ C2 → C3；B4 满足 D8 条件才启动
```

横切依赖：**B2（预览）是批次 3/4 一切 prompt 改造的观测依赖**；A2 是 A3b 的
信号源；A1 是 C1 的代码源。

---

## 8. 风险登记

- **prompt 漂移风险**：批次 3/4 每项都改变注入内容——统一纪律：零变化契约单测 +
  prompt log 前后对照 + 作者实测 2 章起，缺一不可合并。
- **A4 的「锚定本章」按钮可能提高锚定率**——属预期正效果，但需在埋点观察是否有
  作者被提示烦扰（柔性通道，可忽略）。
- **批量裁决误操作**：6 秒撤销 + 逐条 reopen 双保险；undo 链断则降级为仅逐条。
- **私有语义迁移期**：A1 上线前已有 private 实体的书，生成行为变化（秘密从正文
  上下文移入私有块）——属修复性质，提交说明写明，无需数据迁移。
- **useGenerationSession.ts 单文件风险**（路线图 §8 既有）：本批前端改动集中在
  副驾/收件箱/toast，不触键位状态机；若必须触碰，先重读路线图 T1 风险条目。

---

## 9. 全线红线（沿用 + 本期新增）

沿用：柔性可忽略不弹窗不抢焦点 · 作者裁决才落库（AI 不污染事实源）·
零变化契约（无配置书 prompt 逐字节不变）· 画布即事实源。

本期新增：
1. **预览与注入同源**——context-preview 必须与 stitch 真实装配共用同一函数，
   禁止平行实现（防「看到的是一套、注入的是另一套」）；
2. **私有通道双轨纪律**——进 prompt 的文本排除 private props，纯算法消费者
   保持全量，两者不得互相渗漏；
3. **提示不拦截**——C1 快检、A4 警示、A5c 提醒全部只提示，永不阻断写作动作。

---

## 10. 整期出口标准

- 作者录的每类数据在 B2 预览中可见、可知去向、可知被谁挤掉（A3b 后含预算占用）；
- 私有秘密不再从正文上下文裸奔（A1），私有语义在 UI 无歧义；
- 收件箱重复候选显著下降、批量裁决落地，账本漂移的履约成本趋零；
- 生成质量：作者真实写作 3 章以上实测，对照本期前的 prompt log 与成稿手感，
  确认无回退、至少一项可感知提升（样本匹配或前置校验命中）；
- 全部既有测试绿 + 新增单测覆盖本期的零变化契约与排序/去重/聚合逻辑；
- AGENTS.md 与路线图同步更新（每批合并即更新，不攒到期末）。

---

## 11. 施工记录（2026-08-21）

**提交**：代码 `e44dd59`（57 文件，+8086/-338）；同批先落两个在途收口提交
`e7bdf2b`（timeline_view 按书持久化）与 `c0dc3fc`（会话快照 error 态恢复归正）。

**测试基线收口**：后端 225 过/2 预存失败（期初）→ **365 passed / 0 failed**（本期净增
约 140 项，且预存的 boundary-pacing 2 项失败已对齐措辞修复——首次全绿）；前端
35 → **85 passed / 11 文件**，vue-tsc 干净。

**批次 1-4 全部落地**，要点偏差与决策：

1. **B2**：块渲染权威落在 `adaptive_prompts.render_system_blocks`（比设计更强——
   四 builder 本身也消费同一函数，注入序只有一处定义）；装配共享器
   `services/context/stitch_context.py`。
2. **A2**：施工期修正「死者不提权」（在场集加 alive 闸，见 §2.3 第 5 条）。
3. **A1**：stitch 路由四处 builder 接线由协调者闭环（子任务文件所有权所致缺口，
   验收时补齐）；character_statics 消费方分类表已完成（进 prompt 过滤 / 纯算法全量）。
4. **A3b**：MODE_CONTEXT_BUDGETS 五模式同值 12650（满配自然总和，恒等不触发裁剪），
   分档调参留实测期；名字/标签类字段按 16 字/个假设额度（budget.py 注释声明）。
5. **C2**：场景判定经 B2 预览的来源徽标带出（「文风样本库 · 对话场景优先」），
   未加响应字段。
6. **C3**：第 2 条「走向卡进 user」核实现状已满足，跳过（见 §5.3 注）。
7. **A5b 撤销语义**：采用「删产物 + reopen」复合撤销（裸 reopen 会留幽灵事件，
   对齐 models.py 既有契约）。

**收尾批次（同期完成）**：① finish 报告 `memory_indexed` 前后端层级错位修复
（「记忆索引 +N 段」块此前从未显示）；② boundary-pacing 两测试措辞对齐；
③ 五处注释/死代码债（orchestrator 预算注释指向 budget.py、`__init__.py` 旧端点名、
adaptive.py 文件头端点 5→12、死模板 build_inline_branch_prompt/build_settle_propose_prompt
删除、canon_watch 零 LLM 口径修正）。

**遗留与待办**：
- **实测期**（出口标准 §10 的核心，待真实写作）：A1 泄底验证 / C2 样本匹配手感 /
  A3b 预算条分布与调参 / stitch 首字延迟（决定 B4 启动）；
- **GUI 对拍**：B2 预览 vs 真实 prompt log、A5 回流三刀全流程、finish 记忆索引块显示；
- **观察项**：ghost_guard `test_mixed_kinds_capped_and_deduped` 曾一次性 flake，
  此后 25+ 次复跑未复现；
- **独立评估项**：draft_prompts/planner_prompts/orchestration/agentic 休眠链
  是否整体归档 _deprecated（本期只做了测试措辞止血）；
- **B4 真流式**：D8 条件排期维持。
