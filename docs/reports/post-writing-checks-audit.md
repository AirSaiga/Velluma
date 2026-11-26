> **归档说明（2026-09-19）**：写后检查三件套后端实调审计（2026-09-12），直接触发 Refinery 拔除（b6f064c）。

# 写后检查三件套 · 后端实调报告

> 2026-09-12 · 只读全量代码考察（三路并行扫描 + 用量数据核对 + 关键链路人工亲验）· 范围：**完稿体检**（/adaptive/finish）、**润色 Refinery**（/refinery/diagnose + confirm）、**读者反馈**（/reader-feedback）、**AI 编辑审阅**（/critique_chapter）· 只诊断不施工。
> 行号为 2026-09-12 工作区实况；「亲验」标记 = 报告作者逐行复核过源码。

---

## 0. 一页结论

1. **四个功能四套架构、四种年代**：完稿体检是 adaptive 时代的编排（观测齐全、不动正文）；Refinery 是独立服务包（SSE 两段式、进程内存态衔接）；读者反馈是 Refinery 的薄壳独立端点；AI 编辑审阅是最老的一代（legacy 调用层、**零上下文注入、零用量记账、零采纳通道**）——同一页 UI 里的四个「检查」，工程成熟度差着一个时代。
2. **作者主权梯度差极大**：完稿体检全程只出报告（唯一动正文的残句修复是作者过目采纳式，且有三重安全网）；**Refinery 润色的最终抛光稿是「未过目 + 不可 Ctrl+Z 撤销 + 服务端无快照」三连直灌画布**（完整链路已亲验，见 §3.5）——同一「检查」页里最危险的一环，且设计文档宣称的「事后可回滚」在代码中不存在。
3. **上下文注入水平参差**：Refinery 手术拿到 Canon+禁词+文风样本；完稿体检的编辑审阅拿到必达事件/伏笔/角色状态但**拿不到 Canon 真相文本**（语义一致性全靠模型裸审）；读者反馈和 AI 编辑审阅**什么都不给**（后者连大纲都没有，纯裸文本审）。
4. **真实使用为零**：四功能全史只有 4 次 LLM 调用（读者反馈×3、Refinery 诊断×1），全部发生在 2026-07 开发期；完稿体检/编辑审阅/残句修复从未跑过。

---

## 1. 横向对比总表

| 维度 | 完稿体检 | 润色 Refinery | 读者反馈 | AI 编辑审阅 |
|---|---|---|---|---|
| 端点 | POST /chapters/{id}/adaptive/finish | /refinery/diagnose + /confirm（均 SSE） | POST /chapters/{id}/reader-feedback | POST /api/critique_chapter |
| 架构 | orchestrator 编排 + 路由挂点 | 独立服务包两段式，**进程内存字典衔接**（1h TTL） | Refinery 包内独立端点，同步 JSON | 独立路由，3 次重试 |
| LLM 次数 | 2（审阅 1 + 事件抽取 1）+ 残句修复每条 1 | 诊断 1 + 手术 N + 回读 1 + 抛光 1 | 1 | 1 |
| 模型槽 | 审阅=reasoning(2000)；抽取/修复=creative | 诊断=reasoning(6144)；手术=creative(4096×N)；回读=reasoning(2048)；抛光=creative(**10000**) | reasoning(2048, temp 0.7) | **default→reasoning**(4096, temp 0.7) |
| 上下文注入 | 必达事件/开放伏笔/角色状态；**无 Canon 文本** | Canon★private/禁词(四源)/文风样本(k=2)/大纲前 300 字；**诊断阶段不吃文风** | 仅正文截 6000 字+章号+主旨 | **零**（连大纲都不给，docstring 自认） |
| 改不改正文 | **不改**（报告 only；残句修复=过目采纳） | **整章覆写**（draft_text + 前端回灌 content_text） | 不改 | 不改 |
| 用量记账 | generation_runs（critique/event_scout/sentence_fix.0） | generation_runs（五类 stage 齐全） | generation_runs（refinery.reader_feedback） | **不记账、不产 trace** |
| 前端采纳通道 | 残句「修复→采纳」、AI 味「收入收件箱」 | 问题清单勾选确认；**最终稿无过目直接落画布** | 无（纯阅读） | 无（纯展示，唯一 emit 是 close） |
| 历史使用 | **0 次** | 诊断 1 次（7 月） | 3 次（7 月） | 0 次（无记账无法确认，但无任何间接痕迹） |

