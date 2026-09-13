# 文风数据机制全景报告

> 2026-09-13 · 只读代码调研合成（HEAD 8b0db19，行号为当日工作区实况）
> 范围：文风数据从哪来、如何进入生成链、产出后被怎么修、反馈如何闭合——后端服务层 / prompt 编译 / stitch 路由 / 前端消费面全链。
> 与既有文档的分工：`docs/style-module-redesign.md`（S1-S5 设计稿）、`docs/style-paradigm.md`（三平面分权纲领）均为设计意图；本报告是**实现现状的逆向记录**。

---

## 0. 一图流

```
                 ┌────────────── 数据资产 ──────────────┐
                 │ style_cards（画像/旋钮/负面清单/章级覆盖）│
                 │ author_samples（样本库 + 向量）          │
                 │ system_cliches（系统陈词 35 条种子）     │
                 │ style_inbox_items（候选收件箱）          │
                 └──────┬──────────────────┬───────────┘
                        │                  │
        测量层 fingerprint.py（同一把尺子，零 LLM）
                        │                  │
   ┌────────────────────▼─────┐   ┌────────▼──────────────────┐
   │ 偏置平面（生成前，进 prompt）│   │ 反馈闭环（采纳后回流）        │
   │ · render_style_positive    │   │ · ghost_adopt/discard 埋点 │
   │ · retrieval few-shot k≤2   │   │   → sample_prior ±20% 调序 │
   │ · prohibitions 四源禁词    │   │ · 采纳幽灵收编（AI ≤1/批）   │
   │ · blocker 正面化重钉 user 尾│   │ · 「这不像我」→收件箱→清单   │
   └────────────┬─────────────┘   │ · wash-prefer-original     │
                │                  │ · style_events.jsonl 台账  │
   ┌────────────▼─────────────┐   └────────▲──────────────────┘
   │ 呈现平面（生成后，代码执法）  │            │
   │ · wash_ghost_text P1 替换  │   ┌────────┴──────────────────┐
   │ · P2 残留句级修补(严格验收) │   │ 审计平面（只提示不动手）      │
   │ · deai 抛光（邻位）         │   │ · finish 语义扫描 0.78     │
   └────────────┬─────────────┘   │ · 心跳漂移 style_drift      │
                │                  │ · 对账 SVG / negative_hits  │
                ▼                  └───────────────────────────┘
        GHOST_DONE{text, wash, ghost_token, sample_ids…}
                │
        采纳线 ═══════════ 幽灵可洗可改 | 作者文本永远只提示
```

核心命题：**prompt 管不住的确定性约束下沉代码层（洗层），prompt 只承担概率性偏置（few-shot+画像）；测量 > 声明，范例 > 形容，闭环 > 开环**（`docs/style-paradigm.md`）。

---

## 1. 数据资产：三张表 + 四源禁忌面

### 1.1 style_cards（`backend/models/style.py:60-88`）

| 列 | 类型 | 说明 |
|---|---|---|
| chapter_id | UUID nullable | **null=书级；非 null=章级整卡覆盖**（Phase 4 语义：章级卡存在即本章完整文风定义，负面清单亦整体替换，非合并） |
| positive_profile | JSONB dict | 五维画像：sentence_rhythm / vocabulary / register / opening_habit / ending_habit |
| negative_list | JSONB list | `[{word, alternative?, severity}]`，severity 缺省=warning，仅显式 "blocker" 原样收（白名单在 prohibitions.py:255-257 与 confirm 侧 feedback.py:94-113 双侧执法） |
| dialogue_ratio_target | Float | 对话占比目标 0-1（**不进 prompt 文本**——编译为检索排序条件，见 §3.2） |
| paragraph_rhythm | Text | 段落节奏一行 |
| style_knobs | JSONB | `{rhythm|register|density|warmth: tier 1-5}`，缺键=自动档不注入 |
| locked_keys | JSONB list | 画像字段锁：被锁键不被再次提炼覆盖（extractor 侧尊重） |
| fingerprint | JSONB | **写穿缓存**（fingerprint 端点回写），读路径仍实时算——它不是读缓存，是「最近一次快照」 |

