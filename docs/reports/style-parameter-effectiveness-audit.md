> **归档说明（2026-09-19）**：文风参数审计（2026-09-14），废旋钮实证依据；去参数化已落地（a5f102c），文风页 v4（55befcc）收束。

# 文风控制参数真实有效性审计报告

> 2026-09-14 · 系统架构重构调研第三期 · 纯只读审计（零代码改动）
> 议题：文风体系（4 个五档旋钮 / dialogue_ratio_target 浮点目标 / 五维画像文本 / 20+ 指纹指标）在真实生成链（stitch/burst）中的**实际因果效力**——是否存在"过度参数化与控制幻觉"。
> ⚠ 任务书末尾「文风体系极简收敛为两根支柱」的具体表述在传输中截断；本报告按证据自然指向将「两根支柱」推演为 **① 亲笔样本 few-shot（范例）② 负面清单四源执法（禁令）**——这是代码自身范式宣言（"范例>形容、测量>声明"）的必然落点，报告开头如实声明此解释。
> 行号以 2026-09-14 工作区为准；结论分三级标注：**【代码证】**（纯代码可证）/ **【数据证】**（本机真实事件数据）/ **【推断】**（无数据支撑的推理）。

---

## 0. 结论摘要（TL;DR）

1. **参数注入面真相【代码证】**：4 个旋钮里 rhythm 与对话比例目标**一个字都不进 prompt**（P6 改造时被显式移出——渲染函数生成该行后被 `continue` 跳过，settings_bundle.py:691-692）；实际进 prompt 的只有 register/density/warmth 三行意图行 + 五维画像 + 段落节奏（合计 ≤14 行）。
2. **检索数学空转【代码证】**：向量流在**无 dialogue hint 时只取 SQL top-2 再重排**（fetch_limit=k，retrieval.py:226-229）——池里只有 2 条，旋钮修正量再大也**连换序的数学空间都不存在**；"旋钮怎么拧挑出来的都是同两段样本"在主路径上不是风险而是必然。兜底流里旋钮修正只是第 5 优先级排序键，几乎总被前四键（收藏/新旧/场景/先验）屏蔽。
3. **实证核弹【数据证】**：本机真实事件账（data/collab_events.jsonl，7 次幽灵请求）**sample_ids 全部为空数组**——few-shot 样本从未注入过一条；ghost_adopt=1 vs discard=6；`data/style_events.jsonl` **文件不存在**（文风页全部交互零事件）。**文风参数体系在本机真实使用中对任何一段生成文本的因果贡献=可证零**（样本确定零注入；唯一被采纳的幽灵恰是白描风格范本，归因于 prompt 硬契约而非文风参数）。
4. **指标盘点**：20+ 指标中真有下游动作的约 6-7 个（CV/对话占比→审计+漂移提示、重复度→漂移提示、质感密度→finish 样本候选、四件规范原语→审计对拍基石）；**MATTR、TTR、标点族四项、段落族、五桶直方图、修辞族四项均无任何闸/检索器/业务消费——纯展示**。
5. **文本自相矛盾【代码证】**：density 旋钮拧向浓侧（"修辞是常态"）与自称**最高优先级**的白描契约（"坚决剔除通感抒情、向现实派短句靠拢"，adaptive_prompts.py:527-529）正面冲突；warmth 拧向热侧与基座"禁止直接心理升华"冲突。**两个旋钮的半行程在指令层就被硬禁令压制**。
6. **去参数化判定**：旋钮与对话滑块可废（实证零使用+数学空转+文本冲突三重定罪）；画像手填可废但提炼保留；真正该先修的是**样本库零库存**（最大杠杆从未装填过弹药）。建议拆前先跑一次现成的 audition A/B 拿对照数据。

---

## 1. 旋钮与对话目标的"真实杠杆"审计

### 1.1 注入面总表——到底有哪个字进了 prompt【代码证】

