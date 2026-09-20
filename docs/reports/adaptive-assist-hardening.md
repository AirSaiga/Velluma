> **归档说明（2026-09-19）**：治理批次档案（2026-08-25），P0 已完成；问题清单式文档，部分已修部分为历史，勿整体当现状。

# 写作台辅助层治理计划（2026-08-25）

> 来源：2026-08-25 辅助写作后端调研 + 痛点核实（双子智能体调研报告 + 主会话逐行对照）。
> 本文档只列问题、修法、风险与验证方式；**实施顺序即批次序**，每批独立可提交。
> 问题编号沿用分析报告的 A/B/C 分组编号，便于回溯。

## 背景：问题全景

| # | 问题 | 位置 | 类别 |
|---|------|------|------|
| A1 | 走向卡整章缺席/冻结在开篇：layer3 混装 `__dock__`/`__canon_watch__` 缓存项，`need_proj = not projections` 永假；置信度恒 ≥0.5 刷新通道死 | orchestrator.py:199-217 / world_model.py:183 | 结构 bug |
| A2 | 提醒级负面清单词穿透到生成侧硬拦（`_violates` 不分 severity 全丢弃），含 15 个静态反 AI 词 | prohibitions.py:130-132 → settings_bundle.py:180-184 → dock_generator.py:195-203 / future_projection.py:128-138 | 语义矛盾（已出过一次事故） |
| A3 | outline 超字截断砍掉「引向 after_text」的结尾，双端锚定断头 | adaptive.py:831-836 | 生成错误 |
| A4 | stitch 碎片拼回裸子串判定，标点/空白微差 → 开头重复作者原句 | adaptive.py:837-839 | 生成错误 |
| B1 | must_hit 已达成判定过松（任一 3 字片段命中全文即达成）→ 主线推动力提前消失 | direction_weights.py:200-214 | 信号失真 |
| B2 | spine 锚点进度误 hit：通用关键词 + 重启后 growth=全文 + 等长改写吃旧缓存 | adaptive.py:283-321 | 信号失真 |
| B3 | 大纲就近节拍已写判定同构噪声（3 字片段过半命中即已写）→ 就近铁律被部分抵消 | dock_generator.py:178-192 | 信号失真 |
| B4 | canon_watch 角色出场裸子串匹配（「高山」命中「高山上」） | canon_watch.py:77-90 | 噪音（info 级，低害） |
| C1 | stitch/continue 短窗仅 200 字，对话场景装不下一轮 → 重复前文/细节矛盾 | budget.py:364 | 生成错误 |
| C2 | 推理模型 REASONING_DISABLED 仍烧 ~800-1000 隐藏思考 tokens，小预算余量薄 → 「续写产出为空」 | adaptive.py:799-801 | 生成失败 |
| C3 | finish critique 只吃正文头 6000 字，长章后半不在审阅视野 | post_process.py:98 | 审阅偏差 |
| C4 | `_activate_sync` 对在跑异步任务 await 后必重跑 → 同参数 LLM 双调用 | orchestrator.py:304-316 | 成本 |
| C5 | 异步组件失败前端完全静默，「辅助层偶尔什么都不出」不可分辨原因 | orchestrator.py:282-283 | 可观测 |
| C6 | event_scout 无世界实体直接返回 0，轻设定书收件箱永空且不可见 | event_scout.py:97-99 | by design 但不可见 |

---

## P0 —— 一行级结构修复（高收益、零行为面风险，先行）

> ✅ 已完成（2026-08-25，未提交）。三项拍板均按建议执行：提醒词进 prompt、
> A1 加意图版本过期、C1 短窗不动。落地清单：
> - `world_model.set_projections` 覆写保留 `__dock__`/`__canon_watch__` 缓存项；
> - `future_projection` 产出打 `intent_version`；`_decide` 的 need_proj/签名只看
>   真实推测 + 意图版本不一致即过期（缺键旧推测刷新一次）+ 无意图不再空激活；
> - `ProhibitionSet.words(severity=)` 增档位过滤（缺省全量零变化）；
>   `hard_constraints` 新增 `banned_words_blocker`；dock/future 的 `_violates`
>   只拦 blocker 档（手工构造 hard dict 无该键回退全量旧行为）；prompt 禁词块
>   （adaptive_prompts.py:954 等）维持全量未动。
> - 测试：新增 `services/adaptive/test_projection_freshness.py`（12 项）+
>   `test_prohibitions.py::TestWordsSeverityFilter`（5 项）；全量 495 绿。

