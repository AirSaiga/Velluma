# NLE-ADF 3.0 施工日志（时效叙事归档）

> 本文自 AGENTS.md 拆分而来，是施工/事故史的唯一追溯处。稳定契约见 `docs/agent/nle-adf.md`。「未提交批内」= 当时同一工作批内的连续施工，事后均已合入。

### 视野配比短窗实测（2026-08-25）

- 观测窗口过短导致生成「驴头不对马嘴」；P1-3 短窗观测数据门达成后实测修复：续写窗 200→800、burst·outline 500→1200；意图块/点火只给大纲就近一两拍；滚动窗改句界净截。

### facts 顶替正文事故（2026-08-25 加固）

- 事故：层1 facts 顶替正文，致挂件与完稿审阅锚定已删除文本 → 立「当前段落取源唯一权威 paragraph_source.py」红线。

### 系统自己去读 / 连点事故（2026-08-25 战略定稿第七问）

- 观察触发权交给系统（详见 docs/reports/auto-read-quiet-learning.md）。
- 实体/地点创建曾连点重复建档 → 服务端按（书+归一化名+类型）幂等。

### 句子级闸门「闭嘴到端」（2026-08-26）

- 段落停在半句时挂件曾照发/回缓存旧件，旧件永留舱内（此前只清响应不清前端）→ 不生发 + `dock_muted=true` + 前端清舱。

### canon_watch 出场判定零命中（2026-08-26 形状修复）

- 实体名挂在 `ent.character.name` 访问链，读顶层 `.name` 恒空 → 出场提醒自诞生起零命中 → 解包修复。

### 慢端点把自动弹舱守卫拖到永不满足（2026-08-27 观测）

- trace 实证：慢端点推测 70s / 挂件 104s，响应落地时「作者须未动笔」的自动弹舱守卫永不满足，「只剩 Tab 活着」→ 停顿档同步钳制 `SYNC_COMPONENT_TIMEOUT_S=12s` + `_sync_inflight` 在飞去重。（自动弹舱后于 2026-09-09 整体退役，见「Tab 唯一」条。）

### 场景锚定两分法（2026-08-27 导师裁决）

- 挂件上手件/氛围件之分：氛围件自由生发不算发明、上手件必须有出处。

### 挂件两轮加固（2026-08-25 就近 + 08-26 场景锚定/文流第一）

- 挂件铁律逐轮成形的过程批次；07 期 §2.5.2 舱顶自解释行「卡住了？点一个画面接着写」替代旧「约百字」后果提示行。

### 感知常驻拍板（2026-08-29 用户拍板）

- 「无论切到哪都不停感知，除非关闭应用」：切页只 detach、`_lastCtx` 快照、章节纪元守卫。

### 前端二轮清扫（2026-08-19 与 2026-08-29 两批）

- 2026-08-19：BS-ADF 步进 UI 12 组件 + `useGenerationSession` 步进调用逻辑删除（-1168 行）。
- 2026-08-29 全量审查二轮（-~1200 行，清单 frontend/_deprecated/README.md）：session 步进尸体群（currentTask/handleBsadfEvent/轮询自愈/段文本函数族/ADF 产物 ref）、api 层 BS-ADF SSE 分发机、幽灵键位 Ctrl+Backspace、degradation.ts、副驾「结构检查」块与「出场角色」卡、数据页「兜底记录」面板、pendingSaveText watch 全部退役。

### 「不知所云」事故两连（2026-08-29）

- 功能槽位化重构（导师裁决：内容分类学→功能分类学——作者必须能看懂「选这枚会发生什么」）；五向 direction 标签系退役（B7 后不再上屏、仅存分析面）。
- 矛盾检测误报遍地：旧 `_has_contradiction` 裸子串查单字对（活/死、有/无、左手/右手、年轻/老）——「生活」×「死寂」「没有」×「毫无」「老周」×「年轻」全成对命中，作者看不出矛盾在哪；且左手/右手语义本就是反的（设定左手残疾+正文用右手=一致）→ 重写 `_find_contradiction` 只留死活对 + jieba token 边界。

### 幽灵手动删除事故（2026-08-29）

