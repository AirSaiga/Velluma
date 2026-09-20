> **归档说明（2026-09-19）**：一次性调研（2026-09-15），简报化结论已于当日施工落地（e8cd82c）；现行行为见 `docs/ai-view-panel-guide.md`。

# AI 视角轻量化与态势简报化 · Phase 0 可行性调研报告

> 调研日：2026-09-15 · 性质：**纯只读调研**（未改任何代码） · 行号锚点以当日工作区为准
> 调研对象：写作台助手面板「AI 视角」分区（`InspectorPanel.vue` debug 分区 + `ContextPreviewSection.vue`）
> 前置权威：`docs/design/ux-redesign/09-ai-view-redesign.md`（09 期重设计）、`docs/reports/ai-view-panel-report.md`（2026-09-14 面板全景调研）、`docs/reports/foundation-hardening.md` §2.1（同源红线出身）
> 目标形态：上层 4~5 行极简高密【战局态势简报】（当前场景/在场存活人物及状态/焦点道具/守死秘密/当前引力）+ 下层原始 14 块折叠逃生舱 + 空块「还没录」催收框全量静音。

---

## 0. 三句话结论

1. **态势简报零 LLM、零新增查询即可组装**：后端在把上下文渲染成 14 块 Markdown 之前，`StitchContext` 装配对象里已经持有简报五行需要的几乎全部结构化数据（`active_scene` / `kg.present_names`+`dead_names` / `bundle.world_state.character_states` / `bundle.character_secrets`+`field_layer_secrets` / `chapter_intent`+`intent_source`），缺的只有「本场在册白名单」一档精度——而它有现成纯函数 `onstage_projection` 可零成本调用。在 `ContextPreviewResponse` 上加一个可选 `briefing` 对象是**增量字段**，后端约 50 行、旧客户端零影响。
2. **空块全量静音是三处改动里最安全的一刀**：全套 vitest（`contextBlockFormat.test.ts` 225 行 + `contextBudget.test.ts`）只测解析/预算纯函数，**零测试依赖空块渲染**；三段分组骨架本来就是 `blocks.length > 0` 动态过滤（`ContextPreviewSection.vue:126`），空块滤掉后整段皆空的段自动消失，结构无缝。唯一要还的债是 09 设计稿把「空块补录引导」写进了红线继承行——需按既有先例补施工批注，并连带清理 `EMPTY_HINTS` 常量、`.blk-empty` 样式与悬空的副句文案。
3. **一个被低估的耦合**：简报第一行「当前场景」在中插（FIM 骨架跳写）时会**撒谎**——preview 路由现在读的是落库章节尾部（`preview.py:63-79`），而真实 stitch 读的是编辑器活态光标前文（`useAdaptiveAssist.ts:723-732`）。要让简报在光标中插时也如实，路由需补光标窗口入参（前端容器已持有 `chapterEditorHandle`，取窗成本约 30 行）。此项不只是「附加确认」，是 briefing 可信度的前提。

---

## 1. 数据链现状（30 秒版）

```
GET /adaptive/context-preview?mode=…
  └─ preview.py:81 ── assemble_stitch_context(chapter_id, mode, fragment="", rolling_prefix=落库章节尾部)
       └─ 返回 StitchContext（结构化装配快照，stitch_context.py:62-105）
            ├─ bundle: SettingsBundle（canon_context/world_state/character_secrets/…）
            ├─ kg: KnowledgeView（知识平面，含审计字段 present_names/dead_names）
            ├─ active_scene: {loc_id, loc_name, derived, via}｜None（第三弹光标派生取景框）
            ├─ chapter_intent + intent_source（request/outline/inferred/baton）
            └─ proper_nouns/memory_echoes/style_positive/author_samples/…
  └─ build_context_preview(ctx)（stitch_context.py:433-467）
       └─ ctx.system_blocks_with_usage() → 14 块 (key, 渲染文本)
       └─ 返回 {mode, blocks[14], total_chars, world_time, world_time_source, world_sourced, unselected, selected_keys}
```