### 1.2 author_samples（`models/style.py:91-118`）

| 列 | 类型 | 说明 |
|---|---|---|
| scene_type | String(50) | dialogue / action / lyrical / suspense / general（默认） |
| content | Text | 样本正文 |
| embedding | **Vector(1536)** | pgvector；检索走 cosine_distance（SQLite 默认路径下恒 NULL→检索退新近兜底） |
| source | String(50) | manual / golden_snippet / published_chapter / adopted_ghost |
| era | String(16) | recent（语料聚合与兜底优先）/ early（仅存档，聚合剔除 routes/style/fingerprint.py:68-72） |
| favorite | Boolean | 兜底流优先 + 漂移锚加成 -0.1 |

样本四条入库通路：手动粘贴、章节收编（`POST /samples/from-chapters`）、黄金片段双写（选中浮窗）、采纳幽灵收编（文风页采纳池）。

### 1.3 style_inbox_items（`models/style.py:147-170`）

`kind` ∈ {negative_candidate, sample_candidate} + payload JSONB + status pending/confirmed/dismissed + source。
**红线（:152-155）：候选绝不直接生效，作者裁决即闸门。** confirm 负面候选 → 写书级卡 negative_list（按 word 去重 feedback.py:155-156），不再双写已冻结的 `books.style_blacklist`（:159-160）。

### 1.4 四源禁忌面（`services/style/prohibitions.py:172-285`，唯一权威）

`load_prohibition_set(db, book, style_card)` 层序即优先级、同 pattern 先到先得去重：

1. **SystemCliche 表**（:229-241）——DB 失败降级种子库；本书豁免 `books.style_cliche_exemptions` 仅剔除系统层（:238-239）
2. **style_cards.negative_list**（:243-257）——severity 白名单
3. **books.style_blacklist**（:259-275）——三形态兼容（str 分隔符 / list[str] / list[dict]），**冻结只读的历史列**
4. **anti_ai_rules.DEFAULT_BAN_LIST.banned_words**（:277-283）——15 个静态反 AI 词；banned_regexes/manned_micro_actions 不进合并（那是 ai_taste_meter/text_sanitizer 专属，边界声明 :38-41）

任何一层失败跳过该层绝不抛异常。产物 `ProhibitionSet`（:81）构造时编译全部条目（regex 原样编译、否则 re.escape、坏 pattern 静默跳过 :96-99），`finditer(text)`（:151-155）产 `(match, entry)` 供来源感知消费——洗层按 entry.severity/alternative 分流。

系统陈词种子（`default_cliches.py`）共 35 条：ZH_CLICHE_BLOCKER 9 条**故意不带 alternative**（:49-53 注释：高频网文腔无可机械替换的替身词，误填编辑指令会被洗层字面拼进正文——残留走 P2 修补）；ZH_CLICHE_WARNING 13 条带替代表；HOUSE_VOICE 5 条含 2 条正则（`不是.*而是` 等）；EN 8 条。

---

## 2. 测量层：指纹 = 同一把尺子（`services/style/fingerprint.py`，531 行）

纯确定性计算，零 LLM 零 IO；**审计侧 `services/validation/code_auditors.py` 从此 import 规范原语**——两侧指标口径由 `test_fingerprint.py` 对拍锁定（改任一侧先跑它）。

### 2.1 指纹结构（`compute_text_fingerprint` :408，组装 :438-450）

