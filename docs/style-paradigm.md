# 文风三平面分权（2026-08-29 定稿施工）

> ⚠ **2026-09-14 去参数化修订**：P6「旋钮编译为选择器」整体退役——`_selector_adjust` 连同轻指纹设施删除（数学空转实证：零样本书检索池恒空，旋钮参数从未真实影响过任何一次挑样，审计与裁决见 `docs/reports/style-parameter-effectiveness-audit.md`）；`style_cards.style_knobs`/`dialogue_ratio_target` 两列冻结只读。本文 P6 节与「旋钮」字样按当时设计保留、勿据此施工——选择平面现役机制=P5 先验/漂移锚样/收编池/场景匹配/全局笔迹库（scope 补位——「跨书冷启动兜底」旧文已退役）。
>
> 导师方案（teacher-kimi）定稿的文风数据运用重构。**一句话纲领：凡是实证过 prompt 管不住的确定性约束，一律下沉代码层；prompt 只承担概率性偏置。** 这是字数闸（120 字指令实测产出 700 字 → 代码闸一上即治）教训的宪法化。
>
> 权威代码入口：`services/style/ghost_wash.py`（洗层）· `services/style/sample_prior.py`（先验）· `services/style/retrieval.py`（选择平面）· `routes/chapter_generation/adaptive.py`（呈现平面接线）· `knowledge_plane.split_prohibition_tiers`（P0 分档）。测试：`test_style_paradigm.py` + `test_stitch_gates.py` §5。

## 一、四平面架构

| 平面 | 作用时机 | 承担约束 | 机制 |
|---|---|---|---|
| **偏置平面** | prompt | 软引导残余 | 静态反 AI 契约（system 头部）+ 作者 blocker 禁忌 user 尾部重钉（P0）+ 压缩画像（P6） |
| **呈现平面** | 生成后、**采纳线前** | 负面约束执法 | P1 确定性洗 → P2 单次句级修补 → P4 语义警示（shadow 期只落事件） |
| **选择平面** | 生成前 | 正面文风精进 | P5 采纳率先验（±20% 调序）+ 漂移锚样 + AI 来源配比（P6 旋钮编译已于 2026-09-14 退役，见顶部修订注） |
| **审计平面** | 采纳后 | 闭环观测 | finish 扫描/对账/漂移（既有）+ 洗率对账（ghost_wash 事件） |

**架构不变量：采纳线。** 线前（AI 提案）可做确定性干预+自我修订；线后（作者文本）永远只提示。「作者裁决即闸门」从口号变成架构边界。

## 二、P0 位次重排（负面清单双轨分档）

旧结构把作者负面清单全量渲染进第 8 块（prompt 中部遗忘区），而静态反 AI 词在最头部——**作者最硬的禁忌权重最低**，结构性倒挂。修复（`split_prohibition_tiers`）：

- **warning 档**留负面块原位（提醒语义本该弱）；
- **blocker 档**抽出去 **user 尾部重钉**（recency 位，与「【此刻·切记】」同屏）：`不用「X」——改用 Y`（alternative 正面化；无替代词给通用正路「换成具体的动作或物件」；≤6 行）；
- 无 blocker 条目的书逐字节零变化（分档纯函数 + 既有对拍锁）。

## 三、呈现平面

### P1 确定性洗层（`wash_ghost_text`，纯 code 零 LLM）

挂在 ghost 链（复读剥离/字数闸之后、GHOST_DONE 前，与 ghost_guard 同窗口）：

- **只洗命中点**：severity=blocker 且精确命中且有 alternative → 词边界替换；长 pattern 覆盖短 pattern（「深邃」让位「深邃的眼」）；regex 条目只记录不替换；**warning 档永不动手**；
- **全透明**：`GHOST_DONE.wash = {hits: [{pattern, span, replaced, alternative}], original_text}`（原稿快照仅在有替换时携带）；前端薄荷 chip「已规避 N 处禁忌词」展开明细；事件落 `data/style_events.jsonl`（kind=ghost_wash）；
- **零变化契约**：无负面清单/无 blocker 命中 → wash 空、文本原样。

### P1 可逆学习（「用原稿」）

chip 提供「用原稿（保留这些词）」：前端 `useGhostOriginal()` 重灌洗前原稿（保留 ghost mark、隔离撤销栈）+ 对每个 replaced 命中调 `POST /books/{id}/style/wash-prefer-original`——负面清单条目 severity 降 warning；不在清单（系统层）→ 加 `books.style_cliche_exemptions` 豁免。**一次肯定胜过三次否定**，与学着闭嘴同阈值纪律。

### P2 单次修补重试

洗后残留 blocker（无替代词未替换）→ 一次句级修补 LLM 调用（`build_repair_prompt`：点名禁词与替代方向，其余原文照出）。纪律：每幽灵 ≤1 次；每章 60s 冷却 + 在飞去重（`_GHOST_REPAIR_TS/_INFLIGHT`，停顿心跳双烧事故同款防线）；**严格验收**——修补稿重洗后零残留才采纳，否则维持洗层结果带 chip 呈现；失败/限流静默降级为 chip。3 RPM 现实下这是唯一新增 RPM 消费者。

### P3 句窗流式洗：**不需要**