---

## 2. 完稿体检（POST /adaptive/finish）

### 2.1 十阶段流水（settle_finish.py:75-247 + orchestrator.on_finish:619-675）

| # | 阶段 | LLM | 说明 |
|---|---|---|---|
| 0 | trace 绑定 | - | run_id=adaptive_{chapter_id}，trace 落 JSONL |
| 1 | 残句修复配额重置 | - | 进程内存 dict，5 处/轮归零（settle_finish.py:82,279） |
| 2 | **post_process 审计** | 1 | 残句正则扫(≤10)→覆盖率→spine_note→canon 泄露→LLM 整章审阅（budget≥4000 才审）；正文 <200 字短路 skipped；并发守卫 _finish_in_flight |
| 3 | **event_scout 事件抽取**（finish 源） | 1 | 整章截 4000 字抽候选世界事件→pending 池；三道去重+静音过滤 |
| 4 | B5 现实校验 | - | 知识视图 dead/present 名单对照 fresh fold；**失败仅 debug log 键不设（注释宣称「不沉默」实际沉默）** |
| 5 | B9 认知浮现 | - | 反讽机会+戏剧资本；**传空视角集→belief 全 UNKNOWN→所有读者已知命题全计反讽（降级语义名存实亡）** |
| 6 | 记忆重索引 | embedding | 章级替换：删旧块→1000 字硬切重写【第N章 片段i】前缀 |
| 7 | 语义扫描（换字逃逸） | embedding | 生效卡禁忌面 × 正文段余弦；阈值 0.78；未配 embedding 恒空 |
| 8 | 质感样本候选 | - | 句界窗(120~320字)密度≥20/千词→投文风收件箱 texture_pick；去重只比前 60 字 |
| 9 | 收件箱积压计数 | - | book 级 pending 计数+失效心跳缓存 |
| 10 | trace+冲账 | - | generation_runs 落库 |

### 2.2 LLM 调用清单

| 调用 | 槽位 | max_tokens | temp | thinking | prompt 要点 |
|---|---|---|---|---|---|
| 整章审阅（post_process.py:113-152） | reasoning | 2000 | 0.3 | 随配置档（代码不表态） | system=「资深小说编辑…只输出 JSON」；user=正文**首 3000+尾 3000 拼接**+必达事件+开放伏笔[:300]+角色状态[:300]；**不注入 Canon 真相文本** |
| 事件抽取（event_scout.py:160-167） | creative | 1500 | 0.1 | **显式关** | 11 种事件类型表+已入账排除块(15条)+正文截 4000；最多 6 条候选 |
| 残句修复（sentence_integrity.py:167-234） | creative | 1600 | 0.3 | **显式关** | 残缺类型+上句+待修句+下句→只输出修补后完整句；安全网=仍带缺陷/长度比[0.5,2.0]/name_dropped |

### 2.3 确定性检查与 LLM 检查的分界（重要）

- **残句**：3 条高精确正则（`[的地得]了一下` 等，sentence_integrity.py:66-88）——只抓三种硬残型，宁缺勿滥。
- **情节覆盖率**：`check_must_hit_coverage`（canon_checks.py:22-45）用「逗号切词取前 3 个 ≥2 字词、任一子串命中」——**不是** text_match.py 的滑窗统一判据（该判据专为治这类噪声而设，但完稿 coverage 没接入），双字常用词组可能造成「未写被判已写」的反向噪声。
- **秘密穿帮**：`check_canon_compliance` 纯子串匹配（canon [private] 标签词 ≥3 字命中正文）——**语义级泄露检查不存在**：canon/consistency.py 的 check_consistency 根本没被 finish 调（只被 canon_watch 心跳和 canon 路由调）；prompt 里也没给 Canon 文本，语义穿帮完全赌审阅模型裸审。
- **B5/B9/记忆/语义扫描/质感候选/积压计数**：全部确定性或 embedding 检索类。

