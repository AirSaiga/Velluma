# 文风模块重构设计（笔迹：测量式文风指纹 + 意图旋钮 + 反馈环）

> 状态：✅ 全部落地（S1 测量层 / S2 执行层接通 / S3 交互环 / S4 抽象与切分 / S4+ 补全批次 / S5 UX 打磨与样本链路修复，2026-08-18；唯一不做项 E4 见 §8 评估结论）
> ⚠ **2026-09-14 去参数化修订**：S4 旋钮体系（`style_knobs` 四维旋钮/四风格预设/对话目标五档）已整体退役——UI 下线、`style_cards.style_knobs`/`dialogue_ratio_target` 两列冻结只读、`render_style_positive` 不再渲染意图行（上限 14→10 行）；五维画像手填表单同批下线（高级面板只读+保留「从样本提炼」与字段锁）。文风收敛两根支柱=亲笔样本 few-shot + 负面清单执法，「收本章为文风范例」一键装填为样本主通道。本文 §5 意图层/大旋钮/对话滑条等描述按当时设计保留、勿据此施工——审计与裁决见 `docs/reports/style-parameter-effectiveness-audit.md`。
> 范围：`frontend/src/components/StyleCardManager.vue`（已删除，拆解迁入 `features/style/`）；
> `backend/routes/style.py` + `services/style/`（新 fingerprint 模块）+
> `services/context/settings_bundle.py` + adaptive stitch-ghost + `services/refinery/` +
> `workflows/validators.py` / `validation/code_auditors.py`（已改为共用 fingerprint 原语）
> 前置：`docs/reports/canon-world-fusion.md`（C1 已落地，设定页仅剩文风+笔记两个真分区）；
> `docs/reports/world-unified-settings.md`（M1-M6+ 全部落地，文风为其明确非目标）

---

## 0. 背景与目标

**背景**：世界页统一设定工程（M4/M5）把角色/资产/地图/伏笔/期待/世界观全部收进活舆图后，
设定页只剩**文风**与**笔记**两个真分区（其余六个均为 WorldRedirectCard 跳转卡）。文风在
概念上不属于世界页——世界页回答"这个世界**是什么**"（事件溯源的事实源），文风回答
"这个作者**怎么写**"（笔迹，与作者强绑定而非与设定绑定）。两者正交：同一批设定换一支
笔就是另一本书。因此文风不迁入世界页，而是**独立成页并整体重构**。

现状调研（§2）发现：文风卡不是功能不足，而是**大量设施已建成但休眠**——样本向量检索
建好了但生成时 `author_samples=None`；章级覆盖后端支持但前端无 UI；审计侧每章算指纹但
从不回流；refinery 头注释承诺接样本但连 StyleCard 都不读。重构的主体是**接活与闭环**，
不是从零新建。

**三个结构性缺陷（本次要推翻的）**

1. **声明式**：五个空文本框要求作者用术语自我分析（"句长节奏""语域偏好"），会写的人
   不一定会分析自己的写；语料（作者自己写的字）才是更好的事实源，却只用于一次性提炼。
2. **说服式注入**：把抽象描述塞进 prompt（"短句与长句交替，平均 15 字"）。对 LLM，
   一段范例胜过十句形容；且默认主线 adaptive 流只消费负面清单，**正面画像完全不进
   prompt**。
3. **开环**：填完卡没有任何反馈——不知道 AI 贴没贴住、不知道文风在往哪漂；审计侧算
   出的每章指纹（句长 CV/对话占比）躺在 QualityReport 里从不回流。

**目标**

1. 范式转换：**测量 > 声明**（指纹 code 算，画像 LLM 只做解读）、**范例 > 形容**
   （few-shot 样本注入为最大质量杠杆）、**闭环 > 开环**（每章对账 + 漂移可视化 +
   写作现场微交互回流）。
2. 易用性为一等公民：页面自己先干活，**用户只做判断题和选择题，不做填空题**；
   每个控件的效果即时可见（试听），零配置可用。
3. 独立文风页成为作者笔迹的唯一工作台：语料 → 指纹 → 画像 → 负面清单 → 对账，
   单页叙事线。

**非目标**

- 不动 BS-ADF 引擎本体（弃置中，勿新增功能）；其消费链保持原样。
- 不改三层禁词的共享层语义（SystemCliche 全局层只读+本书豁免，不做用户级编辑）。
- 不改 `[private]/[public]/[hook]` Canon prompt 契约（与本模块无关，冻结不动）。
- 不做作者级（跨书）文风卡的表结构迁移——本期保持书级，双层结构列入开放问题（§10）。
- 不做角色声纹的实施（仅确立"笔迹 vs 声纹"概念切分，声纹挂世界实体属 S4 远期）。
- 不做文风卡的版本历史/回滚（远期可选，不入分期）。

---

## 1. 概念切分：笔迹 vs 声纹（前提）

现文风卡混淆了两样东西，重构前先切开：

```
┌─────────────────────────────────────────────────────┐
│ 笔迹（叙述文风，本文档，文风页管）                      │
│   叙事腔调 / 句长节奏 / 修辞密度 / 语域 / 开头结尾习惯   │
│   回答：叙述者听起来像不像作者本人                       │
├─────────────────────────────────────────────────────┤
│ 声纹（角色对话腔，S4 远期，挂世界实体 props.voice）     │
│   老朽带叹词 / 军官短促 / 孩童跳跃——千人千声            │
│   回答：每个角色说话像不像ta自己                        │
└─────────────────────────────────────────────────────┘
```

- **对话占比**是结构指标，仍归文风页（它描述"这本书对话多不多"，不描述"某个角色怎么说话"）。
- 切分的直接收益：文风页职责单一（叙述者声音），世界页职责单一（设定事实源+角色属性），
  也为远期"千人千声"留了挂载点（世界实体 `props.voice`，由 world_bridge 带入生成上下文）。
