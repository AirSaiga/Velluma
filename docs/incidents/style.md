# 文风页施工日志

> 时效叙事自 AGENTS.md 拆分归此，是本信息的唯一追溯处。技术契约见 `docs/agent/style.md`。

### S1 落地：文风页独立（2026-08-18）
- 文风页自设定页迁出为独立工作台（AppRail「文风」`/style/:bookId`）；旧 `components/StyleCardManager.vue` 删除、拆解迁入 `features/style/`。

### S2 执行层接通（2026-08-18）
- 此前 adaptive 只消费负面清单；S2 起文风经范例/画像/润色三路真正进入生成链。零变化契约由 `test_style_injection.py` 锁定。

### S3 交互环闭合（2026-08-18）
- 试衣间、黄金片段/这不像我、收件箱、章级覆盖、禁词审稿五件落地。
- 💛 的 6 秒撤销胶囊当时未做（toast 无 action），S4 补齐。

### S4 抽象与切分（2026-08-18）
- 设计稿 S1-S4 全部落地，唯一不做项 E4（指标制导维持不做：无数据支撑，走向卡已是柔性机制）。
- 意图旋钮四档上线（`style_cards.style_knobs` JSONB + `services/style/knobs.py` 档位权威表），含四维五档按钮 + 对话旋钮（目标值落 `dialogue_ratio_target`，原滑条退役）+ 四风格预设（冷峻短句/绵密抒情/口语白描/章回古雅，一键填旋钮+画像模板）。
- 「这不像我」负面候选投收件箱，旧直写 style_blacklist 路径退役。

### S4+ 补全批次（2026-08-18）
- 台账化（negative_hit_counts）、陈词本书豁免、四列落地（era/favorite/fingerprint/locked_keys）、from-golden、心跳漂移提醒、style_events 埋点，六件随批落地。

### S5 UX 打磨与样本链路修复（2026-08-18）
- `--accent-400` 事故：该 token 从未定义，文风页 6 组件 14 处引用（直方图渐变/hover 边框/焦点环）全部静默失效，是直方图柱子隐形的根因——已全局补齐（浅色 #9685c2 / 深色 #8b6de8）。
- 样本创建链路事故：`AuthorSampleRepository.create_with_embedding` 把 ORM 实例传给 `BaseRepository.create(payload: dict)`（内部 `model(**payload)`）恒 TypeError——手动粘贴/章节收编/黄金片段导入/收件箱确认四条创建通路曾全部 500；已改 dict 契约。另 schema 有 `era` 但路由曾静默丢弃，已补转发。
- 零状态坡道门闸修正：旧 StyleCardManager 时代有配置的书不再被折叠成邀请页（`hasStyleConfig` 判定扩入旋钮/对话目标——后随去参数化改为不含退役字段）。

### 章级特例卡消费接通 Phase 4（2026-08-24）
- 整卡覆盖语义接通全部消费点（settings_bundle 主通路/ADF/选区改写/defat/漂移参照/语义扫描/审计上下文/scan-negative/试听 baseline）。

### 语义扫描任务包 D（2026-08-24）
- embedding 相似度抓「换字逃逸」（如「眼底闪过一丝」→「眼底掠过一抹」），挂点仅 `/adaptive/finish` 报告 semantic_hits。阈值 0.78 未经实测校准，校准工具 `scripts/calibrate_semantic_threshold.py` 手动跑、不进 CI。

### 质感密度批次（2026-09-03）
- 指纹新增 texture 键（感官/体感/微动作词族每千词密度 + 命中 top）；`most_textured_window` 挑全章质感最密窗供 finish 样本候选。

### 设定中心页整体退役（2026-09-05）
- 文风已迁独立页是前奏；设定中心（含旧 CharacterPanel 等）整体删除，AppRail「设定」项移除。

### 路由拆包与剥 HTML 收敛（2026-09-11）
- `routes/style/` 拆为 card/samples/fingerprint/feedback/cliches/events 六子模块 + `_deps` 仓储依赖。
- 剥 HTML 双实现合并：原 `routes/style._plain_text` 与 `rag/memory_indexing._html_to_plain` 两个逐字节双实现收敛为 `services/utils/html_text.html_to_plain` 唯一权威，memory_indexing 保留委托别名。

### 跨书冷启动兜底 B4（2026-09-13）
- 本书零样本时回退作者级黄金池 `list_golden_across_books`（其它书 favorite/golden 样本，卡层隔离不动），对拍 `test_cross_book_fallback.py`。

