# 卡片舱两链边界修复 · Phase 0 红队审查答卷（只读，未改任何代码）

> 2026-09-13。基线：`DOCK_PIPELINE_VERSION = v2.3_suffix300_20260913`；行号锚点=当前工作区实况。
> 结论速览：**6 项目标中 5 项病灶属实可修，1 项（目标 1）病灶描述与代码实况有偏差——机制已存在，真实缺口是模式门；1 项（目标 2）用户方案的两个操作违反「幽灵纯追加 + 作者文本不可触碰」架构红线，须重设计**。文末列 3 个待拍板项。

---

## 一、四个对抗疑点答卷

### 疑点 1：全模式重叠剥离会不会误杀作者刻意的文学叠词？

**结论：不会——前提是沿用既有判据，而不是新造「1~4 字区间」。**

目标 1 提议新造重叠判定，但代码里**已有完整机制**：`_strip_fragment_tail_repeat`（backend/services/adaptive/stitch_gates.py:172），内嵌于 `_strip_fragment_prefix` 尾部（同文件 :162）——整句复读匹配失败后自动进尾缀匹配。它对叠词有**五重既有守卫**：

1. **句末闸**（:184-185）：断点以句末标点收 → 整闸不开。「…他握紧刀。」+「他握紧刀把门闩上。」各是各的句子，不剥。作者刻意叠词多为跨句呼应，此闸护住大半。
2. **等价类匹配 + 幽灵头实义字挡板**：剥的是「幽灵开头与断点尾缀**逐字等价**（抹空白+标点折叠）」的重叠。「他看了一眼」+「**又**一眼，把画框端详很久」——幽灵头的「又」使尾缀「一眼」匹配失败，天然不剥。作者的叠词永远在画布上原样保留，被剥的只是**模型把同一叠词再说一遍**的部分。
3. **≥2 字下限**（:192 循环 `range(…, 1, -1)` 从 2 起）：单字（「了」「的」「想」）永不剥。
4. **剥后标点保留**（:200-201 注释）：「他想了想」+「想了想，才走」→ 剥「想了想」留「，才走」→ 拼合「他想了想，才走」——等价重叠只出现一次，字面与模型意图一致。
5. **剥空回退**（:203）：全文纯复读 → 留原文走空产出处理，剥离层绝不吞幽灵。

**裁定**：目标 1 的正确修法是**把 `_strip_fragment_prefix`（自带尾缀护）的调用门从 stitch 扩到 continue**（burst 待评估），函数本体零改动。用户提案的「1~4 字（或最大 24 字符）」新区间反而**引入误杀面**——2 字小重叠（「一眼」）正是叠词误杀高发区，既有判据用「等价 + 尾缀锚定」恰好避开了它。桥接侧 `_normalize_bridge_seam` 的 ≤24 字窗已独立存在，两者不要合并。

**覆盖矩阵实证**（stitch.py:494-495）：

| 模式 | 复读剥离（含尾缀护） | 现状 |
|---|---|---|
| stitch | ✅ 跑 | 「端上一盆」案例若发生在 stitch（点零件 Space）**应已被剥** |
| continue | ❌ 不跑（`mode == "stitch"` 门） | **真实缺口**——「常规顺句续写」正是此模式 |
| burst / outline / open | ❌ 不跑 | burst 可议；outline/open 无断点续写语义，维持不开 |

⚠ 遗留疑点：用户报告的「端上一盆一盆」若实测发生在 stitch 模式，则是等价类外的形态（如句末断点闸命中），施工期须先用真实 trace 复核穿透案例的 mode 与断点形态，再决定是否需要第二判据。

### 疑点 2：动作前缀与开引号的拓扑调整，ProseMirror 层安全吗？

**结论：纯文本层处理本身无漂移风险；但用户方案的两个操作（移前缀/吞引号）违反更深的架构红线，物理上不可实现。**

**前端契约实证**（frontend/src/features/generation/composables/useGhostDraft.ts:311/314）：

```ts
editor.chain().command(noHistory)
  .insertContentAt(pos, { type: 'text', text: fullText, marks: [mark] }).run()
```

