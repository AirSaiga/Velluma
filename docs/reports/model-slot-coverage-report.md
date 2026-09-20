> **归档说明（2026-09-19）**：模型槽全景报告（2026-09-15）；权威在 `docs/model-vendor-matrix.md` 与 AGENTS.md。

# 模型槽全景覆盖报告（2026-09-15）

> 调研动机：用户把分析槽指到本地 Ollama 后退出 Ollama，卡片舱照常出卡——实测确认卡片舱走写作槽。本报告全量盘点 `model_config.json` 五个模型通道（reasoning / creative / wash / embedding / deai）在后端**全部真实调用点**上的分工，含伪槽位、回退链与纯算法零 LLM 的易误认区。
>
> 方法：grep 全部 `call_llm_with_usage` / `call_llm` / 包装函数（generate_summary / format_text_with_llm / optimize_selection_with_llm）/ `get_embeddings` 调用点，逐一读取 `model_type` 实参并回溯路由入口与前端功能。排除 `_deprecated/` 与测试文件。行号为 2026-09-15 实况，会漂移。

## 一、槽位解析规则（backend/core/model_config.py）

| 请求的 model_type | 实际落到 | 规则 |
|---|---|---|
| `"reasoning"` / `"default"` | **llm.reasoning**（分析模型） | `default` 是旧别名（model_config.py:184）。**不完整**（缺 model 或 api_key）→ 只借 creative 的连接三件套（api_key/base_url/model），thinking 开关（enabled/effort/exclude）保留自己的（:200-208） |
| `"creative"` / `"light"` / 其他任何字符串 | **llm.creative**（写作模型） | else 分支全落 creative（:189）。`"light"` 是发布链用的**伪槽位**——思考语义也随 creative |
| `"wash"` | **llm.wash**（洗涤槽，UI 已隐藏） | 不完整 → **整体**回退 creative（含 thinking 语义；de_ai_washer 回退时强制关 thinking，:193、has_dedicated_wash_profile :220） |

其他要点：

- `call_llm()` 默认 `model_type="default"` → **分析槽**（client.py:573）。**不传 model_type 的调用全走分析槽**——这是最大的一类认知偏差来源。
- `resolve_model_name`：显式传 `model=` 的调用方可以越过槽位（目前仅连接测试在用，system.py:553/571）。
- `get_default_reasoning_config`：槽位 enabled=False → 发显式关闭（REASONING_DISABLED），不再"不表态"（model_config.py:653-676）。
- embedding `follow_llm=true` → 连接跟随文本槽，**creative 优先**、缺 Key 再看 reasoning（get_embedding_follow_source :248-263）。
- deai 独立配置节，DashScope **原生**端点（非 OpenAI 兼容），enabled+api_key+model 三者齐备才生效，否则逐字节零调用（:302-321）。

## 二、写作模型（creative）负责的全部功能

### 写作台（NLE-ADF 自适应主线）

