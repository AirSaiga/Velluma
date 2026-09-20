> **归档说明（2026-09-19）**：卡片舱两链 prompt 实编译快照（2026-09-11），随代码漂移，仅作当时记录。

# 卡片舱两条链全量 Prompt 与逻辑链调研报告

> 交付日期：2026-09-13。代码版本：`DOCK_PIPELINE_VERSION = v2.3_suffix300_20260913`（backend/services/adaptive/components/dock_generator.py:39）。
> 方法口径：**真实编译文本**——附录四份 prompt 全部由当前代码的 builder 函数实际编译产出（输入取自 09-13 巷口送别场景的真实事故数据），拒绝抽象转述；逻辑链以行号锚点定位到当前工作区代码。
> 范围：**链 A = 卡片舱选项生成**（心跳挂件/走向卡的来路）；**链 B = 选中选项后续写**（点零件 Space 缝合、点走向卡 Ctrl+Space 连写的去路）。细纲胶囊（outline）与点火（open）共用链 B 端点但各有专职 prompt，仅在分叉处带过。

---

## 1. 全景：一张图看两条链

```
【链 A：选项生成 —— 卡片从哪来】
作者打字/停顿 → 心跳 /adaptive/heartbeat (heartbeat.py)
  → orchestrator.on_heartbeat (orchestrator.py:158)
      变化检测 detect → salience 影子 → _decide 规则表 (orchestrator.py:290)
  → 停顿心跳(≥4s+段尾) 同步等待 dock_generator.run (dock_generator.py:419)
      取材 9 源（当前段/接缝裁剪推测/养料/硬约束/回响/期待/意图/在册投影/后文锚）
      → build_dock_generator_prompt (adaptive_prompts.py:1467)
      → LLM creative t=0.75 max_tokens=1500 → JSON parts
      → 校对环 8 丢件闸 + 3 影子检 → _finalize_parts 槽位规整 (dock_generator.py:778)
      → 缓存 layer3_projections.__dock__（版本盐+三键签名）
  → 心跳响应 dock_parts / direction_cards / canon_hints / onstage_guests
  → 前端 InlineDock 行间卡舱展示

【链 B：选中后续写 —— 卡片点了之后发生什么】
Tab 唤舱（force_refresh 强制重算）→ 点一枚零件 → Space / 点「接着写」
  → requestContinue('stitch') (useAdaptiveAssist.ts:698)
  → POST /adaptive/stitch-ghost (stitch.py:115)  【SSE】
      assemble_stitch_context 装配 (stitch_context.py:214)
        意图三级源链 → 记忆召回(B3 去敏) → 文风画像+笔迹样本 → 知识平面 kg → 称呼表过滤
      → build_continue_prompt (adaptive_prompts.py:514)  【真实编译全文见附录三】
      → LLM creative t=0.7 max_tokens=max(下限, target*2+1000)
      → 确定性后处理 13 站（§3.5）：
        复读剥离→引号碰撞→接缝归一(+抢场影子)→字数两级闸(微镜头旁路)
        →返修环(改写→切除→拒稿→熔断)→deai 抛光(微镜头旁路)
        →洗层 P1→P2 修补(冷却/旁路)→P4 语义影子→终检→标点归一
      → GHOST_START → GHOST_CHUNK×n 打字机 → GHOST_DONE(warnings/wash/deai/ghost_token)
  → 前端幽灵草稿 mark 上屏 → Enter 采纳 / Esc 蒸发 / 退格删除（reapGhostIfDead）
```

走向卡连写（Ctrl+Space）走链 B 的 `burst` 分支（`build_burst_prompt`，adaptive_prompts.py:707，附录四），prompt 形态不同但装配与后处理链同源。

---

## 2. 链 A：卡片舱选项生成

### 2.1 触发与节流（舱里什么时候会有卡片）

链 A 的唯一调度入口是心跳 `orchestrator.on_heartbeat`（orchestrator.py:158）。前端口径：活跃防抖 3s / 停顿 4s+光标段尾发一次（useAdaptiveAssist.ts）；**卡舱唯一入口是 Tab 主动唤醒**（2026-09-09 用户拍板，自动弹出全线退役，useSparkDock.ts:114-115）——Tab 触发的心跳带 `force_refresh=true`，跳过缓存命中强制重算。

`_decide`（orchestrator.py:290）对 dock 的激活条件（规则 2）：

1. `paused_ms ≥ 4000` 且 `cursor_at_paragraph_end`（段尾）；
2. 段落不在半句（`ends_mid_sentence` 闸，空段=段界不算半句；**Tab 点名 `summoned` 豁免**）；
3. 有意图或正文 ≥300 字；
4. 缓存未命中或 force_refresh。

**缓存签名三键 + 版本盐**（orchestrator.py:390-408）：`当前段文本|打算一句话|全书字数` × `接缝裁剪后推测签名:intent_version` × `场景钉+叙事锚|DOCK_PIPELINE_VERSION`。三键全同才命中（省 ~90% dock 调用）；签名落账是「待定账」制——`_activate_sync` 成功才提交，12s 超时弃账下轮重算（orchestrator.py:111-125）。

停顿心跳对 dock/future_projection/canon_watch 三组件**同步等待**（`SYNC_COMPONENT_TIMEOUT_S=12s`，orchestrator.py:38），产出随本次心跳响应直接带回；在飞去重 `_sync_inflight` 防慢端点并发双烧。

### 2.2 dock_generator.run 的输入装配（九个素材源）

`run()`（dock_generator.py:419）装配顺序与来源：

| # | 素材 | 来源与口径 |
|---|------|-----------|
| 1 | `recent_text` 当前段 | `resolve_current_paragraph`（paragraph_source.py）：心跳实时段优先，回退画布尾剥 HTML。**不用层 1 沉淀事实**（删改即过期）；<30 字跳过本批（dock_generator.py:435-437） |
| 2 | `projections` 层 3 推测 | **接缝裁剪** `_prebeat_projections`（dock_generator.py:890）：stage=beat/after 的节拍不进取材池（切断供给>命令拒绝）；B2 减肥后 prompt 只取 1 条×1 拍 |
| 3 | `nutrients` 设定养料 | bundle 的角色物理特征/资产/地点；**在场制下被在册投影取代**（§2.4 养料块） |
| 4 | `hard` 硬约束 | `banned_words`（前 30 进禁词表）+ `canon_private_labels`；B2 起 character_statics 整体不注入（adaptive_prompts.py:1483 注释） |
| 5 | `memory_echoes` 前情回响 | `recall_memories` k=2（ECHOES_K_DOCK），query=当前段尾 300 字；B3 去敏：V/B 流抹在场实体名 |
| 6 | `reader_expectations` 读者期待 | soft_constraints，前 2 条带张力值 |
| 7 | 意图（spine/大纲/反推） | 大纲就近节拍 `outline_nearby` 优先；无节拍时层 2 反推 `intent_guess` 供料——**衰老闸**：反推后正文推进 >100 字（INTENT_STALE_CHARS）不绑旧意图；置信 ≥DOCK_INTENT_MIN_CONFIDENCE |
| 8 | `onstage` 在册投影 | `onstage_projection`（dock_generator.py:119）纯函数：场景钉作用域存活者 ∪ 当前段提及者（≤8 实体+≤6 物件）+ 场景行 + **临时通行证 guest**（jieba 提名+子串计数 ≥2，别名归一拦截 `_is_alias_or_ambiguous`）。legacy 书恒 None=prompt 走旧形态零变化 |
| 9 | `suffix_anchor` 后文锚 | 心跳透传（前端 `_suffixAfterCursor` ≤300 字）；非空 → 桥接态：`intent_guess` 清零（后文剧透断供）+ template=bridge |

