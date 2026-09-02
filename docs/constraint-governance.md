# 约束治理（Constraint Governance）

> 唯一权威文档 · 2026-09-02 一期施工。背景与调研全文见 memory
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
