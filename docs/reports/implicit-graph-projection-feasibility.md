> **归档说明（2026-09-19）**：可行性调研（2026-09-16），投影器已实装 `services/world/implicit_graph.py`（0d83896，暂无消费方）。

# 事件流隐式图谱投影与子图精炼检索 · 可行性调研报告

> 调研日：2026-09-16 · 性质：**纯只读调研与算法推演**（未改任何代码；性能数字来自对真实/合成数据的临时计时脚本，未落盘）
> 命题：不让作者画图，让 `world_events` 事件流自动投影为隐式因果图；生成时以在场实体为中心抓 1~2 跳关联子图，把宏大设定压缩为在场连通图喂给模型。
> 相关既有事实：`docs/knowledge-retrieval-plane.md`（知识平面 v3.1 唯一权威）、`docs/world-kernel-foundation.md`（事件源 v2）、`docs/design/truth-ux/`（图谱退役决策）。

---

## 0. 三句话结论

1. **底层连通性成立且超预期**：`world_events` 的实体引用全在一等列（`participant_ids`/`faction_ids`/`location_id`/payload 内 ID 键），真实库 ORM 层实测 **149/149 引用 100% 命中实体**（136 角色/7 势力/6 资产）——纯字典解析即可还原 `(Subject) -[EventType]-> (Object)` 带时间戳有向边，零 NLP、零模型。但「因果边」两个既有机制（`causes` 列、canon_edges）实测**全部零数据**，且资产所有权根本不在事件流里——隐式图的边只能是**共时共现边+类型语义**，不是作者显式因果。
2. **性能毫无悬念，收益需要重新框定**：500 事件/100 实体规模实测 fold 0.29ms、2 跳投影 0.18ms（含每次重建邻接），2ms 预算 10 倍余量。但当前两本真实书的注入体量只有 442/2371 档案字符——**token 压缩收益今天≈0**（预算器已把知识段钉死在 16K 逃逸阀 + 12650 模式总预算内）。真实价值在三点：超预算时代的「**幸存质量**」（现在逃逸阀按养料档丢整条，是盲目丢弃）、**新增结构化近史通道**（今天注入里只有 RAG 散文回响，没有任何事件因果）、以及**语义盲召的确定性补位**（血噬式误召的根治性替代）。
3. **正确形态是「事件卡超边」而非「点对边图」，正确位置是 onstage_projection 的下层拓扑提供者**：battle 类多参与者事件若拆点对边会成 20-clique 瞬间爆炸；以「事件卡」为原子（一张卡引用 N 个参与者）天然防爆且信息保真。红队四问全部有解，但三件事必须先认清：稀疏性靠提及通道兜底（已建成）、supersedes 读路径今天根本没过滤（上量前要补）、2 跳必须限「重大类型∪近窗」否则主角一扩就是半本书。

---

## 1. ① 现有事件的图谱连通性底层事实

### 1.1 一等列与 payload 形状（models/world.py:56-94 + eventTemplates.ts）

`WorldEvent` 的实体引用分布在四个**确定性位置**，全部是 ID 或 ID 列表，无任何自由文本需要解析：

| 位置 | 内容 | 覆盖事件类型 |
|---|---|---|
| `participant_ids` JSONB | `[world_entity.id, ...]` 参与角色 | 全部 11 类（battle/custom 等五类**只有**这个） |
| `faction_ids` JSONB | `[world_entity.id, ...]` 参与势力 | battle/alliance/war_declare |
| `location_id` FK | 事件发生地点 | 任意（可选） |
| `payload` JSONB 类型键 | `character_id`（birth/death）、`character_ids+from/to_location_id+path`（move）、`faction_id+polygon+action`（territory_change）、`target_id`（found/destroy） | 6/11 类有结构化必填（eventTemplates.ts `requiredPayloadFields`）；battle/alliance/war_declare/coronation/custom 五类 M1 只填 type+note |

时间轴三件套齐备：`time_start/time_end`（数值日计数）、`sequence_num`（全局回放序）、`time_precision`（exact/interval/unknown）。**结论：`(参与者) -[event_type]-> (共参与者/地点/势力)` 的有向超边，纯 Python 字典解析 100% 可还原，每条边自带时间戳与序号。命题核实通过。**

### 1.2 真实库命中率实测（data/velluma.db，经 ORM 层）

