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

### 意图旋钮去参数化（2026-09-14，第三期审计 `docs/style-parameter-effectiveness-audit.md`）
- 动机两条实证：①`_selector_adjust` 样本排序条件数学空转；②此前 7 次真实生成 sample_ids 全空——根因是作者样本库零库存（零注入元凶），非检索拦截。
- 退役清单：四旋钮 UI/预设/对话滑块下线；`knobs.py` 归档 `_deprecated/style_knobs.py`；`style_cards.style_knobs`/`dialogue_ratio_target` 冻结只读（PUT 剥离）；`render_style_positive` 不再渲染意图行（上限 14→10 行，块配额 2020→1460）；`_selector_adjust` 连同轻指纹设施删除；漂移提示与对账参考带的对话锚改语料实测均值；五维画像手填表单下线。
- 同日新增「收本章为文风范例」一键装填（`samples/from-chapters` 支持 `chapter_id` 单章收编，不限发布状态、幂等 409）。
- 文风收敛两根支柱定稿：亲笔样本 few-shot + 负面清单执法。