| 功能（用户入口） | 调用点 | 说明 |
|---|---|---|
| **卡片舱挂件生发**（Tab 召唤/停顿心跳供给） | components/dock_generator.py:566 | 四槽位镜头卡，过采样 4-6 枚 |
| **走向卡 / 未来推测**（心跳 direction_cards） | components/future_projection.py:101 | 走向卡从 projections 提取（heartbeat.py:100/506） |
| **Space 续写 / 细纲胶囊扩写 / burst / open**（stitch-ghost 五模式 SSE） | routes/.../adaptive/stitch.py:450 | 主生成调用 |
| 字数超闸压缩重试 | stitch.py:472、598 | outline ×1.6 压缩、句界截断前 LLM 压缩 |
| 缝合返修环（带稿改写×1） | stitch.py:686、908 | 约束治理二期 repair_loop |
| **涌现事实抽取**（Ctrl+Enter 沉淀） | adaptive/emergent_facts.py:106 | settle 主抽取 |
| **系统自己去读**（切章 auto-read + 全书通读认人 read-entities） | world_read.py:140 → emergent_facts | 复用同一个抽取器 |
| **谋篇建议**（SpinePanel「要建议」） | routes/.../adaptive/spine.py:207、221 | 1×creative + 重试 |
| **文风试衣间**（文风页「▶试听」） | routes/style/feedback.py:257 | /style/audition SSE |
| **残句定点修复**（完稿报告条目「修复这句」） | workflows/sentence_integrity.py:189、199 | /adaptive/fix-sentence，REASONING_DISABLED 显式关思考 |
| **整章重写/章节优化**（⋯ 菜单「审阅」等） | workflows/refining.py:88、98 | /optimize_chapter，refine_draft |
| **世界速记解析**（Alt+N 一句话入账） | world/event_parser.py:284 | /world/parse-event，只产草稿 |
| **候选事件侦察**（settle/finish 抽候选进收件箱） | world/event_scout.py:160 | 三重去重后进待确认池 |
| **世界冷层摘要编译**（digest 双门/回填） | world/digest.py:199 | compile_digest |
| **文本手术**（一致性守卫消费的手术原语） | text_surgery/surgeon.py:139、148 | ADF 守卫 + 返修环句级切除同族 |

### 发布链（publish_v2，伪槽位 "light" → creative）

| 功能 | 调用点 |
|---|---|
| 角色状态增量更新 | generation/publish_v2.py:291 |
| 伏笔账本激活 | publish_v2.py:530 |
| **滚动摘要更新**（书级） | publish_v2.py:695 |

### ADF 引擎（保留但前端无入口）

segment_writer.py:785/797（正文段写作）、pruner.py:204/305、refiner.py:307、beat_patcher.py:321、state_tracker.py:302 —— 全 creative。

## 三、分析模型（reasoning）负责的全部功能

### 写作台

| 功能（用户入口） | 调用点 | 说明 |
|---|---|---|
| **意图反推**（「打算」tab AI 猜测行） | components/intent_inference.py:137 | 三级源链第三级；失败静默降级——**卡片舱不受它影响** |
| **完稿审计**（「检查」tab 完稿体检报告） | components/post_process.py:157 | /adaptive/finish |
| **读者反馈**（「检查」tab 按需触发） | components/reader_feedback.py:98、107 | /adaptive/reader-feedback |

### 提取与审计

| 功能 | 调用点 |
|---|---|
| **实体提取模态**（写作页「提取」预览 analyze SSE） | extraction/content_extractor.py:168（extraction.py:162 调） |
| **真相提取候选**（真相抽屉「提取候选」C3） | canon/extractor.py:256（canon.py:472/518 调） |
| **质量审计 LLM 级**（数据页质量报告） | validation/llm_auditor.py:153 |
| **文风画像提炼**（文风页「从样本提炼」） | style/extractor.py:100 |

### 章节编辑类（⚠ 最反直觉的一组——"像写作"但走分析槽）

| 功能（用户入口） | 调用点 | 依据 |
|---|---|---|
| **选区「AI 润色/改写」**（选中浮窗） | chapter_optimization.py:132 → optimize_selection_with_llm 默认 `default` | client.py:601 签名默认值 |
| **全文格式整理**（⋯ 菜单，LLM 轨） | client.py:343 format_text_with_llm 默认 `default`（text_formatting.py:189 调，超长/异常回退规则引擎） | |
| **灵感生成**（章节页「灵感」模态） | generation/inspiration.py:246、323、369 三处均不传 model_type | /generate_inspiration |
| **章节摘要**（发布时写 chapters.summary） | client.py:317 generate_summary 默认 `default`（chapter_publishing.py:164 调） | ⚠ 与书级滚动摘要（creative）分属两槽 |

### 发布链（v1 路径，仍在发布路由里跑）