- 作者退格/选删亲手删光幽灵，`ghostActive` 残留真值出僵尸态（吃 Tab、禁 Space、卡 authorLane、sticky 卡舱恢复等不到落沿）→ `reapGhostIfDead` 每个文档事务后扫描收割。

### 接缝两护（2026-08-29「续写接不上」事故）

- trace 实证：压缩模型看不到作者断点，把补完断点的首句（『…在这个世道，这句』+『话像块锈铁卡在齿缝里。』）当修饰删除 → 半句悬空、上屏跳到不相关画面 → `_split_first_sentence` 首句物理摘出。
- 半句断点模型从悬空处重启、复读原句**尾缀**（「在这个世道，这句」）而非整句，整句匹配剥不到 → `_strip_fragment_tail_repeat`。

### mimo 实测边界（2026-08 观测）

- mimo-v2.5 对「节拍对白」禁令三连不服从——prompt 杠杆已尽，归模型 A/B 变量。
- mimo 会把未来推测逐条压缩成挂件 → prompt 加「优先从当前段落生发不得整句照搬」。

### 质感治理（2026-09-03，治「太显式」）

- trace 实证 3/3 幽灵 verbatim 消费节拍措辞 → 质感四措施（意图块重框/双轨契约 texture_contract/beat_rush 代码闸/texture 键量化）；同日落地意图感知三连与 finish 质感样本候选。

### 意图感知入舱（2026-09-03 三连施工）

- 外部讨论定稿「重点改善卡片舱」：层2 三级源链 + 「不对」纠正手势 + 线A stitch 兜底链/线B 意图画像/线C 章首接力棒同批落地。

### 专名称呼表穿帮（2026-09-01 修复）

- 旧「书级全量+必须原样使用」让小模型把不在场的敌方机甲硬编进画面（《最终武装》第1章工头拧「流光」螺栓，trace 实证 8-20 起稳定复现）→ `scene_visible_proper_nouns` 按可见文本过滤。

### 句级轻档证伪（P5 观测）

- 知识字段字符截断与实体数上限全数退役的实证依据：「句级轻档」stitch 0/7 采纳。

### 约束治理一期+二期（2026-09-02 两批施工）

- 二期硬闸门加固由用户拍板「可慢不可错」（docs/constraint-governance.md §11）：缝合返修环/拒稿熔断器/两级开关/终检移位/location_jump/语义抢拍闸同批。
- ghost_guard out_of_scene 窗口 ±10 字按事故语料实证定档。

### 语义抢拍闸校准数据（C0 实测已通）

- 实测分离度：近义 0.695 / 无关 0.29；阈值 0.80 为占位、偏高待校准（校准工具 `scripts/calibrate_semantic_threshold.py`，手动跑不进 CI）。

### 卡舱在场制×分镜组×临时通行证（2026-09-08/09 红队三批施工，未提交批内）

- 在场投影/对白分镜组（红队 R4）/Guest Pass 三批成形；主体锁+白描封杀令系 2026-09-09 实测事故植入（未提交批内）。

### 中插桥接 FIM（2026-09-09 落地，未提交批内）

- 骨架跳写场景上线；同日实测「卡片接着文末写」事故：插入点在送别、卡片全接着文末饭桌场景生发（插入点常是空段，旧口径发空串触发回退画布尾=文档末尾）→ 心跳 `recent_text` 桥接态改送光标前 ≤500 字 + dock 桥接态供给切断。
- 2026-09-13 后文锚扩窗：由「紧邻 1-2 句」扩为 ≤300 字（旧窄窗+前端省略号截尾让后文物证缺席，幽灵写出矛盾内容）。

### Tab 唯一入口拍板（2026-09-09 用户拍板）

- 自动弹出全线退役（停顿秒弹/响应侧自动弹/幽灵落定回弹三路封存于 `SPARK_DOCK_AUTO_POPUP=false`）。
- 思考指示器停顿亮灯随之退役（2026-09-10 补齐）：舱不会自己来之后，停顿 2s 灰点预告+4s 心跳亮灯的承诺落空、实测被当成故障 → 停顿全程光标零反馈。

