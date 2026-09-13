# 写作台侧栏可编辑内容的生成生效链路（调研报告）

> 2026-09-13 · 只读调研 · 行号以当日工作区为准（会漂移，函数名为准）
> 对象：写作台右缘助手栏 `AssistRail` + 助手面板 `InspectorPanel` 五分区里作者可编辑/可裁决的每一项内容，追踪「前端编辑 → 落库 → 哪条生成链消费 → 以什么形式进 prompt / 算法 → 多久生效」。
> 硬口径：所有结论带 file:line 实证，拒绝抽象描述。

## 0. 总览：编辑项 → 生效时延一览

| 编辑项 | 存储 | 生成侧消费路径 | 生效时延 |
|---|---|---|---|
| 打算·意图一句话 | `chapters.spine.intent` | 心跳上行→层2 spine 短路（0 LLM）→意图版本++→dock 换向；纠正史回喂反推 prompt | 下一次心跳（3s/4s 档） |
| 打算·情节锚点 | `chapters.spine.anchors` | 推测 prompt 谋篇锚点块→走向卡 serves_anchor；进度 hit 纯算法判定；finish 附注；outline 扩写全锚点行 | 走向卡=下轮推测；打勾=下一次心跳；附注=下次 finish |
| 打算·锚点岔路 | `chapters.spine.anchors[].branch` | 临近低阈值判定→走向卡舱硬提示卡置顶→选向即决岔 | 下一次心跳 |
| 打算·AI 建议收下 | 同上（此刻才 PATCH） | 同意图/锚点 | 收下后下一次心跳 |
| 「不对」意图纠正 | `spine.intent`（source=author）+ `collab_events.jsonl` 埋点 | 纠正即 spine 短路重写层2 + dock 缓存 bust；埋点成反推 few-shot 教材 | 下一次心跳（豁免 30s 节流） |
| 章节大纲 | `chapters.outline_text` | 心跳变化检测；层2 大纲转化 0.85；就近节拍三消费点（dock/推测/stitch 兜底）；反推输入 | 下一次心跳/stitch 现读 |
| 此刻·本章叙事时间 | `chapters.narrative_time` | world_bridge 四级降级→推演状态进 bundle→prompt 此刻标注/在场名单；dock 缓存签名 | **下一次生成请求即时**（无 bundle 缓存） |
| 此刻·场景钉 | `chapters.scene_location_id` | 在场提权排序、场景身份块+地点档案、dock 在册投影 T3 白名单、地点穿越闸 | 同上 |
| 此刻·在场补记（速记） | 过目→`world_events` | 事件折叠推演→同上 | 下一次生成请求即时 |
| 此刻·候选回流 ✓/✗ | `world_events` / 候选状态 | ✓ 转正进推演（即时）；✗ 累计达阈值静音 event_scout（≥3 裁决零采纳，≤60s 缓存） | ✓ 即时；✗ 累计制 |
| 此刻·静音「恢复」 | `books.assist_mutes`（宽恕时间戳） | 弹静音缓存→event_scout 双闸 + 心跳感知带恢复提醒 | 即时（下次 settle/finish/心跳） |
| 此刻·读者视角 | localStorage | **零生成影响**（纯前端展示过滤） | 永不 |
| 本章·改回全书文风 | 删 `style_cards` 章级行 | `get_effective_card` 回退书级→下次 stitch 文风块换书级 | 下一次 stitch 现读 |
| 检查·残句修复采纳 | 编辑器 insertText→PUT chapter | 正文变了→下一次心跳/stitch 上下文即时；进前情记忆要等下次 finish | 画布即时 / 记忆=下次 finish |
| 检查·AI 味「收入收件箱」 | `style_inbox_items`（pending） | **不直接生效**；文风页 confirm 后进负面清单 | confirm 后下一次 stitch |
| AI 辅助总开关 | localStorage | 纯前端闸：心跳全停/Space/Tab/幽灵采纳/细纲扩出全拦 | 即时（后端无感知） |

---

## 1. 打算分区（Ctrl+1）——写前规划数据，经「意图三级源链」进生成

### 1.1 保存链（所有 spine 编辑共用）