| 参数 | 进 prompt？ | 证据 | 非 prompt 消费面 |
|---|---|---|---|
| `dialogue_ratio_target` | **零字** | settings_bundle.py:682-685 注释明文「可测维度不再写进 prompt——对话占比目标与节奏旋钮编译为样本检索排序条件」；render_style_positive 全函数无此字段 | `_selector_adjust`（≤0.05 距离修正，retrieval.py:175-180）；心跳漂移提示目标档（heartbeat.py:410-412）；DialogueAuditor 审计参考（code_auditors.py:380-403）；ADF 遗产 segment_writer.py:311；提炼 LLM 输出字段（style_extract_prompts.py:95） |
| `style_knobs.rhythm` | **零字** | render_knob_lines 产出「句长节奏意图：…」行后在 settings_bundle.py:691-692 被 `if knob_line.startswith("节奏"): continue` **显式丢弃** | `_selector_adjust`（≤0.1，retrieval.py:171-174） |
| `style_knobs.register` | **1 行** | knobs.py:50-59 档位措辞 → render_style_positive | 无 |
| `style_knobs.density` | **1 行** | knobs.py:60-69 | 无 |
| `style_knobs.warmth` | **1 行** | knobs.py:70-79 | 无 |
| `positive_profile` 五维 | **≤5 行**（每行值截 120 字） | settings_bundle.py:671-678；STYLE_PROFILE_VALUE_MAX_CHARS=120（budget.py:248） | 提炼 prompt 的输出 schema |
| `paragraph_rhythm` | **1 行**（截 80 字） | settings_bundle.py:679-681 | 无 |

注入路径：render_style_positive → 五模式 builder 的 `_style_block_def`（adaptive_prompts.py:127 附近）→ render_system_blocks 注入序第 12 位（画像块，事实层全前于文风层）。总行数上限 **14**（STYLE_POSITIVE_MAX_LINES，budget.py:257——AGENTS.md 写"≤10 行"已过时，实际 14）。

**第一层结论**：作者在文风页看到的 6 类可调参数（四旋钮+对话滑块+画像），**真正有一个字到达模型的只有 3 旋钮行+画像+段落节奏**；rhythm 旋钮和对话滑块对模型完全不可见，它们的全部效力押在 §1.2 的检索微调上。

### 1.2 `_selector_adjust` 的数学公式与量级【代码证】

```python
# retrieval.py:158-181
adj = 0.1 * min(1.0, abs(样本句均长 - 档位锚) / 15.0)      # rhythm：档锚 {1:10, 2:16, 3:22, 4:30, 5:38} 字（:155）
adj += 0.05 * min(1.0, abs(样本对话占比 - 目标) / 0.3)     # dialogue：仅当样本含对话（ratio>0）
```

- 修正上限合计 **0.15**（加到余弦距离上，越大越差）；
- 向量流完整公式（retrieval.py:237-244）：`adj = (distance − 0.1×场景匹配) ÷ 先验因子(0.8~1.2) + selector_adjust − 0.1×漂移锚收藏`；
- 兜底流是排序元组第 5 键（:281-289）：`(favorite, era, scene, prior_key, selector)`。

### 1.3 红队实证算账——修正到底能不能换样本

**向量流·无 dialogue hint（主路径，叙述场景）**：`fetch_limit = k`（retrieval.py:226-229——overfetch 只在 scene_hint_active 时放大 5 倍）。k=2 → `search_by_style` 只返回**余弦距离最小的 2 条** → 无论如何重排，`_cap_ai_source` 取前 2，**入选集合恒等于 SQL top-2**。**旋钮在此路径的效力恒为零，不需要任何 trace 就能证明。**

**向量流·有 dialogue hint（对话场景，rolling 尾 300 字对话占比 >0.35 才激活）**：池=10 条。此时起主导的是场景加成（-0.1）——同型样本已被整体前移；selector_adjust ≤0.15 理论上可在 2-10 名间换序，但需要样本间原始距离差 < 修正差。pgvector 同书同作者样本的余弦距离带宽通常很窄（同题材文本典型 0.05-0.15 量级），**换序可能存在但被场景加成先手覆盖大半，且换的是第 2 名边缘而非选谁入册**。