- 本期实现只动**笔迹**一侧；声纹仅在分期表 S4 列一行占位。

---

## 2. 现状盘点（调研结论，2026-08-18）

### 2.1 数据模型（`backend/models.py`）

- **StyleCard**（936-955，表 `style_cards`）：`book_id` FK；`chapter_id` 可空
  （null=书级，非 null=章级覆盖，948）；`positive_profile` JSONB dict（五固定键：
  sentence_rhythm/vocabulary/register/opening_habit/ending_habit）；`negative_list`
  JSONB `[{word, alternative}]`（950）；`dialogue_ratio_target` Float；
  `paragraph_rhythm` Text；`notes` Text（前端未用）。
- **AuthorSample**（958-981，表 `author_samples`）：`scene_type`
  （dialogue/action/lyrical/suspense/general）、`content`、`embedding Vector(1536)`、
  `word_count`、`source`（manual/golden_snippet/published_chapter——**后两者通路已预留
  但从未写入**）。
- **SystemCliche**（984-1007）：三层禁词合并的系统层（对用户不可见）。
- **章级覆盖**：`chapter_cards.style_override_id` FK→style_cards（927）——后端全链路
  支持（GET/PUT style-card 章级优先），前端无入口。
- 书级遗留：`books.golden_snippets`/`books.style_blacklist` JSONB（199-200）。

### 2.2 后端 API（`backend/routes/style.py`，368 行）

`GET/PUT /api/books/{id}/style-card`（103/119）；`POST .../style-card/extract`
（157-178，**不落库**，前端确认后 PUT——此红线保持）；样本 `GET/POST .../samples`
（185/200，创建自动向量化）、`DELETE`（233）、`POST .../samples/search`（248，向量检索，
**全仓库仅此一处调用**）；系统禁词 CRUD（289-364）。

提炼逻辑 `services/style/extractor.py:54`：1×reasoning（temp 0.2 / json_object /
max_tokens 2000），失败降级题材默认画像并标 `degraded`；prompt 在
`services/prompts/style_extract_prompts.py`。

### 2.3 前端

`components/StyleCardManager.vue`（479 行，通用组件层，非 bible feature 内）四 tab：
正面画像（5 textarea + 「从样本提炼」modal 442-477）/ 负面清单（word+alternative 双行）/
量化指标（**纯手填**：对话占比 0-1 滑条 + 段落节奏 textarea）/ 作者样本（上传 + scene_type
下拉 + 列表删除）。2s 防抖自动保存；保存时 negative_list 同步 `book.style_blacklist`
（137-144）。`styleApi`：`services/api/domain/index.ts:252-299`。

BibleView（352 行）八个导航中六个已是 WorldRedirectCard，剩文风（默认激活）+ 笔记。

### 2.4 消费链现状矩阵（谁在读什么）

| 消费方 | 读的字段 | 现状 |
|--------|---------|------|
| adaptive 流（**前端默认**） | `negative_list`→`style_negative`；`banned_words` 三层合并（settings_bundle.py:101/113-120/471-495）→ orchestrator soft_constraints + dock hard_constraints（adaptive_prompts.py:597） | ⚠ **正面画像/量化指标/样本全部不消费** |
| ADF 段落渲染 | `_build_style_contract`（segment_writer.py:241-300）：正面≤10 行 + 负面≤15 条 + 对话占比 + 段落节奏 | ✅ 全量注入；但 `_build_author_samples`（306-315）被 `adf.py:335` 传 None 封死 |
| ADF refiner | `getattr(style_card, "positive_traits", "")`（refiner.py:289） | 🐛 ORM 无此字段，**恒为空串**——refine 的 style_contract 实际为空 |
| Refinery（V4.1） | 无（polisher.py:28-37 签名有 `author_samples`，头注释承诺"第 4 期接样本做文风指纹"） | ❌ 连 StyleCard 都不读 |
| de_ai_washer | 静态 DEFAULT_BAN_LIST（chapter_optimization.py:159 调用） | ❌ 不读 StyleCard |
| 三层禁词合并 | validators.py:39/55/108-112（SystemCliche + style_blacklist + negative_list） | ✅ 在用 |
| 代码审计 | ClichéAuditor（code_auditors.py:225）读 negative_list；DialogueAuditor（419-425，±0.2 容差）读 dialogue_ratio_target；RhythmAuditor（302-360）算句长 CV | ✅ 在用，但**只测生成文本，结果不回流** |

### 2.5 休眠设施清单（本次接活对象）

1. 样本向量检索（`samples/search` + embedding 字段）——生成链路零调用。
2. 章级文风覆盖（`chapter_cards.style_override_id` + GET/PUT 章级优先）——前端无 UI。
3. 样本 `source` 的 golden_snippet / published_chapter 两条汇入通路——从未写入。
4. `positive_profile` 进 adaptive（settings_bundle 已加载书级卡，只是 to_prompt_context
   不暴露）。
5. 每章指纹数据（QualityReport.metrics：cliche_hits_per_1k/sentence_len_cv/
   dialogue_ratio，models.py:1028+）——算完即弃。
6. refiner.py:289 死字段 bug——顺手修。

---

## 3. 目标架构：六层 + 反馈环