### Tab 重算失败可见化（2026-09-16）

- 本地端点连接错误快速失败不重试 + 舱内朱色报错行 + 缓存旧件明示卡龄——失败不再静默。

### 写作台「桌上一张纸」重构（2026-09-09 08 期，未提交批内）

- 布局总重构（设计稿 docs/design/ux-redesign/08-writing-desk-total-redesign.md）；InlineDock 行间推挤化治旧浮层盖后文 5-6 行（FIM 中插实测）；助手栏由 hover 瞥看改点击制。

### 编辑器本体优化批（2026-09-10，未提交批内）

- 起因：打字/存量稿中文标点不地道 + 粘贴外来色在深色主题下把字弄隐身。
- 存量实证：19 章里 8 章在用 ASCII 三点省略号；某章残留 `<span style="color: rgb(43,45,49)">`（深色纸面上的深色字）。
- 排版死档根因：`RichTextEditor.vue` scoped `:deep(.ProseMirror)` 重复声明把「实验：编辑器排版（宽排）」token 覆写（切 18px/1.8 毫无反应）。
- IAB 真机验证：编辑器零控制台错误挂载、六条输入规则逐条实测、查找条计数/跳转/关闭焦点回流、宽排档 16px/32px⇄18px/32.4px 生效。

### Refinery 润色全家拔除（2026-09-12）

- stage-done→handleGenerated 整章覆写监听连带剪断，stage 轴最小拔除仅存 idle 写入点（后端拔除详见 docs/reports/post-writing-checks-audit.md）。

### AI 视角重设计与轻量化（2026-09-12 09 期 + 2026-09-15 Phase 0）

- 09 期重设计（docs/design/ux-redesign/09-ai-view-redesign.md）；2026-09-15 轻量化重构（Phase 0 报告 docs/reports/ai-view-briefing-feasibility.md，09 稿批注 #4）：顶层新增「战局态势」简报卡；09 稿红线行「空块补录引导」经批注推翻 → 空块全量静音。

### spine×大纲第四弹单轨合流（2026-09-14 施工）

- SpinePanel 重构为叙事引力流面板（docs/reports/spine-outline-merge-feasibility.md 路径 C）。

### 阿尘≠第三人事故（2026-09-11）

- 别名通行证错绑同名不同人（林尘/周尘并存的「阿尘」）→ `_is_alias_or_ambiguous` 尾字归一拦截。

### 意图衰老闸（观测滞后治理）

- 室内转场不在 scene_shift 词表 + 无衰老判定 → 反推意图滞后 11 分钟 → `INTENT_STALE_CHARS=100`。

### DOCK_PIPELINE_VERSION 版本盐沿革（2026-09-13 两连升）

- B2 输入减肥 → v2.2；桥接后文锚扩窗 300 → v2.3（现值 `v2.3_suffix300_20260913`）。规则大改递增即全量缓存失效。

### 词法匹配升级（2026-09-17）

- event_parser 三级匹配升 jieba token 边界（嵌词不成词不命中），名表经 `services/world/jieba_lexicon.py` 注入词典保专名单 token，四处挂点幂等。

### 协作埋点瘦身（2026-09-18，docs/next-phase/05-telemetry-slimming.md，未提交批内）

- 动机：单人项目 n=1 + 不外放，埋点的统计价值前提（人多稀释噪声）永远不成立；路线图一批「视数据再议」缓行件被数据门判无期徒刑。作者裁决删除，代码核实后发现 collab_events.jsonl 上有四个运行时机制消费方——收敛为拆分析层留机制层。
- 手术边界（防误伤的关键发现）：insights「协作」面板里住着 B3 AI 消耗两卡（generation_runs 观测面，设计明确保留）——只摘协作镜像件（四率卡/逐章分布/COLLAB_KIND_LABELS/清空埋点按钮），面板改「用量」tab 保住消耗卡。清空埋点 DELETE 端点保留（机制数据历史重置口，test_collab_clear 锁定）。
- M1 清点结论：保留 5 种（hint_dismiss→静音、ghost_adopt/ghost_discard→sample_prior 先验+收编池、intent_correct→意图纠正教材、ghost_discard_reason→传感器采集），拆除 19 种纯分析。ghost_discard_reason 无后端消费但保留：它是档案在册「失败分类学」的采集 UI，拆发射等于拆 chips 交互面，超出瘦身范围。
- 连带死代码：cards/dock 亮出去重签名变量（只为埋点存在）、BatchAcceptOutcome.chapterId 字段、两处 QuickEventNote 的 quick_note 发射。
- 验证：机制对拍点名跑（test_quiet_learning + test_intent_hardening + test_collab_clear 66 项、style sample_prior 5 项）全绿；全量 1562+381+tsc 净。运行时人工验证挂账：真机收起提醒 ×3 确认静音仍生效（设计 §6 要求，自动化对拍已覆盖同一逻辑）。