| 族 | 键 | 备注 |
|---|---|---|
| 顶层 | char_count / word_count / dialogue_ratio | dialogue_ratio=引号内字符/去空白字数（引号对表 ：73-78） |
| 句长族 | sentence_count / mean / median / **cv** / short_sentence_ratio / 五桶直方图 | 碎句=≤5 字（_SHORT_SENTENCE_MAX_CHARS=5）；句数<10 恒 0.0 防小样本误判 |
| 段落族 | paragraph_count / len_mean / short_paragraph_ratio | **仅叙述段**（排除引号开头段 :136）；段数<4 不判占比 |
| 标点 | dash/ellipsis/exclaim/question per_1k | |
| 修辞 | metaphor/micro_action/transition per_500 + ai_taste_score | light 模式整族跳过（十组正则较重，章节批量用） |
| lexical | token_count / ttr / mattr | <30 token 置 None；MATTR 滑窗 100、O(n) 增量维护 |
| repetition | bigram_repeat_ratio / repeated_bigrams_top | <50 词不判；bigram 频次≥3 计重复；top5 频次降序+字符串升序保确定性 |
| texture | texture_per_1k / hits / top | 55 词五族词表（视觉光线/听觉/嗅觉/触温/身体微动作）:315-330；**参考性指标不进门禁**，解释权属作者 |

### 2.2 三个派生函数

- `aggregate_corpus(contents, max_chars)` :454——**拼接后整体测量**（分布族指标需大样本，非逐条平均）；超限按完整样本条从新到旧取。调用方上限 `_CORPUS_MAX_CHARS = 200_000`（routes/style/fingerprint.py:40）。
- `most_textured_window(text)` :366——句界对齐双指针滑窗（120-320 字），挑质感最密段；消费方 `settle_finish.py:187-210`（finish 完稿时挑「本章最会细写的一段」直投文风收件箱 sample_candidate，60 字头幂等去重）。
- `compute_style_drift_hint(text, target, cv_lo, cv_hi)` :494——<400 字返 None；判据三选一：对话占比偏离目标 ±0.2 带 / CV 低于健康带（AI 腔匀速征兆）/ bigram 重复率 ≥0.15（thresholds.py:81），产出最多 2 条 notes。

---

## 3. 偏置平面：生成前注入（最大杠杆）

### 3.1 装配源头 `services/context/settings_bundle.py`

主入口 `load_chapter_settings_bundle` :282，其中：

- **:414-416 生效卡**：`StyleCardRepository.get_effective_card(book_id, chapter_id)`（repositories/style_card_repository.py:67-80）——章级覆盖优先、回退书级。同语义消费点共 7 处：stitch（经 bundle）、心跳漂移 heartbeat.py:407、选区改写 chapter_optimization.py:157/232、试衣间/扫描 feedback.py:238/318、ADF adf.py:131、finish settle_finish.py:166。
- **:425-434 禁忌面**：`load_prohibition_set` 四源合并；异常置 None（消费侧降级空）。

**render_style_positive（:660-694）**——画像+旋钮唯一渲染口径：

```
五维 positive_profile → "- 句长节奏：{文本截 120 字}"     （_PROFILE_LABELS :651-657）
paragraph_rhythm     → "- 段落节奏：{截 80 字}"
style_knobs          → render_knob_lines 意图行（"语域意图：偏文——……"）
                       ⚠ 节奏行跳过（:691-692）——节奏已编译进检索选择器
最终 "\n".join(lines[:STYLE_POSITIVE_MAX_LINES])   ← budget.py:257 = 14 行封顶
```

关键设计（:682-685 注释，P6）：**dialogue_ratio_target 与节奏旋钮不写进 prompt**——可测维度编译为样本检索排序条件（`retrieval._selector_adjust`），prompt 画像只留样本筛选表达不了的全局维度。
⚠ **文档-代码偏差**：函数 docstring（:661）与 AGENTS.md 写「≤10 行」，实际生效常量 14（budget.py:257 注释自认「五维≤5+节奏1+目标1+旋钮≤4 理论 11 行，14 是防御性封顶」）。

暴露面（三口同源）：`to_prompt_context` :151 / `soft_constraints` :218（注释：「此前 adaptive 只消费负面清单，作者填得最认真的正面画像进不了主线」）/ stitch 装配直取 :277。禁词侧：`hard_constraints.banned_words`（:177-181，60 条封顶）与 `banned_words_blocker`（:185-189，2026-08-25 A2 修复：提醒级词不再把挂件静默杀死）。

