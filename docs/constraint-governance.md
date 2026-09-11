# 约束治理（Constraint Governance）

> 唯一权威文档 · 2026-09-02 一期施工；**二期（硬闸门加固：返修环/熔断/
> 两级开关/语义闸）见 §11**。背景与调研全文见 memory
> `constraint-governance-research-2026-09-02`；导师框架=「违约三要素 ×
> 执法五形态」（teacher-kimi 2026-09-02 审查定稿）。

## 1. 为什么需要治理

事故驱动的教训：约束曾经散落在 prompt 文案里，每次穿帮靠「往 prompt 加一条
禁令」打补丁。实测证明这条路有天花板：

- 中档小模型（qwen3.8-flash/kimi/mimo 级）对 prompt 约束的服从率 <100%，
  且随条数稀释（「禁令堆叠催生新套路与判断稀释」——2026-08-27 诊断结论）；
- 措辞会被误读：「在场实体专名（硬约束）：必须原样使用」被小模型当登场
  指令，把不在场的敌方机甲写成主角正在修的螺丝（2026-09-01 流光穿帮，
  trace 实证 12 天十几轮稳定复现）；
- 模型违规常是**素材缺口信号**：它抓了唯一能抓的东西。禁令被反复违反时，
  先查输入侧是不是没喂对事实。

## 2. 治理总纲

**违约三要素**：一次违约 = 手段（输入里拿得到违规素材）× 动机（prompt 措辞
给了拉力）× 监护缺位（输出无人检查）。掐断任一顶点即止，选最便宜可靠的。

**执法五形态（可靠性降序）**：

| 形态 | 位置 | 实例 |
|---|---|---|
| ① 供给切断 | 输入侧 | 专名可见过滤、prebeat 裁剪、after_text 泄漏手术 |
| ② 输出代码闸 | 上屏前 | ghost_guard 五检、dock 校对环、字数闸 |
| ③ 确定性改写 | 生成后 | 洗层替换、复读剥离、保名闸回退 |
| ④ prompt 偏置 | 生成中 | 正面画像、few-shot、节拍纪律 |
| ⑤ 事后审计 | 上屏后 | finish 报告、语义扫描、constraint_events 度量 |

**铁律：能①饿死的不用②拦，能②判的不用④求；④只承担剩下的纯语义残余**
（OOC、节拍保全、呼应方式——代码判不了真假的）。

**新约束准入判据**：判定性质（判定式可拦/启发式只 warn 或仅菜单件/纯语义
留 prompt）× 代价不对称（漏报贵→激进，误报贵→保守）× 失败代价承担者
（menu 可丢 / ghost 只提示——作者主权红线 / report / data）。

## 3. 约束登记册（registry）

`backend/services/constraints/registry.py`——每条约束声明
id/条文/layers/enforcement/surface/status/when/origin。**status 是代码内
数据**：`shadow`（只埋点不动作）→ `live` → `report-only` → `retired` 留档。

- 同一约束多层执法用同一 constraint_id 关联（首例：`dock-no-psych`
  layers=[prompt, gate]）；
- 首批只录有执法挂钩的 ~25 条；纯文档性条文惰性补录。

**事件台账** `data/constraint_events.jsonl`（写读 API：
`services/constraints/events.py`）：schema
`{ts, book_id, chapter_id, constraint_id, status_at_event, outcome, reason, detail}`。
outcome=hit|drop|exempt|mute|rewrite。信用分机制一期不做，但数据从第一天
攒——缺了未来只能补埋点重来。

**读面**：`GET /api/chapters/{chapter_id}/adaptive/constraints/summary` →
`{chapter_id, total, by_constraint, by_outcome, recent(最新 20 条)}`（324c83a
落地；按章过滤台账聚合，信用分/服从率度量的数据出口——前端「约束健康」面板
等数据体量后再接线；failure 静默返回空结构，零报错契约）。

**强措辞 lint** `scan_prompt_wording`：词典=铁律/绝不/必须/禁止/不许/严禁/
务必（section 标题计入）。dock 编译器验收闸=「铁律」归零、总数较旧基线
（15+）显著下降。

## 4. 分节 prompt 编译器（剂量治理）

