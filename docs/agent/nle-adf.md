# NLE-ADF 3.0 自适应融合写作台（领域档案）

> 本文自 AGENTS.md 拆分而来（编辑本领域代码前必读）

前端默认且唯一的写作路径。核心理念：**作者永远在写，AI 在画布上柔性共生**——不预设拍划分、不跑整章管线前置；作者进章节打字即激活辅助层。与已归档 BS-ADF 步进模式的根本区别在此。施工/事故史见 `docs/incidents/nle-adf.md`。

设计文档唯一权威（本文不重复其内容）：章级谋篇 `docs/chapter-planning-spine.md`；上下文装配 `docs/knowledge-retrieval-plane.md`；约束治理 `docs/constraint-governance.md`；自动阅读与闭嘴 `docs/auto-read-quiet-learning.md`；spine×大纲合流 `docs/spine-outline-merge-feasibility.md`；AI 视角面板 `docs/ai-view-panel-guide.md` + `docs/ai-view-briefing-feasibility.md` + `docs/design/ux-redesign/09-ai-view-redesign.md`；写作台布局 `docs/design/ux-redesign/08-writing-desk-total-redesign.md`；deai 挂点 `docs/deai-integration.md`；字数硬闸门全文见主指南「关键质量护栏」节。

## 端点总表

| 端点 | 用途 | 备注 |
|------|------|------|
| `POST /adaptive/heartbeat` | 心跳感知，响应携 dock_parts/direction_cards/canon_hints/意图信息 | 活跃防抖 3s / 停顿 4s+光标段尾 |
| `POST /adaptive/stitch-ghost` | 幽灵草稿（SSE 打字机） | mode 五档：stitch/continue/burst/open/outline |
| `POST /adaptive/settle` | 手动沉淀（Ctrl+Enter，纯手动无自动门槛） | 另触发 event_scout 候选事件 |
| `POST /adaptive/finish` | 完稿审计 | 报告残句条目可走 fix-sentence |
| `POST /adaptive/fix-sentence` | 残句定点修复 | 只产修复句不改正文，采纳才替换 |
| `GET /adaptive/model` | 世界模型快照 | 副驾「调试」tab（`InspectorPanel.vue`） |
| `GET/PATCH /adaptive/spine` | 章级软脉络 | `chapters.spine` JSONB，部分合并；2s 防抖自动保存 |
| `POST /adaptive/spine-suggest` | 谋篇建议 | 1×creative 建议不落库（D-4 红线） |
| `GET /adaptive/active-beats` | 活跃节拍微标数据 | 与 stitch/dock 同一份 outline_nearby 计算，纯算法，前端防抖 800ms 拉取 |
| `GET /adaptive/context-preview` | AI 所见预览 | 与 stitch 装配同源（见「上下文装配」节） |
| `POST /adaptive/event` + `GET /adaptive/events/summary` | 协作埋点 | 本地 `data/collab_events.jsonl`，零上报；book_id 服务端解析防伪 |
| `POST /adaptive/auto-read` | 切章自动阅读刚离开的章 | 哈希幂等 + 同章 300s 间隔 + 每书每日 30 次预算闸 `services/adaptive/read_budget.py` |
| `POST /adaptive/read-entities` | 全书向导阶段 A 认人 | 只产草稿不落库，作者勾选才建 |
| `POST /adaptive/reader-feedback` | 读者反馈（按需触发） | 检查分区消费 |
| `GET /world/context-card` | 情境浮卡 | 选中 1-12 字或点击 @/# 提及；解析不到静默缺席 |
| `POST /world/parse-event` | 世界速记（Alt+N） | 只产草稿绝不落库，作者过目入账 + 6 秒撤销胶囊 |

⚠ 端点以代码为准：**不存在** perceive/detect-branch/plan-suggest——感知与规划建议均由心跳响应携带。

## 状态机与激活

- **双轴状态机**（`useGenerationSession.ts`）：`authorLane`（idle→composing→ghostStitching→settling，前台主线）+ `aiLane`（dormant→perceiving/suggesting/assisting/digesting/analyzing，后台）。两轴并行不阻塞，与旧 `stage` 单轴（legacy step）共存。
- **激活**：作者进章节打字 ≥4 字 → `enterAdaptive(chapterId)` 置 `authorLane=composing`（不跑 startBeat 管线）。辅助层（`useAdaptiveAssist.ts`）据此挂载。
- **Spark Dock 解耦**：gate 从 stage 解绑，`authorLane=composing` 即激活（零件源从拍卡改为心跳供给 + 章级兜底）。
- 所有辅助触发全部柔性可忽略。

## 感知常驻（用户拍板「无论切到哪都不停感知，除非关闭应用」）

- 切页只 `detach`（解除编辑器监听/中止需活编辑器的 stitch SSE），pending 感知计时器照发。
- 卸载后心跳用 `_lastCtx` 上下文快照（带章号防串章，切章后旧快照作废），结果进世界模型缓存，回台秒弹可用。
- 心跳响应带**章节纪元守卫**：发送后切章 = 旧章感知产物整包丢弃（防错章零件污染秒弹 + 生发档让路压制新章刷新的窗口）。
- 全量停机只随应用关闭发生。

## 心跳与挂件铁律（`/adaptive/heartbeat`）

后端 orchestrator 跑感知决策（B7 起方向权重退役——salience 热层影子 trace-only + dock 具名提示单车道，纯算法 0 LLM）+ 组件（意图反推 0-1 LLM / 未来推测 / 挂件生发 / Canon 感知）。