### 3.2 样本检索 `services/style/retrieval.py`（few-shot 供给）

`retrieve_author_samples_with_meta` :200——返回 `[(sample_id, 截断文本)]`（sample_id 供采纳埋点回指）。

**向量流**（query 非空且 embedding 已配置）：
1. `repo.search_by_style(embedding, book_id, scene_type, limit)`——pgvector cosine_distance 升序（repositories/author_sample_repository.py:73-111）
2. hint 生效时超采 `fetch_limit = k×5`（:81）候选
3. **vec_adjust 四因子重排**（:237-244）：
   - 场景加成：对话场景（rolling 尾 300 字 dialogue_ratio > 0.35，scene_hint.py:51/55）同型样本距离 **-0.1**（:78）
   - 采纳先验：`d ÷ sample_prior_factor`（0.8-1.2，见 §5.1）
   - 旋钮选择器 `_selector_adjust`（:158-178）：rhythm 档 vs 样本句均长偏差（锚表 `{1:10.0 … 5:38.0}` :155）、dialogue 档 vs 样本对话占比偏差——`0.1×min(1,|Δ|/15)` / `0.05×min(1,|Δ|/0.3)`
   - 漂移锚：`drift_anchor=True` 且样本 favorite → -0.1
4. `_cap_ai_source` :184——**`_AI_SOURCE_CAP = 1`（:71）：source=adopted_ghost 每批 ≤1 条，防幽灵自蒸馏**（AI 学 AI 越学越窄）

**兜底流**（未配 embedding / 向量化异常 / 零命中）：`list_by_book` 新→旧取 k×3，五元组排序 `(favorite, era≠early, scene_match, prior_key, selector_adj)`（:260-268）。
**失败红线**（模块头 :49）：任何异常降级空列表，调用方 prompt 零变化。

**剂量权威表**（budget.py）：stitch 默认 k=2（:225）、burst k=3（:230）、每条句界截断 1200 字（:240，`truncate_sample` retrieval.py:99——先找「。」，切点落在前半窗改试「！？…」，仍不行整窗原样）。

### 3.3 禁词分层 `services/context/knowledge_plane.py`

**split_prohibition_tiers（:590-606，P0 核心）**：
- blocker 条目从负面块抽走，编译为**正面化行** `不用「{pattern}」——{alternative}`（无替代表则「换成具体的动作或物件」），≤6 行
- 重钉位置 :563-566：拼进 `kv.recency_pin` 的 `【作者禁忌】` 段——与【此刻·切记】同屏，位于 **user prompt 尾部**（模型对头尾服从最高）
- 负面块（render_knowledge_view :528-541）只留 warning 档：「本书禁词（提醒档，尽量避开）」顿号串

理念（:529-532 注释）：「负面块的执法职能移交呈现平面洗层，prompt 只承担偏置」。

### 3.4 prompt 编译 `services/prompts/adaptive_prompts.py`

**render_system_blocks 块序**（:340-361，注入序权威——事实层全前于文风层）：

| # | key | 标题/形态 | 备注 |
|---|---|---|---|
| 1 | scene | 场景身份 | kg 预渲染，不进预算分配 |
| 2 | warm | 本章打算/spine 温卡 | |
| 3 | entities | 在场与相关人物·物件 | 空时插回旧 proper_nouns 专名兜底块（:362-364） |
| 4 | canon | 作者脑中世界图谱（Canon） | by_key，allocate 后 |
| 5 | secrets | 作者私有设定（你知道但绝不能直接写出） | |
| 6 | worldview | 世界观 | |
| 7 | relations | 人物关系（此刻活跃） | |
| 8 | **negative** | 本书禁词（提醒档） | 只剩 warning 档 |
| 9 | echoes | 前情回响 | |
| 10 | spatial | 空间常识 | |
| 11 | **style_positive** | **作者文风画像** | :123-133 |
| 12 | **author_samples** | **作者笔迹示范** | :143-152 |
| 13 | anti_pseudo_sensory | 白描契约与假感官封杀令 | **仅 stitch/continue**（:353-360），末位最高优先位 |

