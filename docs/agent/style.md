# 文风页（Style）领域档案

> 本文自 AGENTS.md 拆分而来（编辑本领域代码前必读）

权威设计文档：`docs/style-paradigm.md`（三平面分权唯一权威）、`docs/style-module-redesign.md`（S1-S5 设计稿）、`docs/reports/style-parameter-effectiveness-audit.md`（去参数化审计）。⚠ 三份「文风页设计稿」分工（勿拿错版本）：**功能架构**=`docs/style-module-redesign.md`（S1-S5，含 2026-09-14 去参数化修订警示）；**视觉方言**=`docs/design/style-page-redesign.md`（2026-09-17，头部自述「现状权威：代码」）；**早期 UX 稿**=`docs/design/ux-redesign/01-style-page.md`（11 组件期，已被视觉归一批的 13 组件超越）。施工与事故叙事见 `docs/incidents/style.md`。

## 领域定位

作者笔迹的独立工作台：文风回答「这个作者怎么写」，与世界页正交。入口：AppRail「文风」`/style/:bookId`，代码 `features/style/`（`StyleView.vue` 容器 + presentation 分区组件）。范式三原则：**测量 > 声明**（指纹 code 算）、**范例 > 形容**（few-shot 注入为最大杠杆）、**闭环 > 开环**（每章对账）。

## 三平面分权（架构纲领）

纲领：「prompt 管不住的确定性约束下沉代码层，prompt 只承担概率性偏置」。四平面：

- **偏置（P0）**：blocker 禁忌从负面块第 8 位抽到 user 尾部正面化重钉「不用X——改用Y」，实现 `knowledge_plane.split_prohibition_tiers`。
- **呈现**：P1 洗层 `ghost_wash.wash_ghost_text` 挂 ghost 链 GHOST_DONE 前——blocker+alternative 词边界替换、warning 永不动手、wash 增量字段带原稿快照；前端 `GhostWashChip` 薄荷 chip +「用原稿」可逆学习（`POST /style/wash-prefer-original` 降 warning）。P2 残留 blocker 单次句级修补 + 60s 冷却 + 严格验收。P4 语义 shadow 只落事件。P3 不需要——先生成后播放架构下 P1 天然上屏即净。
- **选择（P5）**：采纳率回流——ghost_token+sample_ids 埋点 → `services/style/sample_prior.py` 贝叶斯先验 ±20% 只调序；漂移锚样 drift_anchor；采纳幽灵收编池 `GET /style/adopted-ghosts` 红线通道 + AI 来源样本每批 ≤1。（P6 旋钮/对话目标编译为样本排序条件 `_selector_adjust` 已随去参数化退役，见施工日志。）
- **审计**：洗率进 style_events 对账。

**架构不变量 = 采纳线：线前可干预 AI 提案，线后作者文本永远只提示。**

## 同一把尺子（指纹规范实现，⚠ 改统计口径前必读）

- `services/style/fingerprint.py` 是句长切分/字数/CV/对话字符统计的**规范实现**；审计侧 `services/validation/code_auditors.py` 从此 import（同名 alias，指标口径零变化）。
- 对拍单测 `backend/services/style/test_fingerprint.py`（19 项）锁定「同一文本指纹侧 CV/对话占比 == RhythmAuditor/DialogueAuditor 指标」——改任一侧算法先跑它。
- 指纹结构：句长族（均值/中位/CV/碎句率/五桶直方图）+ 对话占比 + 段落族（叙述段，排除对白段）+ 标点每千字 + 词汇丰富度 lexical（token_count/ttr/mattr）+ 词级重复 repetition（bigram 重复密度+频次 top5，<50 词不判）+ 修辞密度（复用 `ai_taste_meter`，light 模式省略——章节批量算用 light）+ 质感密度 texture（感官/体感/微动作词族 token 每千词密度 + 命中 top）。
- texture 是参考性指标不进门禁（词典收不全「细写」，数值只供趋势对账与候选挑选，解释权属作者）；`most_textured_window` 挑全章质感最密窗供 finish 样本候选。

