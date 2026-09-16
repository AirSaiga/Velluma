# 文风页（Style）领域档案

> 本文自 AGENTS.md 拆分而来（编辑本领域代码前必读）

权威设计文档：`docs/style-paradigm.md`（三平面分权唯一权威）、`docs/style-module-redesign.md`（S1-S5 设计稿）、`docs/style-parameter-effectiveness-audit.md`（去参数化审计）。施工与事故叙事见 `docs/incidents/style.md`。

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

## 页面结构

- 分区叙事线：①你的字（样本库，每条带指纹速览 chips）②笔迹指纹（句长直方图 + 指标网格 + 高级折叠[五维画像/提炼入口/章级特例]）③负面清单 ④对账（章 CV 与对话占比趋势 SVG，参考底色带 = CV 健康区间/目标±0.2，出带点标红，人话总结含「与语料实测差 >0.15」漂移探测）。
- 两栏仪表盘：①+② 并排 5:7、负面清单+对账并排 1:1；流式宽度 96rem 封顶，<74rem 窗宽塌单列，hairline 分隔归容器 `.section-row`。
- 零状态坡道三幕：`zeroState` = 无样本**且无既有配置**（`hasStyleConfig`）→ 整页 hero 邀请 + 章节收编兜底；1-2 条 → 只长样本+指纹（长成预告细带）；≥3 条且画像空 → 浮出提炼建议。章级特例深链强制 full 防死路。
- **提炼红线**：不落库，过目才存；2s 防抖自动保存。
- 顶部常驻状态条 `StyleStatusStrip.vue`：一句话总结实测指标 + ▶试听滚动锚点，sticky，语料为空不报假数字。
- 直方图规格：柱子贴基线/柱顶计数/按最高桶归一峰值 96px/底线轴；样本列表限高 24rem 内滚。
- `--accent-400` 全局 token（浅色 #9685c2 / 深色 #8b6de8）：直方图渐变/hover 边框/焦点环等 14 处引用消费——该 token 未定义时全部静默失效。
- 高级面板：五维画像只读展示 + 保留「从样本提炼」与字段锁（手填表单已下线）。

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
- 阈值 0.78 **未经实测校准**；校准工具 `scripts/calibrate_semantic_threshold.py`（陈词×变体句/无关句分离度矩阵，手动跑不进 CI）。
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