**兜底流（embedding 未配置/零命中——本机实际路径）**：池=list_by_book 前 6 条（:261），排序键 favorite（二值）→ era（二值）→ scene（二值）→ prior → selector。**selector 只在「同收藏档+同 era+同 scene+同先验」的并列组内起作用**——收藏样本若 ≥2 条则永远轮不到它；本机 adopt=1/discard=6 下先验因子近乎均匀（拉普拉斯平滑，sample_prior.py:33-35），实际排序=favorite→新近 序，**selector 的第 5 键几乎必然空转**。

**结论**：`_selector_adjust` 在三条路径中的两条（向量无 hint + 兜底）**数学上不可能改变入选样本**，第三条（向量有 hint）效力被场景加成覆盖。rhythm 旋钮与对话滑块的"真实杠杆"≈0。

### 1.4 采纳率先验的数据基础【数据证】

P5 先验（±20% 乘性因子）的数据源是 ghost_adopt/ghost_discard 埋点携带的 sample_ids。本机 7 个带 sample_ids 的事件**全部为空数组**——先验统计表恒空，因子恒 1.0（sample_prior.py 冷启动语义）。**先验机制从未离开过冷启动态。**

---

## 2. 画像（Profile）vs 亲笔样本（Few-shot）的效力对决

### 2.1 实证现状：对决从未发生过【数据证】

- **few-shot 侧**：7 次幽灵请求样本注入全零（sample_ids 全空）——本机样本库零库存或向量未配置；
- **画像侧**：`data/style_events.jsonl` 不存在——文风页的全部交互（试听 audition/黄金片段/负面投递/预设/抓虫）零事件，无法确认作者是否配置过画像；
- **唯一一次采纳**（ghost_token b84dd66d80b1）的文本：「"路上黑，走大路啊——"王叔的声音从门缝里追出来，被风削掉半截。巷子里没灯，只有谁家窗纸透出一点黄，照见脚下坑洼里积的雨水，黑亮亮的一洼。」——**零样本注入下达成的白描风格范本**。归因指向 prompt 硬契约（基座反 AI 腔 + 白描契约，§2.2），而非任何文风参数。
- **现成的 A/B 工具从未用过**：S3 试听 `POST /style/audition` 本身就是「基线不注入 vs 当前文风」的对照实验台（style_override 可试未保存草稿），零调用。

**判定**：「仅样本无画像是否退化」没有任何本机数据可答——这本身就是审计结论的一半：**一个从未被使用、也从未被测量的参数体系，其存在合理性只能靠代码结构自证，而代码结构给出的答案是 §1 的空转证明与 §2.2 的冲突清单。**

### 2.2 三份注入文本的冗余与冲突对照【代码证】

对同一 stitch/continue 请求，system 侧可能同时存在三份风格治理文本：

| 治理面 | 位置 | 内容要点 |
|---|---|---|
| **基座 `_ADAPTIVE_SYSTEM`**（全模式共享） | adaptive_prompts.py:88-125 | 反 AI 腔四禁令（病态微操/套路比喻/匀速句式/解释性插嘴）+ 禁词表 + 「禁止直接心理升华与内心独白」+ 细节功能尺子 |
| **白描契约 `_ANTI_PSEUDO_SENSORY_BLOCK`**（stitch/continue 专属末位，**自称最高优先级**，用户逐字拍板） | ~~:517-532~~（2026-09 收编批已迁 `services/style/texture_contracts.py`，文案逐字不变；病灶词另列执法词表经洗层/上屏快检/完稿审计旁路合并，见 docs/agent/style.md 写作规矩节） | 假感官封杀 + 「北方硬朗白描…少用形容词与副词…坚决剔除小学生作文式的通感抒情，语言质感向现实派短句靠拢」+ 逗号注水禁令 |
| **画像+旋钮行**（render_style_positive ≤14 行） | settings_bundle.py:660-694 | 五维画像 + 段落节奏 + register/density/warmth 意图行 |

