# 世界内核地基（World Kernel）——四域认知架构 v1.0

> 2026-08-28 · 状态：地基设计定稿（已经 teacher-kimi 导师两轮审阅，附录 B）· 定位：「AI 如何认知小说世界」的**底层内核**设计——一切上层（WCA 四层认知、知识检索平面 v3.1、约束编译、负空间引擎）都编译到这个内核上。
> 上游文档：`docs/knowledge-retrieval-plane.md`（v3.1 已施工）、`docs/world-cognition-architecture.md`（WCA 四层草案）。
> 本文档的使命来自用户指令：**地基优先、第一性原理、不模仿业界、创新与超越**。

---

## 0. 承重墙：四域存在论

全部设计的出发点是一条此前未被挑明的类型纪律：

> **truth（发生了的事）、intent（打算发生的事）、belief（各角色以为发生的事）、presentation（写给了读者的事）是四个不同的存在域，必须类型级分离、同轴可查询。**

业界记忆系统只处理过去；「谁知道什么」与「写到哪」从未进入写作系统的本体。这一条是本内核的承重墙，后面所有裁决都是它的推论。理论谱系：fabula/syuzhet 分离（俄国形式主义）是它的叙事学本名；双时态数据库是它的时间语义来源；动态认知逻辑（DEL）是 belief 域的祖先。

## 1. 第一性原理清单（导师增补后定稿）

1. 小说世界是单一作者主权下的确定性虚构——事实源天然唯一、可完全结构化；
2. **三重认知平面是第一公民**（作者/读者/角色各知什么）；
3. 三只时钟：叙事时间 t、写作时间（第 N 章）、修订时间（写完 20 章后重写第 3 章——反事实传播）；
4. **伏笔=对未来的记忆**：前瞻性知识（伏笔/期待/揭示计划）是带不确定性的未来事实，与过去事实同为第一公民；
5. 正文是终极产物：认知是为了让下一句「必然如此」（亚里士多德必然律的形式化对象）；
6. 显著性是美学的——但现阶段最好的代理是**作者声明+结构位置**（伏笔/锚点/节拍），learned significance 等数据攒够再说；
7. 负空间成立，但有诚实性前提：读者认知只能从呈现证据折叠，**折不出来的必须报 unknown，不许猜**；
8. **呈现与事实的分离是本体性的**：「发生了什么」与「写到哪、怎么写」是两种存在，直接产生「呈现关系」实体；
9. **视角即接口**：一切上下文装配以「视角角色集 × 时刻」为入参（POV 从事后审计闸升格为装配参数）；
10. **正文与世界模型是两种事实源，冲突时正文先赢，但冲突必须浮现**（画布即事实源的内核化——折叠永不覆盖画布，矛盾报警而非自洽）。

## 2. 五条出生决策（现在不定死、将来必反噬）

**决策 1：时间表示——三轴分离，各自成参数。**
valid time（叙事 t：现有整数日 + **精度枚举** exact/interval/unknown + **显式序约束边** before/after）；transaction time（修订：`supersedes` 链，永不物理删改——直接偷双时态数据库语义，不自行发明）；discourse position（话语序：章号×章内偏移，属呈现关系不属事件）。

**决策 2：认知粒度——曝光级 + 声明秘密，无推理闭包。**
Level 0 曝光（在场/被告知 told/发现 discover/witness 事件，纯代码可推）；Level 1 声明秘密（canon private/partial 节点=被精确追踪的命题注册表，按 id 引用逐实体 clearance）；**误信 believes_false 首日进 schema**（误会与误判是戏剧引擎，事后加枚举=改全部认知事件语义）。明确不做：推理闭包（逻辑全知是死路）、自由文本命题级追踪（去重歧义污染折叠纯度）。

**决策 3：模态纪律——统一轴，不统一真值。**
`world_events` 保持 append-only 真值日志；Intent 是**独立可变规划存储**（两张表类型级分离，不做 modality 可空列）。意图携带叙事轴目标位置（t 区间或章区间）；折叠提供「t 时刻世界什么样 + t 之后打算什么」——一个查询面、两个域。兑现时产生真 event，`intent.realized_by = event_id`。