`services/constraints/prompt_sections.py`——数据驱动的分节条件拼装
（PromptSection.text + when(ctx) 谓词）。**通用设施，禁止为单个 prompt 手写
条件拼接**。第一个租户：dock system prompt（2026-09-02）——节拍依赖子句挂
`has_outline_nearby`，【自检】清单已删（中档模型负资产），强措辞 15+ → ≤4。
五模式共享基座的编译器化挂账（stitch 是最敏感质量路径，不同批动）。

## 5. 检测器生命周期

- **shadow 出生**：新检测器只落 constraint_events 不产用户可见信号
  （out_of_scene warning 带 `local_only=True`，stitch 路由过滤出 GHOST_DONE 帧）；
- **promote 门槛**：回归语料库准入（事故样本 100% 命中 + 合法样本 0 误报）
  + ≥20 次真实写作 shadow 命中且人工抽检 FP<10%，registry status 翻 live；
- **回归语料库** `backend/services/validation/regression_corpus/*.json`：
  流光事故真实 trace 文本（hit/no_hit/known_fp_hit 三类归档）+ 边界用例
  （豁免/负面动词清单）。准入即测试
  （`test_regression_corpus.py`）。

## 6. 数据层治理（在场推演救回）

折叠核心只认 birth/move 定位且不读 participant_ids——事件缺结构化链接时
在场推演恒空。三角对策：

1. **写入侧**：`event_parser._resolve_names` 三级匹配（精确 → 双向包含 ≥2 字
   → jieba token 边界），漏报显著减少；歧义不猜（留作者表单改）；
2. **读侧兜底**：`lexical_presence.enrich_state_with_lexical_presence`——
   无状态实体从 ≤t 且带 location_id 事件的 note 词法命中补在场，标
   `presence_source="lexical"`。四个调用点统一同一函数（repo 汇聚点 +
   scene_slice 三处直调点），死者不复活、歧义不填、不回写 participant_ids
   （append-only 事实源保持纯洁）；
3. **缺口可见**：切片条在场行渲染「据正文推断」badge（补录建议载体；浮卡
   后端字段 `presence_source` 已备、前端渲染挂账）；每个词法补填落一条
   `event-participant-gap` 事件（on_event 回调，缺口可聚合度量）；
   `scripts/backfill_event_participants.py` 存量回填（默认 dry-run，
   `--apply` 显式写入；同名歧义双实体不写——须先在世界页改名消歧）。

## 7. 明确不做（导师裁决）

- **constrained decoding / logit bias**：中文 BPE 与词边界错位、厂商支持碎、
  约束的是语义不是 token 序列；
- **实时 LLM-judge 拦截**：judge 只做度量（抽样质检喂台账、prompt 改版 A/B
  评测器——挂账）；
- **多轮自动重试**：retry ×1 仅限句级具体反馈（字数闸模式）；dock 件靠
  过采样（4-6 枚丢违规件保 3-4）代替重试；
- **句级在场的世界状态推演改造**：句级真相在光标前正文（提及扫描），不在
  事件折叠。

## 8. 挂账清单（下一批候选）

- 补全参与者收件箱产品化（回填脚本替代中）；
- judge 抽样质检 + prompt 改版 A/B 评测器；
- 感知带「这是有意的」作者豁免按钮（误报退出成本=作者信任的决定变量；
  style_cliche_exemptions 同款机制）；
- 流式句界增量检（burst 长文「只提示」目前退化为读后提示）；
- 五模式共享基座编译器化；
- **after_text 手术的两条残留**：①recency_pin「本章提及」行仍带 after-only
  名（knowledge_plane 侧）；②outline user prompt 本就含 after_text 原文
  （双端锚定，预期行为——勿当同款 bug 复发再修）；
- 提及扫描光标截断完整语义；
- 约束健康前端面板（等 constraint_events 有体量，照抄协作面板零返工）；
- **persona_drift v2**：阈值 2.0/百字改为相对基线（幽灵密度 > 作者画布自身
  密度 + margin）——第一人称成书会恒定命中，signal-only 下可接受；密度
  分布已进 `adaptive_stitch_complete` trace（`persona_density` 字段）供校准；
- **浮卡 badge 渲染**：`build_context_card` 已返回 `presence_source`，前端
  浮卡组件未渲染（切片条已渲染）；