**模板选择** `pick_shot_template`（dock_generator.py:346）：`bridge（后文锚，最硬）` > `dialogue·末句优先（末行整行引号起收，无条件点燃）` > `dialogue·占比（尾 300 字 >0.35）` > `combat（搏杀手势字 ≥3）` > `panorama（入场手势+段短）` > `default`。除 bridge 外，无在册投影强制归一 default。

LLM 调用参数（dock_generator.py:552-558）：`creative` 槽，temperature=**0.75**，max_tokens=budget_tokens=**1500**，`REASONING_DISABLED`。

### 2.3 链 A system prompt：分节编译器

system 不再是整段字符串，而是 `_dock_system_sections()`（adaptive_prompts.py:1297）定义的 **PromptSection 列表**，由 `render_sections`（constraints/prompt_sections.py:35）按 when 谓词裁剪拼装——「分节编译」（约束治理一期）：

| 分节 key | 出现条件 | 内容一句话 |
|---|---|---|
| role / structure | 恒在 | 物理镜头碎片生成器定位 + 「主语+具体动作」结构要求（action/scene/line 三类） |
| slots | 恒在 | 四功能槽位定义：landing【接着写】必有 1 枚居首位（物理落点=把抽象翻译成主动小动作） |
| slot-toward-beat | 有就近节拍 且 default 模板 | toward_beat【通往节拍】：通往节拍的**第一步**，不是节拍画面 |
| slot-toward-guess | 无节拍+有猜测 且 default | toward_beat 改由 AI 猜测供料，明示「AI 从正文猜的」 |
| slot-echo-mat | 有回响/期待素材 | echo【呼应】至多 1 枚，标 from_memory/from_expectation+echo_ref 序号 |
| slot-echo-none | 无素材 | **允许零呼应**（09-11 强买强卖修复） |
| slot-ambient | 恒在 | ambient【氛围】补位，无叙事包袱 |
| slots-dialogue | template=dialogue | reply【接话缓冲】+ prop【在场特写 anchor_ref】 |
| slots-combat | template=combat | 搏杀槽位取向：起手交换/感官闪现，破绽胜负不出 |
| slots-bridge | template=bridge | 机位四取向 + **下文已写是禁区** + 末枚引到下文门口不跨进去 |
| slots-panorama | template=panorama | 定场质感/第一件可上手物 |
| nearby-common | 恒在 | 就近要求：文流第一（与最后一句直接衔接） |
| beat-preservation | 有就近节拍 | **节拍保全检验**（唯一主判据）+ 节拍>推测 + 禁搬后段高潮 |
| no-beat-fallback | 无节拍 | 只在当前文流就近生发 |
| scene-anchoring-head/rest | 恒在 | 不复述已写 / 空间不瞬移 / 保底本场景 ≥2 枚 |
| props-two-class | 无在册（legacy） | 道具两分：氛围件自由/上手件须出处 |
| props-three-tier | 有在册 | **T1 自然力自由 / T2 派生质感须指源 / T3 上手物与出场人物只从在册** |
| examples | 恒在 | 4 反例（太笼统）+4 正例 |
| hard-rules | 恒在 | 禁心理/禁比喻/禁抽象 + 禁词表 `«BANNED_WORDS»` 占位注入 + 多样性 + landing 首位；只输出 JSON |

桥接态按「无节拍供给」编译（build 侧 `has_nearby = bool(outline_nearby) and not is_bridge`，adaptive_prompts.py:1529-1531）——素材块切断与分节同口径。

完整编译产物见**附录一/二**。

### 2.4 链 A user prompt：分块与来源

user 模板在 build_dock_generator_prompt 尾部（adaptive_prompts.py:1699），块序：

| 块 | 来源 | 备注 |
|---|---|---|
| `# 作者当前段落` | recent_text **保尾 400 字** | 作者真位置在段尾 |
| `# 本场在册` | onstage 投影 | 实体在前物件在后统一编号 `[N]`——anchor_ref 坐标系；模型报序号，后端回查拼 note（模型不经手出处文本） |
| `# 下文已写` | suffix_anchor [:300] | 仅桥接态；09-13 起 300 字+「不得与之矛盾」 |
| `# 本章意图（方向参考）` | spine.intent 一行 | 空则整块缺席 |
| `# 作者大纲·就近节拍` | outline_nearby[:2] | 「几步之外的目的地」定位；桥接态缺席 |
| `# 本章方向猜测` | intent_guess[:80] | 仅 guess_only（无节拍+有猜测+非桥接） |
| `# 接下来的画面方向` | 推测 1 条×1 拍；空=「（无推测，基于当前段落自由生发）」 | 桥接态恒空（剧透断供） |
| `# 此刻值得盯住` | salience_hints ≤6 行 | B7 单车道，空则缺席 |
| `# 读者期待` | 前 2 条带 `[i]（张力N/10）` 序号 | echo_ref 坐标系 |
| `# 前情回响` | ≤2 条带 `[i]` 序号 | 同上 |
| `# 设定养料` | 在册制=在册全行+场外仅名字（「场外人物，只可经呼应带出」）；legacy=养料原文 | 红队 R1 收窄 |
| `# Canon private 禁忌` | canon_private_labels[:5] | 泄密硬禁忌 |
| 尾部指令 | 输出契约 | 4-6 枚×8-14 字；槽位子句按模板/素材动态编译（`beat_clause`：bridge=空 / 在场制=「贴近即可」柔性 / legacy=「含 1 枚」配额）；JSON 输出格式示例（含 slot/type/text/direction/from_memory/echo_ref 全字段示范） |

### 2.5 产出校对环：8 个丢件闸 + 3 个影子检

模型返回 JSON `parts` 后，`_finalize_parts`（dock_generator.py:778）逐枚过闸（约束治理一期枚举原因链，每枚丢件落 constraint_events 台账）：

