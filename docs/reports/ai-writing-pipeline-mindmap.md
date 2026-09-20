> **归档说明（2026-09-19）**：prompt 链路快照导图（2026-09-11），行号与内容随代码漂移，仅作当时记录。

# AI 辅助写作底层链路导图（NLE-ADF 3.0）

> 基线：2026-09-11 代码实况（含本周未提交批：行间推挤卡舱 / FIM 桥接 / 在场制 / 用量成本核算 / 编辑器排版批）。
> 阅读方式：自上而下七条主干 = 作者进章打字后的完整旅程（交互 → 感知 → 供给 → 生成 → 意图 → 数据源 → 治理）。

```text
AI 辅助写作底层链路（NLE-ADF 3.0 自适应融合写作台）
│
├── 1 交互层 · 作者主权
│   ├── 激活：进章打字 ≥4 字 → authorLane=composing（adaptive = 唯一写作路径）
│   ├── 感知常驻：切页只 detach（_lastCtx 快照 + 章节纪元守卫防串章）
│   ├── 键位：Tab=卡舱唯一入口（恒 force 重算）· Space=续写 · Ctrl+Space=走向卡
│   │         Alt+O=细纲胶囊 · Alt+N=世界速记 · Ctrl+Enter=沉淀 · Enter=采纳 · Esc 栈逐层退
│   ├── 卡片舱呈现：行间推挤（InlineDock · ProseMirror WidgetDecoration）
│   │   ├── 锚=光标段后 · 展开撑开 ~270px 推开后文 · 0% 遮挡（治 FIM 浮层盖后文）
│   │   ├── 高度手风琴：展开测高带连接态重试 · 收折动画毕才摘装饰（零闪烁窗）
│   │   └── 选区安全：纯视图装饰（文档/undo/getHTML 零触碰）+ stopEvent/ignoreSelection
│   ├── 幽灵三条：疑点/返修/洗层 chip —— CursorLayer 浮层贴幽灵尾（体积小不进排版流）
│   └── 画布即事实源：无生成预览层 · 层1 事实只做审计账 · 活性派生（删改即过期）
│
├── 2 心跳感知 · AI 的眼睛（POST /adaptive/heartbeat）
│   ├── 节律：活跃防抖 3s · 停顿 4s · 同步组件 12s 超时钳制 + 在飞去重
│   ├── orchestrator 七组件：intent_inference / future_projection / dock_generator
│   │                      sediment / post_process / canon_watch / event_scout
│   ├── 意图三级源链：spine 打算短路 0.9 ＞ 大纲转化 0.85 ＞ LLM 反推 0.55
│   │   ├── 衰老闸：正文推进 ＞100 字未刷新即不绑旧意图
│   │   ├── 证据回查闸：arc 依据须逐字出自正文，编造降信跌破消费阈 0.5
│   │   └── 「不对」一句话纠正手势 → 落 spine + 缓存签名 bust（舱即换向）
│   ├── 响应载荷：dock_parts / direction_cards / canon_hints / onstage_guests / dock_muted
│   └── 桥接态取源：中插时光标前 ≤500 字窗口（recent_text 不发后文，防剧透回流）
│
├── 3 卡片舱供给 · 在场制重力场（dock_generator）
│   ├── 在场投影 onstage：世界书 + 场景钉折叠出「本场在册」白名单
│   │   └── 三档物质性：T1 氛围件自由生发 / T2 上手件须指源 / T3 在册白名单（代码执法）
│   ├── 分镜组模板：bridge ＞ 对白末句优先（行首引号判据）＞ 对白占比 ＞ combat ＞ 全景 ＞ 默认
│   ├── 槽位：landing（恒首位）/ toward_beat / echo / ambient ＋ reply / prop 分镜件 ＋ custom 第 5 槽
│   ├── 素材纪律：文流第一 · 就近节拍只给第一步 · echo 出处后端拼装（不经 LLM）
│   │           · 陈词嗅探黑名单 · beat/after 推测挡在取材池外（供给切断＞命令拒绝）
│   ├── 临时通行证：正文高频未建档人名（jieba 提名＋子串计数 ≥2）→「➔ 建档」往返光标
│   ├── 缓存三键：文本签名（含 word_count）＋ presence_fingerprint ＋ 场景态键
│   │   └── DOCK_PIPELINE_VERSION 版本盐：规则大改递增即全量缓存失效
│   └── 句子级闸门：段停半句不生发不回缓存（dock_muted 无条件清舱，Tab 点名豁免）
│
├── 4 生成链 · 幽灵的诞生（POST /adaptive/stitch-ghost，SSE 流式）
│   ├── 五模式：stitch（50 字微镜头）/ continue / burst / open / outline（细纲胶囊扩写）
│   ├── 装配（唯一入口 stitch_context ↔ context-preview 同源，禁平行实现）
│   │   ├── knowledge_plane：实体/世界观/伏笔/关系 = 条目原子（永不腰斩）
│   │   ├── 注入序权威 render_system_blocks 14 块（事实层前于文风层）
│   │   └── 称呼表按可见文本过滤 · recency 重钉 user 尾部 · 体量约束=条目级逃逸阀
│   ├── 意图兜底链：请求意图 ＞ 就近节拍 ＞ 层2/baton（分档措辞——AI 猜的自认）
│   ├── 质感契约：motion（动作推进）/ texture（停在当下）双轨 · 主体锁三件
│   │          （物镜/发话/静音——单焦距主体守恒）· 白描契约封杀假感官（用户逐字版）
│   ├── FIM 中插桥接：suffix_anchor 双端边界 · 桥接铁律（留在主角一侧/换道具也算提前消耗）
│   │               · 桥接态切断推测/猜测/节拍素材块（防后文剧透）
│   ├── 出闸流水线（顺序固定）：
│   │   复读剥离（前缀＋半句尾缀）→ 桥接接缝归一（停顿收句＋≤24 字重叠剥）
│   │   → 字数闸（微镜头 ≤60 只截断零压缩；两级闸 ×1.6 保头截断→压缩改写→再截）
│   │   → 返修环（硬违规带稿改写→句级切除→拒稿）· 熔断器（10min ≥2 拒稿降级带病上屏）
│   │   → deai 抛光（≤100 字契约窗）→ 洗层 P1 词替换＋P2 句级修补
│   │   → ghost_guard 十检终检 → 半角标点归一（…→……、直引号配对——呈现末站）
│   │   → GHOST_DONE（warnings/wash/deai/repaired/breaker_open 全量上帧）
│   └── 落定：Enter 采纳不回弹 · Esc 蒸发（≥30 字可选理由 chips）· 手删收割 reapGhostIfDead
│
├── 5 意图与谋篇 · AI 懂你在写什么
│   ├── 章级软脉络 chapters.spine（副驾「打算」tab · 部分合并 · 2s 防抖自动保存）
│   │   └── 锚点体系：走向卡挂锚 · 关键词命中纯算法进度判定 · 临近锚点置顶硬提示（选向即决岔）
│   ├── 章首接力棒 baton：空章/短章 previous_summary 确定性接管（零 LLM 不空猜）
│   ├── 意图画像：反推 prompt 注入前几章意图轨迹 ≤5 条（学粒度口吻，不抄内容）
│   └── spine-suggest：1×creative 建议不落库（作者裁决红线）
│
├── 6 世界与文风 · 设定数据双源
│   ├── 世界内核（事件溯源）：world_events 11 类 append-only → compute_world_state 折叠推演
│   │   ├── world_bridge 世界优先：在场提权（死者不进在场集）· 私有实体走 secrets 通道
│   │   │                  · 叙事时间四级降级 · 地点 parent_id 树（祖先算在场）
│   │   ├── 字段级真相分层：档案字段三态（公开/半露/秘密）五消费线（单一事实源不建副本）
│   │   ├── 写作桥 W1-W5：场景切片条 · 情境浮卡 · 速记解析（只产草稿）· 候选收件箱 · 深链往返
│   │   ├── 系统自己去读：切章 auto-read（内容哈希幂等＋每书每日预算闸）· 全书通读向导
│   │   └── 学着闭嘴：静音集合行为派生（裁决 ≥3 且零采纳才静音 · 安全类永不静音）
│   └── 文风三平面（纲领：prompt 管不住的确定性约束下沉代码层）
│       ├── 偏置：P0 禁忌正面化重钉 user 尾部 · 画像 ≤10 行 · few-shot k≤2 场景匹配加成
│       ├── 呈现：洗层（blocker 词替换＋可逆学习）· deai 小模型 · 半角标点归一（AI 侧防增量）
│       ├── 选择：采纳率回流贝叶斯先验 ±20% 只调序 · 旋钮/对话目标 → 样本排序条件
│       ├── 审计：章对账（CV/对话占比趋势）· 语义扫描（embedding 抓换字逃逸）
│       └── 不变量：采纳线——线前可干预 AI 提案，线后作者文本永远只提示
│
└── 7 治理与观测 · 底座
    ├── 约束登记册 registry：执法可靠性序 = 供给切断 ＞ 输出代码闸 ＞ 确定性改写 ＞ prompt ＞ 审计
    │   ├── live：beat_rush 抢拍（返修）/ canon_leak / secret_leak / out_of_scene
    │   ├── shadow（攒校准语料）：location_jump / cast_roll_call / mind_leak / belief_leak
    │   │                     dock-onstage-boundary / dock-bridge-overlap
    │   │                     stitch-bridge-actor-steal / stitch-custom-verbatim / 语义抢拍
    │   └── 台账 constraint_events.jsonl（信用分数据不可补采）
    ├── 模型槽位 model_config：llm / reasoning / creative / wash / embedding / deai ＋ prices 价目表
    │   ├── 厂商档案整形：Kimi K 系采样 schema / DeepSeek 弃用清理 / GLM 温度帽 / MiMo thinking.type
    │   └── thinking 关闭 = REASONING_DISABLED（传空 dict 无效——烧预算事故在案）
    ├── 用量与成本：generation_runs 落库（cached_tokens 双字段提取）
    │   · usage 聚合按链路分组（by_lane）· ¥/token 价目（故意零默认价）· 按章 trace
    └── 本地台账群（零上报个人镜子）：collab_events / style_events / deai_pairs
```

## 一图流（速记版）

```text
作者打字 ─→ 心跳(意图/在场/感知) ─→ 卡片舱(行间推挤, Tab 唤起)
                                      │ 吸附/自定义/数字键
                                      ▼
                              stitch-ghost 五模式
                                      │
       装配(知识平面+文风+桥接) → LLM → 复读剥离→接缝归一→字数闸
                                      → 返修环→熔断→deai→洗层→十检→标点归一
                                      ▼
                              GHOST_DONE(SSE 打字机)
                                      │ Enter 采纳 / Esc 蒸发 / 手删收割
                                      ▼
                              沉淀(settle) → 实体/事件候选 → 收件箱(作者裁决)
                                      └→ 完稿(finish) → 审计/记忆/质感样本
```