- **黄金对拍补一组**：远程节拍场景（就近节拍在别的场景）的第一步质量——
  编译器化时「就近节拍若在别的场景，给『过渡到那一拍』的第一步，不给
  那一拍的进行中」尾句为剂量收敛被裁，toward_beat 槽位定义覆盖大意。

### 8.1 实施审查 P2 备案（2026-09-02 导师 review，不影响提交）

- overflow_tail/overflow_head 的 outcome=`trim` 与 drop=违规 分列
  （防过采样稀释 by_outcome 的 drop 语义）；
- out_of_scene 名字命中经 jieba token 边界复核（`_name_in_text`）——已知
  残余：jieba 把「流光溢彩」整词切割时复核通过率取决于分词结果，普通名词
  义残余属声明接受的误伤面；调窗必须沿用「去空白不去标点」归一口径；
- all_names 候选宇宙单一口径：生产路径走 bundle 内省（`_bundle_all_names`
  只收 character/asset），**禁止显式传 proper_nouns()**（全类型+cap20，
  语料库口径分叉——审查 P1-2 已修）；
- enrich 只收 entity_type=character（P2-8）；
- 回填脚本同名歧义双实体不写入，须先改名消歧（P2-7）。

## 9. 换模型 checklist

服从率是 **模型 × 规则** 的函数（实测：mimo 节拍对白禁令三连不服从、kimi
字数指令不服从）。换厂商/型号时：

1. 跑回归语料库（`test_regression_corpus.py`）确认检测器判据仍对拍；
2. 查 registry 按 `status_at_event` 分桶的近 7 天事件——原模型的低服从
   约束（reason 里的 drop/hit 密集者）在新模型上重新观察；
3. trace 抽 3 条新模型 dock/stitch 产出人工比对（黄金 trace 对拍同款）；
4. model_config 切换后首日关注 `kg_join_dead_speak` / out_of_scene shadow
   命中率漂移。

## 10. 消费面清单（词法兜底 enrichment 的影响范围）

`repo.compute_world_state`（routes/world.py:324/345 调试端点、fold.py、
world_bridge 生成桥接）+ `scene_slice.build_scene_slice`（切片条）+
`build_context_card`（情境浮卡）。前端世界页画布吃严格折叠不受影响；
分叉由「据正文推断」badge 解释。

### 10.1 同批 prompt 变动面（明示，导师审查 P2-9）

- **实体称呼块头**（五模式共享的 `_nouns_block_def`）：「在场实体专名：
  以下名称必须原样使用」→「实体称呼：正文若写到下列名称……称呼规范，
  不是登场清单」——2026-09-01 穿帮修复的措辞卸力，全部 world 书生效
  （legacy 书名单口径不变）；test_style_injection/test_stitch_context 已
  同步，零变化契约在 style 注入维度无失守；
- **dock 数据块措辞**：角色永恒设定两处（system 硬性要求 3 + user 块头）
  改资料性措辞；
- **场景锚定节尾句**：「就近节拍若在别的场景……」在编译器化中被裁
  （见 §8 挂账补对拍）。

## 11. 二期：硬闸门加固（2026-09-02）

> 用户拍板：**可接受每次生成多一次返修的延迟，不可接受错误结果上屏**；
> 「不相信模型自觉」——确定性闸门承载保底承诺，模型只负责写、不负责自觉。
> 针对三类实测事故：续写违反设定 / 人物地点穿越 / 卡片抢拍。

### 11.1 缝合返修环（核心新机制）

一期 ghost_guard 全部「只提示不拦截」，检出问题稿子仍原样上屏。二期闭环：

```
检出硬违规 → 带稿改写重试 ×1（违规清单作反馈）
→ 确定性验收（重跑同一套闸门，零违规才过——不采信模型自我声明）
→ 仍不过 → 句级切除（删违规句）
→ 再不行 → 拒稿不上屏（GHOST_REJECT 帧）
```

- 泛型编排 `services/validation/repair_loop.py`（`run_repair_loop`）——
  prompt 组装/LLM 调用/台账全由调用方注入，模块不感知具体约束种类；
- 插点：**字数闸之后、deai 抛光之前**；单次 stitch 的 creative 调用 3 次
  封顶（初生成 + 压缩重试 + 返修）；