### 2.4 报告契约与消费缺口

前端消费：残句(修复流)/AI 味变体(投收件箱)/覆盖率/打算附注/秘密穿帮/编辑意见(前5)/记忆新增/收件箱积压。**后端产出但前端零消费**：reality_check（B5）、cognition_surface（B9）、texture_sample_candidate、canon public_fact_count、report.word_count——B5/B9 两整个世界内核功能在 UI 上无处可看。

### 2.5 主要风险

1. 无超时钳制：critique+scout+四挂点串行，慢端点下前端「通读中…」无上限（orchestrator 的 12s 同步组件超时不覆盖 finish）。
2. 正文 <200 字短路时报告形状退化，前端渲染静默空白。
3. 「name_dropped 安全网」在 adaptive 路径恒不触发（调用方不传 registered_names，安全网循环空表——settle_finish.py:310-312 vs 注释 :272-274）。
4. 配额与并发守卫均为进程内存态：多 worker/重启即失效。
5. 覆盖率判据未接统一匹配族（见 2.3）。

---

## 3. 润色 Refinery（/refinery/diagnose + /confirm）

### 3.1 五阶段流水（routes/chapter_generation/refinery.py + services/refinery/）

**两段式 HTTP**：诊断与手术之间靠**进程内存字典** `_PENDING_REFINERIES`（1h TTL，无 DB、无跨进程）衔接——刷新页面后 runId 刻意丢弃（前端 :468），服务端重启/超时即「无效或已过期的 run_id」。

1. **诊断**（SSE）：整章按段 `[P0][P1]…` 每段截 800 字，1 次 reasoning LLM（temp 0.2 / 6144 tokens / json_object）产 9 类问题（tell_not_show/pacing_drag/pacing_break/scene_jump/info_leak/character_off/redundancy/weak_hook/emotion_mismatch），每条带段号+精确引文+严重度+建议。**诊断 prompt 不吃文风画像/样本/禁词**（文风只在手术与抛光）。诊断失败静默返回空清单（UI 显示 0 问题不报错）。
2. **确认**（前端问题清单）：pending 默认全勾（提交时一律按 confirmed 发送）；可补自定义问题。
3. **手术规划**（0 LLM，纯算法 planner.py）：按段落范围合并重叠/相邻问题→每组一手术（rewrite/merge/delete/insert 四型）；**定位只用段号**——诊断要求的「精确引文」只用于前端展示，手术不看它。
4. **手术**（每手术 1 次 creative LLM 串行，temp 0.6 / 4096）：「最小侵入式修改」五原则+目标段原文(≤6段/4000字)+禁词表；改后段落按 \n\n 拆开逐位替换，重叠手术后写覆盖先写。
5. **回读+抛光**：回读 1 次 reasoning（temp 0.1 / 2048 / 截 6000 字）产 verdict（**失败降级为 pass，UI 上失败与通过不可区分**）；抛光 1 次 creative（temp 0.5 / **10000 tokens / 全文不截断**，对照作者样本统一语感）。

### 3.2 LLM 次数与成本形态

诊断 1 + 确认后（手术 N + 回读 1 + 抛光 1）；无确认时只跑抛光 1 次。抛光的 max_tokens=10000 是全应用最大单笔输出预算之一——**每跑一次完整润色至少 3 次 LLM + N 次手术**。

### 3.3 Issue 契约与手术机制要点