- 47 条事件（两本书：5+42），类型分布 battle 21 / move 15 / destroy 5 / custom 3 / death 2 / birth 1——**battle 是最大类且零 payload 键**，完全靠 `participant_ids` 共现。
- **149 个实体引用全部命中**（136 character / 7 faction / 6 asset）。⚠ 审计方法学坑：raw SQL 层 entity.id 存 hex32 无连字符、JSONB 引用列存带连字符 UUID，裸 SQL join 全 miss 是存储表示假象——**必须经 ORM/str(UUID) 层判匹配**（与 2026-09-14 数据库卫生批同源坑）。
- **6 个引用指向 asset 类型实体**：资产虽然不进 fold 状态推演（见 §2），但作者实际上把资产当参与者记过事——事件流里已经存在「资产历史边」的野生数据。

### 1.3 两张边表的真相（推翻任务书预设 + 印证定律）

- `WorldEventEdge`（models/world.py:97-117）**不是旧因果图谱的遗物**——它是世界内核 B1 的**时序约束边**（`kind=before|after`，给 time_precision=unknown 的事件定序用）。真实库 **0 行**；生产代码**零写入方**（全库唯一引用是 test_fold_kernel.py:111 断言列存在）。
- 旧「因果图谱」是 canon 侧的 canon_edges——2026-09-03 因「建边零入口、边恒为零」整体退役（前端 CausalityGraphModal 删除、cytoscape 卸载）。
- `WorldEvent.causes` JSONB（显式因果链列）**真实库 47 条全空**。
- 三处证据共同印证本调研的立项定律：**任何要求作者手动连边的机制在这个产品里采用率恒为零**。隐式投影是唯一可行方向，且**不应依赖 causes 列**（它和 canon_edges 是同一种死法）——边的语义必须从「事件类型 × 共时参与」推导。

### 1.4 supersedes 修订链：存在但读路径未过滤

`supersedes` 列（models/world.py:87）真实库零使用；且主装配读路径 `events.list_all_by_book`（world_repository.py:52-60）**不排除被 supersede 的事件**——fold.py:77 注释宣称「链头查询=排除被 supersede 的旧事件」但实现只是直调 `repo.compute_world_state`。今天零数据无实际影响；**子图方案上量前必须补读侧过滤**，否则重写旧章时新旧两代事件会同时进图。

---

## 2. ② 折叠推演现状（时态机制的既有纪律）

`compute_world_state_from_events`（world_repository.py:271-403，与前端 `engine/computeWorldState.ts` 同构）：

- **六类事件改状态**：birth/death/move/territory_change/found/destroy；battle/alliance/war_declare/coronation/custom **M1 不改世界状态**（只挂参与者）——隐式图恰好补位：这五类的价值就在「谁和谁何时共历过什么」。
- **时态单调性已解决**：`applicable = [e for e in events if e.time_start <= t]` 按 `sequence_num` 排序回放，每槽位 last-write-wins（位置/生死/疆域）。**这就是红队第 2 问的现成答案**：「最新有效边」= 同一折叠纪律在边集合上的推广。
- **关系边在另一张表**：`world_relations`（static 恒活跃 / event_ref 锚事件已回放才活跃，world_repository.py:375-393）——1 跳「在场角色之间的直接关系」数据源已存在，但真实库两本书**关系数为 0**（又一条零采用证据）。
- **资产零参与 fold**：所有权/持有状态不在事件流里（无 acquire/own 事件类型，fold 也不消费资产）。红队第 1 问的「怀表没记事件就消失」不是风险而是**现状默认**——今天的兜底是 onstage_projection 的**提及通道**（资产名出现在当前段落=在场，dock_generator.py:174-185）+ `lexical_presence` 词法兜底（compute_world_state 汇聚点统一做，world_repository.py:576-590）。

---

## 3. ③ 子图数据结构草案与算法原型

### 3.1 数据结构定义草案