### P0-1 走向卡冻结修复（A1）

**修法**（两处缺一不可）：
1. `_decide` 的 `need_proj` 判断与 dock projection 签名计算，统一过滤带 `__dock__`/`__canon_watch__` 标记的缓存项——「有无真实推测」只看真推测。
2. `set_projections` 覆写 layer3 时保留既有缓存标记项（否则 future_projection 一跑就把 dock 缓存清了，缓存命中却取不到件）。

**配套增强**（可选，同批做）：projection 失效条件加「intent_version 变化」比对——意图重算后旧推测理应过期，现状是意图变了推测不变。

**风险**：极低。过滤只影响「是否激活」与缓存命中判定，不改产出格式。
**验证**：对拍测试模拟「停顿（无意图，canon 缓存占位）→ 写到 200 字意图反推 → 再停顿」序列，断言 future_projection 被激活；放 `services/adaptive/` 旁既有对拍文件族（test_dock_nearby.py 同款做法）。

### P0-2 severity 穿透修复（A2）

**修法**：`ProhibitionSet.words()` 增 severity 过滤参数（缺省维持全量，零变化契约不破）。**生成侧校对**（dock `_violates`、future_projection `_violates_constraints`、ghost_guard cliche 拦截档位）只消费 blocker 级；**prompt 禁词块维持全量注入**——提醒级词进 prompt 正是「提醒」语义的合理体现，删了反而把软约束变硬。

**需拍板**：提醒级词是否继续进 prompt 禁词块（本计划默认：进）。
**风险**：低。提醒词从「静默杀挂件」变为「prompt 软提醒 + 审计计数」，与 Phase 3 语义对齐。
**验证**：prohibitions 既有测试族 + 新增对拍「warning 级词不拦挂件、blocker 级拦」。

---

## P1 —— 直接治「生成错文本」

### P1-1 outline 截断保尾（A3）

**修法**：`_truncate_at_sentence` 对 outline 模式改「保尾」策略——末段（引向 after_text 的承接段）豁免，超字从中间段删节或首段起截；与旧引擎「末段豁免截断」护栏思想对齐。
**风险**：低，仅 outline 模式触达。
**验证**：构造超 ×1.6 输出 mock，断言截断后文末仍含承接段。

### P1-2 stitch 碎片判定规范化（A4）

**修法**：拼回判定改走 `normalize_for_match`（抹空白）+ 标点折叠比对，替代裸 `in`。
**风险**：极低，纯判定口径收紧。
**验证**：mock 模型输出「碎片标点变体」，断言不再重复拼回。

### P1-3 短窗评估（C1，数据门控，不先动）

**现状**：`STITCH_ROLLING_SHORT_MAX_CHARS = 200`。加长到 300-400 是常量一行改，但违反「默认恒等」安全绳前需要实测依据。
**路径**：先用 context-preview（AI 此刻所见）在真实写作中观察短窗截断点落在哪，收集「重复前文」案例后再定量。**本批只加观察，不改常量。**

### P1-4 推理模型预算余量（C2）

**修法**：REASONING_DISABLED 调用对「已知烧隐藏思考的槽位」（MiMo/deepseek 系，reasoning_adapter 有域名映射可查）固定 +1000 max_tokens 余量，或把 stitch 下限从 1200 抬到 2200。
**风险**：低，纯上限放宽。
**验证**：mock 槽位配置 + 断言 max_tokens 计算。

---

## P2 —— 「3 字滑窗」一族合并治理（B1/B2/B3）

> ✅ B2 spine 进度已完成（2026-08-25，未提交）。判定改走 `text_match.matches`
> 共享判据：hit 档=全片段命中（threshold=1.0，hit 写库不可逆取最严）+ 整串
> 捷径仅对 ≥3 字锚点开放（2 字通用词裸子串不判）+ 就近窗口 2000 字（覆盖
> burst 连写增量上限、封住大块散落噪声面）；临近岔路走 1/3 低阈值档保留
> 宽松提示语义。首轮（`_last_content_len<0`）只记基线不判定（宁漏勿误，
> finish spine_note 兜底）；`_SPINE_PROG_CACHE` 键改内容 md5（治等长改写）。
> pending→hit 写库的 refresh 防覆盖逻辑原样保留。
> 测试：`services/adaptive/test_spine_progress.py`（9 项）。B1/B3 已随
> P0/P1 前置批次走 `text_match` 共享判据落地（`test_text_match.py` 族）。