## 端点（`routes/style/` 路由包）

包结构：card/samples/fingerprint/feedback/cliches/events 六子模块 + `_deps` 仓储依赖。剥 HTML 规范实现收敛于 `services/utils/html_text.html_to_plain`（唯一权威；`rag/memory_indexing` 保留委托别名）。

- `GET /books/{id}/style-fingerprint`：语料聚合 `aggregate_corpus` 拼接整体测 + 逐样本 light 指纹 + `with_chapters=true` 时最近 N 章**实时计算**章指纹 + reference{cv_healthy, dialogue_target} + 负面清单近 10 章命中计数 `negative_hit_counts`（零命中灰显）。**不建新表不回填 QualityReport**——实时算永远与正文同步且不遮蔽审计报告。
- `POST /books/{id}/samples/from-chapters`：已发布章节→样本收编（`source=published_chapter`，摘章节开头至句界；未发布书回落有正文章节）。剥 HTML 转纯文本（html_to_plain 唯一权威）+ 纯文本判空（`<p></p>` 空文档不误判）+ 已收编章节幂等跳过。支持 `chapter_id` 单章收编（不限发布状态、幂等 409）——副驾「本章」「收本章为文风范例」一键装填消费。
- `POST /style/audition`：SSE 试衣间 + 文风页顶部试听横条。`build_audition_prompt` 与 stitch 四模式共用同一套文风块（「所见即所得」有单测锁定）；`style_override` 可试听未保存草稿；A/B = 基线不注入 vs 当前文风；baseline 轨请求带 chapter_id（扫哪章用哪章生效卡）。
- `DELETE /style-card?chapter_id=`：删章级特例卡。
- `POST /style/scan-negative`：三层禁词扫描，纯 code。
- 收件箱四端点：`style_inbox_items` 表，confirm 负面候选 → negative_list + 同步黑名单；**候选不直接生效红线**；文风页 ✓/✗ 区。
- `GET /style/adopted-ghosts`：采纳幽灵收编池（红线通道）。
- `GET /style/events/summary`：埋点汇总，含采纳率。
- `POST /style/wash-prefer-original`：洗层「用原稿」，降 warning。

## 负面清单四源唯一权威

- `services/style/prohibitions.py` 的 `load_prohibition_set`：SystemCliche + negative_list + book_blacklist + 静态反 AI 词表合并为 ProhibitionSet。双写已消亡——style_blacklist 启动迁移入 negative_list 成冻结列。
- severity 两档：**提醒** = 仅提示与统计（默认）/ **硬禁** = 检查时命中即判不通过（只提示，**绝不自动改正文**）；未设按提醒兜底。文风页每条「提醒 ⇄ 硬禁」可切换、扫描审稿模态标硬禁 chip、完稿报告语义命中可投收件箱（confirm 前可就地改词块，`word`/`alternative` 覆盖字段）。
- 系统陈词库折叠可见 + 单条**本书豁免**：`books.style_cliche_exemptions`（validator/ClichéAuditor/scan 三处消费）。
- 数据页质量报告「＋收入负面清单」抓虫：高频项 → 收件箱。

## 写作规矩（质感契约注册表，2026-09 白描封杀令收编批）