```python
@dataclass
class EventCard:
    """事件卡（超边原子）：隐式图的最小注入单位，永不拆成点对边。"""
    event_id: str
    type: str            # 11 类枚举
    title: str           # 用户自拟标题 or 模板标签（eventDisplayName 回退链）
    time_start: int      # 叙事时刻（连续日）
    note_excerpt: str    # note 截 ≤40 字（人话因果描述）
    participants: List[str]   # 全部实体 id（含跨 1/2 跳标记）
    location_id: str

@dataclass
class SubgraphNode:
    entity_id: str
    name: str
    hop: int             # 0=在场根 / 1=共现邻 / 2=历史卡带出
    why: str             # 入图理由（人话：「与林尘在第 2177 天共历 battle」）

@dataclass
class SubgraphSlice:
    """在场连通图切片：knowledge_plane 的新条目源（每卡一原子）。"""
    roots: List[str]           # onstage 实体 id（来自 onstage_projection）
    nodes: List[SubgraphNode]  # 帽 40
    cards: List[EventCard]     # 重大事件卡 帽 12（1 跳成员卡 ≤6 + 2 跳历史卡 ≤6）
    generated_at_t: int        # 投影时刻（叙事时间锚，前缀签名的组成键）
```

### 3.2 纯函数原型（推演版，未落盘为代码文件）

```python
MAJOR_TYPES = {"death", "battle", "territory_change", "destroy", "coronation"}

def project_active_subgraph(events, entities_by_id, world_state, roots, t,
                            max_hops=2, per_root_cards=6, node_cap=40):
    """纯函数：事件流 → 在场连通子图。零 NLP、零 IO、复用 fold 时态纪律。

    纪律：① 只看 time_start <= t 的事件（含 supersedes 过滤——读侧补）；
    ② 按 (time_start, sequence_num) 取每邻「最近重大卡」= 时态单调在边上的推广；
    ③ battle 等多参与者事件是超边（EventCard），不展开 N² 点对——防爆的本质；
    ④ 2 跳只走 MAJOR_TYPES ∪ 近窗（|t - time_start| <= 90 天），普通 custom 不外扩。
    """
    live = [e for e in events if e.time_start <= t and not e._superseded]
    # —— 1 跳：根实体的共现实体 + 直接关系边（world_relations 活跃集） ——
    hop1, cards = set(), []
    for e in sorted(live, key=lambda x: (x.time_start, x.sequence_num), reverse=True):
        parts = set(e.participant_ids or []) | set(e.faction_ids or [])
        if parts & set(roots):
            cards.append(_card(e, hit=parts & set(roots)))          # 最近优先
            hop1 |= (parts - set(roots))
        if len(cards) >= per_root_cards * len(roots):  # 近史帽（防爆线 1）
            break
    # —— 2 跳：1 跳成员的重大历史卡（只取 MAJOR ∪ 近窗，每成员 1 张） ——
    seen_cards, hop2 = set(), set()
    for e in sorted(live, key=lambda x: (x.time_start, x.sequence_num), reverse=True):
        if e.event_type not in MAJOR_TYPES and abs(t - e.time_start) > 90:
            continue
        parts = set(e.participant_ids or [])
        if parts & hop1 and e.id not in seen_cards:
            seen_cards.add(e.id)
            cards.append(_card(e, hit=parts & hop1))
            hop2 |= (parts - hop1 - set(roots))
            if len(seen_cards) >= 6:  # 2 跳帽（防爆线 2）
                break
    nodes = _cap(_rank(roots, hop1, hop2), node_cap)                # 全局帽（防爆线 3）
    return SubgraphSlice(roots=roots, nodes=nodes, cards=cards, generated_at_t=t)
```

### 3.3 性能实测（合成 500 事件 / 100 实体 / 20 地点，200 次取均值）

| 操作 | 平均耗时 | 备注 |
|---|---|---|
| `compute_world_state_from_events`（现有 fold） | **0.289 ms** | 与世界页审计记忆「fold 亚毫秒」一致 |
| 邻接构建 + 3 根 2 跳 BFS（含截断帽） | **0.181 ms** | **每次重建邻接**的悲观口径；按书缓存邻接则进入微秒级 |

**2ms 预算有 10 倍余量**；即便事件涨到 2000 条（≈50 万字书的 4 倍事件密度），线性扫描量级仍在 1ms 上下。瓶颈不在投影，在取事件的 DB 查询——但那条查询（`events.list_all_by_book`，book_id 有索引）本来就在每次装配的 fold 路径上跑（world_bridge → fold → repo），**子图复用同一份事件列表，零新增查询**（fold 目前不向外暴露原始事件，需让 truth 域附带返回或在同 session 补一次同查询——两种都是既有模式，belief 域就是自带独立查询的先例 fold.py:92-98）。