### 意图旋钮去参数化（2026-09-14，第三期审计 `docs/reports/style-parameter-effectiveness-audit.md`）
- 动机两条实证：①`_selector_adjust` 样本排序条件数学空转；②此前 7 次真实生成 sample_ids 全空——根因是作者样本库零库存（零注入元凶），非检索拦截。
- 退役清单：四旋钮 UI/预设/对话滑块下线；`knobs.py` 归档 `_deprecated/style_knobs.py`；`style_cards.style_knobs`/`dialogue_ratio_target` 冻结只读（PUT 剥离）；`render_style_positive` 不再渲染意图行（上限 14→10 行，块配额 2020→1460）；`_selector_adjust` 连同轻指纹设施删除；漂移提示与对账参考带的对话锚改语料实测均值；五维画像手填表单下线。
- 同日新增「收本章为文风范例」一键装填（`samples/from-chapters` 支持 `chapter_id` 单章收编，不限发布状态、幂等 409）。
- 文风收敛两根支柱定稿：亲笔样本 few-shot + 负面清单执法。

### 白描封杀令收编进文风模块（2026-09-17）
- 动机：「白描契约与假感官封杀令」原为 adaptive_prompts.py 硬编码孤儿（2026-09-09 实测事故后用户逐字拍板），与文风模块并排存在、互不隶属；词级病灶只靠 prompt 劝、无代码执法。
- 收编形态：唯一权威迁 `services/style/texture_contracts.py`（契约注册表；正文逐字保留），词令分家——话语级契约仍走 stitch/continue 末位 prompt 块（支持按书覆盖 `books.texture_contracts` 列，缺键=系统默认零变化）；病灶词 13 条另列执法词表（全 blocker、无替代词、2 正则；「倒吸一口凉气」不重复收录——系统陈词层已覆盖）。
- 执法词表旁路合并（不进四源）：stitch 洗层（含 P2 重洗/语义 shadow）、ghost_guard cliche_hit、finish 语义扫描三处扫描前 `ProhibitionSet(ps.entries + texture_enforcement_entries())`。进四源会撞「无卡无样本 prompt 逐字节不变」零变化契约（blocker 渲染进 user 尾部重钉）且 hard_constraints 的 blocker 面会静默杀死挂件/走向卡候选——两条都是前科防线。
- 端点与 UI：GET/PUT `/api/books/{id}/texture-contracts`（整体覆盖写，{}=全部恢复默认）；文风页新增「写作规矩」区（系统默认/本书定制徽标、编辑、恢复默认；导航锚点第 5 位）。编辑只动契约正文，块头「最高优先级」与执法词表恒由系统持有。
- 对拍：test_texture_contracts.py（14 项：正文逐字/mode 门控/覆盖语义/词表口径）+ routes/style/test_texture_contract_routes.py（8 项：净化口径/合并视图）；既有锁定套件（test_continuation_rules 的 TestAntiPseudoSensoryBan、test_c3_mode_differential、test_budget_allocate、test_stitch_context、test_style_injection 零变化契约等）原样全绿——prompt 面逐字节零变化，行为变化仅限执法面（病灶词从无人管 → 记录+P2 修补+疑点条+完稿计数）。

### 字帖工坊 ＆ 现场验枪靶场重塑（2026-09-17，靶场批）
- 动机：原页面"计算语言学实验室"说教感——右侧黄金区被 9 张统计卡片霸屏、无即时验证闭环、发现坏词无法就地抓虫。
- Phase 0 红队四问（动工前纪律）：①audition 单轨 SSE，A/B=前端双发，旧基线"半穿衣"（画像仍注入）→ 后端加 `bare` 开关真裸奔；②全前端无 getSelection 消费方，靶场为首个——commonAncestor 容器包含判定防全局冲突；③`features/style/` 无 __tests__ 目录，折叠统计零断言风险；④沿用容器查询 <60rem 塌单列纪律。
- 契约注册表升级：拍板正文拆 4 条可开关规矩（span 级，全启渲染 SHA256=5f87fd9e…438c 与拍板原文逐字节一致——段1 段头随族内存亡，双关全关不留空头）；覆盖层新增 `disabled_rules`（body 整文覆盖优先），GET 视图带 rules+enabled+customized_via。
- 新页：左 45% 字帖与底线（字帖卡片去统计噪音/清洗库回车加硬禁/规矩四开关）+ 右 55% 验枪靶场（单行引子+🎯 双发 A/B+栏② 划词「🚫 添入禁词库」1~20 字词级）+ 底部研究数据逃生舱（details 默认折叠）；StyleAuditionBar 退役删除。