软块（画像/样本/canon/回响等）打包 `BudgetBlock` 走 `allocate` 按模式预算裁剪（:319-336）；知识平面五块预渲染完整文本不进 allocate（:311-314）。

**两个文风块的精确文案**：

- 画像块（:123-133）：`# 作者文风画像（贴合其笔迹写作，软约束）\n以下是这位作者的文风特征，续写的语感、句式与节奏都应向它靠拢：` + render_style_positive 逐行
- 示范块（:143-152）：`# 作者笔迹示范（学其语感、节奏与用词习惯——只学写法，禁止复制内容或意象）` + `【示范 N】\n{样本}` + 收束句 `（以上是这位作者亲笔写的字。你接下来写的每一句，都应该像同一个人写的。）`

**四模式 + 试衣间差异**：

| builder | 行号 | mode | 文风注入 |
|---|---|---|---|
| build_continue_prompt | :514 | stitch/continue | 画像+样本块 + 白描契约 + 主体锁 `_SUBJECT_LOCK_TEXTS`(:451-466) |
| build_burst_prompt | :700 | burst | 画像+样本块（k=3）；无白描契约 |
| build_outline_expand_prompt | :820 | outline | 画像+样本块 |
| build_opening_prompt | :968 | open | 画像+样本块 |
| build_audition_prompt | :929 | ""（不进预算） | **同一个** `_style_block_def`/`_samples_block_def`（:951-952，标题逐字节一致）——「所见即所得」由 test 锁定 |

**dock 挂件有意不注入画像**（证据）：`build_dock_generator_prompt` :1461-1476 签名无 style_positive/author_samples；唯一文风注入是禁词表占位符 `«BANNED_WORDS»`（:1505/:1535，取 hard_constraints 前 30）。理由（settings_bundle.py:166-169）：8-14 字零件吃不到画像，防轻路径膨胀。

**禁词共享基座** `_ADAPTIVE_SYSTEM`（:54-78）含 `# 禁词表（以下词汇禁止使用）`；prompt 侧追加词 `_PROMPT_ONLY_BANNED`（:46-47，「一抹」「氤氲」「回味」「顿了顿」等 7 个）。

### 3.5 次级消费面

- **选区改写**：`_build_selection_style_context`（chapter_optimization.py:146-187）= 画像 + 负面前 30 条「避免用词」 + 样本 k=1×800 字「笔迹示范」；注入 selection_rewrite.py:201-207 user prompt `【文风约束（改写后的文字要像同一个人写的）】` 块（章节大纲之前）
- **心跳漂移**：`_style_drift_hint_for_heartbeat`（heartbeat.py:381-426）——每次心跳测章尾 3000 字 vs 生效卡 dialogue_ratio_target；产出 `{kind: style_drift}` 并入 canon_hints 感知带（可被 quiet_learning 静音）；缓存键=章 content 长度（:394-397，与 spine 的 md5 键不同）；**同一函数返回值在 stitch.py:139 复用为 drift_anchor 探针**——写作时正在漂移 → 检索时收藏样本加成
- **ADF**（adf.py:131）：author_samples k=3 + 画像（引擎保留路径）

---

## 4. 呈现平面：生成后清洗（代码执法，`services/style/ghost_wash.py`）

**wash_ghost_text（:65-118，P1）**——纯函数零 LLM 零 IO：

1. 只动手 `severity == "blocker"` 命中（**warning 永不动手**）
2. 重叠区去重：**短 pattern 让位长 pattern**（防「深邃」误伤「深邃的眼」内的替换），等长保先到（:81-93）
3. 有 alternative 且非 regex → 字面替换；否则仅记录为 residual
4. `WashResult.original_text`（:116-117）：发生任何替换时保留洗前全文，否则空串——**违规原稿不进任何可回退通道的对偶面：合法替换的原稿必须可回退**