逐维度冲突/冗余判定：

| 画像/旋钮维度 | 与硬契约的关系 | 判定 |
|---|---|---|
| 句长节奏（画像 sentence_rhythm 行） | 基座已有「禁匀速句式：连续三句等长（用长短句交替）」 | **冗余** |
| density 旋钮 4-5 档（"修辞是常态"/"修辞繁密"） | 与白描契约「少用形容词与副词、坚决剔除通感抒情」**正面冲突**——且契约自称最高优先级 | **冲突（半程无效）** |
| warmth 旋钮 4-5 档（"情感外露"/"抒情直接"） | 与基座「禁止直接心理升华与内心独白式总结」「禁解释性插嘴」**冲突** | **冲突（半程无效）** |
| register（文白五档） | 无对应硬约束 | **独立有效**（唯一干净维度） |
| 词汇层级 | 弱关联 | 弱独立 |
| 开头习惯 / 结尾习惯 | 续写模式（stitch 50-120 字微镜头）**结构性没有开头结尾** | **失配**——对续写无效，只对 open 开篇模式有意义 |
| 段落节奏 | 弱关联 | 弱独立 |

**结论**：画像+旋钮的 8 个语义维度中，2 个冗余、2 个半程冲突、2 个失配、1 个弱独立——**只有 register（文白）真正干净**。作者面对 6 类参数调出的信号，有一半要么重复基座、要么被更高优先级的禁令吃掉。

---

## 3. fingerprint.py 指标大盘点：工效 vs 虚荣

### 3.1 全量分类表【代码证：消费面逐项 grep 核实】

**工效指标（有下游代码闸/检索器/业务动作消费）**——7 项：

| 指标 | 消费点 | 动作性质 |
|---|---|---|
| `sentence_len_cv` | RhythmAuditor 审计 warning（code_auditors.py:267-309，< CV_THRESHOLD_LO 告警）+ 心跳漂移提示（fingerprint.py:518-520）+ 前端对账参考带 | 提示（不拦截生成） |
| `dialogue_ratio` | DialogueAuditor（:380-403，vs 目标偏离）+ **scene_hint C2**（scene_hint.py:74-78——**唯一实证能换样本的检索干预**）+ 漂移提示 | 审计+检索 |
| `bigram_repeat_ratio` | 心跳漂移提示（thresholds.py:76 注释+ fingerprint.py:523-527，≥NGRAM_REPEAT_RATIO_HI 才提示） | 提示 |
| `texture_per_1k` + `most_textured_window` | finish 质感样本候选直投文风收件箱（fingerprint.py:359-401 + settle_finish.py:177-229） | 候选产生（作者确认才入库——本机零确认） |
| `count_negative_hits` | 文风页负面清单台账（fingerprint.py:484-491） | 展示+零命中灰显 |
| 规范原语四件（split_sentences/count_words/CV/count_dialogue_chars） | 审计侧 import 对拍（code_auditors，「同一把尺子」契约） | 基础设施 |
| `word_count` | 各处口径 | 基础设施 |

**虚荣指标（算完只进前端展示，零动作）**——13 项：`sentence_len_histogram` 五桶（直方图 SVG）、`ttr`、`mattr`（词汇丰富度——**全库无任何闸/检索/业务消费，grep 全部命中仅为指纹自身+前端指标网格**）、标点族四项（dash/ellipsis/exclaim/question per_1k）、段落族三项（paragraph_count/len_mean/short_ratio）、修辞族四项（metaphor/micro_action/transition per_500 + ai_taste_score——light 模式整体跳过，无门禁消费）、`sentence_len_mean/median`、`short_sentence_ratio`、`repeated_bigrams_top`。

### 3.2 重点核查三问