- 前端单例 `useChapterSpine`（`frontend/src/features/workspace/composables/useChapterSpine.ts`）：就地编辑动作（`setIntent`/`addAnchor`/`updateAnchor`/`removeAnchor`）直接改 `spine.value`，deep watch **2s 防抖**自动保存（useChapterSpine.ts:231-244）；SpinePanel 意图框另有本地 600ms 防抖+失焦兜底（`presentation/SpinePanel.vue:41-63`，2026-09-01 丢稿修复）；切章冲刷在途防抖（useChapterSpine.ts:59-66）。
- 落库 `PATCH /adaptive/spine`（`backend/routes/chapter_generation/adaptive/spine.py:128-148`）：**部分合并**（None 字段保持原值，`_normalize_spine` spine.py:64-88）；硬校验——意图 ≤60 字、锚点 2-12 字/≤5 条（超限 422 人话劝阻）；岔路 `_normalize_branch` 2-3 个 2-12 字走向、非法整个丢弃（spine.py:50-61）；**全空归 null**（无脉络=静默缺席契约，spine.py:139-141）。

### 1.2 意图一句话 → 层2 spine 短路（0 LLM，最高信度）

编辑后的意图经**两条独立通路**进生成：

**通路一：心跳上行（秒级）**。前端每次心跳都带 `spine_intent: spine.value?.intent?.text`（`useAdaptiveAssist.ts:425`）；后端 orchestrator 对它做签名比对，变化即产 `ChangeSignal(spine_updated, severity=0.6)`（`backend/services/adaptive/orchestrator.py:180-185`）——0.6 过反推阈值，且 **spine 非空时豁免 30s 反推节流**（orchestrator.py:316-326，注释明确：吞掉信号会表现为「纠正被无视」）。

**通路二：层2 短路转化**。`intent_inference.run` 读 `chapters.spine`（`components/intent_inference.py:179-199` `_spine_material`），意图非空即短路：`source="author", confidence=0.9, arc=spine_intent[:120]`，**不调 LLM**，直接 `set_intent` 写世界模型层2（intent_inference.py:74-85）。短路上移到正文体量闸门之前——空章写了打算也立刻上桌（线 C，intent_inference.py:68-73）。

层2 意图写库使 `intent_version` 递增，而 dock 的 projection 签名并入 `:v{intent_ver}`（orchestrator.py:391-394）——这是「纠正即换向」的兑现点之一。

**意图三级源链全貌**（intent_inference.py，优先级从高到低）：

1. **from_spine**：author / 0.9 / 0 LLM（如上）。
2. **from_outline**：无 spine 意图但有大纲 → author / 0.85，`arc=_extract_arc_from_outline`（intent_inference.py:86-97, 349-367）——取首条非元信息行 ≤120 字；卷首致辞过滤（整行引语/含《》/<6 字短指示）与就近节拍共用 `outline_nearby.outline_line_is_meta` 判据（`backend/services/adaptive/outline_nearby.py:31-47`）。
3. **baton 章首接力棒**：无作者材料且正文 <100 字 → 上一章结尾摘要纯拼接接管，`source=baton / 0.6 / 零 LLM`（intent_inference.py:104-112, 202-225）；**dock 猜测链不认 baton**（防摘要复读成挂件），stitch 兜底认 inferred+baton。
4. **from_text LLM 反推**：source=inferred，置信 **0.55（证据回查过）/ 0.4（没过）**（intent_inference.py:148-152）；证据回查是代码闸——模型交出的「依据句」必须规范化后 ≥4 字逐字子串出自正文，否则整类掐死（`_valid_evidence` intent_inference.py:273-289）。**dock 消费阈 0.5**（`DOCK_INTENT_MIN_CONFIDENCE`，intent_inference.py:49，orchestrator/dock 同口径）——回查不过的猜测跌破此线，卡舱不吃存疑方向，展示层照常显示。

### 1.3 意图在三个生成面的消费形态