```
            ┌──────────────── 反馈环（§5）────────────────┐
            │  章指纹对账 / 漂移趋势 / 写作台微交互回流      │
            ▼                                              │
┌───────────┴──┐   ┌──────────┐   ┌──────────┐   ┌──────────────┐
│ ① 语料层      │→ │ ② 指纹层  │→ │ ③ 画像层  │→ │ ⑥ 执行层      │→ 生成链路
│ 样本库扩编     │   │ code 测量 │   │ LLM 解读 │   │ 五种注入(§4)  │
│ (事实源)      │   │ (0 LLM)  │   │ +证据链  │   └──────────────┘
└──────────────┘   └──────────┘   └──────────┘
        │                                   ▲
        │         ┌──────────┐   ┌──────────┴───┐
        └────────→│ ④ 负面清单 │   │ ⑤ 意图层      │
                  │ 三层可见   │   │ 大旋钮+档位   │
                  └──────────┘   └──────────────┘
```

- **① 语料层**：样本库 = 文风的事实源（地位对标 world_events）。三条汇入通路全部接活：
  手动粘贴（现状）、黄金片段自动汇入、已发布章节一键收编。样本加时期标记（早期/近期，
  供指纹加权——文风会进化，近期的字更能代表现在的你）。
- **② 指纹层**：纯 code 测量（0 LLM）。抽共享模块 `services/style/fingerprint.py`，
  统计算法直接复用审计侧既有实现（RhythmAuditor 的句长 CV、DialogueAuditor 的对话占比、
  ai_taste_meter 的比喻/微操密度），**生成文本与作者样本用同一把尺子量**——这是对账的
  前提。产出：句长均值/CV/分布、对话占比、段长分布、标点习惯（破折号/省略号频率）、
  修辞密度。
- **③ 画像层**：LLM 只做解读不做测量——「从样本提炼」的输入改为**实测指纹 + 样本原文**，
  数字由 code 给，LLM 负责翻译成可读描述。每个维度带证据链（来自哪几条样本、实测值是
  多少）；字段分两态：**自动**（随语料更新）与**锁定**（用户手改后不再被覆盖）。
- **④ 负面清单**：word→alternative 成对设计保留；三层（系统陈词库/书级黑名单/卡级清单）
  UI 全可见；审计命中一键抓虫回流（详见 §6）。
- **⑤ 意图层**：4-6 个大旋钮（文白/快慢/浓淡/对话多寡/冷热），档位制非连续滑条，
  默认"自动"档（= 语料实测值），拨动即覆盖。映射到底层：画像模板 + 量化目标 +
  样本检索权重。高级面板折叠后才是现在的五维文本框。
- **⑥ 执行层**：见 §4。

---

## 4. 执行层：五种注入方式（按质量杠杆排序）

现状只用了其中最弱的一种（E2 的残版）。五种方式互补，可独立上线：

| # | 方式 | 改动点 | 成本 | 杠杆 |
|---|------|--------|------|------|
| E1 | **范例注入 few-shot** | stitch-ghost 五模式 prompt + adf.py:335 解封 | 0 额外 LLM 调用（token 略增） | ★★★ 最大 |
| E2 | **画像注入（修洞）** | settings_bundle.to_prompt_context 暴露 positive_profile；修 refiner.py:289 | 0 | ★★ |
| E3 | **禁词执行闸门** | 生成后确定性扫描替换（纯 code）+ 审稿模式 UI；de_ai_washer 接 StyleCard | 0 LLM | ★★ |
| E4 | **指标制导** | 段落级动态约束（"本章对话占比偏低"喂下一段），复用方向权重思路 | 0 LLM | ★（远期） |
| E5 | **润色消费** | refinery polisher + /optimize_selection 传文风卡 + 检索样本 | 0（原调用不变） | ★★ |

**E1 范例注入**（最大杠杆，设施休眠待接）：生成时按当前场景类型 + 语义相似度检索
1-2 条样本（各截断 ≤1200 字，沿用 `_build_author_samples` 现成思路），以
"【作者笔迹示范】…【现在开始写】"形式进 prompt。检索：embedding 已配置时走向量
（`samples/search` 现成），未配置走 scene_type 精确匹配 + 新近优先兜底——与 RAG
"默认流打底 + 向量增强"同模式。接入顺序：**adaptive stitch-ghost 优先**（默认主线），
ADF 段落渲染其次（解开 adf.py:335 的 None）。token 预算：单次注入 ≤2400 字样本，
心跳不注入（心跳是 0 LLM/轻 LLM 路径）。

**E2 画像注入（修洞）**：settings_bundle 已加载书级卡（301-306），只需
`to_prompt_context` 增加 `style_positive` 段（正面画像五维，行数截断沿用 ADF 的 ≤10 行
惯例），adaptive 心跳响应组件/dock/stitch-ghost 全链路自然获得。顺手修
`refiner.py:289` 的 `positive_traits` 死字段（改读 `positive_profile`）。

**E3 禁词执行（从提示到闸门）**：现负面清单只是 prompt 里的"请不要"。升级为生成后
确定性扫描：命中禁词 → 替换为 alternative（纯 code，0 LLM），但**绝不静默改正文**——
走审稿模式：替换 diff 清单逐条 ✓/✗（复用世界页待确认收件箱交互契约）。de_ai_washer
接入 StyleCard.negative_list（现只读静态 DEFAULT_BAN_LIST）。

**E4 指标制导（远期）**：对话占比目标现只有事后审计（DialogueAuditor ±0.2）。可在生成
中段把"本章目前对话占比 0.15，低于目标 0.35"作为动态约束喂下一段——与 adaptive 方向
权重同构，0 LLM 成本。列 S4 再评估，防过度工程。

**E5 润色消费（修承诺）**：refinery.py:193/300 调用点补传 StyleCard + E1 同款检索样本；
`/optimize_selection`（写作台选中润色）同。否则"AI 润色"永远把文字往通用腔上拉，
与文风目标背道而驰。

---

## 5. 反馈环