幽灵是**单一 text 节点 + 单一 ghost mark** 在光标 pos 一次性插入（noHistory 事务）。后端后处理产出什么字符串，前端就整段灌什么——两者之间没有行内 mark 交叉，不存在「位置漂移」问题。

**但**幽灵事务的两个不变量封死了用户方案：

- **幽灵纯追加**：`insertContentAt(pos)` 只在断点后插入，永不触碰画布已有字符。「将幽灵开头的动作前缀移至断点开引号**之前**」意味着把内容插到画布引号前——幽灵区间将横跨画布既有字符，Esc 蒸发（删除幽灵区间）会连作者文本一起删，undo 语义、ghost mark 域、`reapGhostIfDead` 全部失配。
- **作者文本不可触碰**：「安全吞并作者未闭合的开引号」需要修改画布上的字符，违反「画布即事实源」与采纳线不变量（线后作者文本永远只提示）。

**替代候选（待拍板，见 §五）**：

| 方案 | 操作 | 性质 | 代价 |
|---|---|---|---|
| X prompt 偏置 | 悬空引号断点坐标进 prompt（压缩改写已有「作者正文停在：『…』」先例，stitch.py:570-572）：「断点停在未闭合的引号内——第一句先接完这句话并闭合作者的引号，不要另起动作」 | 概率性，零架构风险 | 服从度依赖模型 |
| Z 影子先行 | 新影子检 `stitch-dangling-quote`（断点悬空开引号 × 幽灵非引号起 × 幽灵首对引号自洽 → 台账 hit），攒语料定频率后再决定执法 | 合规，符合约束治理生命周期（shadow→live） | 不立刻「修」 |
| Y′ 单边补闭 | 幽灵头补 `”`（把作者悬空引号闭合成 `“”` 空对） | 确定性、单边、拓扑合法 | `“”` 空引号排版瑕疵，观感差 |

**红队推荐 Z+X 组合**：影子检先行攒真实频率 + prompt 加悬空引号指令；若数据证实高频再评估 Y′ 或拒采重生。**不建议在本轮直接上任何文本重排**。

### 疑点 3：桥接指令抽象化后，会不会退化成空泛大词？

**结论：风险真实存在，且有两次同族先例；用「域中性语法 + 跨域微例 + 保留锚句」三件套平衡。**

先例①（08-27 诊断轮，adaptive_prompts.py:96-107 注释）：「措辞以正面任务式为主——中档模型对任务指令的服从度高于负面禁令，禁令堆叠只会催生新套路与判断稀释」。先例②（同文件 2026-08-27 节注释）：旧「感官描写指导」的限额被模型当配额用满。再叠加 dock 实测（mimo 把 prompt 术语逐条压缩成挂件）——**「动势缓释」「温湿度骤变」这类压缩术语有被模型照抄进正文或反向坍缩成「他调整了一下行装」式万能句的双重风险**。

平衡配方（施工期落进文案）：

1. **语法句域中性**：只说「写什么类别的物理事实」，不含任何具体物件；
2. **每取向带 2-3 个跨域微例**（室内/野外/战场各一，用「如」引出——范例是燃料不是枚举封闭集）；
3. **保留四句锚句**（见疑点 4 断言表）——这些句子本身不是硬编码病灶，病灶只是「脱鞋、放包、饭香」等生活化具象枚举；保留它们即可测试零改动 + 模型行为连续性；
4. **剂量纪律**：dock 侧 `slots-bridge` 分节受 `TestDosageLint` 强措辞预算（铁律/绝不/必须/禁止/不许/严禁/务必 七词，total ≤4，test_dock_prompt_compiler.py:91-98）——用户提案文案里「手势收拢」等中性词不计数，但重塑时**不得引入新的强措辞词**；「铁律」一词在 dock 侧基线为零（「铁律归零」验收，同文件 :11-12），链 B 的 `bridge_rule` 标题「桥接铁律」不受此 lint（lint 只扫 dock 编译产物），可保留。

### 疑点 4：断言与契约影响面全清单

grep 实证（当前工作区）：