---

## 4. ④ 与知识平面（knowledge_plane）的融合接缝

### 4.1 现状注入结构（对照基准）

条目五源（knowledge_plane.py:148-292）：entity（档案全文+此刻状态）/ asset / worldview（恒选）/ faction（软恒选）/ relation / hook（恒选）。选择器（:312-357）：**恒选 ∪ 在场/死亡（hard）∪ 提及（后缀化，B6 前缀冻结纪律）**，legacy 全选；预算 `KG_BUDGET_CHARS=16000` 逃逸阀丢整条、`MODE_CONTEXT_BUDGETS≈12650` 模式总预算。前缀签名 `_prefix_signature`（:703-734）对实体/资产/世界观/关系/伏笔/canon/前情摘要逐类哈希，`_PREFIX_CACHE` 章内命中（:757-758）。

**认知校准：现状选择器已经是「1 跳物理名单」**（在场=场景作用域存活∪提及）——本方案真正新增的是 **2 跳历史（事件卡）** 与 **超预算时代的精细化幸存排序**。

### 4.2 真实体量与诚实的压缩比推演

实测两本书：《最终武装》10 实体/442 档案字符/5 事件；《弦上灰》79 实体/2371 档案字符/42 事件/世界观 2 字符（空）。**当前知识段总注入 ≈2~5K 字符，距离 16K 逃逸阀还有 3~8 倍空间——今天做子图精炼，token 收益≈0，反而新增事件卡 +0.5~1.5K。**

50 万字级推演（显式假设：150 实体 × 平均 400 字档案 = 60K 字符实体池 + 500 事件 + 30 开放伏笔 + 世界观 3K）：

| 方案 | 注入构成 | 估算字符 | 说明 |
|---|---|---|---|
| 现状（选择器+逃逸阀） | 在场+提及展开 ≈25 实体 + 恒选块 | ~14K（触阀丢条） | 逃逸阀按 养料→软 档**从尾盲目丢**，丢谁与叙事相关性无关 |
| 子图精炼 | 1 跳 ≈15 档案条目 + 事件卡 12×60 字 + 恒选块 | ~9~11K | **不省多少 token（预算本就封顶），但幸存者与现场相关**，且多了 0.7K 的结构化近史 |

**收益重框（比「压缩」更诚实的说法）**：①超预算时「该留谁」从盲目变相关；②**新增**了今天完全缺席的结构化事件因果通道（现有历史通道只有 RAG 散文回响——语义盲召的病根）；③确定性补位——事件卡是纯代码产物，不依赖 embedding 召回质量。

### 4.3 「条目原子」与「前缀冻结」兼容性

- **条目原子**：EventCard 天然是原子（一卡一条目，逃逸阀丢整卡不腰斩）——与 v3.1 纪律同构，无破坏。
- **前缀冻结**：子图由「根集 + 事件集 + t」决定。**t（章叙事锚）与事件集在章内冻结**（事件变更点=沉淀/世界页编辑/速记入账——恰好是 `_prefix_signature` 现有的刷新触发面）；需把**事件哈希并入前缀签名**（一项增量，entities/assets/… 之后加第七项）。⚠ 根集若含滚动窗提及（随打字高频变），提及驱动的卡必须走 **recency 后缀**（与提及名单同通道，B6 纪律现成），前缀版子图只用 onstage（场景作用域）根——**这条不做，前缀缓存会被每次击穿**，是融合接缝上唯一真正的红线。

---

## 5. 红队四问（死穴推演）

### 5.1 事件稀疏性陷阱——真实且是现状默认，兜底已建成

实测最薄的书只有 5 条事件；「作者随手写林尘拿出老张给的怀表但从不录事件」是**常态而非异常**（这产品的事件录入靠 settle 抽取+候选回流+速记，本来就是稀疏记账）。三重兜底全部现成：①**提及通道**——onstage_projection 已按名字/别名扫描当前段落（怀表被写到就进在场名单，不管有没有事件）；②**词法兜底**——`lexical_presence` 在 fold 汇聚点做 note 级在场增强；③**系统性补账**——settle/event_scout 的候选回流是事件流的长期填充路径。**设计纪律：子图缺边=少上下文，不是错误事实——宁缺勿错，缺的由提及与 RAG 补，绝不从共现外推所有权。**