**live 丢件**（按判定序）：
1. `not_dict` → dock-part-shape
2. `too_short`（<2 字）→ dock-part-shape
3. `violates_hard`（canon private 标签 × blocker 级禁词；`_violates`，提醒级词**不**拦——A2 分级）→ dock-banned-words
4. `camera_stock`（镜头陈词 8 词族：目光失焦/望向远处/瞳孔…）→ dock-camera-stock
5. `psych_word`（心理词族 8 词：心中一紧/感到不安…）→ dock-no-psych（**prompt+代码闸双层执法**首例）
6. `rehash`（对当前段或推测原文 3 字片段命中率 ≥0.5——`text_match.matches`）→ dock-rehash
7. `beat_overlap`（与就近节拍去标点后 ≥4 字连续重叠）→ dock-beat-overlap
8. `suffix_overlap`（与后文锚 ≥4 字重叠=提前消耗下文，仅桥接态）→ dock-bridge-overlap

**shadow 只落台账不丢件**：`beat_rush_semantic`（卡片 vs 节拍向量重合，抓改写式抢拍）、`beat_overlap_n3`（3 字面收紧候选）、`onstage_violation`（T3 边界：非在册名×上手动词共现，正文已提及豁免）。

**配额消化**：输入 >6 枚记 `overflow_head`(trim)、产出 >4 枚记 `overflow_tail`(trim)——与 drop=违规分列（P2-1）。

### 2.6 槽位规整与 note 拼装（出处后端权威）

每枚过闸零件经 `_normalize_slot`（dock_generator.py:696）归一槽位（旧契约 from_expectation→echo；未知→ambient），再由 `_assemble_note`（dock_generator.py:719）**后端拼装副行 note**——模型自由创作出处=编造风险铁律，note 文本一律不出自 LLM：

| 槽位 | note | 出处逻辑 |
|---|---|---|
| landing | 「接着刚才那句往下写」 | 固定文案，恒居首位 |
| reply | 「受话人先接住那句话」 | 固定文案（对白模板，锚对白本身无出处义务） |
| prop | 「镜头对准『X』」 | anchor_ref 回查在册名单；**指认失败→降级 ambient** |
| toward_beat | 「往『节拍前 10 字』那拍走的第一步」；无节拍时「往『猜测截 12 字』那个方向试试（AI 猜的）」 | 优雅截断（向句读回退，不断在人名中间） |
| echo | 「暗示读者在等：…」/「顺笔带出前情：…」 | echo_ref 回查期待/回响素材原文，`_clean_echo_note` 剥机器格式标签 |
| ambient | （留白） | 留白本身是信息 |

槽位拿不到出处 → 降级 ambient（**标签必须承载真实出处，否则不标**）。最终按 SOURCE_PRIORITY 稳定排序（landing 0 > toward_beat/reply 1 > echo/prop 2 > ambient 3），保 4 枚。

### 2.7 缓存与心跳响应

产出经 `_cache_dock_parts`（dock_generator.py:1014）写进 `WorldModelORM.layer3_projections` 末尾的 `{"__dock__": True, "parts", "ver": DOCK_PIPELINE_VERSION, "guests", "ts"}` 项——**跨进程持久缓存**，版本盐读取侧 `_extract_dock_parts`（heartbeat.py:177）过滤陈旧版本兜底活跃心跳窗口。心跳响应组装：`dock_parts` + `onstage_guests`（heartbeat.py:161，guest 出「录入档案」直达入口）+ `direction_cards`（future_projection 组件产出）+ `canon_hints`。

前端 `useSparkDock`/`InlineDockHost` 行间推挤展示（Tab 唤起 ~200px 撑开），两级层级：主行画面 / 副行 10px 灰功能出处；句级闸门（半句不生发，响应 `dock_muted=true` 无条件清舱）。

---

## 3. 链 B：选中选项后续写（stitch-ghost）

### 3.1 触发与请求字段

端点 `POST /api/chapters/{id}/adaptive/stitch-ghost`（stitch.py:115），SSE 五模式。与「卡片舱选项」直接相关的两条触发：

| 动作 | 前端入口 | 请求形态 |
|---|---|---|
| **点零件 → Space 缝合**（mode=stitch） | 有零件时 Space / 零件点击 → `requestContinue('stitch', pickedParts)`（useAdaptiveAssist.ts:698） | fragment=光标前段内文本保尾 200（桥接态）/当前段保尾 200；rolling_prefix=段前 200 字；`picked_parts`（零件文本数组）+`picked_slots`（同序槽位）；target_chars=**50**（微镜头区间 40-60）；suffix_anchor（≤300）；adopted_direction（走向采纳回报埋点） |
| **顺句续写**（mode=continue） | 无零件 Space | 同上但 picked_parts 空，target=200 |
| **走向卡连写**（mode=burst） | Ctrl+Space 选走向卡 → requestBurst（useAdaptiveAssist.ts:805 附近） | `beat_guidance`=卡 event+焦点 anchors；rolling_prefix=段前 **500** 字；target=**700** |
| 细纲扩写（mode=outline） | Alt+O / `[[` 胶囊 | fragment=速记原文；after_text=胶囊后 300 字；target=速记「约N字」clamp 100-800 缺省 400 |
| 点火（mode=open） | 空章 IgnitionCard | fragment/rolling 空；大纲唯一燃料 |

### 3.2 装配：assemble_stitch_context（五模式共用单源）

`assemble_stitch_context`（stitch_context.py:214）——**预览与注入同源红线**（context-preview 端点共用此函数）：

1. **意图三级源链**（stitch_context.py:241-256）：请求自带 chapter_intent（source=request，此时节拍不进 prompt、抢拍闸素材留空）> 大纲就近节拍（source=outline，节拍列表同时供抢拍闸）> 层 2 反推兜底（仅 stitch/continue；source=inferred/baton）。
2. **记忆召回**：query=滚动窗尾+fragment（open 用大纲），k=ECHOES_K_STITCH，B3 去敏 mask_names。
3. **文风执行层**：`render_style_positive` 画像 + `retrieve_author_samples_with_meta` 笔迹样本（k=2；burst k=3；scene_hint 对白加成；drift_anchor 收藏加成）；sample_ids 随行供采纳率回流。
4. **知识平面 kg**：`build_knowledge_view` 条目化→选择器→完整渲染（一字不砍，条目级逃逸阀）。
5. **称呼表过滤**：`scene_visible_proper_nouns`——在场∪死亡∪本章提及∪可见文本点名（09-01 穿帮修复）；outline 模式再剔除仅现于 after_text 的名字。

### 3.3 链 B system prompt：基座 + 注入序 + 模式门控