- **55 词质感词表（texture_per_1k）**：唯一动作=finish 时挑最密窗投样本候选（TEX_PICK_MIN_DENSITY=20/千词门槛，fingerprint.py:362）+趋势对账。**从未拦截或纠偏过任何生成**（词表自认"永远收不全细写…不进门禁"，:313-314 注释明示设计定位即参考）【代码证】；本机 style_events 零事件=候选零确认【数据证】。判定：**有设计定位、无实际战绩**。
- **MATTR**：滑窗 TTR（Covington 1982，O(n) 增量实现很漂亮，:249-269）——但**下游消费为零**。判定：纯虚荣。
- **TTR**：同上，纯虚荣。

### 3.3 一个结构性发现：提炼链不吃指纹【代码证】

样本提炼（extractor.py）的输入是**语料原文文本**，grep 证实 fingerprint 字段零进入提炼 prompt——五维画像是 LLM 从原文提的「声明」，不是指纹测量驱动的。范式宣言「测量>声明」在画像的生产环节就未曾兑现：**测量层算出的 20+ 指标中，真正回流进画像生产的数量为零**。测量与声明两条线在数据上完全平行。

---

## 4. 去参数化（De-parameterization）推演：两根支柱

**支柱定义**（对截断任务书的推演解释，见报告头）：文风收敛为——
- **支柱一：亲笔样本 few-shot**（k≤2×1200 字，检索注入）——代码自身范式宣言认定的最大杠杆（retrieval.py:24-25「一段范例胜过十句形容」）；
- **支柱二：负面清单四源执法**（prohibitions 合并 → prompt 禁词块/blocker 重钉 + 洗层 P1/P2 + finish 语义扫描）——唯一有**词级执法力**的平面。

### 4.1 废除清单与得失

| 废除项 | 判定依据 | 损失评估 | 附带拆除面 |
|---|---|---|---|
| **4 旋钮** | rhythm 零注入+检索空转（§1.3）；density/warmth 半程冲突（§2.2）；register 可降级为画像一行 | ≈0（实证零使用+数学空转+文本冲突三重定罪） | 前端四维按钮/四预设/实测锚偏差提示；DB `style_cards.style_knobs` 冻结只读（global_sys_prompt 冻结先例）；knobs.py 退役 |
| **对话比例滑块** | 零注入+检索 ≤0.05 空转 | 目标值功能由**语料实测锚**接替：漂移提示参考带改为「与你自己语料的实测对话占比比」（fingerprint 端点 reference 已算语料聚合值）——比作者拍脑袋的浮点数更诚实 | DialogueAuditor 的 target 回退固定阈值或语料锚；ADF segment_writer 给常量回退（引擎保留） |
| **五维手填画像** | 8 维语义中 2 冗余 2 冲突 2 失配（§2.2）；提炼链不吃测量（§3.3） | **保留提炼（LLM 从语料提+作者过目），废手填**；行数收缩——开头/结尾习惯仅对 open 模式注入 | 提炼 prompt schema 收缩；STYLE_POSITIVE_MAX_LINES 相应减 |
| **保留**：漂移提示/对账 SVG/质感候选/试听 A/B | 参考无害且有教育价值 | — | 漂移锚改实测（同对话滑块处理） |

### 4.2 断裂面与迁移成本

- **数据层**：两列冻结（style_knobs/dialogue_ratio_target——`books.global_sys_prompt` 冻结只读先例，Bible 退役批次 d75abef）；存量书有配置者 UI 降级为「遗留配置（不再生效）」说明行。
- **测试面**：`test_style_injection.py` 零变化契约（无卡 prompt 逐字节不变）不受影响；旋钮渲染单测、_selector_adjust 相关对拍需同步退役。
- **消费面**：audition 的 style_override 草稿试听（保留，试画像收缩后的形态）；章级特例卡语义（整卡覆盖）在两支柱下简化为「章级样本/负面清单覆盖」。
- **最大风险不是代码而是顺序**：本审计证明了「零使用+空转+冲突」，但**没有证明「画像对生成无增量」**（因为从未跑过对照）。拆除前应先用现成的 audition A/B 跑三组（基线/仅样本/样本+画像）×真实语料各 N 次——工具已存在、成本是一次会话的 LLM 调用。

### 4.3 与两支柱并行的一个更上游的病灶