### 挂件功能槽位化（导师裁决：内容分类学→功能分类学）

作者必须能看懂「选这枚会发生什么」。四槽位（五向 direction 标签系已退役，仅存分析面）：

- **landing**：接着写 = 物理落点，恒居首位，固定副行「接着刚才那句写」。
- **toward_beat**：通往大纲就近节拍第一步，副行 note=节拍原文「通往「…」」。
- **echo**：呼应前情/读者期待。模型报 `echo_ref` 序号、后端回查素材原文拼 note「读者在等：…」「呼应前情：…」。**note 一律后端拼装不经 LLM**（模型自由创作出处 = 编造风险铁律）。
- **ambient**：纯氛围，副行留白——留白本身是信息。

槽位拿不到出处即降级 ambient（标签必须承载真实出处否则不标）。`_finalize_parts` 纯函数规整 + 槽位序排序（对拍 `test_dock_slots.py`）。前端 SparkDock 两级层级（主行画面 / 副行 10px 灰功能出处 ▸/⚑/◆）+ 槽位排序；舱顶自解释行「卡住了？点一个画面接着写」。

### 素材纪律

期待/伏笔账本与前情回响素材块带 [N] 序号供 echo_ref 引用（dock prompt 的 echo 槽位分节按 `has_echo_mat` 编译：无及格素材换「允许零呼应」柔性变体，有素材逐字节零变化）：

1. **文流第一**：与当前段最后一句直接衔接。
2. **大纲节拍降位**「几步外目的地」：只给通往它的第一步、绝不呈现节拍场面（对白显式禁）。
3. **场景锚定**（导师裁决两分法）：**氛围件**（光线/灰尘/远景/声响）自由生发不算发明；**上手件**（人物握拿放捡掏开的物件）必须有出处——判据是「作者接了它欠不欠连续性债」。
4. 禁提前搬后段剧情。

**节拍保全检验**（唯一主判据，替换旧「对白禁令」）：写进正文后大纲那一拍还完整可写吗——写不坏节拍的才是第一步；节拍事件与紧接反应（被打断/惊）都是作者的，节拍内其他人物只许「在来的路上」不许「已到达」。**节拍>推测**（冲突时以节拍为准只取情绪）。**第一优先=物理落点**（1 枚必须是作者最后一句的物理落点：抽象感慨→人物主动小动作）。

注入**大纲就近节拍**（`outline_nearby.py` 共享判据；**未来推测组件同源注入**，推测输出带 `stage` 枚举 now/approach/beat/after）。**接缝裁剪** `_prebeat_projections` 把 beat/after 挡在挂件取材池外（切断供给>命令拒绝），dock 缓存签名基于过滤后集合（对拍 `test_dock_prebeat.py`）。**陈词嗅探** `CAMERA_STOCK_PHRASES`（目光失焦/轮廓模糊族不进菜单）。stitch 零件落地「正文事实最高优先」改造出口。

### 停顿档同步钳制

- `SYNC_COMPONENT_TIMEOUT_S=12s`（`orchestrator._activate_sync` wait_for 超时放弃本轮产出、下轮重算）。
- `_sync_inflight` 在飞去重（防慢端点下两个停顿心跳并发双烧 LLM）。
- ⚠ 实测边界：mimo-v2.5 对「节拍对白」禁令三连不服从——prompt 杠杆已尽，归模型 A/B 变量；prompt 已加「优先从当前段落生发不得整句照搬」（mimo 会把推测逐条压缩成挂件）。

### 卡片舱入口 = Tab 唯一（用户拍板）

- 自动弹出全线退役：`useSparkDock.SPARK_DOCK_AUTO_POPUP=false` 总开关封存停顿秒弹/响应侧自动弹/幽灵落定回弹三路（置回 true 整体恢复）。
- Tab 恒**强制重算**唤醒（`force_refresh=true` 跳过后端缓存命中，每次新鲜批次；连按由 `_summonInFlight` 合并）。
- **Tab 重算失败可见化**：本地端点连接错误快速失败不重试（client.py 本地豁免）、重算失败舱内出朱色报错行、命中缓存旧件明示卡龄——失败不再静默。停顿心跳照发（感知/走向卡/保鲜不中断），只是不再自动弹舱。
- **思考指示器**：光标处薄荷绿脉冲点（`ThinkingIndicator`）只随显式动作亮（Space 续写/Tab 点名含在飞挂起期/burst/点火/细纲扩写）；停顿全程光标零反馈、后台感知保持安静（waiting 态已整体删除，对拍 heartbeatSeam 接缝四）。

### 句子级闸门（闭嘴到端）

- 段落停在半句（`paragraph_source.ends_mid_sentence`）时不生发、不回缓存旧件，且响应带 `dock_muted=true`——前端据此清舱收卡。空段=段界不判半句（勿回退）。
- 写完句子是 Space 续写的活；Tab 显式点名（`summoned`）豁免（作者主权）。

### 感知组件杂项

- **canon_watch 出场判定**：实体名字挂在 `ent.character.name` 访问链（旧 ChapterEntity 与 world 适配器同）——**勿再读顶层 `.name`**（恒空）。
- **矛盾检测 `_find_contradiction`**（旧裸子串 `_has_contradiction` 已废）：只留**死活对**（活着×已死/死了/阵亡/牺牲）；≥2 字 + jieba token 边界匹配（连续 token 拼接恰为该词，杜绝嵌词；jieba 缺失退子串柔性红线）；返回 (设定侧词, 正文侧词) 带方向，conflict 带 `pair` 字段；卡片文案点名矛盾「正文写「X」，设定是「Y」——」。对拍 `test_contradiction_pairs.py`（10 项：旧误报全消/真矛盾命中/双向/嵌词不中/pair 贯通）。