### 开章卡与读者清单（2026-09-18，docs/next-phase/01-opening-card-and-reader-ledger.md，未提交批内）

- 两面镜子：开写前（空章「打算」页顶部四行：该揭/别说破/线头/此刻）与完稿后（finish 报告「读者此刻」栏三段清单）——零 LLM 纯查表/章号算术，作者自己的数据折出来摆在眼前。
- 数据底座一处两用：`services/world/reader_ledger.py` 的 `load_reveal_rows`（read_merge_reveals 全量不窗化）同时供开章卡与 reader_ledger；为携带展开内容（规则二：表/里/揭示计划原文）扩了 read_merge_reveals 行文本三件（加键纯增量）。施工坑：扩 field_layer 分支时替换块整体少了一层缩进——ref/append 摔出 entry 循环，被既有 test_field_layers 的窗外缺席断言当场逮住（测试锁的是真契约）。
- 口径纪律（规则一）：L2 别说破空章常见无在场 → 退全书口径 + scope 徽标；L4 无世界书的 zero 兜底时刻整行消失（「第1年1月1日」是噪音不是信息）。在场复用 build_scene_slice 无平行实现。
- 专用计数（05 瘦身口径首发）：`/adaptive/opening-card/touch`（shown/expand）写独立 `data/opening_card_metrics.jsonl`，不接协作事件总线。
- 字号闸实测：chromeFontSize 对拍逮住 10px 徽标/箭头字号——改 --text-xs（12px 最低可读档）。

### 问书（2026-09-18，docs/next-phase/04-ask-the-book.md，未提交批内）

- 行间手势 `??`（AskNoteNode/AskNoteChip 镜像细纲胶囊家族：InputRule + NodeView + Teleport 浮层 + 存盘剥除）；答案幽灵式浅字只读、Esc 蒸发、永不进正文——无采纳语义天然杜绝滑向代笔。
- 六类纯代码直答零 LLM（线头/该揭/距离/上次出场/谁知道/哪章写过）；「谁知道」双路：Y 是真相→belief 四值判定（proposition_status），Y 是角色→Level 0 同场扫描。M2 意图笼硬闸=名单外名字拒答；M3 材料内合成=引用出处 id 必须都在材料袋，编造整稿拒收（宁拒勿假）。
- 施工坑两枚：① record_result 只吃 LLMResult 形状，测试 (text,usage) 二元组 mock 直接炸被 except 吞成 no_match——testing-guide 的「mock 形状」教训反向显形，照 event_scout 先例 tuple 跳过记账；②「哪章写过」整句当关键词永远不命中——分类时显式截疑问词前的关键词 + jieba 抽词兜底（复合问句单串不命中）。
- 落点收窄：正则抓到 last_appearance 但名字解析不出（口语称呼）才回落 LLM 笼——真 not_found（地点不存在/没写过）是正确答案，不重烧。

### 幽灵改稿自动捕获与三键（2026-09-18，docs/next-phase/03-ghost-edit-capture.md，未提交批内）