= `_base_system()`（adaptive_prompts.py:109，反 AI 腔契约基座：写作原则 5 条/反 AI 腔 4 禁/禁词表（DEFAULT_BAN_LIST+prompt 专属 7 词）/心理描写限制/细节功能三问）+ `render_system_blocks`（adaptive_prompts.py:368）按**注入序权威**拼块：

```
场景身份 → (本章打算warm) → 在场实体 → [无实体时: 专名称呼] → Canon → 私有设定
→ 世界观 → 关系 → 禁词约束 → 前情回响 → 空间常识 → 文风画像 → 笔迹示范
→ [仅 stitch/continue] 白描契约与假感官封杀令（末位最高服从位）
```

关键机制：
- **五模式任务平权**：模式差异只在任务指令，知识注入同份（v3.1 公理二）；但模式总预算不同（MODE_CONTEXT_BUDGETS），软块（画像/样本/回响/空间）过 `allocate` 裁剪——默认预算恒等。
- **在场实体块存在时取代专名块**（名字已含于条目）；无实体数据回退专名兜底位（零变化契约）。
- **单焦距视点锁**（`pick_subject_lock`，adaptive_prompts.py:469）：点选槽位 → 互斥三锁——prop/ambient→物镜锁（情绪不走人物走物件）；reply→静音锁（受话者开腔前缓冲）；landing/speaker→发话锁（钉发话者单人）。toward_beat/echo/custom 不锁。锁文本插在零件块之后、指令区之前。
- **双轨契约选档**（stitch.py:337，`pick_contract`）：stitch/continue 由代码选 motion（推进）/texture（停在当下细写）——零件槽位优先（echo/ambient→texture），无零件走尾部动作密度兜底；其余模式恒 motion。texture 档把「只写新东西」规则换成 `_RULE_TEXTURE`。
- **白描契约与假感官封杀令**（`_ANTI_PSEUDO_SENSORY_BLOCK`，adaptive_prompts.py:496）：禁假感官/禁模式化情绪开关/禁脑补事故与台词抢跑 + 北方硬朗白描 + 严禁逗号串联注水。stitch/continue 专属末位分节（burst/open/outline 各有专职不受染）。

完整编译产物见**附录三 SYSTEM**。

### 3.4 链 B user prompt：stitch 形态分块与来源

stitch 分支的 user 模板（adaptive_prompts.py:678-694），块序与来源：

| 块 | 来源 | 备注 |
|---|---|---|
| `# 上文衔接（保持连续，不重复）` | rolling_prefix 句界净截：stitch/continue 保尾 **800**、burst/outline **1200**（STITCH_ROLLING_*，2026-08-25 实测调窗）+ `# 上一章结尾`（previous_summary 恒选） | 窗首丢半截句防误续 |
| 意图块（三档措辞） | inferred=「# 下一步方向（AI 从已写内容猜的…对不上就忽略它）」/baton=「# 承接上一章」/outline·request=「# 几步之后的目的地（现在不写它本身…只写通往它路上的画面）」 | 09-03 重框治「节拍 verbatim 消费」 |
| `# 作者原句（…绝不重复它，从它的断点直接往下写）` | fragment | 追加式契约：原句已在画布，幽灵纯追加 |
| `# 下文已写` | suffix_anchor [:300] | 桥接态；09-13 扩窗+物证条款（附录三即修复后形态） |
| `# 选定镜头零件（必须落地为画面）` | picked_parts 顿号连接；空=「（无——仅按作者原句顺势续写）」 | |
| 视点锁块 | pick_subject_lock 结果 | 空=缺席 |
| custom 素材指令 | picked_slots 含 custom | 「自定义镜头是素材指令不是成品文本…不逐字照抄」（逐字回声事故） |
| 尾部指令区 | 断点续写指令 + **桥接铁律**（双端边界：主角一侧正向约束/末句门口即止/禁提前出现/位置物证不得违背）+ 零件矛盾改造条款 + advance_rule（新东西/质感二选一）+ 收尾律 + 字数上限 + recency 重钉「【此刻·切记】在场…」 | recency 位=lost-in-the-middle 对冲 |

burst 形态（附录四）差异：`# 本段走向（作者选定）`+「必须覆盖走向的核心事件…绝不允许一句话带过」、2-4 段落、`_RULE_ENDING_PARA` 单行收尾律、**无**视点锁/桥接铁律/白描契约分节。

LLM 调用（stitch.py:445-452）：creative 槽，temperature=**0.7**，max_tokens=max(STITCH_MAX_TOKENS_FLOOR, target×2+1000)（C2 推理隐藏 token 余量），REASONING_DISABLED。

### 3.5 生成后的确定性后处理全序（13 站）

先生成后播放：全部闸门走完才推第一个字（stitch.py `_stream()`）。按执行序：

| # | 站 | 行号 | 做什么 |
|---|---|---|---|
| 0 | 空产出守卫 | 456 | content 剥引号为空 → SSE error |
| 1 | outline 字数双闸 | 460-489 | 仅 outline：超 ×1.6 带压缩反馈重试 1 次→仍超 `_truncate_keep_tail` 保尾截 ×1.5（末段承接段豁免） |
| 2 | **复读剥离** | 495 | `_strip_fragment_prefix`：stitch 模型把原句吐回来→剥前缀（追加式契约，防屏幕重复） |
| 3 | **引号碰撞** | 500 | `_strip_colliding_open_quote`：断点悬空开引号×幽灵以开引号起→剥幽灵开引号 |
| 4 | **桥接接缝归一** | 504 | `_normalize_bridge_seam`：≤24 字最长重叠优先归一衔接（在字数闸/返修环之前——归一改长度）+ `_bridge_actor_steal` 抢场影子检（幽灵末句与后文首句共享登场者→台账） |
| 5 | **字数两级闸** | 536-619 | stitch/continue/burst/open 超 ×1.6：**微镜头（target≤60）只保头句界截断零 LLM**；否则首句物理摘出（衔接句永不进压缩）→剩余保头截 ×1.5→带断点坐标压缩改写到 target→复述衔接句剥除→仍超再截→空产出回落截取稿 |
| 6 | custom 逐字回声影子 | 622-640 | 自定义件 ≥8 字被原样吞→stitch-custom-verbatim 台账 |
| 7 | **缝合返修环** | 642-783 | `check_ghost_text` 预检→`repair_eligible` 硬违规→`run_repair_loop` 带稿改写 ×1（t=0.3）→`_postprocess_repair_draft` 重跑零 LLM 确定性后处理→验收不过句级切除（三豁免：衔接锚句/outline 末段/剩余 ≥max(目标×0.6,80 字)）→**拒稿 GHOST_REJECT 不上屏**（原文随帧作逃生舱）；章级 10min ≥2 次拒稿→**熔断**带病上屏+quality_breaker 警示（老化自愈） |
| 8 | **deai 抛光** | 785-837 | 自训小模型改质感；≤100 字契约窗生效；**微镜头旁路**（出字竞速）；保名闸（在场/死者名单实体名逐字保留否则回退）； DashScope 原生槽不走用量聚合 |
| 9 | **洗层 P1** | 841-886 | `wash_ghost_text`：blocker+alternative 词边界确定性替换（warning 档永不动手）；original_text 快照随帧回传（前端「用原稿」可逆学习） |
| 10 | **P2 句级修补** | 888-907 | 残留 blocker 单次 LLM 修补（t=0.3），严格验收（重洗零残留才采纳）；每章 60s 冷却+在飞去重；微镜头旁路 |
| 11 | P4 语义影子 | 918-933 | blocker 模式向量×幽灵抓换字逃逸，只落事件不改文 |
| 12 | **终检** | 938-966 | `check_ghost_text` 再跑一遍（P2/deai 产物同样必须过检），local_only（shadow）过滤后进 warnings 帧；熔断追加 quality_breaker；dead_speak 命中回查 kg 选择集（kg_join_dead_speak 埋点） |
| 13 | 尾部影子+归一+推流 | 968-1063 | stitch 语义抢拍影子（幽灵 vs 节拍向量）/persona_drift report-only→`_normalize_ghost_punctuation` 半角标点归一（此后所有消费方看同一文本）→GHOST_START→GHOST_CHUNK（stitch/continue 6 字 90ms；burst/open/outline 12 字 40ms）→**GHOST_DONE**（text/word_count/warnings/wash/deai/ghost_token/sample_ids/repaired/breaker_open） |