- **唯一权威 `services/style/texture_contracts.py`**：系统级质感约束（保护性写作纪律，非作者个人口味）统一由此管辖。原硬编码在 `adaptive_prompts.py` 的「白描契约与假感官封杀令」（2026-09-09 实测事故后用户逐字拍板）已迁入，文案逐字保留。
- **词令分家**：契约正文 = 话语级行为规矩（禁脑补事故/禁台词抢跑/白描准则/禁逗号注水），stitch/continue 专属末位高服从位注入（`render_system_blocks` 经 `render_texture_contract(key, mode, overrides)` 消费，mode 门控下沉注册表）；病灶词（喉结滚动/嘴角勾起等 13 条）另列**执法词表**（全 blocker、无替代词、2 条正则）。
- **执法词表走旁路不进四源合并**——`ProhibitionSet(ps.entries + texture_enforcement_entries())` 在 stitch 洗层（含 P2 重洗/语义 shadow）、ghost_guard cliche_hit、finish 语义扫描三处扫描前并集。原因：进四源会撞「无卡无样本 prompt 逐字节不变」零变化契约（blocker 会渲染进 user 尾部重钉），且 `hard_constraints` 的 blocker 面会静默杀死挂件/走向卡候选。
- **按书覆盖**：`books.texture_contracts` JSON 列 `{key: {body, updated_at}}`，缺键/空 body=系统默认（prompt 零变化）；块头「最高优先级」框定恒由系统持有，覆盖只换正文。装配：`settings_bundle` 加载 → 四 builder + `StitchContext.system_blocks(_with_usage)` 同参透传（预览/注入同源红线不破）。
- **端点**：`GET/PUT /api/books/{id}/texture-contracts`（`routes/style/contracts.py`，整体覆盖写；PUT {} = 全部恢复默认）。文风页「写作规矩」区（`StyleContractsSection.vue`）：系统默认/本书定制徽标、展开全文、编辑（textarea）、恢复默认；编辑只动正文，执法词表不受作者编辑影响（病灶词自动查改始终有效）。
- 策展口径：执法词表**不带 alternative**（对齐 default_cliches 2026-09-04 审计修复——机械替身词会被洗层字面拼进正文），命中=记录+P2 句级修补；「倒吸一口凉气」不重复收录（SystemCliche blocker 种子已覆盖，尊重系统层开关/豁免）。
- 对拍：`test_texture_contracts.py`（正文逐字/mode 门控/覆盖语义/词表口径）+ `test_continuation_rules.py::TestAntiPseudoSensoryBan`（builder 级端到端）。

## 页面结构

- **渐进式呈现（渐进批 2026-09）：前台亲民工坊 + 深层 Beta 实验室**。前台主视界默认全屏、0 术语：50/50 对等双列（`<60rem` 容器塌单列，纪律同 duo），**双列栏头对称（视觉归一批 2026-09-17）**——左「亲笔字帖」(pencil-square Icon)/右「写作底线」(no-symbol Icon) 同 sec-title 规格，组件内重复标题退役、「已拦截的禁词」降 `.style-eyebrow` 组眉标（style.css 增量工具类）；右列上=规矩四开关、下=禁词标签池+实体输入组 `[输入想屏蔽的词…][加入拦截]`。左列卡片只留场景标签/字数/星标（star Icon），统计噪音不上卡。
- **深层【Beta 实验室】**：页底 `<details>` 折叠舱（视觉归一批升级为舱盖条形态：chevron 旋转+light-bulb+Beta chip+一行内容预告），默认折叠绝不主动打扰——收纳 A/B 试写靶场（基准输出/文风装载输出，文案中立化，贫嘴全洗）、写作规矩整文编辑（高级面）、指纹 9 卡+直方图（"健康区间/带"改"参考区间/带"，取消不达标暗示）、逐章对账、负面清单全量面（系统陈词库/豁免/扫描审稿）。`:open` 受控+`@toggle` 回写+`openBetaLab()` 展开滚动三件套契约不变；details 不拦截 props/emits 链路，组件常驻挂载事件零中断。
- **状态条联动**：`StyleStatusStrip`「去实验室试听」= `openBetaLab()`（展开折叠舱+平滑滚动到位）；收件箱（空则隐藏）保留 full 阶段；零状态坡道 ramp 整页邀请不变。
- **文案大静音**：全页区块只留标题（亲笔字帖/写作规矩/已拦截的禁词/A/B 试写靶场），原理解释与网梗自嘲全部清除。
- **A/B 试写口径**：`POST /style/audition` 单轨 SSE，A/B=前端并发双发；基准输出 `bare: true`（跳过画像+样本只留系统基座）；装载输出=草稿画像+样本（stitch 同源管线）。
- **划词入禁**：在装载输出中划选词语 → 浮签「添入禁词库」（no-symbol Icon）→ 硬禁入清单头（2s 防抖落库）；全前端首处 getSelection 消费，commonAncestor 容器包含判定 + 1~20 字词级 + 卸载清监听。
- **视觉方言与身份（视觉归一批 2026-09-17，设计稿 `docs/design/style-page-redesign.md`）**：全 feature 统一 token 方言——零 `var(--x,#hex)` 二参/零裸 hex/零 @media（Sandbox 断点= `@container stylepage (max-width:48rem)` 塌单列）/字号下限 --text-xs/图标钮 24px、文字钮 28px；卡面七类归 card-std 档（--surface-card）；界面 emoji 全量 Icon 化（❦ 伪元素保留）；「习字簿」身份四件——样本正文/采纳池摘录/收件箱摘录衬线化（--editor-font-family）、字数 chip 量尺规格（衬线+.tnum）、硬禁行朱批 tick（`inset 2px 0 0 var(--cinnabar-bright)`）、直方图基线 --line-strong。
- 直方图规格：柱子贴基线/柱顶计数/按最高桶归一峰值 96px/底线轴（--line-strong）；样本列表 6 条收展+页滚动唯一（无二级滚动）。
- `--accent-400` 全局 token（浅色 #9685c2 / 深色 #8b6de8）：未定义时静默失效。