- 返修稿必须重跑确定性后处理（`_postprocess_repair_draft`：复读剥离 /
  首句锚定截断 / outline 保尾截断）——防修好违规却引入复读/超字；
- **切除三豁免**：stitch/continue/burst/open 首句（衔接锚句，防半句悬空
  事故复发）不可切；outline 末段不可切；切除后剩余 ≥ max(目标×0.6, 80字)；
  只切内部句，切完重检必须零硬违规；
- 台账 outcome 词表扩 `repair`/`excise`/`reject`/`breaker_open`；返修调用
  独立记账 `stage=adaptive.stitch_ghost.repair`（前端 usage「续写·硬伤
  返修」）。

### 11.2 拒稿三件套（防弱模型频繁拒稿毁掉体验）

1. **章级滑窗熔断**：10 分钟内 ≥2 次拒稿 → 自动降级为「带病上屏 + 醒目
   警示」（合成 warning `quality_breaker`「自动修正连续失败，已暂时转为
   仅提示」），落 `breaker_open` 台账；窗口老化自愈，无需人工复位；
2. **拒稿 toast 逃生舱**：「这次没能写出合格的续写」+ 按钮「仍以疑点提示
   上屏」→ `materializeRejectedGhost` 把被拒原稿以普通幽灵形态灌回
   （Enter 采纳 / Esc 蒸发同契约，疑点清单随附）；
3. 与既有弹舱守卫联动（作者已动笔则不弹）。

### 11.3 两级独立开关（registry 控制面化）

「进帧上屏」与「返修资格」是两个独立开关：

- `status`（shadow/live/report-only/retired）管**可见性**——ghost_guard 的
  `local_only` 不再硬编码，改读 `registry.status_of()`（读不到按 shadow
  兜底）；**out_of_scene 已转 live**——穿越提示从此上屏可见（此前完全
  不可见）；
- `Constraint.repair`（none/excise/rewrite/regenerate，缺省 none）管
  **返修资格**——`repair_eligible(warning)` 三重门：kind 有登记 ×
  status=live × repair≠none；**fail-closed**：未知 id / 未声明一律 none；
- 初始登记：`canon_leak`/`secret_leak`=rewrite（泄密类可直接改写修复）；
  `dead_speak`=none（可能是闪回/对话合法意图，只提示）；`cliche_hit`=none
  （wash 辖区不重复执法）；`out_of_scene`/`location_jump`=none 起步
  （按 §5 promote 门槛攒数达标后再开 excise——改 status 即生效，不用再
  改代码）。

### 11.4 终检移位与防回退污染

- **终检 ghost_guard 移到 wash P2 修补之后**——旧链 P2 修补稿不重检是
  既有洞（修补引入违规无人发现），拒稿时代它承重；
- **违规原稿不进任何可回退通道**：wash 的 original_text 快照存的是过检稿
  （防「用原稿」把被拒违规稿请回屏幕）；前端 repaired chip 只展示计数与
  类目（「已自动修正 N 处穿帮：疑似泄底」），不暴露被拒原稿；
- GHOST_DONE 增 `repaired={count,kinds,action}` / `breaker_open` 增量字段；
  trace `adaptive_stitch_complete` 带 repair_action/repaired_count。

### 11.5 地点穿越闸（第六检，shadow 出生）

判据：幽灵文本出现「转场动词 + ≤2 字填充 + 场景作用域外已知地点名」
（`scene_visibility.find_location_jump_hits`；动词表 11 词：回到/来到/
走进/走入/进入/踏入/迈进/抵达/赶回/赶到/前往——裸查地点名必死，谈论/
回忆/远眺合法；窄填充窗是防误报主闸）。作用域闭包 = 场景钉自身 + 祖先
（scene_scope_ids 既有口径）∪ 全部后裔（保守裁决：建筑内走到下属房间
算合法转场）。边界复核与闪回豁免与 out_of_scene 同一份判据。
**关闭条件**（任一即整检不跑零变化）：非 world 书 / 无场景钉 / 无地点
数据。回归语料 `regression_corpus/location_jump_cases.json`（11 例 +
旗舰断言，准入即测试）。shadow 期只落台账不进帧，promote 门槛同 §5。

### 11.6 语义抢拍闸（全 shadow 双跑）