- **dock 零件舱**：`dock_generator.run` 直读 `chapter.spine.intent`（`components/dock_generator.py:404-413` `_spine_intent`），进 prompt 的 spine_line：`# 本章意图（方向参考）`（`backend/services/prompts/adaptive_prompts.py:1632`）。另有无大纲时的方向猜测块（仅 source=inferred 且置信 ≥0.5 且未衰老，dock_generator.py:471-491；桥接态清零 :511-512）。
- **走向卡/推测**：层2 意图（arc/情绪/铺陈）进 `build_future_projection_prompt` 的「本章意图」区（adaptive_prompts.py:1300 附近）。
- **stitch 续写**：spine 意图与锚点经知识平面**温卡（warm_card）进 system 侧**——「# 本章打算（作者定的方向，软约束）」，五模式全注入、注入序第 2 位（`backend/services/context/knowledge_plane.py:407-431` `_render_warm_card` + `adaptive_prompts.py:346`）。user 侧意图块则只认大纲就近节拍或层2 inferred/baton（`stitch_context.py:169-204` 注释「不走这里…已由温卡注入 system 侧，user 侧不重复注入」——是**去重**不是无视）。〔2026-09-14 修正：本报告初版误判为「spine 不进 stitch」，详见 docs/spine-outline-merge-feasibility.md §1.3〕

### 1.4 情节锚点 → 四条消费线

1. **走向卡挂锚（推测侧写入闸 + 提取侧防御闸）**：pending 非 dropped 锚点以 `- {id}: {text}` 进推测 prompt 的「本章谋篇锚点」块，并指示「推测服务于某锚点则加 `"serves_anchor": "锚点id"`」（`build_future_projection_prompt`，adaptive_prompts.py:1258-1270）；心跳提取走向卡时二次校验 serves_anchor 必须命中本章非 dropped 锚点 id 才透传（`heartbeat.py:497-526` `_extract_direction_cards`）。前端走向卡 ⚑ 小签点击 `flashAnchor(id)` 让 SpinePanel 对应 chip 闪烁 2s（`BeatCardDock.vue:68-72` + useChapterSpine.ts:30-33）。
2. **进度打勾（纯算法零 LLM）**：`_spine_progress_for_heartbeat`（heartbeat.py:250-378）——hit 判定走 `text_match.matches` 共享判据（3 字滑窗片段，**threshold=1.0 全命中**，heartbeat.py:219），只对**新增区段**判定（growth=上次正文长度以来、就近窗口封顶 2000 字，heartbeat.py:287-288）；首轮只记基线不判定（防进程重启后 growth=全文大面积误 hit，heartbeat.py:281-285）；**pending→hit 只前进不回退**，写库前 commit+refresh 重读合并防并发 PATCH 整包覆盖作者编辑（heartbeat.py:329-373，JSONB 浅拷贝坑注释在案）；结果按 content_md5 缓存。响应 `spine_progress` 回前端 `applySpineProgress` 本地打勾（useChapterSpine.ts:36-44）。
3. **finish 附注兜底**：`post_process.run` 收集 pending 锚点 → `report.spine_note = "这几条情节打算里列了还没写到：…"`，仅提示不阻塞（`components/post_process.py:60-66`）。
4. **细纲胶囊扩写（mode=outline）全锚点行**：路由从 `chapter.spine` 抽 `[{text,status}]`（`spine.py:91-116` `_spine_anchor_rows_for_prompt`），渲染成「# 本章锚点：A（待兑现）；B（已兑现）」（adaptive_prompts.py:835-858）；胶囊自挂的单锚另有「本段服务的谋篇锚点（作者定的方向，扩写要朝它去）」行（adaptive_prompts.py:936-942）。

附带：锚点也会进 LLM 反推的输入（「本章非写不可的情节（作者定的）」行，adaptive_prompts.py:1145-1147）——但**仅在意图为空**（短路未触发）时走到。

### 1.5 锚点岔路（branch）→ 临近硬提示 + 选向即决岔

- 保存：`updateAnchor {branch:{options}}` → 后端 `_normalize_branch` 校验（§1.1）。
- 判定：带 branch 的 pending 锚点走**低阈值档 1/3** 宽松命中（heartbeat.py:223, 312-325——有意宽松：只多一张提示卡、不写库、作者可无视），命中进 `spine_progress.near_branches`。
- 前端：心跳响应把 near_branches 的每个 option 摊成硬提示卡 `is_branch: true`，**置顶**排进走向卡集（`useAdaptiveAssist.ts:513-524` `setBeatCards([...branchCards, ...direction_cards])`）——朱色视觉权重区分日常柔性建议。
- 选向即决岔：选卡走向卡连写（mode=burst），所选走向文本经 `beat_guidance` 进 burst prompt（stitch.py:398 一带 `build_burst_prompt(beat_guidance=…)`）；WorkspaceView 选后清 branch 标记。

### 1.6 AI 建议（spine-suggest）——不过目不落库红线