| 测试文件：行 | 断言/受影响内容 | 触及目标 |
|---|---|---|
| test_dock_prompt_compiler.py:197, :209, :255 | `"中插桥接" in system` | 目标 3——**保留该词**则零改动 |
| test_dock_prompt_compiler.py:198 | `"下文已写的事实是禁区" in system` | 目标 3——保留该句则零改动（test_dock_onstage.py:601-602 同款） |
| test_dock_prompt_compiler.py:91-98, :181-185 | `TestDosageLint`：`scan_prompt_wording` 七强措辞 total ≤4 | 目标 3——新文案不得新增强措辞词 |
| test_dock_prompt_compiler.py:54-55, :218 | 「生成 4-6 个」「给了就近节拍则含 1 枚 toward_beat」 | 六目标均不触及（beat_clause 不动） |
| test_stitch_gates.py:927 | `"桥接铁律" in up and "写完过渡即止" in up` | 目标 3（链 B bridge_rule）——保留「桥接铁律」标题与「写完过渡即止」尾句 |
| test_stitch_gates.py:992-993 | `"过渡镜头留在主角一侧"` / `"换个道具演同一件事也算提前消耗"` | 目标 3——保留这两句 |
| test_stitch_gates.py:913-928 | 端到端桥接（suffix→prompt→seam 归一） | 目标 1/3 共用回归 |
| test_dock_onstage.py:607-620 | `test_suffix_overlap_part_dropped`：重叠串「明姐端来脸盆」含动词「端来」 | 目标 5——动词门方案下**仍丢件，测试不破**；须 +1 名词豁免测试 |
| test_subject_lock.py:24-43 | `pick_subject_lock` 槽位映射与优先序 | 目标 4——`bridge` 参数**缺省 False** 则零破坏；+2 条桥接仲裁测试 |
| test_continuation_rules.py:84-85 | `"禁病态微操"` / `"禁套路比喻" in sys_prompt` | 目标 6——基座改写**保留这两句**则零改动 |
| test_continuation_rules.py:78-79 | `"静态贴图"` / `"限额不是配额"`（细节功能节） | 目标 6——只动「感官描写」相关剂量句，不碰细节功能节 |
| test_continuation_rules.py:117-136 | stitch/continue carry「Anti-Pseudo-Sensory Ban」等 | 六目标均不触及 |
| **不存在** `TestDosageLint`×基座 | ⚠ 用户指令中「同步维护 TestDosageLint」与实况有偏差：该 lint 只扫 `build_dock_generator_prompt` 编译产物，`_base_system` 不在其内——目标 6 实际要维护的是 test_continuation_rules 的锚句断言 |

---

## 二、六项目标逐项裁定

| # | 病灶核实 | 方案裁定 | 修正 |
|---|---|---|---|
| 1 全模式接缝消解 | **部分属实**：机制已存在（stitch_gates.py:172，内嵌 :162），stitch 模式已覆盖；真实缺口=continue（及可选 burst）模式门（stitch.py:495） | ✅ 修，但按上述覆盖矩阵收窄 | 扩门即可，**不新造区间判据**；施工前用真实 trace 复核穿透案例的 mode |
| 2 悬空引号×动作前缀 | **属实**（`_strip_colliding_open_quote` stitch_gates.py:209-227 只判幽灵首字符） | ❌ 用户方案两操作违反架构红线（疑点 2） | 改 Z+X 组合（影子检+prompt 偏置），Y′ 备选 |
| 3 桥接去硬编码 | **属实**（slots-bridge 分节 + bridge_rule 两处生活化枚举） | ✅ 修 | 按疑点 3 三件套；保留四句锚句；不新增强措辞 |
| 4 发话锁×桥接铁律 | **属实**（桥接态 landing 槽→speaker 锁 vs bridge_rule 主角一侧，两段同位注入无仲裁） | ✅ 修 | `pick_subject_lock(slots, bridge=False)`：bridge=True 且结果为 speaker → 换新 `SUBJECT_LOCK_HANDOFF`（话音落下→镜头切交主角侧完成物理引渡）；prop/reply 锁与桥接不冲突（物镜只写器物/静音只写缓冲），不仲裁 |
| 5 suffix_overlap 假阳性 | **属实**（dock_generator.py:845 `_beats_overlap_hit(text, [suffix_anchor])` n=4 无差别） | ✅ 修，但**只动 suffix 闸不动 beat 闸** | 新 `_suffix_overlap_hit`：重叠窗口含受控动词表字（`_INTERACTION_VERBS` ∪ 移动/言语小词表）→ 维持 n=4 丢件；纯名词性窗口 → n=6 或豁免；在册实体名参与的重叠段可豁免（场景锚点共现）。语义影子 `dock-beat-rush-semantic` 已在，漏检有兜底 |
| 6 剂量口径归一 | **属实**（基座「每段至多 1 处微操」vs 白描契约「严禁」） | ✅ 修，方向=**动基座不动白描契约**（后者是用户逐字拍板措辞，AGENTS 在案） | 基座两处「每段至多 1 处」改域中性克制表述（如「点到即止，可无」）；保留「禁病态微操」「禁套路比喻」锚句；burst/open/outline 从「允许 1 处」变「未量化克制」为可接受副作用（它们本无白描契约块） |