字面 n-gram 闸抓不住语义改写（节拍「主角进入要塞与守军对峙」被写成
无一字相同的画面）。新通用件 `services/validation/semantic_overlap.py`
（`semantic_overlap_hits`：文本 A vs 目标集 B 的余弦比对；切段复用
semantic_match 同一把尺子；目标向量进程级缓存——大纲节拍章内稳定）：

- **C0 实测结论（2026-09-02，SQLite 默认路径 + 真实 Key）**：纯 API 比对
  不需要 pgvector 存储——新增窄判定 `is_embedding_api_configured()`
  （只看 Key）与纯 API 入口 `get_embeddings_api_only()`（绕过
  get_embeddings 的 SQLite 存储门控；**写侧永远走 get_embeddings**，
  SQLite 下它正确地空转省钱）。实测分离度：近义转述对 0.695 vs 无关句
  0.29——**阈值占位 0.80 偏高**（转述对都过不了），转正前必须用真实
  卡片×节拍语料跑分离度校准（scripts/calibrate_semantic_threshold.py
  同思路）定档；
- dock 侧：≥4 字字面闸保持 live 不动；语义版与「≥3 字+动词重合」加强版
  shadow 双跑落台账对比，攒数据后再转正（丢件由既有 4-6 枚过采样吸收）；
- stitch 侧：幽灵全文 vs 就近节拍语义重合，shadow 只落台账；转正后只走
  返修（令模型改写）不做切除（语义重合无法句级归责）。

### 11.7 SSE 帧与前端透出

- 新帧 `GHOST_REJECT`（code=quality_reject，携带 text+warnings 作逃生舱
  载荷）；前端 `_onGhostReject`：安静 toast + 逃生舱按钮；
- 新 warning kind 四处登记（adaptive.api.ts 类型联合 / GhostWarningsBar
  KIND_META / useGhostDraft WARNING_KIND_LABELS）：`out_of_scene` 人物
  不在场 / `location_jump` 地点穿越 / `cliche_hit` 禁忌词 /
  `quality_breaker` 自动修正暂停；未登记 kind 回退原串不炸；
- `GhostRepairedChip`（薄荷系，与洗层条同「已处理」语义）：
  「已自动修正 N 处穿帮」。

### 11.8 二期明确不做（诚实边界）

- **非实体形状的逻辑矛盾**（如「拿起不存在的物件」）无法确定性检测，
  本期不保——靠台账积累事故案例后逐个确定性化（治理框架既定路线）；
- **LLM 裁判层**（另一个模型审查逻辑）不做——与「不相信模型」原则一致
  且拒绝成本上升；架构留有挂点（run_repair_loop 的 recheck 可换实现）；
- 语义抢拍本期只攒数据不拦截——翻转已隔离为 registry 配置。

### 11.9 二期测试清单（准入即测试）

- `test_repair_loop.py`（9 项：clean 放行 / repaired / excised / rejected /
  预算封顶 / 空改写计失败 / fixed_kinds 去重排序 / 带稿改写契约）；
- `location_jump_cases.json` + `test_regression_corpus.py` 接线（11 例 +
  旗舰动词邻接断言）；
- `test_semantic_overlap.py`（8 项合成向量：阈值边界 / 正交 / best-target /
  目标缓存二次零重嵌 / 未配置零调用 / 异常静默降级 / 降序）；
- `test_governance.py` 二期更新（out_of_scene 转 live 三处旧锁更新 +
  repair fail-closed / 三重门 / location_jump shadow 五新锁）；
- 前端 `ghostRepair.test.ts`（11 项：新 kind 映射 / 汇总话术 / repaired
  灌入纪律 / beginGhost 重置 / 逃生舱灌回）；
- 全量回归：后端 963 绿（929 基线 + 34 新）+ 前端 147 绿（136 + 11）+
  vue-tsc 净。

## 12. 三期：质感与意图面检测器（2026-09-03）

四条新登记 + 一条检源扩展，全部挂 ghost_guard（十检终态）；同批 prompt
侧改动（意图块「目的地」重框 / recency_pin「校验资料非登场名单」重框 /
双轨生成契约 motion·texture）属供给措辞层，见各 registry origin 字段。