## 在场制 × 分镜组 × 临时通行证

- **在场投影 `onstage_projection`**：世界书+场景钉压缩出「本场在册」实体/资产白名单。三档物质性：T1 氛围件自由生发 / T2 上手件须指源 / T3 在册白名单——**代码只执法 T3**。dock prompt 按在册坐标系生发。
- dock 缓存键并入 `presence_fingerprint`（场景钉+叙事时刻）+ `DOCK_PIPELINE_VERSION` 版本盐（现值 `v2.3_suffix300_20260913`；**规则大改递增即全量缓存失效**）+ 实时 word_count（上下文变即重算）。
- **对白分镜组**：末句对白优先（末行整行以开引号起即判对白模板——行首判据天然排除名言）。
  - reply = 受话人接话微前兆（固定 note，锚对白本身无出处义务）。
  - prop = 在场道具/人物特写（`anchor_ref` 指认在册序号、后端回查拼 note，指认失败降级 ambient——echo_ref 同防御哲学）。
- **T3 在场边界影子检 `dock-onstage-boundary`**（registry 登记 shadow 只落台账）：挂件出现非在册名 × 上手动词框架即疑点，正文已提及名豁免。
- **涌现角色临时通行证（Guest Pass）**：正文高频未建档人名入册为素材——jieba 提名 + 子串计数 ≥2 双重核验（分词漂移免疫）、≤2 名封顶、泛称亲属词停用。
- **别名归一拦截 `_is_alias_or_ambiguous`**：阿X/小X/老X 昵称与 X叔/X姐 类尊称的核心字配已知名**尾字**（王叔→「王」命中「工头老王」、不会错绑「王阿婆」——尾字婆）。唯一命中归主不发证、多命中（林尘/周尘并存的阿尘）歧义同样压制、零命中照发（明姐流程不受染——「明」不命中任何尾字）。对拍 `test_dock_onstage.py` TestAliasCanonicalizer。
- 心跳响应带 `onstage_guests`，前端出「录入档案」直达入口（建档往返：模块单例存光标 + pos 钳位 + 指纹失配退文档尾）。
- **意图衰老闸 `INTENT_STALE_CHARS=100`**：反推后正文推进超 100 字未刷新即不绑旧意图。
- 对拍：`test_dock_onstage.py` / `test_subject_lock.py`。

## 续写（Space → `/adaptive/stitch-ghost`）

有零件=缝合续写 / 无零件=顺句续写。SSE 打字机灌幽灵草稿，复用 `useGhostDraft`。S2 起四模式 prompt 均注入文风：正面画像块 + 作者笔迹示范 few-shot（`style/retrieval.py` 按当前上下文检索 k≤2，无样本零变化）。

- **stitch 追加式契约（勿回退拼回）**：幽灵纯追加在光标后、原句已在画布——prompt 只要求从断点直接续（禁复读原句/不重说断点附近的词）；路由侧「拼回」已废除，改**复读剥离** `_strip_fragment_prefix`（等价类前缀匹配，语义变体不剥）。模型复读原句必致屏幕重复。
- **接缝两护**：
  1. **压缩改写首句豁免**——压缩模型看不到作者断点，会把补完断点的首句当修饰删除致半句悬空。`_split_first_sentence` 首句物理摘出、只压缩剩余、产物=首句+压缩稿；压缩 prompt 带断点尾句坐标（首句超 target×0.6 退整稿路径）。
  2. **半句断点尾缀复读 `_strip_fragment_tail_repeat`**——模型从悬空处重启复读的是原句**尾缀**非整句。断点非句末且产出以尾缀开头即剥；句末断点不开此闸（同词开头是新句复用词汇不是复读）；切割点后标点保留。对拍 `test_stitch_gates.py` §6。