**ghost_guard 十检**（check_ghost_text 判据族，validation/ghost_guard.py）：canon_leak/secret_leak/字段秘密（3b）/dead_speak 死者开口/out_of_scene 场外实体×上手动词（±10 字窗）/location_jump 地点穿越/beat_rush 抢拍/mind_leak/belief_leak/cliche_hit——live 状态进返修环与终检，shadow 状态只落台账（registry.status_of 驱动，两级开关）。

### 3.6 GHOST_DONE 之后：前端消费

- 幽灵以 TipTap mark 灌入光标后（stitch 插光标处；outline 插胶囊钉后）；绿色高亮，可继续打字微调（ghostDirty）。
- **Enter 采纳**：去 mark 落正文 + ghost_token/sample_ids 埋点回流（采纳率→sample_prior 先验 ±20% 调序）；**Esc 蒸发**（≥30 字浮理由 chips 攒失败分类学）；**退格删光**→`reapGhostIfDead` 收尸（防僵尸态吃 Tab）。
- 增量 chip：`GhostWashChip`（洗层计数+用原稿）、`GhostRepairedChip`（返修计数）、warnings 疑点提示（薄荷系只计数不暴露原稿——违规原稿不进任何可回退通道）。

---

## 4. 两链对照与一致性防线

| 维度 | 链 A 选项生成 | 链 B 选中后续写 |
|---|---|---|
| LLM 调用 | 1×creative t=0.75 / 1500 tok / 每停顿或 Tab 一次（缓存省 ~90%） | 1×creative t=0.7 / target×2+1000；压缩/返修/P2/deai 各可 +1 次（stitch 上限封顶） |
| 产出粒度 | 4-6 枚×8-14 字画面碎片 JSON | 50 字微镜头 / 200 字顺句 / 700 字段落 |
| 注入坐标系 | 在册投影（T3 白名单）+ 序号回查（anchor_ref/echo_ref） | 知识平面条目化注入（任务平权）+ 称呼表 |
| 后文约束 | suffix_overlap ≥4 字面丢件（桥接态） | 桥接铁律（prompt）+ 接缝归一 + 抢场影子 |
| 防线哲学 | **切断供给>代码闸>prompt 偏置**（接缝裁剪/意图断供/过采样 4-6 枚吸收误报） | **先生成后播放**：确定性闸门链 13 站，终点永远是作者裁决（拒稿有逃生舱/熔断降级） |
| 缓存 | layer3 持久化+三键签名+版本盐 | 无缓存（每次实编） |
| 观测 | 丢件台账 constraint_events/丢件原因枚举 | context_manifest/adaptive_stitch_complete/quality 台账 |

一致性同源件（两链共享）：就近节拍判据 `outline_nearby`（dock 取材与 stitch 意图块同一函数）；记忆召回与去敏 mask_names 同口径；文风样本检索同一 `retrieve_author_samples`；禁词四源 `load_prohibition_set`。

---

## 5. 附录：真实编译 prompt 全文

> 以下四份由当前代码 builder 实际编译（脚本直调 `build_dock_generator_prompt` / `build_continue_prompt` / `build_burst_prompt`），输入取 09-13 事故场景（巷口送别）；合成部分仅限世界观/档案等条目**形状**（真实条目值以真实书为准，不影响结构）。行宽原样保留。

### 附录一：链 A system（default 模板 + 在册 + 有节拍/期待/回响）

见 §2.3 分节表按 when 谓词拼装；完整文本与附录二同骨架（role/structure/slots 全量 + slot-toward-beat + slot-echo-mat + nearby-common + beat-preservation + scene-anchoring + props-three-tier + examples + hard-rules），篇幅关系不重复贴——差异分节已逐条列于 §2.3 表。

### 附录二：链 A bridge 形态全量（system + user）

**SYSTEM**（分节开关：has_nearby=false、has_echo_mat=false、has_onstage=true、template=bridge）：