---

## 三、最小文件清单与接口变更

**后端 4 文件 + 测试 4 文件；前端零改动**（目标 1/2 均在后端文本层，前端灌入契约不受影响）。

| 文件 | 变更 |
|---|---|
| `backend/routes/chapter_generation/adaptive/stitch.py` | ① :495 mode 门 `== "stitch"` → `in ("stitch", "continue")`（burst 授权后加）；② 新增 dangling-quote 影子检挂点（复用 `_log_constraint_event` 模式）；③ :417 `pick_subject_lock(request.picked_slots, bridge=bool(suffix))` 一行 |
| `backend/services/adaptive/stitch_gates.py` | ① 新 `detect_dangling_quote_collision(text, fragment) -> bool`（纯函数）；② 新 `_suffix_overlap_hit(text, suffix, onstage_names=None)`（动词门 + 名词豁免，n 动态 4/6） |
| `backend/services/adaptive/components/dock_generator.py` | :845 suffix 闸换调 `_suffix_overlap_hit`，传入在册名（onstage 已在作用域）；beat 闸 :840 不动 |
| `backend/services/prompts/adaptive_prompts.py` | ① `slots-bridge` 分节 + `bridge_rule` 文案重塑（保留锚句）；② `SUBJECT_LOCK_HANDOFF` 常量 + `_SUBJECT_LOCK_TEXTS` 增条 + `pick_subject_lock` 加 `bridge: bool = False` 参；③ `_ADAPTIVE_SYSTEM` 两处剂量句改写 |
| test_stitch_gates.py | +continue 复读剥离回归 ×1（「端上一盆」形态）；bridge 文案锚句断言核对 |
| test_dock_prompt_compiler.py | 锚句断言核对（预期零改动）；剂量 lint 自动守护 |
| test_dock_onstage.py | +名词性重叠豁免测试 ×1；既有 suffix_overlap 测试零改动（动词重叠仍丢件） |
| test_subject_lock.py | +bridge 仲裁测试 ×2（speaker→HANDOFF / prop 不仲裁） |

**不变量红线（施工期自检）**：作者画布文本零触碰；幽灵纯追加；beat 闸判据不动；白描契约措辞不动；四句桥接锚句 + 「禁病态微操/禁套路比喻/静态贴图/限额不是配额」锚句保留；dock 强措辞 total ≤4。

---

## 四、待拍板项（3 个）

1. **目标 1 的 burst 扩面**：只扩 continue（最小修）还是连 burst 一起（burst 断点=段尾，复读形态更少）？推荐只扩 continue，burst 观察一轮。
2. **目标 2 的路线**：Z+X（影子检+prompt 偏置，推荐）还是直接 Y′（补闭引号，确定性但有 `“”` 瑕疵）？
3. **目标 5 的名词处置**：纯名词重叠是「放宽到 n=6」还是「在册名/停用词构成即豁免」（更精准但多一个词表维护面）？推荐后者，因为 5 字纯名词抢拍（如「端来洗脸盆」无动词字命中时）在 n=6 下会漏。

## 五、施工授权

以上答卷与清单就绪，**未改任何代码**。待逐项拍板（或整体按推荐项）后即可开工；建议施工顺序：目标 1（最小）→ 4 → 3 → 6 → 5 → 2（影子检先行），每步带对拍测试。