- **中插桥接（FIM）**：骨架跳写、光标停在上下文之间时请求带 `suffix_anchor`（**光标后 ≤300 字后文锚**；前端 `_suffixAfterCursor` 取 ≤300 带、后端 dock 入口与两 prompt 编译器同口径 `[:300]`；心跳与 stitch 双路上行）。prompt 注入双端边界与桥接铁律、桥接态断点改取光标前文；产出尾部接缝 `_normalize_bridge_seam` 归一（≤24 字最长重叠优先，归一在字数闸/返修环之前）；dock 侧 `dock-bridge-overlap` 闸拦「桥接机位与后文 ≥4 字重叠 = 提前写掉已写事实」。
- **心跳/挂件侧桥接取源 + 供给切断**：心跳 `recent_text` 桥接态改送光标前 ≤500 字窗口（`_anchorRecentText`，与 stitch fragment 分支同判据；`_lastCtx` 感知常驻快照同口径）。后端 `build_dock_generator_prompt` 桥接态（`is_bridge`）切断推测/方向猜测/就近节拍素材块——三者全以含后文的画布全文推导 = 后文剧透，供给切断>命令拒绝（`intent_guess` 在 dock_generator.run 消费前清零，含 note 拼装兜底）；空 suffix_anchor 逐字节零变化。对拍 `test_dock_prompt_compiler.py` TestBridgeForm + 前端 `heartbeatSeam.test.ts` 接缝三。
- **主体锁 + 白描封杀令**：单焦距主体守恒律 `pick_subject_lock` 三锁——物镜（prop/ambient 只写器物/环境自身物理感官，情绪不走人物走物件）/ 发话（landing/speaker 焦点钉发话者单人，其余人等下一笔）/ 静音（reply 只写受话者开腔前的缓冲）；自定义输入不锁。`render_system_blocks` 末位「白描契约与假感官封杀令」块（stitch/continue 专属、空串拼接零变化，措辞用户逐字拍板）。
- **幽灵死亡收割 `reapGhostIfDead`（勿删）**：作者退格/选删亲手删光幽灵（而非 Esc 蒸发）时 ghostActive 残留真值——僵尸态吃 Tab（结构闸「ghostActive 只吞不唤」）、禁 Space、卡 authorLane 在 ghostStitching、sticky 卡舱恢复等不到落沿。RichTextEditor onUpdate 每个文档事务后扫一次：状态说有幽灵而文档扫不到 ghostDraft 节点即按「作者亲手蒸发」收尾（埋 `ghost_discard` 供学习回流、不弹理由 toast 问第二遍）；部分删除/改词不触发（mark 存活走 ghostDirty 微调语义）。对拍 `__tests__/ghostReap.test.ts`。

## 细纲胶囊

- 入口：Alt+O / 输入 `[[` / 选中文本转换（`extensions/OutlineNoteNode.ts` + `OutlineNoteChip.vue`）。作者亲笔剧情速记以胶囊嵌在正文任意位置 →「落笔扩写」走 stitch-ghost mode=outline。
- 双端锚定：胶囊前 500 字 + 后 300 字；目标字数解析速记中「约N字」，clamp 100-800、缺省 400；×1.6 压缩重试 + ×1.5 句界截断硬闸门（闸门全文见主指南「关键质量护栏」节）。
- 扩写启动即塌缩为钉 ⚑ 可再扩写；**会话级，存盘剥除**（与幽灵同契约，`stripGhostDraftHtml` 一并剥 `[data-outline-note]`）。
- 编排经 `velluma:outline-expand` 事件解耦（`useAdaptiveAssist.requestExpandOutline`）。

## 章级谋篇（spine）

- `GET`/`PATCH /adaptive/spine`（`chapters.spine` JSONB，部分合并；2s 防抖自动保存）+ `POST /adaptive/spine-suggest`。
- **叙事引力流面板**（spine×大纲单轨合流，路径 C 见 `docs/spine-outline-merge-feasibility.md`）：🎯方向行（spine.intent 高亮锚）+ 锚点 chips + 📝情节节拍区（outline_text 迁入，InspectorPanel 旧大纲卡已删除）单卡连贯。**数据层双字段与 prompt 剂量位零改动**（分割边界=控件边界，maxlength 拦截整段粘贴进方向行）。
- 活跃节拍微标「▶ 续写正朝这拍走」= `GET /adaptive/active-beats`（与 stitch/dock **同一份** outline_nearby 计算，纯算法，防抖 800ms 拉取）。
- **强制冲刷**：`velluma:flush-planning` 事件——useAdaptiveAssist 的 summonParts/requestContinue 入口 dispatch → InspectorPanel 监听执行 `chapterSpine.flushNow()` + outline 500ms 防抖冲账；双保险=心跳上行本就携带 spine_intent/outline_text；节拍区 blur 也冲刷。
- OutlineView 全书大纲页编辑经 store 响应式回流（textarea 直绑 store 值，draft 仅记作者输入）。
- 走向卡 ⚑ 挂锚点（serves_anchor 写入/提取双侧代码闸）；pending 锚点关键词命中 → 纯算法进度判定进心跳；带 branch 的临近锚点置顶为硬提示卡（选向即决岔）；finish 报告附 spine_note（未兑现锚点仅提示不阻塞）。

## 意图感知

- **层2 意图三级源链**：**spine 打算短路**（confidence 0.9、0 LLM，作者写了打算反推直接让位，纠正即时生效）> **大纲转化**（0.85，卷首致辞过滤：引语/《》/超短指示行不当本章弧线）> **LLM 反推**（0.55/0.4 + 证据回查闸：arc 依据必须逐字出自正文，编造降信跌破 dock 消费阈 0.5）。
- **「不对」纠正手势**：打算 tab 意图行一句话修正落 spine + intent_correct 埋点；下次心跳带 spine_intent 触发层2短路 + dock 缓存签名 bust（纠完舱即换向）。
- dock toward_beat 无大纲节拍时由反推 next_direction 供料，note 后端拼装如实标「AI 猜的」（模型自由创作出处=编造风险铁律不变）。
- **线A stitch 意图兜底链**（assemble_stitch_context）：请求意图 → 大纲就近节拍 → 层2 inferred/baton，置信阈与 dock 同 0.5，纯 SELECT 不走 get_or_create 读路径，仅 stitch/continue 开（burst/outline/open 各有方向载体）。`build_continue_prompt` 按 `intent_source` 分档措辞：inferred「AI 猜的，对不上就忽略」/ baton「承接上一章」/ 目的地框逐字节零变化。
- **线B 意图画像**：反推 prompt 注入前几章 spine 意图轨迹 ≤5 条「第N章：…」——学作者写意图的粒度与口吻不抄内容；纠正量 ≥2 追加「宁答方向不明别硬编」保守指令。
- **线C 章首接力棒**：spine/大纲短路上移到正文体量闸之前——空章写了打算也立刻上桌；无材料且正文 <100 字时 previous_summary 确定性接管（source=baton / 0.6 / 零 LLM 不空猜）。dock 只消费 source==inferred，前端猜测行 v-if inferred——baton 对双侧天然隐身。