- `POST /adaptive/spine-suggest`：1×creative LLM，**不落库**（spine.py:151-153，D-4 红线）；输入含大纲/世界观/Canon/**上一章未兑现 pending 锚点顺延**（spine.py:159-176）；空输出兜底重试一次（REASONING_DISABLED 800，spine.py:198-210）。
- 「收下」`adoptSuggestion`：**此刻才 PATCH 落库**（source='ai'，useChapterSpine.ts:123-146）；「不用」只清本地建议卡（discardSuggestions）。

### 1.7 意图纠正手势「不对」——三路生效 + 数据飞轮

`correctIntent(text, guessed)`（useChapterSpine.ts:175-182）做两件事：写 `spine.intent={text, source:'author'}`（恒 author，覆盖 ai 建议来源——作者改过的就是作者的）；埋点 `intent_correct {guessed, corrected}` 落 `data/collab_events.jsonl`。

生效链：
1. **层2 即时换向**：下一次心跳 spine_intent 上行 → spine_updated 信号（豁免节流）→ spine 短路重写 intent（§1.2 通路一/二）。
2. **dock 舱即换向**：dock 文本签名并入 spine_intent 与 word_count（orchestrator.py:368-377——「纠正的瞬间段落文本没变，但 spine_intent 行该换料」）+ projection 签名并入 intent_version（:391-394）——双签名 bust，缓存必失效重算。
3. **纠正史回喂（越用越像你）**：下次 LLM 反推时 `_recent_intent_corrections` 扫 jsonl（30s 缓存，intent_inference.py:307-346，parents[4] 路径坑注释在案）进 prompt 口味教材；纠正 ≥2 追加「宁答方向不明别硬编」保守指令（intent_inference.py:119-128）；同批还注入前几章作者亲笔意图轨迹（`_chapter_intent_trajectory`，intent_inference.py:228-264）。

前端乐观更新：`confirmCorrectIntent` 即时把 planSuggestions 置 `{source:'author', arc:text, confidence:1}`（`InspectorPanel.vue:446-456`），不等心跳。

### 1.8 章节大纲（outline_text）→ 就近节拍是主消费面

- 保存：侧栏 textarea 500ms 防抖 → `store.updateChapter` → `PUT /chapters/{id}`（`InspectorPanel.vue:152-159`；后端 `routes/chapters.py:102` exclude_unset 部分更新）。
- **就近节拍**（`outline_nearby.py:63-87`）：从头扫大纲，跳过已写行（`text_match` ≥2/3 命中即视为已写，outline_nearby.py:50-60）与元信息行，取接下来 1-2 拍原文（每拍 ≤60 字）。三个消费点：
  1. **dock**：素材块「作者大纲·就近节拍（**几步之外的目的地**——碎片只给通往它的第一步，不是节拍本身的画面）」（adaptive_prompts.py:1641）；槽位子句按 `has_nearby` 分节编译（有节拍→「给了就近节拍则含 1 枚 toward_beat」，adaptive_prompts.py:1692-1705）；桥接态切断（dock_generator is_bridge）。
  2. **未来推测**：「推测画面必须是通往它路上的合理一步，人物此刻在哪/在做什么以此为准」（adaptive_prompts.py:1286-1293）。
  3. **stitch 意图兜底**：请求未带 chapter_intent 时 `resolved_intent=就近节拍行`、`intent_source='outline'`（`stitch_context.py:246-248`）→ `build_continue_prompt` 渲染为「几步之后的目的地（只作方向参照：现在不写它本身——它的场面、事件与对白都留给作者）」重框（adaptive_prompts.py:617-635）。
- 其它消费：心跳变化检测（outline 签名对比触发反推重算，orchestrator.py:171-175）；层2 大纲转化 0.85（§1.2）；LLM 反推输入。
- ⚠ 边界：finish 报告的「关键情节完成度」来源是**章节卡 must_hit_events**（`check_must_hit_coverage(full_text, bundle)`，post_process.py:53），不是大纲行——大纲行没有逐行对账。

### 1.9 观察：stitch 请求的 chapter_intent 字段前端零发送

`StitchRequest.chapter_intent`（`adaptive.api.ts:424`）后端全链支持（stitch.py:149→stitch_context.py:241-242 `intent_source='request'`），但**前端无任何调用点赋值**（全 frontend grep 零命中）——「请求自带意图」档当前是休眠路径，实际 stitch 意图总走就近节拍（outline）或层2 兜底（inferred/baton，置信 ≥0.5）。分档措辞已备好：inferred→「AI 猜的，对不上就忽略」/ baton→「承接上一章」（adaptive_prompts.py:623-634）。

---

## 2. 此刻分区（Ctrl+2）——世界切片的时空编辑

### 2.1 前端写入链（useWorldSlice）

`frontend/src/features/world/composables/useWorldSlice.ts`：`setNarrativeTime`/`setScenePin` 都走 `PUT /chapters/{id}`（useWorldSlice.ts:105-114 → world.api.ts:366-379），写 `chapters.narrative_time` / `chapters.scene_location_id`（`backend/models/narrative.py:123,126`）；写后 `{silent:true}` 立即重取切片（useWorldSlice.ts:72-92）。保鲜三时机：切章 watch / 心跳 `world_version` 事件（useAdaptiveAssist.ts:558-561 → notifyVersion 比对 events 数+updated_at 才重取）/ 窗口聚焦兜底（useWorldSlice.ts:148-156）。

### 2.2 叙事时间 → 世界推演 → prompt

- **四级降级**：`resolve_narrative_time`（`backend/services/context/world_bridge.py:58-102`）本章锚→前序最近锚→事件最大时刻→0。
- 推演经 Fold API 唯一入口（`world_fold`，world_bridge.py:361-364）→ bundle 携带 `world_state/world_time/world_time_source`（`settings_bundle.py:338-374`）。
- **prompt 形态**（`backend/services/context/knowledge_plane.py`）：场景身份块带 `叙事时刻：t={world_time}（本章锚/前序最近锚/事件最大时刻）`（:469-475）；在场实体块逐条 `【此刻·t=N·位于北岸要塞】` 时态标注、块尾「与档案描述冲突时以【此刻】为准」（:496-512）；user 尾部 recency 重钉（:544-554）。角色行的 `此刻：{dynamic_state}`（「在途（进度 40%）」「已死亡」）由 `dynamic_state_text` 生成（world_bridge.py:167-188）。
- **生效时延：下一次生成请求即时**——`assemble_stitch_context` 每次 stitch 现调 `load_chapter_settings_bundle`（stitch_context.py:238），dock `run` 同样现读（dock_generator.py:429），无 bundle 级缓存。

### 2.3 场景钉 → 在场提权 + 在册投影 + 穿越闸

- **在场提权**：`load_world_overlay`（world_bridge.py:381-405）——场景作用域=钉定地点自身+全部祖先（`location_tree.py:100-111`），**死者不进在场集**（:386-391）；角色排序键 = 在场→有事态→重要度（:399-405）；无钉书第一键恒 0（零变化契约，:377）。
- **场景身份块**：`本章场景：{loc_name}（作者钉定）` + 祖先链地点档案逐级注入（knowledge_plane.py:452-468）。
- **dock 在册投影**：`onstage_projection`（dock_generator.py:119-227）产「本场在册」白名单（T3 执法）；`presence_fingerprint = f"{scene_loc_id}:{narrative_time}"`（dock_generator.py:230-237）进 dock 缓存 stage 签名（orchestrator.py:227-238, 400-408）——**换景/换锚即重算整舱**。
- **地点穿越闸**：stitch 侧用 scene_location_id 闭包（自身+祖先∪子树）算越界地点名表（stitch.py:188-213）。

### 2.4 候选回流收件箱 ✓/✗

- ✓ 采纳：`accept_candidate`（`backend/routes/world.py:491-555`）——canon_extract 分流建 tentative CanonNode；普通候选先过**重复转正闸**（归一化子串判重，命中标 `auto_reject:"duplicate"` 不建事件，:524-550）再 `world_events` append；幂等非 pending 409。转正后 fold 纯函数现读（`compute_world_state_from_events`，`backend/repositories/world_repository.py:271`）→ 下一次生成请求即时可见。6s 撤销胶囊=删事件+候选回 pending（useWorldSlice.ts:135-139 → world.py:572）。
- ✗ 丢弃：候选标 rejected 留痕（world.py:558-569）→ **学着闭嘴**静音派生：`_compute_muted_keys` 从裁决史计数（quiet_learning.py:256-305），**裁决 ≥3 且 ✗ ≥3 且 ✓==0 才静音**（:107-119，阈值常量 :57-58），auto_reject 假拒绝不计（:281-282）；静音集 60s 缓存（:233-236）。生成侧双闸：event_scout prompt 排除块 + 落池过滤（`backend/services/world/event_scout.py:144-156, 214-216`）。
- 批量采纳：串行走同一 accept 端点 + 整批 6s 撤销（`frontend/src/features/world/composables/batchAccept.ts:111-164`）。

### 2.5 世界速记（Alt+N /「少了谁？补一句」）

`POST /world/parse-event` **只产草稿绝不写库**（`backend/services/world/event_parser.py` 模块 docstring；routes/world.py:413）；作者过目后走既有 `POST /world/events` 落库（QuickEventNote commit，workspace 版 `presentation/QuickEventNote.vue:136-163`）；工作台版对 new_entities 只提示不代建（:281-283），世界页版才勾选代建。落库后同 ✓ 采纳即时进推演。

### 2.6 静音「恢复」

`POST /books/{id}/assist-mutes/forgive`（routes/assist.py:46-64）→ `books.assist_mutes` 只记宽恕时间戳（quiet_learning.py:315-326）——静音集合本身**永不落库**、每次从裁决史+hint 收起史派生，宽恕即「该时刻前的记录一笔勾销」；宽恕同时弹 60s 缓存 → 下一次 settle/finish 抽取与下一跳心跳感知带（heartbeat.py:129-138 过滤点）即时恢复。

### 2.7 读者视角——零生成影响（实证）

`worldReaderView` 全仓引用仅两处（useUiPrefs.ts:13 + WorldSceneSlice.vue:73-90），只过滤前端 presence/encounters/伏笔区显示；不在任何 API 请求体、后端 schema 无对应入参；`slice_mode` 埋点只进行为账不进生成上下文。

---

## 3. 本章分区（Ctrl+3）——文风卡的唯一面板内操作

- 「编辑本章专属文风」= 跳文风页深链 `?chapter=`（InspectorPanel.vue:417-421），编辑发生在文风页。
- 「改回全书文风」= `DELETE /style-card?chapter_id=`（InspectorPanel.vue:423-432 → `backend/routes/style/card.py:113-129`）删章级覆盖行 → `StyleCardRepository.get_effective_card` 三态回退书级（`backend/repositories/style_card_repository.py:67-80`：章级覆盖存在即**整卡覆盖**——负面清单也整体替换）→ **下一次 stitch 现读生效**（每请求 `load_chapter_settings_bundle` 现查，settings_bundle.py:414-432）；唯一小缓存是心跳文风漂移提示按正文长度缓存一拍（heartbeat.py:395-397 `_STYLE_HINT_CACHE`）。
- 文风块注入五模式全通：画像块+样本 few-shot（k≤2，burst k=3）经 `render_system_blocks` 尾两块（adaptive_prompts.py:344-365，事实层前于文风层）；**dock 零件 prompt 有意不注入画像/样本**（build_dock_generator_prompt 签名无 style 字段），但**禁词进 dock**（banned_words ≤30 经占位符注入 + `_violates` 仅按 blocker 档丢违规挂件，dock_generator.py:1072-1090）。

---

## 4. 检查分区（Ctrl+4）——裁决式操作

### 4.1 残句修复采纳

后端 `POST /adaptive/fix-sentence` → `repair_single_defect` **只产修复句不改正文**（`backend/services/workflows/sentence_integrity.py:239-268` docstring；安全网 :218-234）；匹配口径=画布正文 `written_text`（settle_finish.py:308-311，找不到 409）。前端「采纳」→ `replaceSentenceInDoc` 编辑器 insertText 替换（InspectorPanel.vue:340-365），落库靠编辑器 update-chapter 机制。
**对生成的影响**：画布文本直接进 stitch 的 rolling_prefix/fragment/检索 query（stitch_context.py:229-230, 261, 281）与心跳 recent_text（请求体上行）——**下一笔生成即时吃到新正文**；但进**前情记忆要等下一次 finish**（`index_chapter_memories` 只挂 finish，settle_finish.py:127-145，章级先删后建幂等，`memory_indexing.py:57-84`）。

### 4.2 疑似 AI 味「收入收件箱」——候选不直接生效红线

投递链：侧栏按钮 → `styleApi.addInboxItem('negative_candidate')`（InspectorPanel.vue:379-396）→ `style_inbox_items`（pending，`backend/routes/style/feedback.py:67-91`，模块头红线「候选不直接生效」:5）→ 文风页 confirm 写**书级卡** negative_list（feedback.py:116-184，按 word 去重）→ **下一次 stitch 立即生效**：负面清单四源合并**无缓存每次直查**（`backend/services/style/prohibitions.py:44, 172-285`），warning 档进 prompt 禁词块第 8 位（adaptive_prompts.py:352）、blocker 档正面化重钉 user 尾部【作者禁忌】（knowledge_plane.py:563-606）+ P1 洗层词边界替换（`ghost_wash.py:65-118`，挂 stitch 链 GHOST_DONE 前 stitch.py:877-922）。

### 4.3 完稿体检的写动作与回流

`POST /adaptive/finish`（settle_finish.py:75-256）按序：post_process 审计（含 spine_note 附注）→ 整章候选抽取 event_scout 进 pending 池 → 记忆重索引 → 语义扫描（只进报告不进收件箱，:147-175）→ 质感样本候选直投文风收件箱（`most_textured_window`，fingerprint.py:366 + settle_finish.py:177-229）→ `candidates_pending` 计数。回流面：检查分区报告（残句/语义命中/收件箱积压「去处理」跳此刻分区）+ 文风页收件箱（质感样本）。读者反馈**零落库零回流**（settle_finish.py:330-373）。

---

## 5. AI 辅助总开关——纯前端闸

状态：模块级单例 + localStorage `velluma:assist:enabled`（`useAssistEnabled.ts:12-23`，默认开）。门控点（后端无感知、无任何请求字段）：

- 心跳全停：`if (!assistEnabled.value) return`（useAdaptiveAssist.ts:178）——关闭即无停顿感知/卡舱供件/走向卡；
- Space 续写幽灵浮层（`useGenerationSession.ts:594`）与幽灵态 Space 采纳（:729）；
- Tab 卡舱点名（:607）与 adaptive 激活（:627）；
- 细纲胶囊落笔扩出（useAdaptiveAssist.ts:922-924）。

---

## 6. 机制注记（编辑侧视角的边界与红线）

1. **两级防抖嵌套**：spine 编辑=SpinePanel 600ms（意图框局部）→ useChapterSpine 2s（整对象 PATCH）；大纲=500ms。侧栏 UI 上「打完字马上 Tab 点卡舱」可能吃不到刚写的打算（最多滞后 ~2.5s 落库 + 下一次心跳上行）。
2. **dock 缓存签名三键**：文本签名（recent_text+spine_intent+word_count）× projection 签名（接缝裁剪后集合+intent_version）× stage 签名（presence_fingerprint=场景钉:叙事锚+DOCK_PIPELINE_VERSION）（orchestrator.py:375-408）——侧栏任一时空编辑（改锚/换钉）都必然穿透缓存；Tab 点名另有 force_refresh 全豁免。
3. **hit 只前进不回退**：锚点自动打勾不可逆（宁漏勿误，漏判有 finish spine_note 兜底）；作者唯一回退手段是手动划掉（dropped 不再参与判定与警示）。
4. **两条「不落库」红线在侧栏直接可见**：spine-suggest 建议（收下才写）、世界速记草稿（过目才建事件）；一条「不直接生效」红线：AI 味候选（confirm 后才进负面清单）。
5. **spine 意图与 stitch 的关系**（2026-09-14 修正）：spine 意图+锚点**确实进 stitch**——经知识平面温卡注入 system 前缀（五模式全通，knowledge_plane.py:407-431），且 spine 整体哈希进章内冻结前缀缓存签名（knowledge_plane.py:688-702——改 spine 必失效前缀，正确行为）。层2 兜底只认 inferred/baton 是 user 侧意图块的**去重纪律**（同一信息不在 user 侧二遍注入），不是供给缺口。user 侧「目的地」槽刻意只收大纲就近节拍——弧线级材料进该槽会复现 08-25 冲章事故（见 docs/spine-outline-merge-feasibility.md §1.4）。chapter_intent 请求档前端零发送（§1.9）。
6. **世界侧编辑全部即时**（无 bundle 缓存、每请求现读+fold 现算）；文风/负面清单同样现读无缓存。唯一的延迟面：候选 ✗ 的静音效果（累计 3 次+60s 缓存）与记忆重索引（只随 finish）。