- deai 数据飞轮收集端零操作化：手动两步五步实质停滞（10 天 2 对）→ 书签位置映射全自动。「不找文字，跟住位置」——采纳瞬间暂存 AI 原样 + 首尾 ProseMirror position（纯内存不进 HTML），RichTextEditor onUpdate 随事务映射（插字后移/删句靠拢/整段塌缩零宽守原地——「删了重打」重新张开照样成对）；保存时对比并更新（同幽灵只留最新版=POST+DELETE），切章定稿聚合提示+按批撤销。
- 三键阶梯（作者逐点拍板）：Tab 采纳（正承诺）/ Enter 暂留（零承诺——最易手滑的键映射到无害动作）/ Esc 丢弃+60s 找回窗（Space 原样重现不重新生成）。上膛纪律：流式期间按键只打断（中止 SSE）不采纳；GHOST_DONE 后 400ms 缓冲窗。一期一个暂留位；暂留最终丢弃=「看过了但没要」强信号（ghost_discard 带 parked 标记）。
- 实现要点：位置映射挂 RichTextEditor onUpdate（扩展层不 import feature 层——GhostTrack 只管未审虚线装饰）；未审标记碰过即消（插件 state 存加标时文本，docChanged 比对）；reapGhostIfDead 对暂留天然豁免（ghostActive=false 不被收割看护）。Enter 旧语义=采纳 → 新语义=暂留：键位状态机 Enter 分支重写，commit 统一出口不变（commitGhost 内挂书签+未审标记，暂留回场 Tab 也走它）。
- 施工坑：mapTrackedPositions 初版用 Math.min/max 单调钳位防漂——直接废掉「删句靠拢/塌缩」两条正路（测试当场逮住：书签永不收缩）；钳位只保留塌缩保护（to<from 时归位）。meta.source 三源（manual_mark/auto_ghost/capsule）落 pairs 后端白名单。
- 对拍：ghostPairTracker.test.ts 17 项（决策纯函数/映射三形态/覆盖语义/final 清账/失败静默/上膛窗）；ghostReap/heartbeatSeam 等既有对拍全数无恙。

### 交叉验证轮（2026-09-18，五稿互检，未提交批内）

对 next-phase 五稿做代码实态互检（不依赖测试绿灯），抓出三枚接缝缺陷当场修复：
- **04 手势冲突实锤（设计稿 §6 预警项）**：chineseTypography 会把「前一位是中文」的半角 `?` 即时转全角 `？`——只认 `??` 则手势在中文正文后永不触发。修：InputRule 改 `[?？]{2}`（半/全角两形态都认）。
- **03 流式判据用错标志**：session 的 `stitching` ref 是旧路径遗物、从未被置真——「未灌完不上膛」形同虚设（流式中 Tab/Enter 可直接采纳半截幽灵）。修：useGhostDraft 新增 `ghostStreaming`（beginGhost 起 / GHOST_DONE·commit·evaporate·reap 止），ghostActionReady 内聚判据。
- **03 暂留位静态位置漂移**：parked 存 from/to 缓存位置，暂留期间作者任何编辑都会使其漂移——丢弃时删错区间=数据损失。修：parked 只存 {source}，一切范围操作现扫 ghostDraft mark（与 findGhostRange 同哲学，对编辑天然免疫）+ parkGhost 重入防御。
- 顺修：父包 `chapter_generation/__init__.py` 端点注释漂移（仍称 events/summary 存在）、三处「Enter 采纳」陈旧注释同步三键语义（session 两处 + useSparkDock 两处）。
- 复验：pytest 1585 / vitest 398 / tsc 净 / **npm run build 过**（本批首次——GhostTrack/AskNote 的 @tiptap/pm 子路径导入有 editorFind 先例无风险）。

### GUI 自动化测试轮（2026-09-19，web-gui-tester 第一档，未提交批内）

环境：复用用户在跑的后端（8002，--reload 已含新代码）与 vite（5176）；`scripts/gui_test_seed.py` 造两本「GUI测试·」书（正文哈希预锚保证零 LLM）。全程 Playwright 角色 click 卡 actionability（疑常驻动画稳定性检查不过）→ 改 CUA 坐标点击；IAB 键盘字符经系统输入法转全角。

**通过**：T1 开章卡（四行三显+空集消失+就地展开表里计划；截图 gui-test-screenshots/）；T4 insights（协作 tab 拆净/用量 tab 存活/空态诚实）；T2 键盘裁决全链（↑↓光标/Enter 采纳+撤销胶囊/Delete 丢弃/批量模态 Space+Enter+引文行）；T3 问答链路 API 佐证六问全对（含距离 2.4 天/章号换算/原句出处）。