## 续写质感治理（治「太显式」）

1. prompt 侧意图块重框「几步之后的目的地」（不给节拍场面）+ recency_pin 在场名单重框「一致性校验资料，不是登场名单」。
2. **双轨生成契约** `texture_contract.pick_contract`——motion（动作推进，旧行为零变化）/ texture（停在当下细写）两档进 stitch prompt；槽位映射 landing/toward_beat→motion、echo/ambient→texture。
3. 输出侧代码闸见「约束治理」节 ghost_guard（beat_rush live+rewrite / cast_roll_call shadow）。
4. 质感密度可测量化进 fingerprint texture 键 + finish 质感样本候选（见文风领域）。

## 沉淀（`/adaptive/settle`）

- **纯手动** Ctrl+Enter，无自动字数门槛；抽涌现实体 + 可选落库（设定逆向生长）。
- 另触发 event_scout 抽候选事件进收件箱——**三重去重**（prompt 排除近 15 条已入账事件 + 归一化双向子串预筛 + pending 池幂等）。
- 收件箱**批量裁决**（逐条预览剔除 + 6s 复合撤销=删产物+reopen）；积压 >5 走心跳 canon_hints 的 `kind=world_inbox` 感知带提示；settle 完成 toast 直达收件箱。

## 完稿审计（`/adaptive/finish`）

残句/覆盖率/Canon 合规/整章审阅 + 记忆重索引 + 整章候选抽取 + **质感样本候选**——`most_textured_window` 挑本章质感最密段直投文风收件箱 `sample_candidate`/`texture_pick`，60 字头幂等去重，作者确认才入样本库。

## 系统自己去读

- 观察触发权交给系统：切章自动阅读刚离开的章（`POST /adaptive/auto-read`，内容哈希幂等 + 同章 300s 间隔 + 每书每日 30 次预算闸 `services/adaptive/read_budget.py`）。
- 世界页待确认抽屉「通读本书」全书向导：阶段 A 认人 `/adaptive/read-entities`（只产草稿不落库 → 作者勾选才建）→ 阶段 B 记事。
- 实体/地点创建服务端按（书+归一化名+类型）幂等。
- 候选池判重全书级归一化子串 + 转正前账本判重闸（命中标 `auto_reject=duplicate` 不建事件）；无叙事锚时候选显示「第 N 章」不伪造默认日期。

## 学着闭嘴（被拒学习）

- 唯一权威 `services/adaptive/quiet_learning.py`。
- 静音集合从行为派生不落库（候选裁决史 + hint_dismiss 埋点史）；`books.assist_mutes` 只存宽恕时间戳。
- 阈值纪律：裁决 ≥3 且零采纳才静音（一次肯定胜过三次否定）；安全类（泄露/矛盾）永不静音。
- 消费=event_scout 生成侧双闸 + 心跳感知带过滤；感知带提醒卡悬停 × 收起；静音清单在副驾收件箱可见可恢复。
- 幽灵蒸发理由条（Esc ≥30 字浮可选 chips，落 `ghost_discard_reason` 攒失败分类学）。

## 生成质量视野配比

- 续写窗 800 字 / burst·outline 1200 字。
- 意图块/点火只给大纲**就近一两拍**（`services/adaptive/outline_nearby.py` 共享判据，dock 挂件同源；防整章地图诱导冲章）。
- 滚动窗句界净截 `sentence_clean_tail`（`paragraph_source.py`，context-preview 同源）。

## 设定数据双向驱动（`settings_bundle.py`）

- 章级绑定 + 书级 Canon（[public]/[private]）+ 世界观，一次加载供所有 adaptive 端点共用。
- **世界设定层优先**（world_bridge）：世界页有实体时 bundle 的角色/资产/地点/关系切换为 world 数据 + 叙事时刻推演状态，无实体回退旧表。
- 写作中感知 + 后台 salience 显著性影子（B7 起取代方向权重规划）两个层面同时利用。

## 上下文装配与预算

- stitch 装配唯一入口 `services/context/stitch_context.py` 的 `assemble_stitch_context`——stitch 路由与 `GET /adaptive/context-preview` 预览**同源共用**（**红线：禁止平行实现**）。设计权威 `docs/knowledge-retrieval-plane.md`。
- **知识平面 `services/context/knowledge_plane.py`**（条目化→选择器→完整渲染）：实体/世界观/伏笔/关系归一为**条目原子**（永不劈开）；选择器=场景恒选/在场/提及（本章全文）/时刻/作者显式（宁多勿漏）；渲染带时态标注（【此刻·t=N】）+ 折叠态优先声明 + user 尾部 recency 重钉。
- **知识字段字符截断与实体数上限已全数退役**（勿再新增：settings_bundle 渲染器、world_bridge 名单 cap、open 世界观 200 字双重截断、轻档画像压缩——「句级轻档」已被实测证伪）。
- 注入序唯一权威 `adaptive_prompts.render_system_blocks`（**事实层前于文风层**）：场景身份→在场实体[取代纯专名块]→canon→secrets→世界观→关系→禁词→回响→空间→画像→样本。
- **专名称呼表按可见文本过滤**：`stitch_context.scene_visible_proper_nouns` = 在场∪死亡∪本章提及∪本次可见文本（就近节拍/滚窗/碎片）点名；块措辞「称呼规范，不是登场清单」。legacy 书零变化；context_manifest 埋点带过滤后名单。
- 五模式+预览消费同一份注入物（任务平权）；负面清单四源合并进禁词块；previous_summary 恒选全量。
- 唯一体量约束=条目级逃逸阀 `KG_BUDGET_CHARS`（丢整条不腰斩、丢弃可见）。
- 预览带「已选/未选（原因）」两栏；路由 trace `kg_selected` 选择集 + `kg_join_dead_speak` 漏选 join 埋点。
- `budget.py` 旧截断常量仅剩历史定义（**勿再新增使用**）；`allocate` 机制保留但默认恒等。