- 10 类问题枚举 + 三档严重度 + 影响半径；位置=段号(0-based)+范围+引文+char_offset（后者 LLM 基本不产、后端不消费）。
- **custom issue 陷阱（真实行为缺陷）**：前端自定义问题不带段号 → planner 归 (-1,-1) → surgeon 兜底**改最后一段**——作者写「第 5 段读起来不顺」实际重写的是**章末段**（RefineryIssuesPanel.vue:88-98 → planner.py:53-54 → surgeon.py:69-72）。
- `IssueDecision.edited_suggestion` 字段被收下但完全忽略；Operation 的 context_summary/canon_constraints 规划时填、手术时不读。
- 手术 prompt 的「全文上下文摘要」实际=大纲前 300 字透传；emotion_curve/character_states/active_hooks/author_intent 四字段**恒空**（注释「第 2 期接入」至今未接）——对应块永远渲染「（未提供）」。
- light 模式（中低severity自动确认）在 schema 里存在但前端写死 deep，**UI 不可达**。

### 3.4 产物落盘链（亲验完整闭环）

```
抛光完成（后端）
→ SSE TEXT_CHUNK 流入前端 streamText（useGenerationSession.ts:726-728）
→ onDone 置 stage='done'（:721）
→ WorkspaceView watch stage（:362-363）→ handleGenerated(streamText)
→ store.updateChapter(selectedChapter.id, {content_text, draft_text})（:917，后端同时独立覆写 draft_text routes:420-429）
→ 编辑器 modelValue watch → setContentNoHistory（RichTextEditor.vue:698-705）
→ 画布整体替换，toast「已写入本章」
```

### 3.5 三连风险（亲验，本报告最重要的发现）

1. **未过目**：作者确认的是「问题级手术」，但抛光是整章重写——**最终抛光稿没有任何 diff/预览/过目步骤，直接落画布**（旧的 preview 属性链已随写作台重构移除）。
2. **不可撤销**：外部 modelValue 写入走 `setContentNoHistory`（RichTextEditor.vue:705）——**Ctrl+Z 撤不回抛光前的正文**；服务端也无快照/undo 端点。设计文档 generation-v4.1-refinery.md:311,426 两处宣称「事后可回滚」，**代码中不存在任何回滚实现**。唯一的恢复途径是抛光前的自动保存历史（若后端有版本留存——当前 chapters 表无版本机制，等于没有）。
3. **跨章覆写**：handleGenerated 写的是 `selectedChapter.value.id`（**当前选中章**，非发起润色的章，WorkspaceView:914-917 无章节守卫）——润色流式期间切到另一章，A 章抛光稿会**整章覆写 B 章画布**。同类风险在 stitch/heartbeat 已有「章节纪元守卫」防护，Refinery 链路没有。

### 3.6 其他风险

- 诊断每段截 800 字（超长段后半不参与诊断）；回读/读者反馈截 6000 字但**抛光不截断**——前读后改所「见」内容不一致。
- SSE 完成帧是绕过标准封装的裸 `{"event":"COMPLETE"}`；文档/头注宣称的 REFINERY_COMPLETE、REREAD_DONE/POLISH_DONE 事件均不存在。
- 回读失败降级 verdict=pass → UI 显示「✓ 通过」；抛光失败降级返回原文但「抛光完成」事件照发。
- 与「章节优化 refine_draft」（/optimize_chapter，workflows/refining.py）和 ADF refiner 是**三套同名不同实**；/optimize_chapter 前端零调用（死路径）；深度清脂（wash 槽）与 Refinery 零函数复用，只共享禁词源。

---

## 4. 读者反馈（POST /chapters/{id}/reader-feedback）