- **对账**：每章完稿（adaptive finish / 保存触发补算）后，用同一把尺子算章节实际指纹，
  与文风目标并排呈现。数据源 QualityReport.metrics 已存在（sentence_len_cv /
  dialogue_ratio / cliche_hits_per_1k），只差：①历史章节补算任务（纯 code 批处理）；
  ②文风页可视化。
- **漂移趋势**：章节指纹按叙事序连成线，目标区间画底色带，落带外的点给人话建议
  （"最近三章对话持续偏少——是在压对话，还是无意的？"）。显著漂移可走进心跳感知通道
  （canon_hints 同款位置）轻提示——S4。
- **微交互回流**：写作台 💛 收为样本 / ⚠ 这不像我（详见 §6.5）→ 统一进**文风收件箱**
  （复用世界页待确认分区的 ✓/✗/撤销契约），攒批过目，不打断写作流。

---

## 6. UX 设计（一等公民）

### 6.1 五条总原则

1. **零配置可用，数据越多越准**——不填任何东西页面也能运转（语料实测自动画像）。
2. **能测量的绝不问用户**——句长节奏 code 算出来给用户看，用户只在"算得不对"时出手。
3. **每个控件都有即时可见的效果**——黑盒配置是易用性死敌，试听（§6.4）是核心界面。
4. **写作现场随手喂养，不打断写作流**——文风数据主入口在写作台，文风页是管理后台。
5. **与全站既有交互语言严格一致**——胶囊/抽屉/`v-autogrow`/2s 防抖/6 秒撤销胶囊/
   ✓✗ 收件箱/SSE 打字机/深链，全部复用，一个新交互模式都不造。

### 6.2 信息架构：四 tab 表单 → 单页叙事线

tab 碎片化且隐藏内容（量化指标/样本库藏在 tab 后，用户永远不点开）。改单页滚动 +
页内锚点导航，顺序本身在讲故事：

```
┌─────────────────────────────────────────────┐
│ 文风状态条：一句话总结 + [▶ 试听]              │ ← 顶部常驻
├─────────────────────────────────────────────┤
│ ① 你的字（样本库：事实源，一切从这里长出来）      │
│ ② 笔迹指纹（实测图 + 大旋钮；高级文本框折叠）     │
│ ③ 负面清单（三层可见 + 命中计数 + 抓虫回流）      │
│ ④ 对账（每章实测 vs 目标 + 漂移曲线）            │
└─────────────────────────────────────────────┘
```

组件按分层规范落 `features/style/`（containers + presentation），不再放 components/；
StyleCardManager 拆解迁移，bible 页剩笔记（bible 改名/保留另行决定，不在本文档范围）。

### 6.3 零状态坡道（首次体验）

现零状态是五个空文本框，改名换姓的吓人。重做三幕坡道：

1. **首次进入**：整页只有一个邀请——大输入区"贴一段你写过的字（200–2000 字）"+
   兜底"或从本书已发布章节自动采样"（书里已有章节时一键收编，source=published_chapter
   通路现成）。用户唯一付出的劳动是复制粘贴自己写过的字，零创作负担。
2. **贴入第一段后**：3 秒内（纯 code）展示实测指纹——句长分布、对话占比、段落节奏。
   "原来我写字长这样"是第一个啊哈时刻，奖励第一次投入。
3. **样本 ≥ 3 条**：浮出"一键提炼文风画像"建议（LLM，结果必须用户过目才落库——
   现状 extract 不落库的红线不动）。

页面随数据生长，而非一开始摊开全部复杂性。

### 6.4 关键交互细节

- **旋钮三态，拒绝假精确**：现对话占比 0-1 步长 0.05 滑条是假精确（用户对 0.35 vs 0.40
  无感知）。改**五档分段旋钮**（如对话多寡：极少/偏少/适中/偏多/极多），每档映射底层
  数值区间。三态：**自动**（默认，跟随实测值，旋钮上标刻度"你目前在这里"）/ **自定义**
  （拨动即覆盖，2s 防抖保存）/ **停用**（此维度不注入）。拨离实测太远轻提示"和你最近的
  字差得有点远——有意转型吗？"；一键"回到自动"。
- **试衣间（试听）顶部常驻横条**：默认测试段自动取用户最近写的一小段（可换）；▶ 走
  **真实注入管线**流式改写（SSE 打字机复用）；支持 A/B 模式（调参前后各一版左右对照）；
  按钮旁标注"约 5 秒 · 1 次调用"，成本透明。解决文风卡最根本的信任问题：**调了看得见**。
- **负面清单台账化**：每条禁词显示**命中计数**（"近 10 章命中 3 次"——清单是否在工作的
  直接证据；命中为零的词反向提醒可能不需要它）；系统层 AI 陈词库默认折叠（"AI 高频
  陈词 · N 条"），可展开，单条**本书豁免**（不删全局层）；质量报告陈词命中加"＋ 收入
  负面清单"按钮。
- **术语人性化**：不出现"变异系数 CV"——叫**句长起伏**；dialogue_ratio 叫**对话占比**；
  每个数字 hover 显示"怎么算的、来自哪几条样本"（可解释性）。

### 6.5 写作台触点（不打断写作流的喂养）

- **💛 收为样本**：选中浮窗已有"黄金片段"按钮——做的是**接通**样本库而非加新按钮。
  点击后浮 6 秒撤销胶囊（Alt+N 同款）："已汇入文风样本库 · 撤销"。
- **⚠ 这不像我**：选中 AI 写的不对味的文字 → 轻量 popover 两个选项："把这段改得更像
  我"（立即改写，走 E5 润色通路）/"以后避免这种写法"（提炼为负面清单**候选**，绝不直接
  生效）。意图收敛为两个按钮，不开对话框。