## 执行层：样本检索与 prompt 注入

- `services/style/retrieval.py` 的 `retrieve_author_samples`：向量流 `search_by_style` 优先 + 新近兜底，k≤2 × 1200 字句界截断，失败 → 空列表。
- 跨书冷启动兜底（B4）：本书零样本回退作者级黄金池 `list_golden_across_books`（其它书 favorite/golden 样本，卡层隔离不动），对拍 `test_cross_book_fallback.py`。
- 场景匹配（P5 C2）：stitch 链路按 rolling 尾 300 字对话占比 >0.35 判 `scene_hint=dialogue`，向量流同型样本 +0.1 软加成、兜底流同档提前；None/general 逐字节零变化。burst 模式 k=3。
- 注入面：stitch-ghost 四模式 prompt 注入「作者笔迹示范」块（学语感禁复制）；ADF `adf.py` 的 `author_samples` 传 List[str]、k=3；`settings_bundle.render_style_positive`（五维中文标签，≤10 行，块配额 1460）经 `to_prompt_context`/`soft_constraints` 暴露 `style_positive`，四 builder 注入「作者文风画像」块；refinery `_build_refinery_context` 填 `author_samples`（polisher 休眠签名接活）+ 负面清单进 `forbidden_terms`；`/optimize_selection` 注入文风约束块；`adf/refiner.py` 经 `_build_style_contract` 统一口径。
- **零变化契约**：无文风卡/无样本的书 prompt 逐字节不变（`test_style_injection.py` 锁定）。
- dock 零件 prompt 有意不注入画像（8-14 字零件吃不到画像，防膨胀轻路径）。

## 交互环

- 选中浮窗「黄金片段」双写文风样本库（golden_snippet 通路）；💛 6 秒撤销胶囊（useToast/Toast 加 action）。
- 「这不像我」→ 负面候选投收件箱（旧直写 style_blacklist 退役）；「改得更像我」 = 既有「AI 润色/改写」（带文风）。
- 章级覆盖：文风页高级面板「编辑对象」切换 + `?chapter=` 深链 + 副驾「本章文风」卡。
- 禁词审稿：`POST /style/scan-negative` + 负面清单区审稿模态（替换/收入清单/忽略逐条裁决）；de_ai_washer 增 `extra_banned_words`（defat 带章节上下文）。

## 意图旋钮（已退役，列档备查）