**P2 残留句级修补**（调用方 stitch.py:858-886，不在 ghost_wash 内）：
- 触发：residual_hits 非空（blocker 命中但无替代表）
- 节流：`_GHOST_REPAIR_COOLDOWN_S = 60s`（:89）+ 章级在飞去重 `_GHOST_REPAIR_INFLIGHT`（:88）
- `build_repair_prompt`（ghost_wash.py:121-137）：非重生成——residual 前 5 条逐处列「『pattern』→改用『alternative』或同义具体表达」，明示其余句子一字不改
- **严格验收**（stitch.py:879-883）：修补稿重跑 wash_ghost_text，零 residual 才采纳；限流/失败/超时静默降级为 chip 呈现——**终点永远是作者裁决**

**在 stitch 链中的位置**（stitch.py）：装配(:142) → 生成(:441) → 字数闸(:460/:537) → 返修环(:633-774) → **deai 抛光(:783-826) → 洗层(:848-886)** → ghost_guard 终检(:933-947) → 标点归一(:1031) → GHOST_DONE(:1042)。与返修环/deai 的次序语义：返修环管「世界一致性硬违规」（切除/重写），deai 与洗层管「文本味道」，ghost_guard 终检扫最终稿不再返工。

**P3 不存在的原因**（paradigm 定稿）：先生成后播放架构下，P1 在上屏前完成，天然「上屏即净」，无需第三道。

---

## 5. 反馈闭环（四条回流线 + 一本台账）

### 5.1 采纳率先验（`services/style/sample_prior.py`）

```
GHOST_DONE 带 ghost_token + sample_ids（stitch.py:838-839）
  → 前端 Enter 采纳 useGhostDraft.ts:352-358 dispatchCollabEvent('ghost_adopt',
      {ghost_token, sample_ids, wash_hits, text[:400]})；Esc 蒸发 → ghost_discard(:413-417)
  → POST /adaptive/event → data/collab_events.jsonl（events.py:54-90，5MB 轮转）
  → sample_prior.load_adoption_stats()（:60-106，按 mtime 缓存，只认 ghost_adopt/discard
      且 detail.sample_ids 为 list，键 book_id:sample_id 累计）
  → factor = 0.8 + 0.4 × (adopted+1)/(adopted+discarded+2)   （拉普拉斯平滑，:117）
  → 回灌 retrieval vec_adjust：d ÷ factor（:240）——只调序不筛选
```

无数据恒 1.0；全采纳 1.2、全拒绝 0.8——**±20% 封顶**。

### 5.2 采纳幽灵收编

`GET /style/adopted-ghosts`（feedback.py:407）倒序扫 collab_events 的 ghost_adopt，正文去重回读近 30 条；文风页「AI 写的、你留下的」池逐条「收为样本」（StyleAdoptedPool → createSample source=adopted_ghost，在飞守卫防双击重复入库 StyleView.vue:316-333）。**`_AI_SOURCE_CAP=1` 在检索侧执法**（§3.2）——收编通道永远开放，但每批 few-shot 里 AI 来源最多占 1 席。

### 5.3 洗层可逆学习

前端 GhostWashChip「用原稿（保留这些词）」（CursorLayer:100-104 → WorkspaceView:222-232）：先用 original_text 重灌幽灵区，再逐 pattern 调 `POST /style/wash-prefer-original`（feedback.py:353）——词在书级 negative_list 且 blocker → 降 warning；属系统陈词层 → 进 `books.style_cliche_exemptions` 豁免（:392-402）。作者用行动教洗层闭嘴。

### 5.4 负面候选回流

写作台选中浮窗「这不像我」（RichTextEditor.vue:196-222）→ 收件箱 negative_candidate（word=选中前 16 字 + source_text 佐证）→ 文风页 StyleInboxSection ✓ 确认（确认前可就地改词/替代表 overrides）→ 写书级 negative_list。完稿报告语义命中（semantic_hits）同走收件箱（InspectorPanel.collectSemanticHit:379-397，source=semantic_scan）。

### 5.5 语义扫描（仅 finish，只提示）