**样本库零库存**（本机 sample_ids 全空）意味着支柱一从未装填弹药。比拆参数更优先的是冷启动通路：章节收编（POST /style/samples/from-chapters）、黄金池跨书兜底（B4，2026-09-13 已上线）、finish 质感候选——设施全在，缺的是写作台/文风页的入口引导（hero 邀请已有，但作者没走）。**先让支柱一真正开火一次，再决定画像的生死**——这比任何代码推演都更接近真相。

### 4.4 顺手机会：light 模式的计算浪费【代码证】

light 模式（章节批量指纹+心跳漂移+scene_hint）现在仍计算 lexical/repetition/texture 三族（fingerprint.py:446-449 注释「代价可承受」）——但 light 的全部下游只消费 cv/dialogue/repetition（漂移提示）与 dialogue（scene_hint）。texture 只在全量（finish 候选）需要，lexical/TTR/MATTR 谁都不需要。**light 模式跳过 jieba 分词三族可省每章一次分词**——顺手优化项，与去参数化同向。

---

## 5. 总裁定

| 体系件 | 有效力证据 | 裁定 |
|---|---|---|
| 4 旋钮 | rhythm 零注入+空转；density/warmth 冲突；register 干净但无独立验证 | **废**（register 可留画像一行） |
| 对话比例滑块 | 零注入+≤0.05 空转 | **废**，锚改语料实测 |
| 五维手填画像 | 半数冗余/冲突/失配；提炼不吃测量；零 A/B 数据 | **废手填留提炼**，先跑 A/B 再终决 |
| few-shot 样本 | 范式公认最大杠杆——但本机零注入 | **保留+修冷启动（最优先）** |
| 负面清单+洗层 | 唯一词级执法平面（wash/blocker 重钉/语义扫描） | **保留（支柱二）** |
| fingerprint 工效 7 项 | 审计/漂移/候选在消费 | 保留 |
| fingerprint 虚荣 13 项 | 零下游 | 停算或降级为「高级折叠」（直方图保留作教育展示可议） |

**一句话**：作者的直觉（"调了到底有没有用"）是对的——在本机的真实使用与代码的数学结构上，6 类参数里有 4 类的效力为零或自相矛盾；文风体系真正能打的两根支柱（样本+禁令）一根没装填、一根在低频运转。先装填、再测量、后拆除。

---

## 附录：证据索引

- 注入面：settings_bundle.py:660-694（render_style_positive+P6 注释+:691-692 节奏行跳过）· knobs.py:39-112（四维档位表+render_knob_lines）· budget.py:248-257（120/80/14 行上限）· retrieval.py:154-181（_selector_adjust 公式+档锚表）
- 检索数学：retrieval.py:200-301（fetch_limit=k 逻辑 :226-229、vec_adjust :237-244、兜底排序键 :281-289、AI 配比 :184-197）· sample_prior.py:27-80（±20% 因子+拉普拉斯平滑+冷启动恒 1.0）
- 真实数据：data/collab_events.jsonl（35 事件分布：dock_delivered 9/cards 7/ghost_discard 6/batch_accept 5/ghost_request 4/context_card 2/spine 2/ghost_adopt 1；**7 个 sample_ids 全空**；ghost_adopt 文本见 §2.1）· data/style_events.jsonl **不存在**
- 文本冲突：adaptive_prompts.py:88-125（基座）· :517-532（白描契约，"最高优先级"+北方硬朗白描）· :86-105（句级三律）
- 指标消费：fingerprint.py 全文（:315-330 词表 55 词、:359-401 质感窗、:484-491 台账、:494-531 漂移）· code_auditors.py:267-309,380-403（RhythmAuditor/DialogueAuditor）· thresholds.py:76（重复度阈值）· scene_hint.py:46-78 · extractor.py（grep fingerprint 零命中）
- 交叉引用：docs/style-paradigm.md（三平面分权）· docs/reports/style-mechanism-report.md · 生成质量诊断档案（文风页零使用结论同源）