关键事实：**结构化 → 渲染的折叠点在 `build_context_preview`**。渲染成 Markdown 字符串是最后一步；此前的 `StitchContext` 全程是结构化对象。简报要做的事 = 在这个折叠点上「抄近道」，把结构化字段分流一份给 briefing，不经过 Markdown 渲染。

前次调研（`docs/reports/ai-view-panel-report.md` §12）已发现的三处漂移与本报告直接相关：前端 `ContextPreviewBlock.key` 联合类型停在 7 键（实际 14 键，`adaptive.api.ts:233`）；后端 `selected_keys` 被 response schema 静默丢弃（schemas.py:116-124 未收录）；`unselected` 已下发但前端从未消费。三者共同说明：**「后端加增量字段」这条路是畅通的，且已有半成品躺着**。

---

## 2. ① 结构化数据就绪度审计（简报五行逐项对照）

| 简报行 | 后端现成字段 | 形态 | 就绪度 |
|---|---|---|---|
| 当前场景 | `ctx.active_scene`（`{loc_id, loc_name, derived, via}`，`active_scene.py:72-78`） | **结构化 dict** | ✅ 现成（第三弹已接流进装配，`stitch_context.py:306-322`）；但受 §5 光标盲失真影响；None=未派生时需回退 `bundle.chapter.scene_location_id`+地点名 |
| 在场存活人物及状态 | `ctx.kg.present_names` / `kg.dead_names` / `kg.present_entity_ids`（`knowledge_plane.py:94-98`） | **结构化名单** | ✅ 现成（名字级）；「及状态」（位于北岸要塞/在途 40%/已死亡）明细在 `bundle.world_state["character_states"]`（list of `{entity_id, alive, location_id, dynamic_state, label}`，`world_bridge.py:370-372` 消费口径）✅ 同样现成 |
| 焦点道具（上手件） | `onstage_projection(bundle, scene_loc_id, recent_text)`（`dock_generator.py:119`，纯函数） | **结构化在册表**（人物+物件+场景行） | ⚠ 需轻量调用：stitch 装配链**不跑** onstage_projection（那是 dock 侧设施）；但它纯函数零查询，输入三件（bundle/钉或派生 loc_id/光标前文）在 `build_context_preview` 现场全有。注意退化梯子：legacy 书（`world_sourced=False`）恒 None——简报该行对 legacy 书直接不渲染 |
| 守死秘密 | `bundle.character_secrets`（`[{name, text}]`，整人私有）+ `bundle.field_layer_secrets`（字段级，`settings_bundle.py:111/117`） | **结构化列表** | ✅ 现成（ghost_guard 3b 同源零额外查询）；canon `[private]` 段则混在 `canon_context` 渲染字符串里无结构化形态——简报「守死秘密」行建议只吃 secrets 两通道 + canon 行数统计可从字符串 `count("[private]")` 类轻判，或干脆不展示 canon 细目 |
| 当前引力（意图/去向） | `ctx.chapter_intent` + `ctx.intent_source`（`stitch_context.py:74-81`） | **结构化**（文本+来源枚举） | ✅ 现成，但有口径细节：作者 spine 打算**不走这两个字段**（spine 经知识平面 `kg.warm_card` 温卡注入 system 侧，`stitch_context.py:181` 注释明示）——简报「当前引力」行需要 `chapter_intent`（有则用）与 `kg.warm_card`（spine 短路时的载体，渲染文本）二选一取材，或后端在 build 时直接读 `bundle.chapter.spine` 的 intent 键（装配时零成本，一致性最稳） |
| （附）叙事时刻 | 响应已有 `world_time`/`world_time_source` | 结构化 | ✅ 已在响应里 |

**改动成本核定**：

- **后端**：`schemas.py` 加 `ContextPreviewBriefing(BaseModel)`（约 15 行）+ `build_context_preview` 里从 `ctx` 挑字段组装 dict（约 25-40 行，含 onstage_projection 可选调用与 legacy 降级）+ `ContextPreviewResponse` 加可选字段。**零新增 DB 查询、零 LLM**——所有数据都是装配顺产的副产品。向后兼容：增量字段 + `response_model_exclude_none`，与 `unselected` 入场时的先例同款。
- **前端**：新增 `ContextBriefing.vue` 展示组件（或 ContextPreviewSection 头部区块，约 80-120 行）+ `adaptive.api.ts` 类型扩展。纯展示，无状态管理改动。
- **明确反对的替代路线**：前端拿现有 `blocks` 的 Markdown 解析提炼简报——解析渲染文本天然脆弱（格式属于 prompt 层资产，随注入措辞调整就会碎），且违背「结构化先行」；`unselected` 下发了没人消费的前科已经证明「等前端自己挖」不可靠。