## 约束治理

把「约束」从 prompt 文案升格为注册管理的代码资产。设计权威 `docs/constraint-governance.md`（二期=docs §11）。

- 执法可靠性序 = 供给切断 > 输出代码闸 > 确定性改写 > prompt 偏置 > 事后审计（违约三要素：手段/动机/监护缺位）。
- **`services/constraints/registry.py`** 约束登记册：id/layers/enforcement/surface/status=shadow|live|report-only|retired 是代码内数据；多层执法同 id 关联（首例 dock-no-psych=[prompt,gate]）。
- `events.py`：`data/constraint_events.jsonl`，schema 含 constraint_id/status_at_event/outcome/reason——信用分数据不可补采。
- `prompt_sections.py` 分节编译器（剂量治理通用设施，dock 是第一租户：节拍子句挂 has_outline_nearby、自检清单已删、强措辞 15+→≤4）。
- `persona_drift.py`（B5 report-only）。
- **ghost_guard 第五检 out_of_scene**（shadow）：warning 带 local_only 不进 GHOST_DONE 帧；白名单=称呼表同一产物经 visible_names 透传不重算；判据=非白名单实体×上手级动词框架 ±10 字窗；回归语料库 `validation/regression_corpus/` 准入即测试；promote 门槛=语料库全对 + ≥20 次真实命中 FP<10%。
- **输入侧 `scene_visibility.py`**：称呼表过滤迁此 + after_text 泄漏手术（仅出现于胶囊后文的名字不进称呼表；挂账残留见 docs §8）。
- **event_parser 三级匹配**（精确/双向包含/jieba token 边界——嵌词不成词不命中；名表经 `services/world/jieba_lexicon.py` 注入词典保专名单 token，注入挂点=enrich/心跳/event_scout/detect_guest_names 四处幂等）+ `lexical_presence.py` 词法兜底（participant 缺失实体从事件 note 补在场标 presence_source=lexical；四调用点统一同一函数；死者不复活/歧义不填/不回写事实源）+ 切片条「据正文推断」badge + `scripts/backfill_event_participants.py` 回填工具。
- **明确不做**：constrained decoding / 实时 judge 拦截 / 多轮重试（dock 靠过采样 4-6 枚代替）。
- **缝合返修环 `services/validation/repair_loop.py`**（用户拍板「可慢不可错」）：检出硬违规 → 带稿改写×1 → 确定性验收零违规才采纳 → 句级切除 → 拒稿 GHOST_REJECT。插点=字数闸后 deai 前；单次 stitch creative 3 次封顶；切除三豁免=衔接锚句/outline 末段/剩余≥max(目标×0.6, 80字)。
- **拒稿熔断器**：章级滑窗 10min ≥2 次拒稿 → 降级带病上屏 + 合成 warning quality_breaker（老化自愈）；toast 逃生舱「仍以疑点提示上屏」= materializeRejectedGhost。
- **两级独立开关**：status 管进帧可见性（ghost_guard local_only 读 registry.status_of()，不硬编码）；Constraint.repair 字段管返修资格（fail-closed 缺省 none，repair_eligible 三重门；canon_leak/secret_leak=rewrite 初始登记）。
- **终检移位 wash P2 之后**（旧链修补稿不重检的既有洞已堵）；违规原稿不进任何可回退通道（wash original_text 存过检稿）。
- **第六检 location_jump**（shadow）：转场动词 11 词 + ≤2 字填充紧邻作用域外地点名；闭包=场景钉自身+祖先+后裔；非 world 书/无场景钉/无地点整检关闭零变化；语料 location_jump_cases.json 准入即测试。
- **语义抢拍闸全 shadow 双跑**（`services/validation/semantic_overlap.py` 通用 A-vs-B 余弦比对）：纯 API 比对走 `get_embeddings_api_only()`（绕过 SQLite 存储门控；写侧仍走 get_embeddings 正确空转省钱）；阈值 0.80 占位偏高待校准；dock 语义版 + ≥3 字面加强版双跑落台账、stitch 幽灵 vs 就近节拍 shadow；转正只走返修不切除。
- GHOST_DONE 增 repaired/breaker_open 字段 + 前端 GhostRepairedChip「已自动修正 N 处穿帮」（薄荷系只展示计数不暴露原稿）。

## 画布即事实源