- **1 次 reasoning LLM**：temp 0.7（注释「要自然」）/ 2048 tokens / 无 JSON 格式；输入=正文截 6000 字+章号+主旨（大纲前 300 字）。
- **人设**：「资深网文读者，刚读完一章」——明确**不做编辑式找问题**（「那是另一道工序的事」）；第一人称、像跟朋友聊、300-600 字、结尾一句「读者期待」；自然融入五方面（最吸引段/主角喜不喜欢/哪里出戏/读后最想知道什么=钩子有效性/节奏）。
- **零落库**：反馈文本不存任何表，刷新即失；只有 LLM 用量进 generation_runs。
- **零上下文**：不知道任何设定/文风/前情——好处是「干净读者视角」名副其实，坏处是它无法评价设定一致性（本来也不该它评）。
- 前端 InspectorPanel 调用不传 raw_text（后端取 draft_text or content_text）。

---

## 5. AI 编辑审阅（POST /api/critique_chapter）

- **最老一代实现**：走 legacy `call_llm` 包装（内部采了 usage 但**返回时丢弃**）——**不进 generation_runs、不产 trace 文件**，这个功能的 token 成本在观测体系里完全不可见。
- **模型槽**：不传 model_type → default → 映射 reasoning 槽（当前配置 qwen3.8-flash / effort=max）；max_tokens=4096 / temp 0.7（前端不传 temperature，请求参数成死参）/ 3 次重试。
- **零上下文注入**（docstring 自认「纯粹基于文本内容」）：文风/设定/大纲/前情一概不进 prompt——**整章无截断直塞**（对照：完稿体检审阅还有首尾 3000+3000 截断）。编辑看不到伏笔与设定，对一致性/伏笔类问题天然易误判。
- **输出**：`comments[]{exact_quote, type(自由字符串), reader_feeling, suggestion}` + 总评（50 字内）——无 severity、无段号/偏移；引文定位靠模型自觉，前端纯文本展示。
- **无采纳通道**：弹窗唯一 emit 是 close；建议只能人工照抄（对照：灵感弹窗有「应用到大纲」）。
- 人设与三个诊断维度（AI 味扫雷/节奏句式/Show Don't Tell）与完稿体检的审阅 prompt 是两套措辞，同为「编辑视角」但互不知晓。

---

## 6. 使用数据（generation_runs 全史）

| stage | 次数 | 时间 |
|---|---|---|
| refinery.reader_feedback | 3 | 2026-07-21 ~ 07-23（开发期） |
| refinery.diagnostic | 1 | 2026-07-21 |
| adaptive.post_process.critique / event_scout.finish / sentence_fix.0 / critique_chapter（不记账） | **0** | — |

四个功能合计 4 次 LLM 调用，全部来自 7 月 Refinery 开发验证；此后两个多月零使用。

---

## 7. 综合观察

1. **同名不同实家族**： refine_draft（整章重写，UI 死路径）/ Refinery（本报告主体）/ ADF refiner（Phase 6 补埋器）——「润色」「审阅」「检查」三个词在 UI 上至少覆盖了 6 个不同的后端实现。
2. **编辑视角 prompt 有三套互不相认**：完稿体检 critique（一致性/情节/伏笔）、critique_chapter（AI 味/节奏/Show Don't Tell）、Refinery 诊断（9 类网文问题）——三套人设、三套分类学、零共享禁词/文风/上下文基线。
3. **作者主权按危险度排序**：完稿体检（只报告+过目采纳）> 读者反馈/编辑审阅（纯阅读）> **Refinery（未过目整章覆写+不可撤销+可跨章）**。建议任何收敛工作从 Refinery 落盘链补「最终稿过目/diff」与「章节守卫」开始——这是唯一能动作者正文的检查功能。
4. 观测落差：adaptive 系记账齐全；critique_chapter 完全游离在观测体系外——若保留该功能，先接 RunRecorder。

## 附：方法与可信度

三路并行只读考察（finish 全链 / Refinery 全链 / critique）+ 用量数据核对 + **三条关键链路人工逐行亲验**：①Refinery 产物落盘闭环（streamText→stage done→handleGenerated→updateChapter→setContentNoHistory）②跨章覆写无守卫（handleGenerated 写 selectedChapter 而非发起章）③noHistory 隔离外部写入（RichTextEditor.vue:698-705）。所有 bug 级定性发现均有源码行号支撑。