```
你是一个物理镜头碎片生成器。基于作者当前段落、本章推测方向和设定养料，生成镜头特写挂件。

每个挂件是一个 8-14 字的【微型镜头】，作者扫一眼就能在脑中想象出那个画面，并立刻判断"要不要顺着写"。

【结构要求 —— 每个碎片都要有"主语 + 具体动作/状态"】
- action 类：[谁] + [具体动词] + [对象/方向] → "林尘攥紧扳手摸向灯塔基座"
- scene 类：[具体物件/环境] + [可视感官细节] → "礁石滩泛着暗红的金属锈光"
- line 类：[完整台词原文] +（可选说话人）→ "别在退潮时回头。阿晚的声音"
- 扎根设定但生发新画面：角色动作符合其性格设定，但要是作者还没写过的具体动作

【功能槽位 —— 每个碎片属于一个槽位，按槽位生发（作者要能看懂「选这枚会发生什么」）】
- slot=landing【接着写】（必有 1 枚，放首位）——接住作者刚写的：作者最后一句（或正说着的那句话）的"物理落点"——把抽象的感慨、判断、情绪翻译成人物此刻**主动做出**的一个小动作（把书往口袋深处按了按、把后半句咽回去、手上的活故意慢了半拍）。要是人物主动发出的动作——不是表情、不是静止状态
- slot=echo：本批无相关前情或读者期待素材——无需强行生成呼应件，全部生成现场分镜镜头（呼应类允许零枚）
- slot=ambient【氛围】（其余补位）：无叙事包袱的画面（光影/声响/物件质感），作者随手就能用，不指向任何去向

- 中插桥接（本批补写上下文之间的十秒过渡）：机位四取向——物理落脚（脱鞋、放包、解外套）/ 室内感官（饭香、热气、灯光）/ 身体松劲（松肩、揉腕）/ 目光所向（望向下一幕的人或物）
- 下文已写的事实是禁区：user 材料里「下文已写」块中的事（端来的东西、说出的话、做出的动作）一概不出——过渡只写抵达它之前的路
- 末枚机位把画面引向下文首句的门口，但不跨进去
【就近要求 —— 碎片是"下一屏"的画面，不是章末预告】
- 文流第一：碎片与作者当前段落的最后一句**直接衔接**——作者下一句就能顺着接上写，中间不需要任何过渡句

- 没有大纲节拍可用时，也只在当前文流上就近生发

【场景锚定 —— 碎片长在作者此刻的场景里】
- 道具三档（「本场在册」已列出此刻在场的人物与物件）：**自然力**（天气、光线、声响、气温——无主不可拾）自由生发；**派生质感**（气味、反光、震动、浮尘）要指得出它的来源物——指不出来源的质感就是造物；**上手物件与出场人物**只从「本场在册」或本章正文已出现者里取：人物碰过的物件会进入后续所有画面，作者接了它就欠下连续性债
- 不复述已写：碎片是还没落笔的画面——作者已写的画面（刚引用的原文、刚描写过的物件）换个说法再端上来，等于没给选项
- 空间不瞬移：碎片发生在当前段落的同一场景/时刻，或通向下一拍的过渡画面（抵达、开门、天亮——除非抵达本身就是那一拍的事件）
- 保底本场景：碎片中至少 2 个发生在当前段落的同一场景内——作者不换景就能直接落笔

【反例 —— 这些是"太笼统"，不要产出】
× "传送带突然停转"（停转了然后呢？没有"谁"做什么）
× "环境变得压抑"（抽象形容词，不可视）
× "阿晚说过一些话"（什么话？没有内容）
× "林尘感到不安"（心理描写，违反本要求）
× "气氛紧张起来"（纯氛围概括，不可操作）

【正例 —— 这些是"具体可操作"，要产出这样的】
✓ "林尘攥紧扳手摸向灯塔基座"（主语+动作+对象，能展开成行为段）
✓ "礁石滩泛着暗红的金属锈光"（物件+视觉感官，能展开成环境段）
✓ "别在退潮时回头。阿晚的声音"（完整台词，能展开成对话/回忆段）
✓ "一只手从灯塔窗洞里伸出来"（物件+动作+位置，制造悬念）

硬性要求：
1. 禁心理描写（"心中一紧"/"感到不安"）、禁比喻（"宛如"）、禁抽象形容词（"压抑"/"紧张"）
2. 禁词表（以下词汇不用）：«实际为 hard.banned_words 前 30 个顿号连接，示例书为：冷冽、深邃、一抹、顿了顿»
3. 多样性：不要全是 action 或全是 line，混搭让作者有不同方向
4. landing 必居首位；呼应类至多 1 枚

只输出 JSON，不要解释。
```

**USER**（bridge 形态，注意：推测块被切断为占位行、意图/节拍/期待/回响块整体缺席、下文已写 300 字全量进块）：

```
# 作者当前段落
“阿尘，留下吃个饭吧，怎么说也得谢谢你啊。”王叔招呼道。林尘把工具包往肩上颠了颠，拉开门闩。外头风从巷口灌进来，他缩了缩脖子，迈步下了台阶。“不用不用。”林尘回头笑了笑，“明姐还在家等我呢，说是今晚做了好吃的，特地嘱咐我早点回去。”

# 本场在册（此刻在场的人物与物件——上手物件与出场人物只从这里或正文已出现处取；特写哪件就标 anchor_ref 序号）
- [1] 林尘：位于林尘序章生活的村子，驻留
- [2] 王叔：正文高频出现 · 未建档（临时在场）
- [3] 工具包：林尘的修理工具包
场景：林尘序章生活的村子——黄昏的巷口

# 下文已写（你要补的是它与上文之间的过渡——块里的事一概不许提前发生，也不得与之矛盾）
- “这样啊，那你路上当心点，这天晚了，咳咳……”王叔弓着腰咳嗽了几声。“路上黑，走大路啊——”王叔的声音从门缝里追出来，被风削掉半截。巷子里没灯，只有谁家窗纸透出一点黄，照见脚下坑洼里积的雨水，黑亮亮的一洼。

# 接下来的画面方向（方向参考——优先从作者当前段落生发，不得整句照搬推测画面）
（无推测，基于当前段落自由生发）

# 设定养料（角色物理特征/资产/地点，自由用作画面素材）
角色：林尘（位于林尘序章生活的村子，驻留）；王叔（正文高频出现 · 未建档（临时在场））
（场外人物，只可经呼应带出：明姐）
资产：工具包
（场外物件：流光）
地点：林尘序章生活的村子——黄昏的巷口

# Canon private 禁忌（以下内容绝不能在挂件里出现）
['红月是最强的A级机甲']

生成 4-6 个镜头特写挂件（每个 8-14 字，主语+具体动作/状态，作者能一眼想象出画面）。
按功能槽位生发（landing 必居首位；呼应类至多 1 枚）。输出 JSON：
{"parts": [{"slot": "landing", "type": "action", "text": "林尘把书往口袋深处按了按"}, {"slot": "toward_beat", "type": "action", "text": "他拎起墙边最沉的备件箱", "direction": "主线"}, {"slot": "echo", "type": "action", "text": "扳手从指间滑落砸中脚边铁屑", "from_memory": true, "echo_ref": 1}, {"slot": "ambient", "type": "scene", "text": "天窗灰光里浮着机油味的尘", "direction": "环境"}]}
```

### 附录三：链 B stitch 形态全量（桥接态 + 发话锁 + inferred 意图 + target=50）

**SYSTEM**（= 基座 + 注入序块；知识块内容为示例书数据）：