### 布局降噪、靶场解耦与 Tab 化（2026-09-17，降噪批）
- 动机：靶场霸屏右侧黄金视口挤压高频资产（字帖/禁词/规矩）；区块挂 2~3 行说教文案；锚点导航与双列布局冲突；残留虚线占位框。
- Phase 0 红队三问：①Tab 切换状态驻留——v-show 三 pane 不卸载，草稿/开关/验枪结果零丢失（无需 KeepAlive）；②`features/style/` 无 __tests__ 目录，旧锚点类名/旧文案零测试绑定（grep 实证）；③50/50 双列沿用容器查询 <60rem 塌单列。
- 变更：顶栏三模式 Tab（笔迹工坊默认/现场验枪独立视口/语言学数据）；工坊 50/50——左样本字帖（标题「样本字帖」，副标删）+右规矩四开关上/拦截库下（实体输入组 `[输入词汇…][+ 拦截]`，虚线框退役）；状态条 ▶=直切验枪 Tab；旧 anchor-nav/workbench 45:55/lab-accordion/grow-teaser 全部退役。

### 渐进式呈现：前台亲民工坊 ＆ 深层 Beta 实验室（2026-09-17，渐进批）
- 动机：学术化验单与日常写作设置混一屏，生涩指标+网梗文案认知过载；确立"渐进式呈现"定位——前台零门槛工坊，深层留有余地的 Beta 实验室。
- Phase 0 红队三问：①折叠不解耦——details 不拦截 props/emits，组件常驻事件零中断（StyleKnobsSection 已退役不存在，StyleAuditionBar 上批已删，均为 stale 引用）；②features/style 无 __tests__（第四次核实），无可见性断言；③50/50 沿用容器查询 <60rem 塌单列。
- 变更：三 Tab 退役，前台工坊=默认主视界（左亲笔字帖/右🛡️写作底线列头+规矩开关+已拦截的禁词池带计数+实体输入组）；A/B 靶场/指纹/对账/整文编辑/负面清单全量收纳页底 `🧪 文风实验室 (Beta)` details（:open 受控 + @toggle 回写，状态条 ▶=openBetaLab 展开+滚动）；页头改「文风设定」；指纹/对账「健康区间/带」全改「参考区间/带」；靶场文案中立化（基准输出/文风装载输出，删"裸奔/油/没思路"）。

### 文风页 UX 重设计·视觉归一批（2026-09-17，docs/design/style-page-redesign.md）
- 动机：渐进批/靶场批两轮功能改版后页面存在两种视觉方言——靶场批 4 组件（BanList/RulesSwitches/Sandbox/Contracts）全用 px+`var(--不存在的token, #hex)` 二参回退（--accent-warm/--bg-subtle/--bg-card/--bg-input/--danger-soft/--text-link/--text-tertiary 七枚 token 实为零定义，已 grep 核实），深色主题白卡穿帮；Sandbox 还残留 `@media 560px` 视口断点（违反 01 期 S-03 零 @media 纪律）。
- 分工沿 UX 重构既定模式：teacher-kimi-2 出设计稿（docs/design/style-page-redesign.md，接口零变更/容器 script 零改动为红线），主 agent 审稿后施工。
- 结构两刀：①工坊双列补齐对称栏头（左 ✎ 亲笔字帖 / 右 ⊘ 写作底线，同 sec-title 规格），组件内重复标题退役、「已拦截的禁词」降 `.style-eyebrow` 组眉标（style.css 唯一增量工具类）；②实验室 details 升级舱盖条（chevron 旋转+light-bulb+Beta chip+内容预告行），:open/@toggle/openBetaLab 三件套不动，状态条按钮改「去实验室试听」。
- 方言归一：靶场批 4 组件样式全量重写为 token 方言（映射表在设计稿 §2.1）；全 feature 二参 var/裸 hex/@media/小于 12px 字号 grep 清零；Sandbox 断点改 `@container stylepage (max-width:48rem)`。
- 习字簿身份四件（全 token 化，十态成立）：样本正文/采纳池摘录/收件箱摘录衬线化（--editor-font-family）；字数 chip 量尺规格（衬线+.tnum）；硬禁行朱批 tick（`inset 2px 0 0 var(--cinnabar-bright)`）；指纹直方图基线归 --line-strong。
- emoji 全量 Icon 化（星标/箭头/折叠符/✎/✕/🛡️/🧪/🎯/🚫/🪶，❦ 伪元素保留）；「+ 拦截」改「加入拦截」；档位钮/图标钮点击目标统一 28/24px（--control-h-*）。
- 卡面归一 card-std 档（--surface-card）：上传卡/样本卡/规矩卡/A·B 靶栏/契约卡/收件箱卡/扫描命中卡七类。
- 验收：grep 机检六项零命中 + vue-tsc 净 + vitest 370/370 + build 过 + 浏览器实测三景（浅色工坊/深色禁词区含朱批 tick/深色靶场）全部通过；测试禁词经 UI 加入→删除还原（API 复核 negative=0）。
- 顺手修正：docs/agent/style.md 页面结构节「样本列表限高 24rem 内滚」陈旧描述（06 期起已是 6 条收展+页滚动）随本批一并校正。