- **文风收件箱**：负面清单候选、审计抓虫、样本汇入统一进收件箱，✓/✗/撤销——完全复用
  世界页"待确认"分区交互契约（用户已学会过一次）。
- **副驾「章节」tab「本章文风」卡**：默认"继承书级文风"（只读摘要）；拨任一旋钮自动
  创建章级覆盖（`style_override_id` 现成），出现"恢复继承"按钮。状态永远可见——
  一眼看出"本章是不是特例"。
- **深链**：写作台副驾/审计报告的"文风贴合度"→ `?panel=style` 或文风页锚点跳转，
  沿用世界页深链先例。

### 6.6 防错与诚实红线

- 样本 < 3 条：指纹照常显示但标"样本尚少，仅供参考"——不假装精确。
- 一切 LLM 产物（提炼画像、负面清单候选）**作者过目才落库**（现状红线，保持）。
- 禁词自动替换走审稿模式：diff 清单逐条 ✓/✗，绝不静默改正文。
- 试听/提炼按钮成本透明（次数+预计时长）。
- 特殊文体（诗歌/剧本）指纹失真：允许全字段手动锁定，自动测量让位。

---

## 7. 数据模型与接口改动

### 7.1 表改动（MIGRATIONS 追加，全部加法不改旧列——✅ 补全批次全部落地）

- `author_samples`：`+ era VARCHAR(16) DEFAULT 'recent'`（✅ early 只存档，**语料聚合只用近期**）、`+ favorite BOOLEAN`（✅ 检索兜底流收藏优先）。
- `style_cards`：`+ fingerprint JSONB`（✅ **写穿缓存**：GET /style-fingerprint 计算后回写供未来消费方取用；读路径仍实时算保新鲜）、`+ locked_keys JSONB`（✅ 画像字段锁——被锁字段不被「从样本提炼」覆盖，「全部锁定」即 §6.6 特殊文体让位通路）、`+ style_knobs JSONB`（S4 旋钮）。
- `style_inbox_items` 收件箱表（✅ S3）+ `books.style_cliche_exemptions JSONB`（✅ 补全批：系统陈词库本书豁免，validator/auditor/scan 三处消费）。
- 章指纹：**不建新表也不回填**——S1 实施调整：`GET /style-fingerprint?with_chapters=true`
  **实时计算**最近 N 章（纯 code 毫秒级，永远与当前正文同步；且避免 metrics-only 报告行
  在 `get_latest` 里遮蔽真实审计报告）。原"补算入 QualityReport"方案作废。

### 7.2 端点改动（routes/style.py 扩展，前端 domain api 同步）

| 端点 | 说明 |
|------|------|
| `GET /api/books/{id}/style-fingerprint` | 文风指纹（纯 code）：语料聚合（**仅 era=recent 样本**）+ 逐样本 + `with_chapters=true` 时**实时算**最近 N 章章指纹 + 参考区间 + **负面清单命中计数**（近 10 章，台账化）+ 指纹写穿缓存。取代原 backfill 端点（见 §7.1 实施调整） |
| `POST /api/books/{id}/style/audition` | 试听：给定段落 + 当前/指定文风配置，走真实注入管线改写（SSE 流式）✅ S3 |
| `POST /api/books/{id}/samples/from-golden` | 黄金片段汇入样本（✅ 补全批：按内容去重导入存量 golden_snippets） |
| `POST /api/books/{id}/samples/from-chapters` | 已发布章节一键收编（零状态坡道兜底）✅ S1 |
| `PATCH /api/books/{id}/samples/{sample_id}` | 样本局部更新：era / favorite（✅ 补全批）/ scene_type / content（正文变更重算字数并重向量化，失败清 None 宁缺勿旧） |
| `GET/PUT /api/books/{id}/cliche-exemptions` | 系统陈词库本书豁免（✅ 补全批：validator/auditor/scan 三处消费） |
| `GET/POST /api/books/{id}/style/inbox` + `POST .../inbox/{item_id}/confirm|dismiss` | 文风收件箱 ✅ S3 |
| `POST /api/books/{id}/style/events` + `GET .../events/summary` | 使用埋点（✅ 补全批：本地 JSONL 零外部上报，audition/golden/⚠/收件箱/预设/抓虫全打点，summary 含收件箱采纳率） |

stitch-ghost / settle / finish / refinery 的请求 schema **不改**——文风注入在服务端
settings_bundle 层自动生效，前端零改动（与 world_bridge 的接入方式同款）。

### 7.3 共享统计模块

新 `services/style/fingerprint.py`：从 `validation/code_auditors.py`（RhythmAuditor
302-360 / DialogueAuditor 419-425）与 `services/nlg/ai_taste_meter.py` 抽出统计算法为
纯函数（输入文本 → 指纹 dict），审计侧与文风侧共用——**同一把尺子**由单点维护。
jieba 已在依赖，无新依赖。

---

## 8. 分期路线（每期独立可发布）