---

## 3. ② 空块「还没录」催收框全量静音的断裂面评估

**结论：无测试断裂，无骨架破坏，三个小尾巴要顺手清掉。**

### 3.1 测试依赖：零

- `frontend/src/features/workspace/__tests__/contextBlockFormat.test.ts`（225 行）全部针对 `contextBlockFormat.ts` 解析纯函数：保字不变式对拍（:94-114）、节点形态（:116-187）、行内切分/着色（:189-202）、段分组与来源映射（:204-224）。**不 import 组件、不断言渲染输出、不触空块**。
- `contextBudget.test.ts` 只测 `budgetFillPercent/isBudgetHot` 纯函数。
- `ContextPreviewSection.vue` 本身**没有任何组件级测试**（无 mount/渲染测试存在），`EMPTY_HINTS`/`blk-empty`/`还没录` 在 `frontend/src` 全量检索中除组件自身与设计稿外零引用。

### 3.2 三段分组骨架：天然兼容

`segments` computed（`ContextPreviewSection.vue:120-127`）本来就是对 `SEGMENT_ORDER.map(...).filter(s => s.blocks.length > 0)` 的动态过滤——段是数据驱动的，不是固定三行。把块过滤条件从 `b => segmentOfKey(b.key) === id` 收紧为 `b => b.content && segmentOfKey(b.key) === id`，整段皆空的段（如零设定书的「约束与记忆」段）自动消失，`.filter` 既有语义原样承接。`expandedKeys` 默认含 `'scene'`（:73）不受影响（scene 块恒非空——`render_system_blocks` 序列里 scene 由知识平面恒渲染）。

### 3.3 三个连带清理项（不做会留尸体）

1. **09 设计稿红线修订**：`09-ai-view-redesign.md` 头部「红线继承」行明文列有「空块补录引导」，§8 契约行也锁了「`EMPTY_HINTS` 的 key 对应关系」。全量静音是产品决策对设计红线的推翻——按既有先例（该文档§附录已有三条施工批注，含「plain 兜底改衬线」同级别修订）补第四条批注留档，勿静默漂移。
2. **死代码**：`EMPTY_HINTS` 常量（:60-68，7 条）、`.blk-empty` 全套样式及 `.blk + .blk-empty` 等四条相邻 margin 选择器（:564-599、:574-579）一并删除。
3. **悬空文案**：副句「AI 续写时读到的，就是下面这些字。**空着的块 = 这次用不上。**」（:183）后半句失去指涉对象，需改写；骨架屏（:225-234）不涉空块可不动。

### 3.4 顺带确认的静音原则一致性

简报层应继承同一纪律：**briefing 某行数据为空（无场景/无在场/无秘密/无意图）时整行不渲染**，不要在简报层再造一批「还没录」变体——否则只是把催收框换了个楼层。

---

## 4. ③ 09 期宪法级不变量（重构中必须严格继承的资产清单）

通读设计稿与实现后，以下九项是 09 期沉淀的**不可回退机制**，态势简报化改造中无论怎么动 UI 都必须原样保留：

