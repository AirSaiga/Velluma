# 动态场次流转与场景钉解绑可行性分析报告

> 2026-09-14 · 系统架构重构调研第二期 · 纯只读调研（零代码改动）
> 议题：文学空间单元是「场景/镜头」而系统钉死「一章一地」（`chapters.scene_location_id`）——500 字内「维修棚→村道→明姐家厨房」三场流转在当前架构下如何困境重重，以及章内动态转场（Intra-Chapter Scene Transit）三种设想的穿透审查。
> 行号以 2026-09-14 工作区为准；所有关键结论附代码证据。第一期报告（docs/spine-outline-merge-feasibility.md）结论在本文中被引用两处。

---

## 0. 结论摘要（TL;DR）

1. **矛盾的机制学确诊**：系统的空间真理源其实**已经是事件流**（`world_events` 的 `move` 事件 + fold 推演"谁在哪"），场景钉只是写作时的**取景框**——两者的粒度错配才是病根：事件按**叙事时刻 t**（年/月/日）记账，钉按**章**记账，而文学转场发生在**正文位置**（第 500 字）这个三者中最细的轴上。三个轴互不通译。
2. **"识别推门进屋"的能力其实已经存在，只是用途错位**：`LOCATION_JUMP_VERBS` 11 个转场动词+地点名紧邻判定（scene_visibility.py:212-230）能识别"走进明姐家"——但它挂在 ghost_guard 的 location_jump shadow 检上，是**守门员（报警）不是导航员（换景）**。`change_detector` 的 `scene_shift` 信号 14 个词全是**时间跳变词**（"第二天/三天后/与此同时"），零室内转场动作词，且该信号只驱动意图反推、不驱动任何空间状态（change_detector.py:96-106）。
3. **没有沉睡的 scenes 表**（models/world.py 12 表全查无 scenes/scene_segments；_deprecated 里的"场景"只是措辞），但存在四件半成品资产可直接复用：move 事件、11 转场动词表、scene_scope_ids 树闭包口径、onstage"提及即在场"补丁。
4. **三设想裁定**：**设想 A（隐式转场）推荐为主干，但必须做成"光标局部派生视图"而非"漂移状态机"**（按光标向前扫最近命中=无状态计算，删改回滚天然正确）；设想 B（节拍绑定场景）**不推荐**——与第一期结论正面冲突（节拍是消耗品/大纲是自由散文红线）；设想 C（显式分割线）降级为 A 的**纠偏 UI**（细纲胶囊 TipTap 先例可参照，但 500 字三打标记的心流成本高于现状手动换钉）。
5. **红队三问全部有解但都不是顺手活**：finish 分场回查技术上顺（run_reality_check 已是 (t, loc) 参数化纯函数）但知识视图需按场切分+场次时间戳；随身物品是真缺口（onstage 道具"提及即在场"——上一场提过的工具包换场后即出册，模型不能写"从包里掏扳手"）；缓存震荡有天然 4s 停顿节流兜底但需滞回设计防 A↔B 抖动。
6. **建议分期**：P0 转场感知进感知带（纯检测零状态，先攒识别准确率数据）→ P1 active_scene 光标派生视图（钉语义从「本章地点」升维为「显式锚」，识别做锚间自动桥）→ P2 随行物+finish 分场回查。

---

## 1. 场景钉的全生命周期与消费闭环

### 1.1 数据面与写入链

- 列定义：`backend/models/narrative.py:126`——`scene_location_id = Column(UUID, ForeignKey("world_locations.id", ondelete="SET NULL"), nullable=True)`，**章级单值**，地点被删时置空。
- 写入唯一入口：`PUT /chapters/{id}`（schemas/chapter.py:44/77 两处 Optional[UUID]；routes/chapters.py:102 exclude_unset 部分更新）；前端 `useWorldSlice.setScenePin`（useWorldSlice.ts:111-114 → world.api.ts:374-379）。无任何自动写入点——**钉是纯手动字段，从出生起就没有"自动跟随正文"的通路**。
- 读取消费全清单（后端 12 处 + 前端 3 文件）：