| 期 | 内容 | 价值验证点 |
|----|------|-----------|
| **S1 测量层 ✅ 2026-08-18** | `services/style/fingerprint.py`（规范原语 + 指纹计算 + 语料聚合；审计侧 code_auditors 改为共用同一把尺子，对拍单测 `test_fingerprint.py` 锁定 CV/对话占比同值）；`GET /style-fingerprint`（语料+逐样本+`with_chapters` 章指纹实时算+参考区间）+ `POST /samples/from-chapters`（零状态收编，published_chapter 通路首次写入）；前端 `features/style/` 独立页（AppRail「文风」`/style/:bookId`，单页叙事线四区：你的字/笔迹指纹[直方图+指标网格+高级画像折叠]/负面清单/对账[章 CV 与对话占比趋势 + 参考底色带 + 人话总结]；零状态坡道三幕；提炼 modal 迁入+样本库预填；`components/StyleCardManager.vue` 删除，bible 只剩笔记+跳转卡）。**未建新表未加列，生成链路零改动**。 | 首次进入贴一段字 → 3 秒内看到句长分布图；对账区数字与质量报告可互证 |
| **S2 执行层接通 ✅ 2026-08-18** | **E1 范例注入**：`services/style/retrieval.py`（向量流 `search_by_style` 优先 + 新近兜底，k≤2×1200 字句界截断，全失败→空列表零变化）→ stitch-ghost 四模式 prompt 新增「作者笔迹示范」块；ADF `adf.py` 的 `author_samples=None` 解封（List[str] k=3——ORM 对象无 .text 会被 str() 兜底，必须传字符串）。**E2 画像注入**：`settings_bundle.render_style_positive` 公共渲染器（五维中文标签 + 段落节奏 + 对话目标，≤10 行）→ `to_prompt_context`/`soft_constraints` 暴露 `style_positive` + 四 builder「作者文风画像」块。**E5 润色消费**：refinery `_build_refinery_context` 填 `author_samples`（polisher 休眠签名接活）+ 负面清单进 `forbidden_terms`（手术 prompt 同步生效）；`/optimize_selection` 注入文风约束块（画像/避免用词/1 条示范 ≤800 字）。**修死字段**：`adf/refiner.py` positive_traits → `_build_style_contract` 统一口径。零变化契约单测锁定（`test_style_injection.py` 32 项：无卡无样本时四 prompt 与旧版逐字节一致）。**实施偏差**：dock 零件 prompt 未注入画像——8-14 字零件吃不到画像维度，避免膨胀 0-1 LLM 轻路径（§4 E2 的「dock 拿到」缩窄为 bundle 数据层可达）。 | 盲测注入前后「像作者」程度；S1 对账区章指纹趋势（sentence_len_cv 往语料实测值靠拢） |
| **S3 交互环 ✅ 2026-08-18** | **试衣间**：`POST /style/audition`（SSE 打字机，`build_audition_prompt` 与 stitch 四模式共用同一套基座/画像块/示范块——所见即所得有单测锁定；`style_override` 支持未保存草稿配置试听；A/B = 基线版不注入文风 vs 当前文风版）+ 文风页顶部试听横条（默认测试段取最长样本，成本明示）。**💛/⚠ 微交互**：选中浮窗「黄金片段」双写文风样本库（source=golden_snippet 通路接活）；「黑名单」按钮改造为「这不像我」→ 负面候选投收件箱（原直写 book.style_blacklist 的旧行为退役——候选不直接生效红线）；「改得更像我」复用既有「AI 润色/改写」（S2 起带文风注入，不另设入口）。**收件箱**：`style_inbox_items` 表 + GET/POST/confirm/dismiss 四端点；confirm 负面候选 → 书级卡 negative_list + 同步 style_blacklist；文风页收件箱区 ✓/✗（空则整区隐藏）。**章级覆盖**：DELETE `/style-card?chapter_id=`（恢复继承）+ 文风页高级面板「编辑对象」切换（书级/第N章特例）+ `?chapter=` 深链 + 副驾「本章文风」卡（状态一眼可见 + 跳链 + 就地恢复继承）。**E3 禁词审稿**：`POST /style/scan-negative`（三层禁词合并扫描，命中按词聚合带上下文，纯 code）+ 负面清单区「扫描章节」审稿模态（替换替代词到本章正文/仅收入清单/忽略，逐条裁决绝不静默改）；de_ai_washer 增 `extra_banned_words`（defat_selection 带章节上下文传入）。**实施偏差**：💛 的 6 秒撤销胶囊未做（toast 无 action 支持，样本可在文风页删）——S4 若 toast 支持 action 再补。 | 试听点击量 / 💛⚠ 使用率 / 收件箱采纳率（后端有数据基础，前端埋点 S4） |
| **S4 抽象与切分 ✅ 2026-08-18** | **意图旋钮档位制**：`style_cards.style_knobs JSONB` + `services/style/knobs.py`（四维五档：快慢/文白/浓淡/冷热，缺键=自动档不注入）→ `render_style_positive` 渲染意图行；前端「意图」区（实测锚点 + 偏差提示「有意转型吗」）；对话旋钮=目标值五档 UI（滑条退役）。**风格预设**：四预设一键填旋钮+画像模板。**声纹**：实体档案 `speech_style` 即声纹载体（不另建字段，单测锁定 world_bridge 通路）。**💛 撤销胶囊**：Toast action 支持，6s 可撤销。 | 拨旋钮→试听差异可闻 |
| **S4+ 补全批次 ✅ 2026-08-18（「完整落地」勾销全部残留项）** | ①**台账化三细节**——负面清单每条带近 10 章命中计数（`negative_hit_counts`，零命中灰显反向提醒）；系统陈词库折叠可见（"AI 高频陈词库 · N 条"）+ 单条**本书豁免**（`books.style_cliche_exemptions`，validator/ClichéAuditor/scan 三处消费，不删全局层）；数据页质量报告「＋收入负面清单（候选）」抓虫按钮（解析「高频项：词×N」→ 收件箱，过目红线）。②**§7.1 四列全部落地**——`era`（语料聚合只取近期）/`favorite`（兜底检索收藏优先，`order_samples_for_fallback` 单测）/`fingerprint` 写穿缓存（读仍实时算）/`locked_keys` 画像字段锁（🔒 逐字段 + 全部锁定=特殊文体让位；提炼跳过锁定字段并提示）。③**from-golden 端点**（存量黄金片段按内容去重导入）+ 文风页「导入黄金片段」入口。④**心跳漂移提醒**（补上缓行项：章尾 3000 字同尺测量，`kind=style_drift` 并入 canon_hints 走感知带，按内容长度缓存零重复计算）。⑤**埋点**（补上缓行项：本地 JSONL `data/style_events.jsonl` 零外部上报——audition/golden/⚠/收件箱裁决/预设/抓虫全打点，`GET events/summary` 含收件箱采纳率）。**E4 维持不做**（评估结论不变：无数据支撑且走向卡已是柔性机制）。 | 命中计数/豁免/抓虫的日常使用；events summary 的采纳率趋势 |
| **S5 UX 打磨与样本链路修复 ✅ 2026-08-18** | **坡道重修**——零状态 hero 化（垂直居中 + 衬线大标题 + 大输入区，分类下拉移出第一幕，§6.3「整页只有一个邀请」成立）；门闸修正：`zeroState` = 无样本**且无既有配置**（`hasStyleConfig` 扩入旋钮/对话目标，旧卡用户不被折叠）；`growthStage` 三幕（early 态 1-2 条只长样本+指纹+长成预告细带）；章级特例深链强制 full。**状态条**——§6.2 草图「一句话总结 + ▶试听」补齐（`StyleStatusStrip` sticky 常驻，语料为空不报假数字）。**两栏仪表盘**——52rem 窄表单改 96rem 流式（clamp 侧 padding）：①你的字+②笔迹指纹 5:7 并排（贴字→测量的即时反馈并排成立）、④负面+⑤对账 1:1、意图整宽，hairline 分隔归容器，<74rem 塌单列；直方图重做（贴基线/柱顶计数/按最高桶归一峰值 96px/底线轴）。**`--accent-400` 全局补齐**（浅色 #9685c2/深色 #8b6de8——曾未定义致文风页 14 处引用静默失效，直方图柱子隐形根因）。**样本创建链路事故级修复**——`create_with_embedding` 违反 `BaseRepository.create(payload: dict)` 契约传 ORM 实例恒 TypeError，**四条创建通路（手动粘贴/章节收编/黄金片段/收件箱确认）曾全部 500**，改 dict 契约 + `era` 转发（此前静默丢弃）；from-chapters 剥 HTML 转纯文本（与 memory_indexing 同口径）+ 纯文本判空（`<p></p>` 不误判）+ 已收编章节幂等跳过。 | 宽窗两栏并排/窄窗单列均浏览器实测通过；贴字/收编/导入/收件箱写入全部 201 |