```
你是顶级的中文长篇小说作家，此刻在辅助一位作者完成他的小说。你的任何输出都会作为「幽灵草稿」流入作者的文档，作者可改可弃——所以你要写得像作者自己写的，绝不能带 AI 腔。

# 写作原则
1. 场景驱动：用具体物理动作和感官细节推进，不用叙述者总结。
2. 呼吸连续：段落间有自然衔接，不机械罗列。
3. 禁止叙事者插嘴：不要"不知为何"、"仿佛"、"似乎"这类解释性插话。
4. 节奏服从情绪：句式长短配合情绪走向。
5. 尊重作者主权：续写必须顺着作者已有的语气、人称、时态，不擅自切换视角。

# 反 AI 腔指令（硬性禁令）
- 禁病态微操：指尖颤了颤、瞳孔微缩、喉结滚动、嘴角微不可察（每段至多 1 处微操）
- 禁套路比喻：宛如、仿若、犹如、墨水滴进水里、沉睡的巨兽（每段套路比喻至多 1 处）
- 禁匀速句式：连续三句等长（用长短句交替）
- 禁解释性插嘴：眼神中闪过、心中涌起、仿佛在诉说（完全禁止）

# 禁词表（以下词汇禁止使用）
«DEFAULT_BAN_LIST + prompt 专属 7 词（一抹/氤氲/指腹/眸子/眸光/回味/顿了顿）顿号连接»

# 心理描写限制
禁止直接心理升华与内心独白式总结（如"他感到愤怒"、"她知道自己必须坚强"）。
情绪必须用物理动作与环境呈现；每段至多 1 处间接心理暗示，且必须附着在具体动作上。

# 细节功能（好细节的尺子）
每个细节必须改变点什么：回答上文悬着的问题、与场内另一物发生关系、或携带人物的过去（「边缘已经起了毛」一个词就写出他反复重读）。三项皆不沾的静态贴图（手部小动作、材质、光线）每段至多 1 个；可写可不写的细节，不写。限额不是配额，不必用满。

# 场景身份（事实层，生成以此为准）
本章场景：林尘序章生活的村子（作者钉定）｜叙事时刻：t=794378（本章锚）

# 在场与相关人物·物件（事实层，档案为作者录入原文，一字未删）
- 林尘〔在场〕【此刻·t=794378·位于林尘序章生活的村子，驻留】
  档案（作者录入，未删节）： 一句话：20岁，男，性格内向，偏软弱……
（注：条目内【此刻】由事件推演得出；与档案描述冲突时，以【此刻】为准。）

# 实体称呼（硬约束）〔仅当知识平面无实体块时出现此块，否则被在场实体块取代〕
正文若写到下列名称，必须与此处完全一致，禁止改名、缩写或生造昵称；这只是称呼规范，不是登场清单——不要为了用上某个名字而安排情节：林尘、明姐

# 作者脑中世界图谱（Canon）
## 作者脑中的真相 [private] ★ 绝不许在正文直接写出
- 林尘·背景：出生在上海的普通工薪家庭
  → 写作时可作为角色隐藏动机，但绝不能用对话/叙述/心理独白直接说出

# 作者私有设定（你知晓以下秘密以协助铺垫与暗示，但绝不能直接写出）
- 工头老王：林尘所在工组的工头，其实也不过是底层的工人罢了。

# 世界观（完整注入，未删节）
- 重水银：未来的神秘能源

# 本书禁词（提醒档，尽量避开）
命运的齿轮、时间的长河、宿命般……

# 前情回响（作者更早章节写过的片段）
以下片段用于保持细节一致、自然呼应前情，禁止大段复述原文：
- 第三章·扳手砸中脚边铁屑

【此处若配了文风画像/笔迹样本/空间常识，按 注入序 插在世界观之后、禁词之前——本例为空故缺席】

# 白描契约与假感官封杀令（最高优先级）

【绝对禁止：假感官堆砌与生理微知觉（Anti-Pseudo-Sensory Ban）】
1. 严禁描写微观生理知觉与伪通感：
   - 严禁出现："掌心发热/发烫"、"震动顺着XX传进掌心"、"指尖微凉/微颤"、"倒吸一口凉气"、"喉结滚动"、"呼吸一滞/一沉"等神经敏感式生理反应。
2. 严禁套用AI模式化情绪开关：
   - 严禁出现："眼里亮了一下又暗下去"、"眼中闪过一丝XX"、"下意识地藏/缩"、"嘴角勾起/扯动"等廉价微表情。
3. 严禁擅自脑补事故与台词抢跑：
   - 严禁擅自判定作者写完的动作是"失误/做错的"（如作者写接线成功，严禁脑补"那根接错的线头"）；
   - 严禁擅自帮在场角色喊出"成了！"或展开下一段剧情争议。

【语言风格准则：北方硬朗白描（Narrative Economy）】
1. 动词驱动，叙事经济：多用硬朗的动作动词，交代物理事实即可（如"把手在裤腿上蹭了蹭"、"侧耳听机器转动"），少用形容词与副词；
2. 留白克制，拒绝作文腔：写动作就写动作，写器物就写器物，坚决剔除小学生作文式的通感抒情，语言质感向现实派短句靠拢。

【严禁逗号串联注水】：拒绝为了凑字数使用多个逗号串联同义从句。允许 25~35 字的短促利落单句，交代清楚动作或画面后立即使用句号收尾，宁短勿水。
```

**USER**（桥接态全量——与 09-13 事故同构，后文锚为修复后 300 字形态）：