| # | 不变量 | 出处 | 为什么不能动 |
|---|---|---|---|
| 1 | **保字排版不变式**：解析只许把结构标记（#/−/｜/缩进/换行）转排版结构，其余字符不增不删不改写；`normalize(摊平) === normalize(原文)` 对拍测试是合入前置 | 设计稿 §5.5 / `contextBlockFormat.ts:1-16` / 测试 :94-114 | 「所见即所读」的可执行定义。下层原始块逃生舱保留 = 此不变量天然保留；若动渲染必须跑对拍 |
| 2 | **「原文」等宽逐字核对逃生舱**：全局开关，全部块正文回退 `<pre>` 逐字直出，组件内 ref 不持久化 | §5.4 / `ContextPreviewSection.vue:74-75,274` | 信任的兜底。简报是新的「提炼层」，**逐字原文仍是唯一信任锚点**——简报层绝不能取代或裁撤它 |
| 3 | **同源红线**：preview 与 stitch-ghost 共用 `assemble_stitch_context` + `render_system_blocks`，禁止平行实现 | §8 / `stitch_context.py:5-11` / `preview.py:30-32` | briefing 数据必须从同一 `StitchContext` 派生（build_context_preview 内组装），**禁止**为简报另起查询链或前端拼装——否则简报与真实注入漂移，比没有简报更糟 |
| 4 | **注入序三段分组**：事实与设定 → 约束与记忆 → 文风与笔感（+other 兜底），段=视觉切分、块=折叠单元，序不重排 | §2.2 / `contextBlockFormat.ts:32-47` | 注入序是「事实层前于文风层」架构决策的可见面；下层逃生舱保持此结构 |
| 5 | **折叠头行即仪表盘**：标题/N 字/来源/预算条/trimmed 全在头行，展开即全量、无嵌套滚动（grid 0fr→1fr 动画） | §4.2 / 组件 :259-300 | 「2 秒扫完」已经在这层实现过一次——简报层是其极致化，不是替代 |
| 6 | **模式五档 + 切换保留展开态 + 切章复位**：五模式检索锚不同；重读时旧列表半透明冻结零跳动；切章数据置空复位 | §4.1/§4.3 / `InspectorPanel.vue:301-321` | briefing 必须同样随模式切换重算（不同模式在场集/召回不同）、随切章复位 |
| 7 | **健康横幅条件置顶**：`componentErrors` 有错才渲染、默认折叠计数行 | §4.4 / `InspectorPanel.vue:899-914` | 信任问题最先看到；简报层插在它之下，不动其置顶地位 |
| 8 | **折叠/开关态组件内不持久化**：不入 localStorage（启动脚本换 origin 漂移教训） | §4.1 / 组件 :70-76 | 简报层的任何开关（如「展开原始块」）同纪律 |
| 9 | **措辞承诺句**：「AI 续写时读到的，就是下面这些字」 | §7 / 组件 :183 | **本次最大的措辞风险**：简报是提炼视图而非逐字注入，若简报层措辞暗示「这就是 AI 读到的」，会稀释承诺句的公信力。简报须自带口径标注（如「态势提炼 · 逐字注入见下方」），承诺句归属下层原始块 |

另有一条前端待还的技术债可随批清偿：`ContextPreviewBlock.key` 联合类型 7 键 → 14 键（`adaptive.api.ts:233`），`unselected`/`selected_keys` 是否消费随简报一并拍板（简报的「未选清单」诉求与它天然重叠）。

---

## 5. ④ FIM 中插态的真实切片问题（preview 光标盲失真）

### 5.1 差异实锤（双路由取源对照）

| 维度 | 真实 stitch（`POST /adaptive/stitch-ghost`） | 预览（`GET /adaptive/context-preview`） |
|---|---|---|
| rolling_prefix | **编辑器活态**：当前段落起点前 200 字（`useAdaptiveAssist.ts:731-732`） | **落库章节尾部**：`_html_to_plain(chapter.content_text)` 剥 HTML 后 `sentence_clean_tail` 截窗（`preview.py:63-79`） |
| fragment | 光标前段内文本尾 200 字（桥接态=段首到光标，`:723-727`） | **恒空串**（`preview.py:84`） |
| suffix_anchor（FIM 后文锚） | 光标后 1-2 句（`:750`，`StitchRequest.suffix_anchor` schemas.py:83） | **无此参数** |
| 失真后果 | — | ①中插时光标后的已写内容全部漏出（读到的是文末语境）；②`update-chapter` 落库防抖窗口内读到旧稿；③`active_scene` 派生源 `rolling_prefix+fragment`（`stitch_context.py:310`）在预览里=章节尾部——**简报「当前场景」行在骨架跳写时直接错场景** |

### 5.2 路由需要补什么