- 写作台无生成预览层；作者写的即真实文档；沉淀只做后台消化（抽实体+可选落库），不产生第二份文本。落库由 `ChapterEditor` 的 `update-chapter` 机制实时覆盖。
- **「当前段落/已写内容」取源唯一权威 `services/adaptive/paragraph_source.py`**（`resolve_current_paragraph`：实时段→剥 HTML 画布尾/全文；对拍单测 `test_paragraph_source.py` + `test_world_model_liveness.py`）。层 1 事实（layer1_facts）只是沉淀审计账，**不得代替正文**进 prompt/审阅对象/已达成判定。
- `world_model.snapshot` 对事实带**派生活性**（规范化文本仍是画布子串=活，删改后过期、贴回来自动复活，不回写）；`fact_count/total_words/live_facts` 只计活事实。
- fix-sentence 匹配与 post_process 审阅对象同走 `written_text` 口径。

## 写作台「桌上一张纸」布局

设计稿 `docs/design/ux-redesign/08-writing-desk-total-redesign.md`。纸列是唯一常驻主角，三边各司其职。

- **左是书**：左缘书签 `ChapterSpine` 点开目录抽屉 `ChapterTocDrawer`；无选中章时纸面本体即目录页 `TocPage`。
- **右是 AI**：右缘助手栏 `AssistRail`（点击制；栏位序：AI 辅助总开关（带状态点）/打算/此刻/本章/检查/AI 视角/？快捷键一览）+ 浮出助手面板 `InspectorPanel`（单分区壳贴栏左开、Ctrl+\\ 固定；检查图标 6px 朱点=完稿报告到达未看）。
- **中间是我**：纸面上只有作者写的与递到眼前的。

### SparkDock 卡舱行间推挤化

- `extensions/InlineDock.ts`（TipTap Extension + ProseMirror WidgetDecoration）+ `presentation/InlineDockHost.vue`（高度手风琴宿主）把卡舱挂进正文流——锚=光标段后（`useSparkDock.sparkAnchorPos`，sticky 态段落粒度跟锚）；Tab 唤起在段下方撑开 ~200px 推开后文（**0% 遮挡**）。
- 选区安全=装饰纯视图层（文档/undo/getHTML 零触碰）+ `stopEvent`/`ignoreSelection`；关沿经 Host 收折动画 transitionend 后才摘装饰（`requestInlineDockRemoval` 带重开竞态守卫）。
- 舱内事件经 `inlineDockBridge` 模块桥回 WorkspaceView；`.ProseMirror` 加 `overflow-anchor:none` 防原生滚动锚定与 scrollIntoView(nearest) 互搏。
- **幽灵三条（疑点/返修/洗层）仍走 `CursorLayer` fixed 浮层贴幽灵尾**。
- 纸左页边批注点 `PerceptionBand`（圆点轨+覆态读卡右开，不占布局宽）；常驻顶栏已退役，字数进页头 meta 行。
- 列内页面头（`第N章` label + 衬线大标题 input + ⋯ 章节动作菜单：发布/灵感/审阅/全文格式整理，经 `editorHandle.formatWholeDocument`，现居 `ChapterEditorView.vue`）；正文区**无常驻格式工具栏**（选中文字浮窗保留 B/I/U + AI 润色/改写 + 黄金片段 + 这不像我；TipTap 排版扩展仍加载，仅删工具栏 UI，避免旧章节格式在下次保存被剥除）。

### 助手面板四分区

- **打算**（写前规划）：章级软脉络 SpinePanel + 大纲编辑卡 + 意图反推小字行（带「不对」纠正手势）。
- **此刻**：世界场景切片 + 候选收件箱。
- **本章**：字数与出场角色统计、本章文风、真相账本跳转（世界页 `?panel=canon` 深链）。
- **检查**（按 检查→修改→反馈 三组排布）：完稿体检按钮+报告（含 Phase D 加固：编辑审阅注入 Canon 真相 / 世界账本核对卡 / 信息差卡）、沉淀抽取结果、读者反馈（按需触发，走 /adaptive/reader-feedback）。Refinery 润色全家已拔除（stage-done→handleGenerated 整章覆写监听连带剪断，stage 轴最小拔除仅存 idle 写入点）。

### AI 视角分区

设计稿 `docs/design/ux-redesign/09-ai-view-redesign.md`，使用说明 `docs/ai-view-panel-guide.md`。

- 分区常开去大按钮；块默认折叠只留头行（头行即仪表盘：箭头/标题/N字/来源/预算条），展开即全量无嵌套滚动。
- 块正文**保字排版**（`presentation/contextBlockFormat.ts` 解析 #/##/-/【此刻】/〔在场〕/缩进档案体为排版结构——**字不增不删红线**；保字不变式对拍 `workspace/__tests__/contextBlockFormat.test.ts` 为合入前置；「原文」开关等宽逐字核对兜底）。
- 注入序切三段（事实与设定/约束与记忆/文风与笔感 + other 兜底）；来源文案前端人话化映射 friendlySource（后端零改动）；健康横幅置顶折叠；世界模型结构化摘要。
- 进分区自动装配一次 + 切章复位自动重拉；块折叠态组件内 Set 不持久化（原 ContextPreviewSection 的 open/toggle 契约已退役）。
- **「战局态势」简报卡**（`ContextPreviewResponse.briefing` 增量字段，`stitch_context._build_briefing` 从同一装配快照派生）：场景（active_scene 派生/钉回退 + bridge 中插标记）/ 在场+焦点物件（复用 dock `onstage_projection` 纯函数，legacy 书恒 None）/ 守死秘密（character_secrets+字段级 secret，partial 不入）/ 引力（chapter_intent>spine intent）。零 LLM 零新查询；**行空不入 dict**（简报层不做催收，全空仅「暂无态势」状态行）。
- 底层原始 14 块收进默认折叠手风琴（头行「查看底层原始提示词细节（共 N 字）」；「原文」开关移驻头行点击顺带展开；模式切换/刷新不重置折叠=isReloading 冻结流不置空 preview，仅切章复位）；**空块全量静音**（segments 按 content 过滤；EMPTY_HINTS 与 .blk-empty 样式已退役）。
- **preview 光标真切片**：`GET /adaptive/context-preview` 可选 `before_cursor`(≤600)/`after_cursor`(≤200) query 参——前端 `InspectorPanel._previewCursorWindow` 送光标前 500/后 150 字，传入即以光标前文取代落库章节尾部装配（中插不再读文末语境；after_cursor 只标 briefing.scene.bridge 不进装配，与 stitch 桥接语义一致）。⚠ preview 路由 **db 居第三位是直调兼容契约**（单测 positionally 传 session），新 query 参一律排 db 后。前端 `ContextPreviewBlock.key` 类型 7 键补齐 14 键。