**决策 4：不确定性表示——枚举与区间，拒绝浮点。**
意图生命周期枚举（declared/tentative/fulfilled/abandoned/broken_deliberately）+ 软窗口；时间用精度枚举+区间+序边；信念四值（knows/believes_false/unaware/**unknown——合法且重要**）。概率浮点没有语义没有校准只有假精确；将来需要排序加 rank 不加 probability。

**决策 5：折叠内零 NLP/零 LLM——全设计最重要的一条法则。**
折叠只做集合运算与序运算；一切语义提取发生在**写入前的气闸**（world_event_candidates 管线扩展），经作者裁决后入账。折叠纯度是「可再生成/前后端同构对拍/速度」三者的共同前提——混进一次 LLM 调用，三者同时死亡。

## 3. 内核本体（schema 级）

| 实体 | 内容 | 与存量的关系 |
|---|---|---|
| **Event v2** | 现有 11 类型全保留；+time_precision、+supersedes、+epistemic 类型家族（told{subject,object}/discover/misbelieve/witness——认知事件本身是真事件，住同一张表合法）、+序约束边表 | world_events 原位增量扩展，MIGRATIONS 加列默认 null=现行为 |
| **Intent（新表）** | kind(beat\|foreshadow\|expectation\|reveal\|promise) / scope(book\|chapter) / target(event_stub\|proposition_ref\|free_text) / window(t 或章区间) / 生命周期枚举 / setup_event_id / realized_by / serves_anchor / provenance(author\|ai) | 伏笔的 setup↔payoff、期待火候、canon 揭示计划、大纲节拍、spine 锚点全部归一为字段子集 |
| **命题注册表** | canon_nodes 原位升级：canon_text/public_text/三态即「被精确追踪的秘密命题」，认知模型按 id 引用 | [private]/[public]/[hook] 三段 prompt 契约冻结不动（有单测锁） |
| **Depiction（新表）** | subject(event_id\|proposition_id) / chapter_id / mode(shown\|told\|hinted\|symbolized) / status(confirmed\|candidate) / source(extracted\|author) | **fabula↔syuzhet 的桥，当前地基最大空洞**；读者折叠的唯一原料；摄入走候选池 |
| **三类边不混** | 时序边（before/after，管折叠顺序与未知日期定位）/ 因果边（causes 列已有）/ 主题边（setup→payoff，由 Intent 承载） | |
| **Fold API（唯一入口）** | `fold(t, perspective_set, domains[truth\|belief\|intent\|reader], tx_head)` | settings_bundle/scene-slice/上下文装配/digest 编译全部经此，无旁路 |

## 4. 地基牢固 = 十一条不变量（每条附检验方式）

1. **单一事实源**：世界真相只在事件日志+实体固有属性，其余皆可删。检验：删全部派生物冷启动重建，折叠逐字节一致。
2. **折叠纯度**：同输入同输出，无 LLM/NLP/时钟/随机。检验：前后端双实现对拍 fuzz（随机事件流→两边状态相等）。
3. **模态封闭**：四域类型分离，任何查询显式声明域。检验：property test——随机日志+actual-only 折叠永不含 intent/private 内容（「泄漏在类型层不可能」的诚实版本）。
4. **三轴参数化**：narrative t / tx head / discourse position 全显式。检验：折叠调用点无默认值。
5. **派生可再生成**：每份 digest/场景卡/装配带 provenance 信封（source keys + fold version + compiler version + params hash）。检验：按信封重算相等。
6. **修订传播完备**：supersede → 受影响集（依赖事实/呈现/意图/派生物）可枚举、必浮现、作者了结。检验：修订场景单测比对 affected set。
7. **认知可回答性**：任意参与者×注册命题→四值可答。检验：随机场景查询不抛异常。
8. **作者主权气闸**：日志只含作者确认事实，AI 提案痕迹留 provenance。检验：写路径审计——insert 必经候选池或作者 UI。
9. **诚实降级**：缺数据→unknown 不猜。检验：未回填章节的读者折叠返回 unknown。
10. **现实校验**：抽样 digest 论断回查折叠，失败即失效不沉默。检验：注入脏 digest，校验必须抓到。
11. **幂等摄入**：重复 settle/回填零重复入账。

## 5. 存量升维映射（升维不推翻）

| 存量 | 命运 |
|---|---|
| world_events（11 类型+causes） | 内核真值日志原位扩展 |
| world_entities/locations/relations | 内核原位；belief=认知事件折叠出的 overlay，不加基表 |
| canon_nodes | 命题注册表原位升级；reveal_plan/expected_reveal_chapter 迁 Intent(kind=reveal)，消费侧切走后旧列冻结 |
| plot_ledgers | **降级为视图**：行迁 Intent，UI/API 双读过渡，切走后旧表冻结只读 |
| chapters.spine | 作者编辑器保留；存储语义改为 chapter-scope Intent 投影，双写过渡 |
| chapters.narrative_time/scene_location_id | 话语轴锚点原位不动 |
| world_event_candidates | **升格为 Universal Airlock**：kind 扩展 depiction/epistemic/supersession 提案 |
| 书级大纲节拍 | =Intent kind=beat；outline_nearby 共享判据改查 Intent |
| 全书通读向导 | 扩展**阶段 C：呈现关系回填**（存量书读者折叠的数据来源） |

## 6. 激进方向裁决记录（A-F）

| 方向 | 裁决 | 备注 |
|---|---|---|
| A 统一时间轴 | 有强对应物（双时态库/scheduled intent），**质变，地基级** | 关键纠正：统一的是轴与查询面，不是存储与真值性 |
| B 认知平面 | 对应物 DEL/线索图，**做成即超越** | 关键纠正：「结构性不可能泄密」只在供给侧成立；真实贡献=secrets 从书级扁平块变**场景级视角配给** |
| C 约束传播 | 有对应物，**是交付机制不是地基材料** | 与知识块重分层非替代：知识供内容、约束供义务；推迟零损失 |
| D 读者负空间 | **写作系统内真创新，「超越」最实的落点**（Iser 空白理论的第一个引擎实现） | 依赖呈现关系表+回填数据 |
| E 编译+校验 | 对应物明确，但**是地基牢固唯一可检验的定义** | provenance 信封 retrofit 成本最高，现在加只是几列 |
| F 作者心智镜像 | 存储进地基、呈现推迟；**nagging 版诱人但错误** | 偏差信号的三个活源已有（spine 进度/丢弃理由/静音集合）；描述性+finish 时机+可驳回才合宪 |

**叙事学吸收**：fabula/syuzhet（命名）、Genette 聚焦与时间修辞（视角参数/序边词汇）、Iser 空白（负空间认祖归宗）、Ryan 最小偏离原则（未陈述的按常识处理——默认值纪律，省 token 防过度说明）、Barthes 阐释代码（canon 三态即其实现，半露=揭示一等阶段）、亚里士多德必然律（约束集的谱系）。
**叙事学拒收**：可能世界分支（修订用 supersession 足够）、Dramatica（问卷陷阱违宪）、故事语法/Propp（BS-ADF 预设拍已因此归档）、叙事规划器（作者就是规划器）、世界物理仿真（世界做作者让它做的）。

## 7. 地基版六件 + 施工顺序

**范围原则：地基只收「出生时不定死、将来必反噬」的东西。**

1. **world_events v2**：+time_precision +supersedes +epistemic 家族 +序边表（纯增量迁移）；
2. **Intent 统一存储**：五 kind/生命周期/软窗口/realized_by；plot_ledgers、spine 锚点、大纲节拍、canon 揭示计划**复制**迁入，旧表双读过渡（迁移风险最高步，配往返单测——延续 test_context_contract.py 锁契约传统）；
3. **认知 overlay**：fold 扩展 belief 域（四值可答，unknown 合法）；canon_nodes 原位成命题注册表；
4. **Depiction 表+气闸 kind 扩展+通读阶段 C 回填**：读者折叠只承诺「已回填范围可答」；
5. **Fold API 唯一入口化**：全消费方收口 + 前后端对拍 fuzz；
6. **Provenance 信封+现实校验任务**：贯穿全程，每交付一件就把派生物纳入信封纪律。

施工顺序：1+5 先行（schema+查询面纪律）→ 2（双读过渡）→ 3 与 4 并行 → 6 贯穿。

**明确不进地基版**：负空间清单 UI、约束编译器（C）、心智镜像呈现（F）、不可靠叙述检测、数值不确定性、learned significance。

## 8. 宪法级警告与红线

**可见性悖论**：这套内核把「谁知道什么」变成可计算对象，最大产品风险不是技术而是——作者一旦看见「每个角色的信息状态全图」，会忍不住想填满它（Dramatica 问卷陷阱的变种）。**UI 纪律与 schema 纪律同时定：认知模型默认不可见，只在泄密疑点、反讽机会、负空间清单三种时机浮现。地基服务写作，不服务观赏。**

红线汇总：折叠零 LLM/零 NLP；world_events append-only 神圣不可变；canon prompt 契约冻结；概率浮点禁入；反事实分支不建；作者主权气闸不可绕过。

---

## 附录 A：与上层的关系

知识检索平面 v3.1（已施工）= 内核之上的注入车道；WCA 四层（冷/温/热/计划）= 内核之上的物化视图族；约束编译（C）与负空间引擎（D）= 内核之上的消费者——全部经 Fold API 取数，全部受 provenance 信封与不变量管辖。

## 附录 B：审阅记录

- 第一轮（2026-08-27）：WCA 骨架成立；三处承重修正（digest 节级键控/提及注入逐出前缀/计划层补位）；Phased by telemetry。
- 第二轮（2026-08-28，地基轮）：挑明四域存在论为承重墙；A-F 逐条裁决；五条出生决策；schema 级本体；十一条不变量；存量升维映射；叙事学吸收/拒收清单；地基版=A+B+E+D 数据基座六件；可见性悖论警告。