stitch 链是**先生成后播放**（非流式生成完整文本再逐 chunk 播放）——P1 洗层天然发生在任何上屏帧之前，**「上屏即净」自动成立**。导师方案 P3 是为真流式设计的；本架构零成本获得同等效果。

### P4 语义 shadow

`semantic_scan_text`（embedding 比对 blocker 模式向量，抓「换字逃逸」变体）前移到 ghost 链，**shadow 纪律**：只落事件（trace `ghost_semantic_shadow` + style_events），不改文不弹 chip；未配置 embedding（SQLite 默认路径）内部零调用短路。finish 扫描阈值已定档 0.72（2026-09-24 实测，见 `docs/reports/semantic-threshold-calibration.md`）；攒 2-4 周数据与 finish 扫描对拍后再决定 ghost 链是否升 chip 警示——**ghost 链永不做语义自动替换**。

## 四、选择平面（P5/P6）

### P5 采纳率回流（破「只测不干预」，但只破在排序）

数据链：GHOST_DONE 带 `ghost_token + sample_ids` → 前端 `ghost_adopt`/`ghost_discard` 事件回传同 token + sample_ids（adopt 另带正文 ≤400 字）→ `sample_prior.py` 从 `collab_events.jsonl` 派生每样本贝叶斯先验 `(adopted+1)/(total+2)` → 因子 0.8~1.2（线性封顶）：

- 向量流：距离 ÷ 因子；兜底流：排序末位键（收藏→时期→场景→先验；原「旋钮」尾键已随 P6 退役移除）；
- **只调序不筛选**（scene_hint 软加成同款纪律）；冷启动均匀先验=1.0 零变化；mtime 缓存防检索路径全文件扫。

### P5 漂移锚样

本章 `style_drift` 提示在态（心跳侧内容哈希缓存复用）→ `drift_anchor=True` → 收藏样本 +0.1（v1 锚样启发式：漂移检出时作者认证的示范优先）。

### P5 采纳幽灵收编（红线通道）

文风页「AI 写的、你留下的」池（`GET /books/{id}/style/adopted-ghosts` 读 adopt 事件正文）→ 作者点「收为样本」才入库（`source=adopted_ghost`）→ **装配配比：AI 来源样本每批 ≤1**（`_cap_ai_source`）——防采纳幽灵自蒸馏把文风拉向 AI 味。

### P5 跨书冷启动兜底（B4，2026-09-13；❌ 已退役 2026-10-05——全局笔迹库 scope 维度接棒）

本节按当时设计保留、勿据此施工：`list_golden_across_books` 旧门票暗道（本书零样本时回退其它书 favorite/golden 样本）已整体退役，`list_global` 接棒——样本 `scope` 两档（book/global），检索候选=本书 ∪ global、本书绝对优先不足 k 条才补位（「补位不抢位」，向量流与兜底流同律），卡层隔离不动；对拍 `test_cross_book_fallback.py` + `test_global_scope_vector.py`。现役口径见 `docs/agent/style.md`「执行层」节，施工叙事 `docs/incidents/style.md`（2026-10-05 全局笔迹库批）。

### P6 画像编译为选择器（❌ 已退役 2026-09-14）

「声明不再写给模型看，编译成挑样本的条件」（`_selector_adjust`，纯轻指纹现算）：

- rhythm 旋钮手动档 → 目标句均长锚（1→10 … 5→38）→ 样本句均长距离微调（≤0.1）；
- dialogue_ratio_target → 样本对话占比距离微调（≤0.05）；
- prompt 画像瘦身：对话占比目标行与节奏旋钮行**移出** `render_style_positive`（语域/浓淡/冷热/作者亲笔节奏描述保留——样本筛选表达不了的全局维度）。

## 五、注入序终态（P0 后）

```
system: 静态反AI契约(头部) → 场景 → 在场实体 → canon → 私有 → 世界观 → 关系
        → 禁词(仅warning档) → 回响 → 空间 → 画像(瘦身版) → 样本
user:   任务指令 …… 尾部:【此刻·切记】… + 【作者禁忌】不用「X」——改用 Y
```

## 六、安全不变量汇总

1. 任何洗/修补必出 chip + 原稿可回视——无 chip 不改文，宁可漏洗；
2. 作者正文（采纳线后）永不被自动触碰；
3. warning 档永不动手；regex 永不替换；
4. 语义层 ghost 链只警示（shadow 期只落事件）永不替换；
5. 洗率/先验分布进对账观测（洗率爬升=模型退化或清单过宽，提示修剪）；
6. 所有新机制失败路径静默降级（洗层挂了=零变化，修补失败=chip 呈现）。

## 七、验证与后续

- 单测：`test_style_paradigm.py`（20 项：分档/洗层/修补指令/先验/配比/选择器）+ `test_stitch_gates.py` §4-5（字数闸两级 + 洗层路由级对拍 + 修补严格验收）；
- 实测期待：ghost_wash 事件命中率（模型服从度的逆指标）、修补触发率（预期 <10%）、采纳率随先验的变化趋势（分 mode 出报表）；
- 后续候选：P4 shadow 数据达标后升 chip；洗率对账页；词表收编（前端 defatText 与后端 DEFAULT_BAN_LIST 双表漂移——已知未收编项）。