`semantic_scan_text`（semantic_match.py:136-203）：精确匹配抓不到的「换字逃逸」（眼底闪过一丝→眼底掠过一抹）用 embedding 余弦补位。门槛三连：`is_embedding_configured()` 为假（SQLite 默认恒假）第一时刻短路返 []；候选只收非 regex 且 ≥4 字 pattern；切段与指纹同一把尺子（split_sentences+超长句逗号细切，≤200 段）。阈值 0.78 **未经真实写作校准**（校准脚本 scripts/calibrate_semantic_threshold.py 手动跑）。**红线：只进 finish 报告 semantic_hits，不进收件箱直写/任何 SSE 流式路径**——AI 味变体的最终解释权在作者。

### 5.6 台账 `data/style_events.jsonl`（services/style/events.py:27-43，零上报）

事件 `{ts, book_id, kind, detail}`；后端写入点：ghost_wash（stitch.py:899，hits/replaced/repaired 四计数）、ghost_semantic_shadow（:918，P4 只落账）、deai_polish（:820）、wash_prefer_original（feedback.py:404）。前端 POST kinds：golden_to_sample / not_like_me / audit_collect / apply_preset / audition_run(_ab) / inbox_confirm / inbox_dismiss。`GET /style/events/summary` 返回 `{total, by_kind, inbox_accept_rate}`（收件箱接受率=confirm/(confirm+dismiss)）。

---

## 6. 一次 Space 续写：文风数据经过的全部站点（时序）

1. **POST /adaptive/stitch-ghost**（stitch.py:114）
2. 漂移锚探针 `_style_drift_hint_for_heartbeat`（:139）——章尾 3000 字 vs 生效卡对话目标；漂移中 → 后续检索 favorite 样本 -0.1
3. **assemble_stitch_context**（stitch_context.py:214）：
   a. bundle 装配 → get_effective_card 章级整卡覆盖（settings_bundle:414）→ prohibitions 四源合并（:425）
   b. render_style_positive ≤14 行（:277）
   c. retrieve_author_samples_with_meta（:286-293）：向量流 + 场景加成 + 采纳先验 + 旋钮选择器 + AI≤1，产出 sample_ids
   d. build_knowledge_view → blocker 正面化重钉进 recency_pin【作者禁忌】（knowledge_plane:566）
4. context_manifest trace 逐块记 chars（:295）
5. **build_continue_prompt(mode="stitch")**（:414）→ render_system_blocks 按序：…禁词（提醒档）→ **文风画像 → 笔迹示范【示范 N】** → 白描契约末位；user 尾部 pin_line 带【作者禁忌】
6. call_llm_with_usage（creative, t=0.7, :441）
7. 字数闸（:460/:537）→ 返修环（:644/:692）→ deai（:798）
8. **洗层 wash_ghost_text**（:855）；残留 → P2 句级修补（:869-881，60s 冷却+零残留验收）
9. ghost_guard 终检（:933）→ 标点归一（:1031）→ **GHOST_DONE**{text, wash, deai, ghost_token, sample_ids, repaired, breaker_open}（:1042）
10. 打字机播放 → 作者裁决：Enter 采纳 / Esc 蒸发 / 删光收割 → ghost_adopt/discard 落账 → **sample_prior 下次检索换序（回到站点 3c，闭环）**

---

## 7. 架构不变量与红线（违约即架构崩塌）

| 不变量 | 实现锚点 |
|---|---|
| **采纳线**：线前（幽灵）可洗可修，线后（作者文本）永远只提示 | 洗层只挂 GHOST_DONE 前；scan-negative/语义扫描/漂移全部只提示 |
| **零变化契约**：无文风卡/无样本的书 prompt 逐字节不变 | test_style_injection.py 回归锁定四模式 |
| **候选不直接生效** | style_inbox confirm 才写 negative_list；提炼不落库（card.py:94-97）须显式 PUT |
| **同一把尺子** | code_auditors import fingerprint 原语，test_fingerprint 对拍 |
| **AI 来源 ≤1/批** | retrieval._cap_ai_source（防自蒸馏） |
| **洗层可逆** | WashResult.original_text 快照 + 用原稿端点降档/豁免 |
| **先测量后声明** | dialogue_ratio_target/节奏旋钮不进 prompt，编译为检索排序 |