| # | 消费点 | 用途 | 章内转场受害面 |
|---|---|---|---|
| 1 | world_bridge.py:383-405 | 在场提权（scene_scope=钉+祖先；死者排除；排序键在场→事态→重要度） | 人到明姐家后 fold 推演位置仍在维修棚→明姐不进在场集 |
| 2 | knowledge_plane.py:158,446 | 场景身份块「本章场景：X（作者钉定）」+场景恒选集 | 整章 prompt 头部宣称错误场景 |
| 3 | knowledge_plane.py:701 | **前缀冻结缓存签名第 4 元** | （见 §1.2） |
| 4 | orchestrator.py:233-236 | presence_fingerprint(loc, t) → dock stage 签名 | （见 §1.2） |
| 5 | dock_generator.py:501 → onstage_projection(:119-227) | 在册白名单（T3）+场景行+anchor_ref 坐标系 | 换场后整册过时 |
| 6 | stitch.py:188-213 | location_jump 闭包：合法=钉**自身+祖先+全部后裔**（保守裁决「建筑内走到下属房间算合法」），其余世界地点名为候选 | 钉维修棚→「走进明姐家」被当穿越候选 |
| 7 | scene_slice.py:219 | 切片条「脚下」+pinned 徽标 | 显示陈旧地点 |
| 8 | settle_finish.py:88-99 → reality_check.py:97-101 | **完稿现实校验基准 (t, loc) 单点** | （红队问题 1，§4.1） |
| 9 | routes/world.py:1057 | state-for-chapter 推演 | 同 1 |
| 10 | schemas/world.py:291 | slice.scene.pinned 标志 | — |
| 11-12 | database.py:651（迁移）/FK 约束 | — | — |
| F1-3 | WorldSceneSlice.vue / useWorldSlice.ts / world.api.ts | 选地点钉/换/取消 | 唯一 UI |

### 1.2 写作中途换钉，各缓存的响应与时延（实测链路推演）

作者在 WorldSceneSlice 点「换地方」后：

| 缓存层 | 失效机制 | 时延 | 证据 |
|---|---|---|---|
| **dock 三键缓存** | stage 签名=presence_fingerprint=loc:t（dock_generator.py:230-237）+DOCK_PIPELINE_VERSION（orchestrator.py:400）——三键之一变即失配 | **最慢：下一次停顿心跳**（paused_ms≥4000+光标段尾才激活 dock，orchestrator.py:340-343）。活跃心跳期间旧零件照常上屏（_extract_dock_parts 只按 ver 过滤不管 loc）；Tab force_refresh 可立即 | orchestrator.py:404-412 |
| **前缀冻结缓存** | 签名第 4 元（knowledge_plane.py:701） | **即时**：下一次任何 bundle 装配（每次 stitch/preview/finish 现读）失效重算，纯 CPU 无 LLM | knowledge_plane.py:626-632 |
| **world fold** | **根本没有缓存**——fold 是纯查询每次现算（fold.py:34「纯函数式消费…同输入同输出」，无任何 memo） | 即时 | fold.py:44-80 |
| **前端切片** | setScenePin 后 `{silent:true}` 立即重取（useWorldSlice.ts:72-92） | 即时 | — |
| **心跳 world_version** | 四表 max(updated_at)+events 计数（world_repository.py:591-623）——**换钉不改世界表，不 bump** | 不适用（钉是章表字段） | — |

结论：**换钉本身没有缓存破损问题——三签名/fold/切片全部正确联动**。瓶颈不是缓存而是 dock 只在停顿档激活：换钉后最长 4s+的窗口里卡舱仍供旧场景零件。这为 §3 设想 A 提供了一个重要前提：**只要 active_scene 能进入 presence_fingerprint，全部既有失效链路原样复用，零新缓存设施**。

---

## 2. 章内场次基础设施的沉睡资产盘点

### 2.1 不存在的：scenes 表