三处同构噪声匹配（must_hit 已达成 / 大纲行已写 / 锚点进度 hit），各自「宁松勿严」是有意设计，单点收紧易引入回归，**合并一批改、共享一个判据**：

1. **统一判据**：从「任一/过半 3 字片段命中全文」改为「命中率阈值 + 就近窗口」（如 ≥50% 片段命中且只看近 N 字新增区段）。抽一个共享helper（如 `text_match.py`），三处共用。
2. **B2 附加修复**：`_last_content_len` 随世界模型持久化（或 `_SPINE_PROG_CACHE` 缓存键从内容长度改内容 hash）——治进程重启后首轮「全文当增量」的大面积误 hit（hit 只前进不回退，误判不可逆，是三处里唯一写库的）。
3. **B4 顺带**：canon_watch 出场匹配加词边界（前后非词字符）即可，成本低搭车做。

**风险**：中。三处都是柔性机制的判定心脏，行为迁移必须有对拍测试锁定——每处先写「现状行为快照测试」再改判据。
**验证**：三处各一组对拍（构造通用词污染文本 vs 真实命中文本）。

---

## P3 —— 可观测与成本

> ✅ 四项全部完成（2026-08-25，未提交）。P3-1：orchestrator 记
> `last_component_errors`（秒级时间戳+单行摘要，成功即清），心跳响应与
> `/adaptive/model` 增量透出，副驾「AI 视角」新增「AI 辅助遇到的问题」块
> （空则不渲染）；P3-2：`_activate_sync` await 后按入参签名（recent_text
> 签名+budget 档）等效即复用不再重跑，不等效维持重跑；P3-3：critique 改
> 首 3000+尾 3000（中间省略记号，短于 6000 零变化）；P3-4：event_scout
> 跳过返回 `{code, reason}`，settle/finish 无候选产出时透出 `scout_skipped`，
> 前端收件箱空态显示一句作者语言提示。
> 测试：`test_orchestrator_health.py`（8 项）+ `test_critique_and_scout.py`
> （5 项）；全量 553 绿（基线 532 + 新增 21）。

### P3-1 异步组件失败可见化（C5）
heartbeat 响应或 `/adaptive/model` 快照带 `last_component_errors`（组件名+时间戳，不含堆栈）。前端不主动打扰，进副驾「AI 视角」调试区。
**风险**：零（增量字段）。

### P3-2 双跑去重（C4）
`_activate_sync` await 到异步任务后，若其入参签名与本次等效（同段落签名/同 budget 档），直接复用其产出不再重跑。
**风险**：低；需定义「等效签名」，默认不等效则维持重跑（现状）。

### P3-3 finish critique 首尾截取（C3）
`text[:6000]` 改「首 3000 + 尾 3000」，长章后半进审阅视野。
**风险**：零（prompt 输入变化，格式不变）。

### P3-4 event_scout 空书可见性（C6，可选）
settle/finish 响应带 `scout_skipped_reason`（无实体/正文不足），前端收件箱空态可显示「世界页建几个角色后开始工作」。
**风险**：零。

---

## 执行约束

- 每批独立提交；P0 两项可合一批（都是「缓存项/分级语义」主题），P1 四项可合一批。
- 所有「默认零变化」红线不破：无大纲/无文风/无世界数据的书行为逐字节不变。
- B 组判据收紧前必须先落「现状行为快照测试」，防柔性机制隐性转向。
- C1 短窗常量维持数据门控——真实写作回收案例前不动。
- 测试纪律：新测试进 `services/adaptive/` 同族对拍文件或前端 `__tests__/`，跑 `pytest` 前确认被收集（历史假绿事故）。

## 拍板清单（实施前需确认）

1. 提醒级负面清单词继续进 prompt 禁词块？（默认：进；校对拦截才分级）
2. A1 配套是否同批加「intent_version 变化使推测过期」？（默认：加，一行判断）
3. C1 短窗是否接受「先观察后调」？（默认：接受）