## 8. 本次调研发现的文档-代码偏差（2 处，均为低危）

1. **「≤10 行」陈旧措辞**：render_style_positive docstring（settings_bundle.py:661）与 AGENTS.md 文风节均称画像 ≤10 行；实际 `STYLE_POSITIVE_MAX_LINES = 14`（budget.py:257，注释自认 11 理论/14 防御封顶）。
2. **ghost_wash 模块 docstring 引用的 `test_ghost_wash.py` 不存在**：对应测试已并入 `test_style_paradigm.py`（该文件 import wash_ghost_text/build_repair_prompt 可证）。

## 9. 前端消费面速查

**文风页**（features/style/，StyleView.vue 1161 行容器 + 10 个 presentation 纯组件）：StyleSampleSection（①你的字，ramp hero 形态）/ StyleFingerprintSection（②指纹+直方图+高级折叠：五维编辑/提炼/字段锁/编辑对象）/ StyleKnobsSection（③意图四维五档+四预设+实测锚偏差提示）/ StyleNegativeSection（④负面清单 severity 切换+命中 chip+陈词豁免）/ StyleReconciliationSection（⑤对账双 SVG）/ StyleAuditionBar / StyleInboxSection / StyleAdoptedPool / StyleScanModal（三按钮裁决：替换/收入清单/忽略）/ StyleStatusStrip / StyleExtractModal。
零状态三幕判定：`zeroState`=无样本且无任何配置（StyleView.vue:117-126）；`growthStage` ramp→early→full（:132-137，?chapter= 深链强制 full）。

**写作台**：选中浮窗「黄金片段」（RichTextEditor.vue:164-193，6s 撤销胶囊）/「这不像我」（:196-222）/ GhostWashChip 用原稿（CursorLayer:100 → WorkspaceView:222）/ GhostRepairedChip（纯展示）/ 副驾「本章文风」卡（InspectorPanel.vue:398-430，本章专属 vs 跟随全书徽章 + ?chapter= 深链源头）。

**API 层**：`styleApi` 25 方法（services/api/domain/index.ts:421-637，注意不在独立 style.api.ts）。

---

## 附：跨文件关键数值速查

| 数值 | 值 | 锚点 |
|---|---|---|
| few-shot k | stitch 2 / burst 3 / 选区 1 / ADF 3 | budget.py:225/230；chapter_optimization.py:177 |
| 样本截断 | 1200 字句界（选区 800） | budget.py:240；truncate_sample retrieval.py:99 |
| 场景判定 | dialogue_ratio > 0.35，窗口=rolling 尾 300 字 | scene_hint.py:51/55 |
| 场景加成 / 漂移锚 | 距离 -0.1 / favorite -0.1 | retrieval.py:78/:242 |
| 采纳先验 | 0.8-1.2，平滑 (a+1)/(n+2) | sample_prior.py:37-38/117 |
| 画像行数 | 14 封顶（docstring 称 10，见 §8） | budget.py:257 |
| blocker 重钉 | ≤6 行进 user 尾部【作者禁忌】 | knowledge_plane.py:604 |
| 语义阈值 | 0.78（未校准），≤200 段/每 pattern 3 条/总 20 | semantic_match.py:65-70 |
| P2 修补 | 60s 冷却 + 在飞去重 + 零残留验收 | stitch.py:87-89/879 |
| 漂移判定 | ≥400 字才测，章尾 3000 字，CV<0.35/重复≥0.15/对话±0.2 | fingerprint.py:505；thresholds.py:81 |
| 语料聚合上限 | 200,000 字，era≠early | routes/style/fingerprint.py:40/68 |
| AI 来源样本 | 每批 ≤1 | retrieval.py:71 |
| 系统陈词种子 | 35 条（blocker 9 无替代表） | default_cliches.py:118-149 |