models/world.py 全部 12 张表：WorldEvent / WorldEventEdge / WorldIntent / WorldDepiction / WorldDigestSection / WorldLocation / WorldEntity / WorldMapLayer / WorldMapStroke / WorldRelation / WorldEventCandidate / WorldModelORM——**无 scenes、无 scene_segments、无任何场次实体**。`_deprecated/bsadf/` 里的"场景"（slot_builder.py:111「机甲仓库场景」等）只是情节语境措辞，不是空间场次资产。

### 2.2 已存在的空间事实源：move 事件 + fold

- 事件模板 `move`：「角色从 A 地到 B 地（**沿 path 弧长插值在途位置**）」，requiredPayloadFields=[character_ids, from_location_id, to_location_id, path]（frontend/src/features/world/engine/eventTemplates.ts:32-40）——**章内动态空间的世界观早已建模**：fold 推演能给出"在途（进度 40%）"这类连续位置（world_bridge.py:167-188 dynamic_state_text）。
- 但两个缺口使其无法充当写作时取景框：①**记账轴错配**——事件挂叙事时刻 t（年/月/日），作者不会为"推门进屋"记一条 move（速记 Alt+N 的成本远高于打一句话）；②**无正文位置语义**——fold 知道林尘 14 时在明姐家，不知道"正文第 500 字"。
- 结论：事件系统是**宏观空间真理**（谁最终在哪），不是**微观取景**（此刻写的是哪场）。两者本就该是两层。

### 2.3 识别"推门进屋"的现有能力与用途错位

- **LOCATION_JUMP_VERBS**（scene_visibility.py:212-215）：`回到/来到/走进/走入/进入/踏入/迈进/抵达/赶回/赶到/前往` 11 词 + ≤2 字填充紧邻（"走进了北岸"），判据=作用域外**已知地点名**×动宾紧邻 + jieba 边界复核 + 闪回豁免（:233-274）。**这套判定换个方向就是转场识别器**——当前挂在 ghost_guard location_jump（shadow，只报警）与 stitch 闭包计算上。
- **change_detector 的 scene_shift**（change_detector.py:66-69, 96-106）：词表 14 词**全是时间跳变/叙事单位词**（第二天、次日、三天后、一周后、回到、与此同时、另一边、不久、随后、后来、那天晚上、清晨、黄昏、入夜）；判定=**当前段落首句前 40 字**子串命中，severity 0.6。它识别不出"推门进屋"的原因有三层：词表语义定位是"时间/章节节拍切换"而非"空间位移"；首句前 40 字窗太窄；即便命中，**信号也只汇入 aggregate_severity 触发意图反推**（orchestrator.py:307-332），不写任何空间状态。09-09 意图 11 分钟滞后事故的根因之一正是"室内转场不在词表"（档案在案）。
- **scene_hint.py 的命名撞车警示**：`detect_scene_type` 只有两档 dialogue/general（对话占比 >0.35，scene_hint.py:46-78），职责是文风样本场景匹配（P5 C2）——**与空间场景零关系**。任何新设计不得复用这个名字。

### 2.4 其余可复用半成品

- `scene_scope_ids`（location_tree.py:100-111）：自身+祖先闭包口径；location_jump 附加后裔（保守不误报）。树闭包是"钉粒度过宽/过窄"问题的既有缓解器。
- `onstage_projection` 的**"提及即在场"**（dock_generator.py:126-131 docstring：「物件=当前段落提及的资产（**世界 fold 不携带资产位置——提及即在场**）」；人物=钉作用域存活∪当前段提及）——这是系统对"空间真相不完整"的现行补丁，也是红队问题 2 的现状答案（§4.2）。
- 细纲胶囊 `OutlineNoteNode`（TipTap 自定义节点+双端锚定+存盘剥除契约）——设想 C 的工程形态先例。
- `encounters`（切片条相遇=此刻同地角色组）：已有"同地"计算面。
- 意图衰老闸先例 `INTENT_STALE_CHARS`（正文推进 100 字即弃旧意图）——转场检测若做成状态，同款"正文推进即过期"纪律可直接套用。

---

## 3. 三种设想的穿透审查

### 3.1 设想 A：正文标记驱动 / 隐式转场——**推荐主干，但必须做成"派生视图"而非"漂移状态机"**