- **ghost-guard-beat-rush（第七检，live + rewrite 出生）**——首个跳过
  shadow 直接 live 的新检。判据复用已 live 的 dock-beat-overlap 同族并
  加严（单 4 字窗 → 同拍 ≥2 个 4 字窗 + 正文尾部已有词排除），FP 面事前
  论证完毕；repair=rewrite，excise 明确不授权（抢拍是方向性错误，删句
  对整稿伤害大于改写）。when=stitch/continue 且有未写就近节拍——
  open/outline/burst 的本职就是写节拍，整检关闭。origin=trace 实证 3/3
  幽灵 verbatim 消费「被工头打断」节拍措辞。
- **ghost-guard-cast-roll-call（第八检，shadow）**——短幽灵点名 ≥2 个
  在场者（正文尾部已点名的不计）= 名单演出疑点。输出侧计数粗代理
  （「有没有戏份」代码判不了），攒精确率后再议 promote。
- **ghost-guard-mind-leak（第九检，shadow，repair=none）**——非在场/
  提及名单实体名 × 内心动词六词族（心想/暗想/思忖/盘算/意识到/明白过来）
  ±10 字 → 思绪泄漏（旁白替不在场者报告内心=POV 相机拍不到的画面）；
  闪回/转述豁免；只抓具名主语——代词指代无法确定性解析，宁漏勿误。
- **ghost-guard-belief-leak（第十检，shadow，repair=none）**——在场者
  无人知晓的私有真相命题，其里文本短语（≥4 字整段）被逐字写出。
  路由侧预裁「无人知晓」（belief.fold_belief + proposition_status，
  任一在场者 KNOWS 即合法——知情者 POV 叙述），guard 保持纯文本比对。
  canon_leak 护标签词、secret_leak 护私有实体档案，本检补「真相里文本
  内容本身」的检出面缺口。
- **3b 检源扩展（无新 id）**——字段级真相分层（b8209f5，
  world_entities.field_layers）的秘密/半露字段内容并入 secret_leak
  同一判据同一 kind，rewrite 资格随之贯通；bundle.field_layer_secrets
  由 overlay 适配器派生，零额外查询。
- shadow 三检 promote 门槛不变（§5：回归语料库准入 + ≥20 次真实命中
  FP<10% 人工抽检）；前端 warning kind 未登记——shadow 不进帧无需登记，
  beat_rush 经返修环消化，熔断降级带病上屏时未登记 kind 回退原串不炸
  （§11.7 既有纪律）。
- 测试（准入即测试）：`test_beat_rush_gate.py`（23 项）+
  `test_mind_belief_leak.py`（16 项，含 `_bundle_all_names` 回归锁——
  None 属性名事故：零报错契约把 out_of_scene 整检死亡吞成静默数月，
  **新检首轮实测必须确认命中路径可达**）；全量回归后端 1090 绿。


## 13. dock 红队三批新增约束（2026-09-08/09，未提交批内）

红队审查「重力场方案」落地后随批登记的两条新约束（`registry.py`）：

- **`dock-bridge-overlap`**（live，gate）：中插桥接（FIM）机位与后文锚
  `suffix_anchor` 去标点后 ≥4 字连续重叠 → 撞车丢件——后文已写的事实是
  禁区，过渡不许提前消耗它。判据复用 `_beats_overlap_hit` 同族 n-gram
  （纯字符串零算力）。origin=2026-09-09 FIM 红队 R2：rehash/beat_overlap
  只防前文与大纲，后文防线此前缺位。
- **`dock-onstage-boundary`**（shadow，gate）：挂件出现非在册实体/资产名 ×
  上手动词框架（握拿放捡掏开等）→ 在场越界疑点，只落台账不丢件（转正后
  丢件由过采样吸收）。when=世界书且本场在册非空（`onstage_projection`
  可得；正文已提及名豁免）。origin=2026-09-08 红队 R3「地面」：dock 曾是
  唯一不注入场景身份的生成路径，T3 可指涉物白名单代码闸与 ghost_guard
  out_of_scene 同族判据。

配套行为面见 AGENTS.md NLE-ADF 节「卡舱在场制×分镜组×临时通行证」条
（在场投影/末句对白优先/anchor_ref 对白分镜组/Guest Pass/意图衰老闸，
对拍 `test_dock_onstage.py`）。