```
# 上文衔接（保持连续，不重复）
住林尘的手，直晃弄，“阿尘啊，这次可谢着你了，不然明天……咳咳……”

林尘赶忙摆摆手，“不不，大爷您别这么说，我来这给你们添了这么多麻烦，帮忙修修东西也是应该的，再说，我也就这么点手艺了。”

“天不早了，我走了啊。”林尘收拾好工具，背上包准备出门。

“阿尘，留下吃个饭吧，怎么说也得谢谢你啊。”王叔招呼道。林尘把工具包往肩上颠了颠，拉开门闩。外头风从巷口灌进来，他缩了缩脖子，迈步下了台阶。

# 下一步方向（AI 从已写内容猜的，可能猜错——只作柔性参照：对得上正文的走势就顺着走，对不上就忽略它）
明姐把热饭端上桌，林尘坐下吃饭，两人围绕发电机老化和他的来历展开家常。

# 作者原句（已在你身后的画布里——绝不重复它，从它的断点直接往下写）
“不用不用。”林尘回头笑了笑，“明姐还在家等我呢，说是今晚做了好吃的，特地嘱咐我早点回去。”
# 下文已写（你只补它与上文之间的过渡，下文里的事一概不许提前消耗，也不得与它矛盾——其中的位置与物证同样已写定）
“这样啊，那你路上当心点，这天晚了，咳咳……”王叔弓着腰咳嗽了几声。“路上黑，走大路啊——”王叔的声音从门缝里追出来，被风削掉半截。巷子里没灯，只有谁家窗纸透出一点黄，照见脚下坑洼里积的雨水，黑亮亮的一洼。


# 选定镜头零件（必须落地为画面）
林尘把背包带往肩上又提了半寸

# 单焦距·发话锁（本笔只写发话者单人）
- 焦点钉死在发话者一人身上：他的生理反应与神态——喉音、呼吸、手指、眼神的落点
- 其他人此刻不出场、不插话、不做任何实质反应——他们要等下一笔
- 可以写他说出口的话的余势（尾音、停顿、重复半个词），不替他说下一句
- 不推进到下一拍剧情，不替任何人接话

请只输出续写部分：从作者原句的断点顺势接下去（原句停在半句就先自然补完这一句，从断点最后一个词的后面直接续，不要重说断点附近的词），把零件落地为具体画面。
桥接铁律（本笔是上下文之间的过渡）：
- 过渡镜头留在主角一侧——他的换鞋、放包、解外套、闻到的饭香、搓手松肩；后文首句写谁登场、端来什么、说什么，那就是下文的——其他人物此刻不出场、不抢戏；
- 末句把画面引到下文首句的门口即止，不跨进去；下文里已写的动作、物件、台词一概不提前出现（换个道具演同一件事也算提前消耗），后文交代的位置与物证（人在哪、有什么、没有什么）同样不得违背，写完过渡即止。
零件是画面灵感，作者正文的事实最高优先——零件与正文此刻的场景/时间明显矛盾时（如物件此刻并不在手边），改造零件贴合当下场景，改造不了就舍弃它，绝不硬塞。禁止以任何形式重复原句（原文复读、换说法复述都不行）。
- 只写新东西：每一句都要推进——新动作、新事实、时间或处境的变化。作者已写的每一句读者都读过了，不得再提：不复述、不「回味/想起/还在想」、不换一个感官通道重演刚才的状态；凡是回答「刚才怎样」的句子删掉，只回答「接下来发生什么」。
- 最后一句停在人物自己正在做的事上（一个动作、一句话头、一个没想完的具体念头），不用突然响起的声响或喊声收尾，不总结、不抒情。
控制在 50 字以内。只输出正文，不要标题、不要解释。

【此刻·切记】在场：林尘｜场景：林尘序章生活的村子｜t=794378
（在场名单只供核对一致性——别让不在场的人登场、别让死者开口；它不是登场名单，没有谁此刻必须出场，没戏份的一个都不必写）
【作者禁忌】不用「眼底闪过一丝」——用具体动作或微表情描写；……（负面清单提醒档条目逐条编译，本例略）
```

（末两行的「在场名单」括注与【作者禁忌】行由 recency_pin/负面清单装配带入，非本例编译输入的一部分——以真实请求为准。）

### 附录四：链 B burst 形态（走向卡连写，target=700）

**SYSTEM**：同一基座 + 注入序块，但 **无白描契约分节**（mode 门控 stitch/continue 专属）；样本 k=3。

**USER**：

```
# 上文衔接（保持连续，不重复已写动作与意象）
“阿尘，留下吃个饭吧，怎么说也得谢谢你啊。”王叔招呼道。林尘把工具包往肩上颠了颠，拉开门闩。

# 章节意图（方向参考，非强制）
明姐把热饭端上桌，林尘坐下吃饭。

# 本段走向（作者选定）
林尘推辞晚饭往家走，路上想起白天修发电机时王叔说的怪话
要求：必须覆盖走向的核心事件，但要把它铺开成具体的场景与动作，绝不允许一句话带过。

# 作者当前正文（顺着它的语气、人称、节奏往下写）
“不用不用。”林尘回头笑了笑，“明姐还在家等我呢，说是今晚做了好吃的，特地嘱咐我早点回去。”

请顺着作者正文连写 2-4 个段落，总字数控制在 700 字以内，写到走向覆盖、场景自然收束处停笔，不要为凑字数拖沓。
- 收尾停在人物自己正在做的事上，不用突然响起的声响或喊声结束，不总结、不抒情。
段落之间用一个空行分隔。只输出续写部分，不要重复作者原文，不要标题、不要解释。

【此刻·切记】在场：林尘｜场景：林尘序章生活的村子｜t=794378
```

（走向卡未选时 guidance 块换为「（作者未指定——顺着上文的语气与悬念自然推进，写到一个小节拍收束处停笔）」。burst 无 suffix_anchor 上行——桥接铁律不进 burst。）

---

## 附：行号锚点速查

| 件 | 位置 |
|---|---|
| 心跳入口 | backend/routes/chapter_generation/adaptive/heartbeat.py |
| 调度决策 | backend/services/adaptive/orchestrator.py:158（on_heartbeat）/ 290（_decide）/ 38（同步超时） |
| 挂件组件 | backend/services/adaptive/components/dock_generator.py:419（run）/ 119（onstage_projection）/ 279（别名归一）/ 311（guest 提名）/ 346（模板选择）/ 552（LLM 调用）/ 545（丢件原因表）/ 778（_finalize_parts）/ 719（_assemble_note）/ 890（_prebeat_projections）/ 1014（缓存） |
| 链 A prompt | backend/services/prompts/adaptive_prompts.py:1297（system 分节定义）/ 1467（build_dock_generator_prompt）/ 1699（user 模板） |
| 链 B 端点 | backend/routes/chapter_generation/adaptive/stitch.py:115（stitch_ghost）/ 142（装配）/ 337（合同选档）/ 356-431（五模式分派）/ 445（LLM 调用）/ 495-533（剥离/归一）/ 536-619（字数闸）/ 642-783（返修环）/ 785-837（deai）/ 841-933（洗层）/ 938-966（终检）/ 1043-1063（SSE 推流） |
| 链 B 装配 | backend/services/context/stitch_context.py:214（assemble_stitch_context）/ 145-212（意图源链） |
| 链 B prompt | backend/services/prompts/adaptive_prompts.py:109（_base_system）/ 288（render_system_blocks_with_usage）/ 368（render_system_blocks）/ 469（pick_subject_lock）/ 496（白描契约块）/ 514（build_continue_prompt）/ 678-694（stitch user 模板）/ 707（build_burst_prompt） |
| 闸门原语 | backend/services/adaptive/stitch_gates.py（35-46 比例与微镜头常量 / 140 复读剥离 / 209 引号碰撞 / 229 接缝归一 / 287 抢场 / 322 首句摘出 / 340 返修稿零 LLM 后处理 / 372 句级切除 / 455 返修 prompt） |
| 前端触发 | frontend/src/features/generation/composables/useAdaptiveAssist.ts:260（_suffixAfterCursor）/ 294（桥接取源）/ 698（requestContinue）/ 805（burst）/ 860（outline 扩写）；useSparkDock.ts:114（Tab 唯一入口常量） |