| 功能 | 调用点 |
|---|---|
| 角色提取工作流 | generation/character_extraction.py:311（chapter_publishing.py:212 调） |
| 世界终局快照 | workflows/snapshot_extractor.py:155（chapter_publishing.py:303 调） |

### 其他

| 功能 | 调用点 |
|---|---|
| 角色动态状态更新 | generation/chapter.py:108（routes/characters.py:191 POST /characters/{id}/update-dynamic-state） |
| ADF（无 UI）：climax_designer:333 / consistency_guard:311、433 / structure_checker:159 | reasoning |
| 连接测试（两槽各测一次） | routes/system.py:553（reasoning）、571（creative） |

## 四、洗涤槽（wash → 回退 creative）

| 功能 | 调用点 | 说明 |
|---|---|---|
| P1 洗层 + P2 残留 blocker 句级修补 | nlg/de_ai_washer.py:222、232（`_WASH_MODEL_TYPE="wash"`） | ghost 链 GHOST_DONE 前；独立槽尊重自身 thinking，回退 creative 时强制关 |

## 五、向量（embedding：自管 Key 或跟随文本槽）

| 功能 | 调用点 | 通道 |
|---|---|---|
| RAG 向量召回增强（stitch 上下文/记忆召回） | rag/recall.py:45、199 | get_embedding（未配置时纯词法+结构化，向量只是增强层） |
| 记忆写侧索引（settle/finish/发布重建 memory_chunks） | rag/memory_indexing.py | get_embeddings |
| **作者笔迹样本检索**（stitch few-shot / audition / ADF 注入） | style/retrieval.py:185 → repo.search_by_style | get_embedding |
| **完稿语义扫描**（finish 报告「疑似 AI 味变体」） | style/semantic_match.py:114、164 | get_embeddings（未配置第一时刻短路返 []） |
| **语义抢拍闸 shadow**（dock + stitch vs 就近节拍） | validation/semantic_overlap.py:64、95 | get_embeddings_api_only（绕过 SQLite 存储门控） |
| 章节记忆向量 | routes/memories.py:147 | |
| 发布摘要向量 | chapter_publishing.py:172 generate_summary_embedding | |
| 连接测试向量探测（配置了才测） | routes/system.py | |

## 六、deai（独立通道，DashScope 原生端点）

| 功能 | 调用点 | 说明 |
|---|---|---|
| 幽灵短稿抛光 | stitch.py → services/deai/client.py polish_fragment | ≤100 字契约窗、字数闸后洗层前、超时 8s 保底回退原文 |

## 七、纯算法零 LLM（容易被误认走模型的功能）

- 心跳感知决策与 salience 显著性影子（orchestrator，纯算法 0 LLM）
- **canon_watch / canon_checks**（感知带提醒、泄密短语检测、字段级秘密检）——纯词法
- ghost_guard 十检、矛盾检测、在场投影 onstage、意图三级源链的前两级（spine 打算/大纲转化）
- 情境浮卡 context-card（world/scene_slice.py 折叠推演）、active_scene 取景框、outline_nearby 就近节拍
- AI 视角面板（context-preview，纯装配）、usage/约束台账、insights 全部图表

## 八、Ollama 场景影响面（今天的实际问题）

把**分析槽**指到 Ollama 并退出 Ollama 后（槽位完整故不触发 creative 回退）：

- **照常工作**（creative=云端）：卡片舱、走向卡、Space 续写、细纲扩写、谋篇建议、文风试听、世界速记、涌现抽取、发布链 v2 三件。
- **实际已断**（静默降级或报错）：意图反推（意图行悄悄消失）、完稿审计、读者反馈、提取模态、真相提取、质量审计、文风提炼、**选区 AI 润色/改写**、全文格式整理（自动落规则引擎轨）、灵感生成、发布时的章节摘要/角色提取/终局快照、角色动态状态更新。

把**写作槽**指到 Ollama 才会影响卡片舱与续写（Tab 强制重算可立即验证）。