**缺陷三枚**：
- **#1a 开章卡开关非即时**（已修）：computed 读 localStorage 无响应性。修=useUiPrefs 增响应式镜像 `openingCardEnabled` + 唯一写口 `setOpeningCardEnabled`（双写存储）；InspectorPanel/AppSettingsModal 改读镜像。
- **#2 问书「知道」正则截短**（已修）：Y 组懒惰匹配无行尾锚取最短（「明姐的身世吗」→「明」）→ canon 标签匹配失败降级同场分支；**单测断言太松假绿**（降级文案也含「知道」）。修=Y 组贪婪+`_strip_knows_tail` 剥语气词；断言收紧至命题分支专属措辞+回归用例（1586 项含新增）。运行时验证：「林尘知道明姐的身世吗」→「按认知账本：林尘知道『明姐的身世』」。
- **#1b 打算分区切章 stale**（挂账未修，预存在）：切章后 SpinePanel 意图框与开章卡均显示旧章数据，tab 往返自愈。代码推演锁定两条疑机制（SpinePanel intentDirty 挡外部同步遗留；OpeningCard 章切换未重取），需浏览器可观察调试定谳——测试中 IAB 输入注入通道整体故障（CUA 点击 0 事件达 window 层，双 tab+reload 复现）无法继续。留真机/浏览器修复会话。