**原料齐全度（全部现成）**：转场动词表✓（11 词起步，需扩"推门/跨进/踱进/拐进"类）；地点名册✓（bundle.locations + 别名，含内部构造全路径）；边界判据✓（scene_visibility._name_in_text 的 jieba token 边界复核，防嵌词误命中）；缓存通道✓（active_loc 进 presence_fingerprint 即走 §1.2 全部既有失效链，**零新缓存设施**）；心跳供料✓（recent_text 500 字窗已在请求体）。

**核心难题与解法——漂移状态机的回滚陷阱**：朴素实现（"检测到转场→更新 active_scene_loc_id 状态"）在删改面前全是坑：作者删掉"走进明姐家"那句要不要回退？分叉改写后"最新命中点"在哪？FIM 中插时光标在两段之间听谁的？

**解法是把状态变派生**：`active_scene(chapter, cursor_pos) = 从光标处向前扫描，最近一次「转场动词×名册地点名」命中 → 该地点；无命中 → 回退显式钉（或本章锚）`。无状态纯函数，每次心跳现算——删改回滚天然正确（重算即得）、分叉天然正确（光标所在分支）、FIM 天然正确（光标局部）。这与 world_model「派生活性」哲学同构（规范化文本是画布子串=活，删改即过期），与意图衰老闸同族。

**假阳/假阴分析（专名约束是天然防漂闸）**：
- 假阴：「走进那间屋子」（无专名）识别不到 → 保持旧场景。无害——取景框滞后半场，比错漂强；
- 假阳：「回到过去」（比喻/回忆）→ 目标"过去"不在名册 → 命中失败保持原景。**目标必须是名册地点**这一约束把漂移宇宙限定在作者已建模的空间里；
- 残余风险：真地点名的回忆性提及（"他想起明姐家的脸盆"）+转场动词邻接（"回到明姐家的记忆里"）——需要闪回豁免词表（FLASHBACK_WORDS 已有，scene_visibility.py:271-273 同款可直接复用）。

**复杂度**：后端一个纯函数（光标窗扫描，复用三件现成判据）+ presence_fingerprint 换料 + 前端零改动。**中低**。
**断裂面**：①「当前场景」语义=写作现场（光标处）而非"全章"——回读模式（光标在章首）场景=开场地，这是**正确行为**但需要在切片条如实标注「按光标推断」；②finish/审阅类全章消费不能用它（见 §4.1）；③钉与识别的优先级需拍板（建议：钉=显式锚/开场地，识别=锚之后的自动桥；取消钉=纯识别）。
**创作者无感化：最优**——零 UI、零输入、零新概念。

### 3.2 设想 B：大纲节拍绑定场景——**不推荐（与第一期结论正面冲突）**

- 大纲是**自由散文**，无结构化槽位——intent_repository.py:253-255 明文「chapters.outline_text 大纲节拍（**自由文本**，作者逐拍编辑的事实源…）」，第一期红线同源（chapter-planning-spine.md:45）。往大纲行塞地点槽=把自由文本结构化，违背其存在理由，且 14 个消费面（大纲板整页/向导/loader embedding/refine/审阅，第一期 §3.2 清单）全部外溢。
- **粒度错配**：500 字三场 vs 大纲一行一拍——三场很可能同在一行（「林尘修好发电机后去明姐家蹭饭」）。
- 跃迁时机依赖节拍 hit（text_match 2/3 命中）——hit 是「写到了」的**事后**判定，滞后半拍；且 hit 宁漏勿误（改写不命中）→ 场景滞留旧地。
- 复杂度最高（大纲行地点抽取需 LLM 或格式约定）、破坏性最大。**三维度全劣，出局。**

### 3.3 设想 C：显式场次分割线——**降级为 A 的纠偏 UI，不独立成案**