依赖顺序：S1 独立（纯加法）；S2 依赖 S1 的指纹（试听 A/B 与检索权重需要实测值），但
E2/refiner bug 可提前单独修；S3 依赖 S2（试听走真实注入管线才有意义）；S4 各项独立可拆。

---

## 9. 风险与对策

| 风险 | 对策 |
|------|------|
| E1 范例注入 token 成本膨胀 | 样本截断 ≤1200 字/条、k=1-2、心跳路径不注入；trace 观测 usage 后再调 |
| 短样本指纹低置信误导 | <3 条标"样本尚少"；低置信时 E2 画像不注入，E1 范例照常（范例无需统计置信） |
| 指纹算法对特殊文体（诗歌/剧本）失真 | 全字段手动锁定通路（§6.6）；锁定后自动测量让位 |
| 试听被当玩具刷调用 | 成本明示"1 次调用"；本地桌面应用不设硬限，trace 可审计 |
| 禁词自动替换误伤正文 | 审稿模式逐条 ✓/✗（§6.6），绝不静默改 |
| 指纹/画像与作者自我感知冲突引发不信任 | 一切数字可解释（hover 证据链）；"自动 vs 锁定"把最终裁决权留给作者 |
| 共享统计模块改动波及审计阈值 | fingerprint.py 抽纯函数，审计阈值（thresholds.py）保留在审计侧不动；抽离前后对同一文本跑出同值（对拍单测） |
| 章指纹补算拖慢启动 | 补算走显式端点后台任务，不进启动迁移；幂等可重入 |

---

## 10. 开放问题

1. **作者级 vs 书级**：文风"和作者强相关"的推论是跨书存在（作者换书不换笔）。库结构已
   暗示双层模式（`chapter_id` 可空=书级，同理可加 book_id 可空=作者级）。本期保持书级
   不动，S4 后视使用数据再议。
2. **风格预设模板库**："冷峻短句""绵密抒情"等预设作为旋钮起点——描述自撰，不抄名家
   原文；是否署名风格（"古龙式"）待议。
3. **bible 页归宿**：文风独立后 bible 只剩笔记——改名"笔记"页 or 笔记并入他处，另行
   决定（不影响本分期）。
4. **E4 指标制导**：可能过度工程，S4 开工前先评 S2/S3 的实际贴合度数据。

---

## 11. 与现有系统的边界确认

- **笔记**：不动（bible 残留分区，本设计不碰）。
- **黄金片段旧表**（`books.golden_snippets`）：双写维持（💛 写旧表+样本库；
  `/samples/from-golden` 一键收编存量）。**S4+ 收编评估结论**：旧表不冻结不删除——
  双写成本一行代码，旧表仍是独立「黄金锚点」语义的宿主；收编（停写旧表）留到有明确
  迁移诉求时再议，届时样本库已是唯一事实源，切换无痛。
- **world_* 全部**：零改动（声纹结论：实体档案既有 `speech_style` 字段即声纹载体，
  已经 world_bridge `static_prompt` 流入生成——不另建 `props.voice`，单测锁定通路）。
- **Canon / 泄密检测 / CanonHighlight**：零感知。
- **BS-ADF**：引擎本体不动；其 style_contract 消费链保持原样（弃置中，不新增功能）。
- **RAG 记忆流**：不动 recall_memories 三层结构；样本检索是独立通路，不混入记忆检索。
- **设置面板（model_config）**：文风不引入新模型配置项；提炼/试听/改写全部复用
  reasoning/creative 既有配置。