### 5.2 时态单调性——fold 纪律直接推广，但有两处前置债

「最新有效边」的答案就是现有折叠律：`time_start <= t` 过滤 + `sequence_num` 排序 + 同槽 last-write-wins；「某配角对主角的最新一次态度转折」= pair 事件按 `(time_start, sequence_num)` 取 max。前置债：①**supersedes 读侧过滤缺失**（§1.4）——重写旧章场景下会双代事件并存，上量前必须补；②`world_event_edges` 时序边零数据零写入方——time_precision=unknown 的事件实际只能靠 sequence_num 定序，投影器不要对边表抱期待。

### 5.3 组合爆炸——事件卡超边 + 三道帽，实测 0.18ms

核心洞见：**battle 是最大事件类（21/47），多参与者事件拆点对边即成 K₂₀ 团，主角挂 300 事件时 2 跳点对展开=全书半数节点**。防线四道：①**超边表示**（EventCard 引用参与者，永不展开 N²）；②**近史帽**（每根 ≤6 张卡，recency 排序）；③**2 跳限「重大类型∪近窗」**（death/battle/territory/destroy/coronation 或 90 天内，custom 不外扩）；④**全局节点帽 40**。合成压测 500 事件/100 实体/3 根带帽遍历 0.181ms——帽子先于爆炸生效。

### 5.4 与 onstage_projection 的关系——下层拓扑提供者（不取代、不包裹其执法职能）

onstage_projection 有两个身份：T3 在场白名单的**执法面**（dock 代码只执法在册名单，必须精确小集合）+ 生成供给面。子图应作其**下层拓扑提供者**：`roots = onstage_projection 输出`（同一名册同一推演，零口径分裂），子图只负责把 roots 向历史与共现方向扩张后**喂知识注入**。执法名单保持小而准，知识注入大而相关——两职分离，互相不越界。简报卡（briefing）消费的也是 onstage 输出，天然不受影响。

---

## 6. 落地路线建议（三步 + 明确不做）

| 期 | 内容 | 验收 |
|---|---|---|
| P1 事件卡通道（先给增量价值） | `project_active_subgraph` 纯函数（§3.2）+ knowledge_plane 新条目 kind=`event_card`（恒选软档，注入为新块「在场近史」或实体块尾段）+ 前缀签名并入事件哈希 + trace 记录卡命中率 | 无事件书逐字节零变化；有事件书新增 ≤1.5K；`test_implicit_graph` 对拍（时态单调/帽/超边不展开） |
| P2 幸存排序（超预算时才生效） | 逃逸阀丢弃顺序从「养料档」升级为「与子图距离」加权（1 跳成员>2 跳>无关节点） | 仅 16K 触阀的大书行为变化，小书零变化；预览 unselected 面板可见新 reason |
| P3 提及卡后缀化 | 滚动窗提及驱动的根产生的卡走 recency 后缀（B6 纪律），前缀版只用 onstage 根 | 前缀缓存命中率不衰减（trace 对拍） |

**明确不做**：①依赖 `causes` 列做因果（零采用定律，同 canon_edges 死法）；②给作者任何「看图/连边」UI（同定律）；③用子图取代 RAG/提及通道（三者分工：子图=结构化近史、RAG=散文质感、提及=稀疏兜底）；④在 fold 主链外加独立事件查询以外的东西（一次索引查询是上限）。

## 7. 风险登记

| 风险 | 等级 | 处置 |
|---|---|---|
| 事件稀疏使子图长期空转（录入习惯不改变） | 高（产品层） | P1 只在有事件书生效；事件卡本身的注入质量就是「录事件有回报」的示范，反向激励录入 |
| supersedes 未过滤 → 重写场景双代事件 | 中 | P1 前置补读侧过滤（一行 query 条件 + 对拍） |
| 前缀缓存被提及根击穿 | 中 | P3 纪律：提及卡只走后缀（红线，§4.3） |
| 事件 note 质量差（占位/跑题）进卡污染 prompt | 中 | note 截断 + 2026-09-11 召回相关性门同类思路：卡片带 title 优先、note 仅摘 40 字 |
| 与 RAG 回响内容重复 | 低 | 分工不同（事实 vs 散文）；trace 观察重复率再调卡帽 |