- 工程先例成熟：细纲胶囊 OutlineNoteNode（TipTap 自定义节点+`data-outline-note` 存盘剥除+双端锚定扩写）证明「正文内元标记」这条路走得通，撤销天然正确（删标记即回退）、识别零假阳、还天然给 finish 分场回查提供现成边界。
- 但**心流成本高于现状**：500 字三场=作者打三次标记——相比现在去侧栏点一下「换地方」没有省事，只是把动作搬进正文；且标记混入文学文本，阅读/导出依赖可靠剥除。
- 作者主权与无感性不可兼得：C 的每一分可靠性都来自要求作者多做一个动作。
- **定位**：作为 A 的纠偏层——识别错了（假阴/假阳）时作者插入一个显式场次标记强制锚定（或一键「钉到这里」，走既有 setScenePin 链）。独立成案不成立。

### 3.4 三维度对比总表

| 维度 | A 隐式转场（光标派生版） | B 节拍绑定 | C 显式分割线 |
|---|---|---|---|
| 实现复杂度 | 中低（1 纯函数+签名换料，前端零改动） | 最高（大纲结构化+14 消费面外溢） | 中（TipTap 节点+心跳透传+剥除契约） |
| 破坏性断裂面 | 低（钉语义升维；全章类消费另议） | 高（违背自由散文红线+粒度错配+hit 滞后） | 低（但正文混元数据） |
| 创作者无感化 | 最优（零输入） | 差（写大纲要带地点） | 差（每场一标记） |
| 删改回滚正确性 | 派生重算=天然正确 | 依赖 hit 重判 | 删标记即回退=正确 |
| 可复用资产 | 动词表/名册/边界判据/缓存链全现成 | 几乎全新 | OutlineNoteNode 全套先例 |

---

## 4. 对抗性红队推演（动态转场的新灾难清单）

### 4.1 完稿体检（finish）的现实校验基准

**现状**：`run_reality_check(db, book_id, t, knowledge_view, scene_location_id)`（reality_check.py:97-101）以**单点 (t, loc)** 回查 fresh fold——知识视图的 `present_names/dead_names` 是整章单一论断集，t 取本章叙事锚。章=一个时空单点的假设 baked in。

**动态转场后**：技术上分场回查是直的——函数已参数化，按场次分段各调一次即可；真正的深水有二：①**知识视图按场切分**——present_names 来自前缀在场块（整章口径），需改为按场提取；②**场次时间戳**——章内时间也在流动（晚饭前→晚饭后），一场一 fold 需要每场一个 t，而正文没有时间轴刻度（叙事锚只有一个）。短章可行（场景区间→最近时间提示），但这是新数据缺口，不是参数化能解决的。**缓解**：finish 先保持整章基准（用章末场景/叙事锚），分场回查列为 P2 且只在作者标记场次的章启用。

### 4.2 跨场景随身物品（工具包问题）

**现状确诊**：onstage 的物件在册判据=「当前段落提及」（dock_generator.py:172-183——世界 fold **不携带资产位置**，提及即在册）。后果：上一场林尘提过工具包 → 换到明姐家段，当前段没提 → 工具包出册 → T3 上手件约束下（「上手物件与出场人物只从『本场在册』或本章正文已出现者里取」，adaptive_prompts.py:1469-1470——注意「**本章正文已出现**」这个豁免口子实际已经存在！）模型生发"从包里掏出扳手"是否违规取决于该约束的执法面（dock _violates 按何口径）。**"本章已出现"豁免意味着随身物问题在 prompt 层已有半解**，但 onstage 在册坐标系（anchor_ref 坐标）不含它们——道具特写槽（prop）指认坐标系里没有工具包。
**方案谱系**（都要真设计）：①便宜版——onstage props 提及窗从「当前段」扩到「本章已写」（会重新引入宽白名单污染=背景里的恶果 1，需配合物质性三档消化）；②事件版——move 事件 payload 扩 carried 资产（schema 现成可扩，但依赖作者记账）；③启发式——「上手即随行」：上一场被 anchor_ref 指认过的 prop 进随行集，直到显式"放下/交出"。建议 ③ 起步（纯算法、贴作者行为语义）。

### 4.3 缓存震荡雪崩（场景边缘反复删改）