- 四旋钮 UI/风格预设/对话滑块已下线；`services/style/knobs.py` 归档 `_deprecated/style_knobs.py`；`style_cards.style_knobs`/`dialogue_ratio_target` 两列**冻结只读**（PUT 一律剥离）；`retrieval._selector_adjust` 连同轻指纹设施已删除。
- `render_style_positive` 不再渲染意图行（上限 10 行，块配额 1460）；漂移提示与对账参考带的对话锚 = **语料实测均值**（heartbeat/fingerprint 端点）。
- 文风收敛两根支柱 = 亲笔样本 few-shot + 负面清单执法。
- 不做项：E4 指标制导维持不做（无数据支撑，走向卡已是柔性机制）。

## 台账化、漂移提醒与埋点

- `author_samples.era/favorite`：语料聚合只取近期；兜底检索收藏优先。
- `style_cards.fingerprint`：写穿缓存，读仍实时算。`style_cards.locked_keys`：画像字段锁（🔒 逐字段/全部锁定 = 特殊文体让位，提炼跳过锁定字段）。
- from-golden：存量黄金片段去重导入 + 文风页入口。
- 心跳漂移提醒：章尾 3000 字同尺测量，`kind=style_drift` 并入 canon_hints 走感知带，按内容长度缓存。
- 埋点：本地 `data/style_events.jsonl` 零上报，kind = audition/golden/⚠/收件箱/预设/抓虫。

## 语义扫描（embedding 抓「换字逃逸」）

- `services/style/semantic_match.py` 的 `semantic_scan_text`：精确匹配（prohibitions.finditer）抓不到的改写变体（如「眼底闪过一丝」→「眼底掠过一抹」）用 embedding 余弦相似度补位。
- 挂点**仅在** `/adaptive/finish` 报告 `semantic_hits`（前端报告区「疑似 AI 味变体」块，作者裁决）；**不进收件箱/scan-negative/任何 SSE 流式路径**（红线）。
- `is_embedding_configured()` 门控：未配置/SQLite 默认路径第一时刻短路直返 []，行为逐字节零变化。
- 切段与指纹同一把尺子（split_sentences + 超长句逗号细切）；批量向量走 `embedding.get_embeddings`（单次全量 input）；模式向量进程级缓存（key 含 model/dims/patterns）。
- 阈值 **0.72**（2026-09-24 实测定档：抓 9/20 变体、干净负例 0 误报，依据 `docs/reports/semantic-threshold-calibration.md`；校准工具 `scripts/calibrate_semantic_threshold.py`，手动跑不进 CI）。
- 单测 `test_semantic_match.py`（14 项合成向量锁行为）。

## 章级特例卡（整卡覆盖语义）

- 章级卡（`style_cards.chapter_id` 非空）存在即该章**完整文风定义**：负面清单/正面画像/段落节奏整卡生效（旋钮/对话目标列已冻结、随卡亦不生效），书级不再参与（前端编辑本是「书级基底快照+全量保存」，语义自洽）；无章级卡回退书级，无卡逐字节零变化。
- 统一入口 `StyleCardRepository.get_effective_card(book_id, chapter_id)`，消费点：settings_bundle（主通路 → stitch-ghost 五模式/dock/context-preview/finish 审阅/ghost_guard）、ADF、选区改写、defat、心跳漂移参照、finish 语义扫描、quality-report 审计上下文（`_build_audit_context`）、scan-negative（扫哪章用哪章生效卡）、试听 baseline 轨。
- **保持书级**：指纹对账参考带（书级仪表盘）、收件箱确认写路径。
- prohibitions 四源权威与 prompt 排序零改动。
- 单测 `services/context/test_chapter_style_override.py`（7 项：repository 三态 + bundle 整卡覆盖/回退/无卡零变化）。

## 笔迹 vs 声纹切分

叙述文风（句长/语域/浓淡/冷热）走文风页（画像+样本 few-shot）；角色对话腔调走世界实体档案 `speech_style` 字段（world_bridge 注入，未另建 voice 字段，单测锁定通路）——两条通路在生成上下文里自然汇合。

## 样本创建链路契约

`AuthorSampleRepository.create_with_embedding` 走 dict 契约（内部 `model(**payload)`，传 ORM 实例恒 TypeError）；`era` 参数须由路由转发至 repository（schema 有 era，路由不得静默丢弃）。