### 快捷键与分区切换

Ctrl+1~4 打开助手面板对应分区、Ctrl+5 打开 AI 视角、Ctrl+\\ 固定/收起；Esc 逐层退出（蒸发幽灵→收卡舱→取消吸附）。切章默认分区按章节状态（空章→打算、有正文→此刻，用户手动切过即尊重）。润色与读者反馈门槛为**本章有正文**（`chapterHasContent`）。

### 已删除（勿复活）

- BS-ADF 步进 UI（GenerationStepper/StoryboardPanel/BranchDecisionPanel/CurrentTaskBar/BeatSlotCardView/FocusAssetsPanel/GhostTimeline/BranchBanner/AutoCutHint/GenerationOverlay/PlanConfirmModal/TierSelector）与 `useGenerationSession` 内步进调用逻辑已整体删除；**adaptive 是唯一写作路径，旧 step 入口不存在**。
- 前端二轮清扫清单见 `frontend/_deprecated/README.md`：session 步进尸体群（currentTask/handleBsadfEvent/轮询自愈/段文本函数族/ADF 产物 ref）、api 层 BS-ADF SSE 分发机、幽灵键位 Ctrl+Backspace、degradation.ts、副驾「结构检查」块（adfAudit 永无新数据）与「出场角色」卡（旧 character_ids 口径）、数据页「兜底记录」面板、pendingSaveText watch；快照只保留 Refinery 产物；「本章」tab 统计只剩字数。

## 编辑器本体优化

### 中文标点规范化（`extensions/chineseTypography.ts`）

- 判据铁律=**只在中日韩上下文动手**（`3.5`/`1,000`/`Mr. Smith`/`Hello... world` 一律原样）。
- 输入侧 InputRules 打字即正：`...`→`……`、`--`→`——`、半角 `,.?!:;()` 前一位是中文时转全角、直双引号按段内左右引号数判开闭；正则一律**零宽后顾**（range 只覆盖标点本身，不重建前一个汉字的文本节点）。
- 批处理侧 `normalizeDocumentPunctuation`（⋯ 菜单「整理标点」，零 LLM/零 API Key，单事务一次 Ctrl+Z 反悔，**保留命中处行内格式**）。
- 两消费面共用逐字符单遍扫描的 `punctuationEdits`（**按位置升序返回是契约**——引号规则会先记右引号的账，不排会让拼接错位）。

### 粘贴净化 + 清除外来样式（`extensions/foreignStyles.ts`）

- `transformPastedHTML` 剥长相类样式 color/background/font-family/font-size（粗斜下划线等排版意图保留）。
- ⋯ 菜单「清除外来样式」治存量——**带预检**（区间内真有无外来标记）决定提示语；整篇清理靠 selectAll 后**必须还原原选区**（否则作者回正文一打字替换整章）。

### 查找替换

- `extensions/editorFind.ts`（插件：搜索态 + Decoration 纯视图命中高亮，未搜索零成本短路）+ `composables/useEditorFind.ts`（状态机）+ `presentation/EditorFindBar.vue`（纸面右上浮出单行条，Esc 走全局 Esc 栈不自行处理）。
- 块内扫描不跨段、原子节点占位挡住、跨文本节点命中位置映射走共享 `extensions/blockTextMap.ts`（与标点归一同一底座）。
- 替换逐条独立事务、全部替换单事务；跳转只移选区不抢焦点（**查找条开着时屏蔽选区浮窗**）；替换走 JSON 内容/裸 `tr.insertText`（字符串会被当 HTML 解析）。
- **关条焦点用 `ed.view.focus()` 而非 `commands.focus()`**（后者把 view.focus() 推迟进 rAF，窗口不可见时 rAF 被节流→焦点停在 body）。

### 排版

- `RichTextEditor.vue` 的 scoped `:deep(.ProseMirror)` 不重复声明 font-family/size/line-height——排版唯一权威= `--editor-*` token。
- `--editor-font-family` 栈底补 `SimSun`（栈里一个中文衬线都命中不到时，`“”…` 会被 Georgia 先抓走致字与标点对不齐）。

### 入口与对拍

⋯ 章节动作菜单「查找替换（Ctrl+F）/整理标点/清除外来样式」+ 快捷键速查表补 Ctrl+F。对拍 `extensions/__tests__/{chineseTypography,editorFind,foreignStyles}.test.ts`（34 项）。