---

## 12. 2026-08-24 禁忌面归一、NLP 扩展与章级特例接通（任务包 A-F + Phase 4 注记）

设计稿 S1-S5 之后的后续批次，本节为增量记录（详规见各模块 docstring）：

- **禁忌面四源归一（任务包 A/B/C）**：负面清单/黑名单的**四源唯一权威**收敛到
  `backend/services/style/prohibitions.py`（`load_prohibition_set`：SystemCliche +
  `style_cards.negative_list` + `books.style_blacklist` + 静态反 AI 词表，按层序
  先到先得去重，产出编译好的 `ProhibitionSet`）。**双写已消亡**——
  `style_blacklist` 启动时迁移并入 `negative_list`，原列冻结不再读写。
  消费方（settings_bundle prompt 注入 / ClichéValidator / scan-negative /
  defat / refinery / ghost_guard）全部换源，`bundle.prohibitions` 即加载产物。
- **指纹扩展**：指纹结构在原句长/对话/段落/标点/修辞之外补
  `lexical`（词汇丰富度：token_count/ttr/mattr）与 `repetition`（词级 bigram
  重复密度+频次 top5，<50 词不判）两键（`services/style/fingerprint.py`）。
- **语义扫描（任务包 D）**：`backend/services/style/semantic_match.py` 的
  `semantic_scan_text`——embedding 余弦相似度抓精确匹配漏掉的「换字逃逸」变体
  （「眼底闪过一丝」→「眼底掠过一抹」）。要点与红线：
  - 挂点仅在 `/adaptive/finish` 完稿报告 `semantic_hits`（前端报告区
    「疑似 AI 味变体」块），作者裁决；**不进收件箱 / scan-negative /
    任何 SSE 流式路径**。
  - `is_embedding_configured()` 门控：未配置（SQLite 默认后端恒未配置）
    第一时刻短路直返 `[]`——**SQLite 默认路径行为逐字节零变化**。
  - 切段与指纹同一把尺子（`split_sentences` 句切 + 超长句按 [，；、：]
    细切，段上限 200）；批量向量走 `embedding.get_embeddings`（一次调用
    带全量 input，逐条维度校验，失败等长降级全 `[]`）；禁忌 pattern 向量
    进程级缓存（key = sha1(model|dims|sorted(patterns))，全空不落缓存防
    瞬时故障毒化）。
  - 上限：每 pattern ≤3 段、总命中按相似度降序截 20、短模式（<4 字）与
    正则条目不进语义流（精确匹配已覆盖/句式形状语义不同）。
  - **阈值 0.78 未经实测校准**（遗留风险：可能漏抓或误报）——校准脚本
    `scripts/calibrate_semantic_threshold.py`（约 10 条种子陈词 × 手写同义
    变体句 vs 无关句的相似度矩阵与分离度建议，手动小工具不进 CI；
    只调 embedding API 不碰向量库，不受 SQLite 方言门控影响）。
  - 单测 `backend/services/style/test_semantic_match.py`（14 项：合成向量
    精确控制余弦值，覆盖阈值边界/候选过滤/切段/截断/缓存命中/降级）。
- **Phase 3 severity 两档与语义回流（任务包 E/F，2026-08-24）**：负面清单条目
  `NegativeItem.severity` 两档贯通——**提醒**（warning，默认；仅提示与统计）/
  **硬禁**（blocker；检查时命中即判不通过，只提示**绝不自动改正文**）；未设
  severity 处处按提醒兜底（前端保存不补键，后端默认 warning）。前端触点：
  负面清单每条「提醒 ⇄ 硬禁」切换（StyleNegativeSection）、禁词扫描审稿模态
  硬禁红 chip（StyleScanModal）；prompt 注入作者清单优先排序（后端包 E）。
  收件箱 confirm 端点支持可选 `word`/`alternative` 覆盖字段——收件箱确认前
  可就地编辑词块（点词/✎ 进编辑，Enter/失焦定稿、Esc 取消），编辑后随
  confirm 请求覆盖生效（不带则旧行为）。完稿报告「疑似 AI 味变体」每条新增
  「收入收件箱」按钮（InspectorPanel → `styleApi.addInboxItem`，
  `source=semantic_scan`，word 取片段前 20 字，投后按钮变「已投递」防重复；
  只投候选不直接入清单，红线同「这不像我」）。
- **Phase 4 章级特例卡消费接通 ✅ 2026-08-24（c1f8094）**：章级卡
  （`style_cards.chapter_id` 非空）存在即该章**完整文风定义**——负面清单/
  正面画像/旋钮/对话目标/段落节奏**整卡生效，书级不再参与**（整卡覆盖语义，
  用户拍板：负面清单不合并）；无章级卡回退书级，无卡逐字节零变化。统一入口
  `StyleCardRepository.get_effective_card(book_id, chapter_id)`，消费点全部接线：
  settings_bundle（主通路——stitch-ghost 五模式/dock/context-preview/finish
  审阅/ghost_guard）、ADF、Refinery、选区改写、defat、心跳漂移参照、finish
  语义扫描、quality-report 审计上下文、scan-negative（扫哪章用哪张生效卡）、
  试听 baseline 轨（请求带 chapter_id，前端章级编辑态已传）。**保持书级**：
  指纹对账参考带（书级仪表盘）、收件箱确认写路径。prohibitions 四源权威与
  prompt 排序零改动。单测 `services/context/test_chapter_style_override.py`
  （7 项：repository 三态 + bundle 整卡覆盖/回退/无卡零变化）。