**环境阻断**：？？/[[ 手势在 IAB 合成输入下均不触发（TipTap InputRule 不 firing，对照实验定责环境非手势缺陷）；真机验证挂账。小观察：撤销胶囊 label 用 note（「正文提及」）非 summary，观感欠佳（预存在）。

### 写作台引导体系重构（2026-09-20，审计 §6 一层 4 落地，未提交批内）

用户抱怨写作台「提示不明显缺引导 / 快捷键全堆一处冗杂」。三件同源施工（均前端提示层，不动门控/状态机语义）：

- **渐进引导基础设施**：`composables/useProgressiveHint.ts`——「前 N 次显示、确实显示过的回合落沿计数、看过淡出」，次数持久化 `useUiPrefs.hintsSeen`（velluma_ui_prefs_v1，version 不动靠 spread 兼容合并）；模块级缓存同 key 共享实例（防多处消费各持 ref 漂移）。单测 3 项（初始可见/持久化读回/共享实例）。
- **就地渐进提示两枚**：①幽灵三键阶梯「Tab 采纳 · Enter 暂留 · Esc 蒸发」——CursorLayer 幽灵尾浮层可见条件从「三条数据任一」扩为「或提示未淡出」，与疑点条同锚，上膛后（!ghostStreaming）才显示；②卡片舱首开引导行「数字键直写单镜头 · ↑↓ 浏览 · 点选可吸附多枚 · Esc 关」——09-09 删掉的舱顶自解释行以限次形态回归（常驻版嫌冗杂、零提示又不会用，折中「头几次教你」）。走向舱常驻 hint 补「打字即收起」（B8）；点火卡 hint 10.5px→text-xs。
- **速查表场景化重写**：ShortcutsCheatsheet 从「键位字典」（16 条平铺 3 组、内容漂移）改为「什么时候按什么」四组（写的时候/幽灵在屏/改稿/记进世界与界面），每条=键+动作+条件小字；补齐审计 §2.2 全部漂移（Alt+O/`[[`/↑↓/两卡舱分写/Space ≥4 字门槛/Esc 逐层含走向舱）；新增全局 `?` 键唤出（正文/输入框/IME 组合态不触发）。
- **静默失败反馈（审计 B1/B3/B4/B5）**：空章 Tab（三层静默）→ 正文<4 字明说一次「先写满 4 个字，或点『⚡ 写个开头』」并跳过 summon（激活阈值提成常量 MIN_ACTIVATE_CHARS=4 双处同口径）；requestContinue 空 fragment → reportWarn 一次；Ctrl+Enter 不满足沉淀 → 吞键但解释一次（仍吞：作者意图是沉淀不插换行）；走向舱数字键非写作态 → inAuthoringContext 追加 beatDockVisible（舱开着=写作上下文，Esc/数字键不再死在舱上）+ 关舱解释一次。各提示均每章/每会话一次闸防刷屏。
- placeholder 双态：AI 辅助关闭时不再承诺 Space 续写（审计 §6-E）；开启态 Alt+N 让位给 Tab（卡片舱唯一入口更该占位）。
- 验证：vue-tsc 净 / vitest 48 文件 416 项全绿（413 基线+新增 3）。未做（另属产品决策拍板）：B6 走向卡鼠标路径门控、B7 `[[` 无门、assistEnabled 总开关边界、新手 tour。

### 语义阈值定档与 embedding 批量静默失效（2026-09-24，next-phase 06 F3）

- 三个语义阈值（扫描 0.78 / beat_rush 0.80 / suffix 0.80）原为拍脑袋占位；经 `scripts/calibrate_semantic_threshold.py` 真实语料分离度校测定档：**扫描 0.72**（抓变体 9/20、干净负例 0 误报）、**beat_rush 0.78**（改写式抢拍 6/6 全抓，0.80 漏 1/6）、**suffix 维持 0.80**（0.82 断崖至 3/8）。全过程见 `docs/reports/semantic-threshold-calibration.md`。
- **事故级发现**：该校准顺带实锤 qwen3.7-text-embedding 单批上限 20 条——生产 `_request_embedding` 不分批整包直发，>20 条整体 400 被吞成**全空向量且零报错**；语义扫描（finish，可达 200 段）与两个语义 shadow 检对长文**此前整体失效**。这是「shadow 检长期零命中」的根因之一，再次印证前科教训：**零命中不等于零事件，可能是采集链静默全灭——新检第一轮必须实测确认命中路径可达**。修：`embedding.py` 透明分批（EMBEDDING_BATCH_SIZE=20，串行不并发、单批失败整体降级同既有语义），8 项对拍 + 真实 API 冒烟 25 条通过。
- 结构性遗留（降阈值治不了，报告 §6）：铺陈式抢拍语义上合法抓不住；8-16 字短碎片 vs 长句余弦天花板 0.6-0.87。

### prompt 治理加固 F1/F2（2026-09-24，next-phase 06——与上节 F3 同批施工 `c6cf581`）

- 动机：2026-09-19 prompt 敏感性调研定论「敏感性高且被反复实证，dock 侧管理较好、**stitch 侧基座裸奔**」——微调措辞不炸任何测试、行为静默改变，只能事后翻 trace。
- **F1 stitch 基座快照锁**：`services/prompts/test_stitch_base_snapshot.py` 对基座 17 块常量文案（`_ADAPTIVE_SYSTEM`/续写五律/视点锁四锁/桥接铁律块/五模式 user 模板代表渲染）做 SHA256 锁，改一字即红——「动基座」从此必须显式更新哈希确认（更新程序在测试文件头注释）；对齐质感契约哈希锁先例（`texture_contracts.py`）。
- **F2 快照对拍 + 双跑工具**：`scripts/prompt_snapshot.py` 纯渲染快照落 `logs/prompt_snapshots/{ts}/`（复用现有装配函数，零 LLM 只读 DB）；`scripts/prompt_replay.py` 旧/新 prompt 同模型双跑，确定性闸门（字数闸/禁词/ghost_guard 快检）自动判分，裁决落 `data/prompt_replay_log.jsonl` 供 AI 二次修改反馈。非目标：不做产品化 A/B 平台、本轮不动 prompt 文案本身。
- **F2d 全局版本号**：`services/prompts/prompt_version.py` 持 `PROMPT_VERSION`（首版 `2026-09-24.1`）进 `adaptive_stitch_complete` trace 事件与快照 manifest；与 DOCK_PIPELINE_VERSION 缓存盐职责互斥（一个管措辞归因、一个管缓存失效），递增纪律写入 AGENTS「改 Prompt」条。测试基线随批 1618→1646（快照锁 +20 / embedding 分批对拍 +8）。