**攻击面**：active_loc 进 presence_fingerprint 后，作者在转场句边缘反复删改（写"走进明姐家"→删→改写）→ active_loc A↔B 抖动 → 三连锁：①dock 整舱重算（LLM 大头）；②前缀冻结签名反复失效（纯 CPU，可忍）；③location_jump 闭包/穿越闸口径反复翻转。
**天然防线盘点**（已存在，非新增）：dock 只在**停顿档**激活（4s 节流天然限频）+ `_sync_inflight` 在飞去重（orchestrator.py:253-254）+ 缓存三键全同才命中（抖动=必失配但受停顿门限频）+ force_refresh 才立即。**实际震荡频率上限=停顿心跳频率**，不是每次键击。
**仍需新增的滞回**：①光标派生本身天然带缓冲（删掉转场句后 active 立即回旧场——重算结果与抖动前相同，缓存内容级等价可命中？不能——fingerprint 不同键必失配，但**算两次的钱**封顶）；②建议加「转场点距光标 >N 字才切换」的粘滞窗（作者在转场句上编辑时场景保持旧值），一行判据即可。

### 4.4 附加发现：转场句×半句门禁的相互作用

转场句常以半句形态被书写（「他推开门，」——`ends_mid_sentence` 判 mid → dock 闭嘴不生发，heartbeat.py:94-98）。也就是说**作者最需要"新场景第一屏"零件的时机恰好被句子级门禁挡住**（写完这句才有零件）。这不是动态转场引入的新问题（现状即如此），但 A 方案落地后会更显眼（场景已切换、舱却因半句静默）。记录为设计约束：新场景首屏零件的生发时机需要与门禁协调（例如转场句后首个句号完成视为高优先停顿），P1 施工时验证。

---

## 5. 分期建议

- **P0（零风险感知先行）**：转场检测进感知带——纯检测零状态：复用 11 动词+名册+闪回豁免扫 recent_text，命中即 canon_hints 提醒「看起来进新场景了，要换钉吗？」，点击走既有 setScenePin 链（§1.2 已证缓存全通）。**先攒识别准确率数据再谈自动化**（与第一期「先埋点再重构」纪律同源）。
- **P1（设想 A 核心）**：`active_scene(chapter, cursor)` 光标派生纯函数 → presence_fingerprint/场景身份块/onstage/location_jump 闭包换料；钉语义升维为「显式锚/开场地」（识别做锚之后的自动桥）。滞回窗+「按光标推断」切片条标注同批。
- **P2（红队补课）**：随行物（「上手即随行」启发式起步）+ finish 分场回查（仅显式标记场次的章启用）+ 转场句首屏零件时机协调。
- **不做**：B（三维度全劣）；C 独立成案（降级为 P1 的纠偏 UI，可后置）。

---

## 附录：证据索引

- 场景钉消费：models/narrative.py:126 · world_bridge.py:381-405 · knowledge_plane.py:158,446,701 · orchestrator.py:227-238,400-412 · dock_generator.py:501,119-227 · stitch.py:185-213 · scene_slice.py:219 · settle_finish.py:88-99 · reality_check.py:85-140 · schemas/world.py:291 · routes/world.py:1057
- 缓存响应：dock_generator.py:230-237（presence_fingerprint）· orchestrator.py:340-343,404-412（停顿档门+三键）· knowledge_plane.py:626-632（前缀签名）· fold.py:34-80（无缓存纯查询）· useWorldSlice.ts:72-92（silent 重取）
- 沉睡资产：models/world.py（12 表无 scenes）· eventTemplates.ts:32-40（move/path 弧长）· change_detector.py:66-69,96-106（scene_shift 词表+首句 40 字窗）· scene_visibility.py:212-274（11 动词+填充窗+闪回豁免）· scene_hint.py:46-78（dialogue/general 两档）· location_tree.py:100-111（树闭包）· dock_generator.py:126-131（提及即在场）· OutlineNoteNode 先例
- 交叉引用：第一期 docs/spine-outline-merge-feasibility.md（节拍消耗品/大纲自由散文红线/三签名纪律）；09-09 dock literary diagnosis 档案（scene_shift 词表不含室内转场的实证）