最小且与 stitch 同构的方案：**GET 增加可选 query 参数**（缺省=现状章节尾部路径，逐字节零变化契约）：

- `before_cursor`：光标前连续正文窗（前端可用现成 `_anchorRecentText` 口径，桥接态=光标前 500 字，普通态=当前段+段前文），后端映射为 `rolling_prefix`+`fragment`；
- `after_cursor`：光标后 1-2 句（=stitch 的 `suffix_anchor`），供桥接判定/称呼表泄漏手术/`active_scene` 后文语境——不必进 prompt（预览本来就不生成），但影响装配分支。

替代形态：直接收 `rolling_prefix`/`fragment`/`suffix_anchor` 三参直通 `assemble_stitch_context`（与 `StitchRequest` 字段同构，保真度最高）。GET query string 放 500 字中文有 URL 长度顾虑但远未到浏览器上限（Electron/Chromium 2MB 级），可接受；若求稳可改 POST（`response_model` 不变，前端 `requestJson` 调用处一行改动）。

### 5.3 前端成本

`InspectorPanel.vue` **已经 import `chapterEditorHandle`**（:29，:411 在用）——光标窗口在容器层可直接取，`loadContextPreview`（:287-298）加取窗与传参约 30 行；`adaptiveApi.contextPreview`（`adaptive.api.ts:337-338`）签名扩两个可选参数。面板打开而编辑器不在场（切页快照态）时回退现状路径即可。

---

## 6. 最小改造建议（推荐分期）

**总原则：上层做「提炼」新层，下层原样降级为逃生舱；一切数据从同一 `StitchContext` 派生；空数据不渲染。**

### Step 1 · 空块全量静音（纯前端，~15 行，零风险，可先行合入）
`segments` computed 加 `b.content` 过滤 + 删 `EMPTY_HINTS`/`.blk-empty` 样式 + 改副句 + 09 稿补批注（§3.3 三尾巴）。

### Step 2 · briefing 增量字段（后端 ~50 行 + 前端 ~100 行，零 LLM 零新查询）
- `schemas.py`：`ContextPreviewBriefing`（scene/onstage/props/secrets/intent 五行结构 + 各行缺省 None）；
- `build_context_preview`：从 `ctx` 组装；「焦点道具/本场在册」按需调 `onstage_projection(bundle, active_loc_id or 章钉, rolling+fragment)`（legacy 书降级 None）；「当前引力」优先 `chapter_intent`、spine 短路时读 `bundle.chapter.spine`；
- 前端简报组件置顶渲染，行空不渲染；措辞带口径标注（不变量 #9）。

### Step 3 · 光标真切片（后端路由 ~20 行 + 前端 ~30 行）
§5.2 方案；这是 briefing「当前场景」行在 FIM 态不撒谎的前提，建议与 Step 2 同批或先行——**briefing 上线而光标盲未修，等于给作者看一个中插时会错场景的简报**，比现状更伤信任。

### 不做清单
- 不在 briefing 里解析 blocks Markdown（§2 反对理由）；
- 不为 briefing 加任何 LLM/新查询；
- 不动注入链（briefing 只读，`render_system_blocks`/四 builder 零改动）；
- 不动健康横幅/世界模型卡/原文开关/三段分组（下层原样继承）；
- 不动 `unselected` 消费（是否把「未选清单」并进简报另案拍板，数据已在响应里躺着）。

---

## 7. 风险登记

| 风险 | 等级 | 处置 |
|---|---|---|
| briefing 与真实注入漂移（若绕开同源） | 高 | 不变量 #3 写死：只在 build_context_preview 内组装 |
| 简报措辞稀释「所见即所读」承诺 | 中 | 口径标注 + 承诺句归属下层（不变量 #9） |
| FIM 态简报场景行错误 | 中 | Step 3 前置或同批（§6） |
| 空书/零设定书简报全空 | 低 | 行空不渲染原则；空态回落现有汇总行 |
| onstage_projection 进 preview 的隐性耦合 | 低 | 纯函数零查询；但它是 dock 侧资产，跨包 import 需在报告施工时留意分层（`services/adaptive/components/` → `services/context/` 反向依赖，建议经参数注入或在 stitch_context 侧薄封装） |
