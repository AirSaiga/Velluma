# Velluma 演进路线图

> 本文档是生成与交互侧演进的**唯一权威载体**（append-only 编年体，每期一节）。
> 方向与定位已拍板（2026-08-18，详见 §0）：优先「世界页完善 × 写作台人机交互协作」；
> 产品定位「**真实可用的玩具**」（自用验证优先，可作开源产品但不社区化）；
> SQLite 切换日与 BS-ADF 归档等基建/架构债在功能期间隙插入（已完成）。
> **已完结期次（§1–§5、§9–§20）的长叙事已抽到 `docs/roadmap-archive.md`（节号不变，冻结）**；
> 本文件保留 §0 排序原则、§6–§8 三张横向表（决策点/分期总表/风险登记）与 §21 起近期期次。
> 关联：`docs/reports/canon-world-fusion.md` §7（C2/C3 详设）· `docs/world-writing-bridge.md` §6（W5 缓行件）· `docs/style-module-redesign.md` §8（E4 维持不做）

---

## 0. 背景与排序逻辑

### 0.1 方向与定位拍板（2026-08-18）

产品方向确定为两条主线：

- **线 A · 写作台人机交互协作**：心跳感知/走向卡/细纲胶囊/审校等协作交互的深化与补全；
- **线 B · 世界页完善**：真相层挂接（C2/C3）、W5 桥接件、旧表收尾。

两条线是**同一个飞轮的两侧**：世界页生产设定数据，写作台消费它做协作，W 桥接件
是连接件。因此排期不按线隔离，而按「度量 → 协作交互 → 世界数据喂协作」的依赖序
交织。原路线图（2026-08-18 首版）的「生成能力回补」在本方向下重新定位：P2a/P2b
不是「让 AI 更能写」，而是**协作交互设计**——尤其章级谋篇，是人与 AI 在章级尺度
上的共谋形态，而非渲染管线回归。

**定位四问确认**（同日，战略层拍板）：

- **项目定位 = 真实可用的玩具**。自用验证优先（开发者本人即长篇作者与深度用户）；
  可作开源产品，但**不社区化**（不做账号/分享/多人协作功能）。设计验收标准由此
  定为双轴：**有趣（可玩性/手感/美学）× 真实可用（一致性守护/人味守护）**。罗盘、
  空白舆图、衬线题签这类「玩具感」元素不是装饰，是产品本质的一部分；世界页与
  协作交互的打磨同时按效率与把玩感两个维度验收。终极验收标准：作者本人下一次
  真实写作的体感。
- **画像收窄成立，D3 定案**：不服务「AI 代笔成书」需求。依据：模型短期无法解决
  「不说人话」，完全代笔破坏作者心流，写作体感不如作者主导。推论：文风体系与人味
  防线（指纹/负面清单/洗涤/human-flavor 研究）的战略地位再升一级——**AI 帮忙，
  人味由作者守护**。
- **验证方式 = 自用验证**。P0 埋点的用途收窄为**自我可见性**（协作质量与 token
  成本的个人镜子），不做增长分析、不设跨用户指标。
- **冷启动延后并改写定义**：新书启动本就要求作者想清楚设定并亲手录入，AI 即时
  生成的初始设定是无效信息——冷启动不由「AI 生成内容」承担，而由**世界页的录入
  乐趣与顺滑**承担（新书第一小时 = 玩世界）。路线图不设冷启动主线；建书向导/导入/
  逆向提取维持现状；世界页完善的验收标准因此增加一条：**空态体验与录入顺滑度就是
  产品的第一小时**。

### 0.2 三个决定优先级的事实

1. **协作体验无仪表**。adaptive 各组件调 `call_llm_with_usage` 后 usage 全部丢弃；
   走向卡/细纲胶囊/切片条/情境浮卡**无任何采纳度量**。没有这些数据，协作交互的每次
   调优都是盲调，W5 缓行件「视数据再议」永远无数据可议。
2. **世界页数据尚未充分喂到协作现场**。相遇提示、疆域控制方、真相层秘密等数据已在
   世界页可维护，但到走向卡/感知带的桥还是 lite 态或未建（W5 缓行件）。
3. **章级尺度是协作的最大空白**。段落级共生（心跳/幽灵续写/胶囊）已成熟，「本章要
   去哪」没有任何伴生参照物——这是协作线最大的一件，且必须先出设计稿。

### 0.3 排序原则

```
P0 度量先行 → P1 协作交互深化 → P2 世界页数据喂协作 → P3 基建/架构债（间隙插入）→ P4 数据驱动激活
```

- P1 与 P2 不按线隔离，按依赖交织：世界页侧的桥接件（相遇→走向卡）直接服务 P1 的
  走向卡质量环；
- schema 变更（C2）排在 SQLite 切换日之前——MIGRATIONS 双库共享单一事实源，一次
  收敛，切换日只搬最终形态；
- 缓行件不用计划替代数据：凡「视数据再议」的项，一律等 P0 度量落地后按触发条件激活。

### 0.4 非目标（全程有效）

- E4 段落级指标制导维持不做（S4+ 复核结论：无数据支撑，走向卡已是柔性机制）。
- 多时间线 / 平行世界；实时推送同步（版本号轮询够用）。
- 不回到「按拍渲染」老路——章级谋篇的任何形态都不得把规划物变成渲染槽位。
- **整章代笔不做**（D3 定案，依据见 §0.1）。
- 不做社区化功能：账号体系/分享/多人协作/读者分享版地图（定位拍板推论）。
- 写作页内不做任何空间编辑；文风/笔记/应用设置不进世界页。

---

## 6. 决策点

| # | 决策 | 状态 |
|---|------|------|
| D1 | C2 与 SQLite 切换日先后 | ✅ **已解**（方向拍板自然排序：C2 在归档 §3.1，切换日在归档 §4.1，schema 一次收敛） |
| D2 | 章级谋篇（归档 §2.4）设计稿先行 | ✅ **已拍板**（2026-08-18）：可行，核心约束「度」（前置成本趋零、不损心流）；设计稿 `docs/chapter-planning-spine.md` |
| D3 | 是否保留整章代笔入口 | ✅ **定案不做**（2026-08-18）：模型短期无法解决「不说人话」，完全代笔破坏作者心流，体感不如作者主导 |
| D4 | 比例尺标定是否投入 | ✅ **已拍板**（2026-08-18）：投入，设计委托 Agent 完成；设计稿 `docs/reports/map-scale-spatial.md` |
| D5 | 「私有」语义 = AI 知晓但绝不能直接写出（对齐 canon `[private]`），不从上下文删除 | ✅ **已拍板**（2026-08-20，foundation-hardening §1） |
| D6 | 叙事时间默认值问题首版零行为变化：来源可见 + 录入侧警示（chapter_ref 方案已排除——该列全库无写入点） | ✅ **已拍板**（2026-08-20，foundation-hardening §1） |
| D7 | 上下文预算管理器分两期：A3a 纯重构零行为变化 → A3b 动态分配单独实测 | ✅ **已拍板**（2026-08-20，foundation-hardening §1） |
| D8 | stitch-ghost 真流式条件排期：批次 1-2 后实测首字延迟再定 | ✅ **已拍板**（2026-08-20，foundation-hardening §1） |

---

## 7. 分期总表

| 期 | 内容 | 性质 | 状态 |
|---|---|---|---|
| P0 | 在途批次提交 + adaptive 观测落库 + 协作交互埋点 + 状态机/model 端点补洞 | 纯接入 | ✅ 2026-08-18 完成（vue-tsc 净 + bsadf 118 单测全过 + 冒烟验证） |
| P1 | 写作台协作深化：感知层补全 / 审校修复闭环 / 走向卡质量环 / 章级谋篇 M1-M3 | 交互主线 | ✅ 2026-08-19 完成 |
| P2 | 世界页完善：C2 真相挂接 / 相遇→走向卡桥 / C3 激活 / M4 收尾 / D4 比例尺 | 数据主线 | ✅ 2026-08-19 完成 |
| P3 | SQLite 切换日 + BS-ADF 归档 | 基建/架构债 | ✅ 2026-08-19 完成 |
| P4 | 缓行件激活 | 数据驱动（归档 §5 触发条件；05 瘦身后数据门已废改推理分诊） | ⏸ 按推理逐项重新分诊 |
| P5 | 地基加固期：契约修复（私有语义/在场提权/叙事时间可见/回流闭环）+ 录入回报可见（AI 所见预览/用量）+ 预算管理器 + 生成效果调优 | 加固/体验/效果 | ✅ 施工完成 2026-08-21（`e44dd59`，后端 365/0 首次全绿、前端 85；实测期事项与 B4 待真实使用验证） |
| §12+ | 此后各期（战略定稿/世界内核/deai/约束治理/真相质感/运维收口/去参数化/写后收敛/next-phase 五批等）见本文 §21 起与 `docs/roadmap-archive.md` §9–§20 | 连续编年 | ✅ 逐期登记在案 |

---

## 8. 风险登记

- **useGenerationSession.ts（2426 行，步进逻辑已删）**：仍是 adaptive 主逻辑的最大
  单文件——拆分为独立任务 T1（归档 §9），拆分前改动需谨慎；新交互件优先落在
  useAdaptiveAssist / useChapterSpine 等独立 composable。
- **协作信息过载**：P1 感知层与走向卡升级的共同风险是打扰作者心流——所有新提示
  一律走「柔性可忽略」通道（感知带/挂件，不弹窗、不抢焦点），上线后凭无视率
  数据回调密度。
- **SQLite 切换演练**：迁移脚本虽有行数对照 + FK 校验，切换日前仍需真实大书库演练
  一轮（SystemCliche 种子翻倍前科需回归验证）。
- **观测接入性能**：heartbeat 是高频端点（防抖 3s），RunRecorder 落库必须异步不阻塞
  响应（adf.py 已有先例）。
- **双库并存期测试盲区**：切换日后 PG 路径保留，CI 目前只跑 py_compile——canon
  兼容层两个方言各需冒烟验证手段。

---

## 21. 候选回流链路修缮期（2026-09-18，设计稿 `docs/next-phase/02-candidate-reflow-repairs.md`，已提交 c304440；09-19 补测试 124df8a）

修缮非新建（链路本体幂等/去重/批量采纳不动）：候选补出处（抽取 prompt 要求 evidence 逐字摘录 + event_scout 落池「去空白子串」校验，编造出处剥除不上屏、候选降级无出处档；前端收件箱悬停/批量模态引文/世界页卡片三面展示）/ 撤销单事务化（`POST /world/candidates/{id}/undo-accept` 删转正产物+回 pending 一个 commit；accept 记录产物 id 入 draft）/ 拒绝史进防重（30 天窗/200 条归一化判重，auto_reject 假拒绝不计，suppressed_rejected 计数）/ 键盘裁决（↑↓/→·Enter/←·Delete，`inboxKeyboard.ts` 纯函数三宿主）/ 回场补读（进章也发枪 auto-read，哈希幂等闸兜底零成本重进）/ read-entities 失败不写幂等锚（`EmergentFacts.failed` 区分失败与无涌现）+ 顺修 `adaptive/schemas.py` 缺 `Any` 导入致 read-entities 响应必炸的预存在隐患 / 用量停机冲账（lifespan+atexit 双路 `flush_all_adaptive_records`）。叙事见 `docs/incidents/world.md`，契约见 `docs/agent/world.md` ④ 与 `docs/agent/nle-adf.md`。测试基线：后端 1531→1562、前端 370→381；09-19 补齐批（124df8a）加 observing 停机冲账行为契约 + 涌现失败/无涌现显式区分，基线至 1586+398。

## 22. 协作埋点瘦身期（2026-09-18，设计稿 `docs/next-phase/05-telemetry-slimming.md`，已提交 6845578）

拆分析层留机制层：`GET /adaptive/events/summary` 聚合端点与 insights「协作」面板（四采纳率卡/逐章分布/COLLAB_KIND_LABELS/清空埋点按钮）退役——面板只剩成本/质量/用量三 tab（B3 用量两卡是 generation_runs 观测面，原样保留）；纯分析事件接线 19 种全拆（前端发射点收缩到机制 3 文件 5 处：hint_dismiss/ghost_adopt/ghost_discard/intent_correct + 传感器 ghost_discard_reason）；事件总线与写侧保留（机制四件的水管），`DELETE collab-events` 端点保留为机制数据重置口。原则修订落 `docs/ai-writing-philosophy.md` §8（埋点不当门卫只当刽子手；两纪律废除：新功能必须配埋点 / COLLAB_KIND_LABELS 上屏映射）；归档 §5 缓行表与 §2.3/§2.4 数据门标注「已废改推理分诊」。M1 全量清点清单在 05 稿附录。机制对拍（quiet_learning 66 项/intent_hardening/style_paradigm sample_prior 5 项）全绿；基线 1562+381+tsc 净不变。

## 23. 开章卡与读者清单期（2026-09-18，设计稿 `docs/next-phase/01-opening-card-and-reader-ledger.md`，已提交 ce48e09）

两面镜子零 LLM：**开章卡**（M1——`GET /adaptive/opening-card`：空章「打算」页顶部四行：该揭（含逾期深度）/别说破（scope 徽标全书·在场两档）/线头（真实总数+最久）/此刻；三规则宪法=真实总数+口径徽标·点一下就地展开·空集零像素；设置弹窗「写作台」开关；专用计数 touch 端点写独立 jsonl——05 瘦身口径首发）/ **读者清单**（M2——finish 响应 `reader_ledger`：本章新知道/已经知道/还不知道按计划章分桶+未排期，报告末尾「读者此刻」栏）。数据底座 `services/world/reader_ledger.py` 复用 read_merge_reveals（扩文本三件）+ build_scene_slice（在场口径无平行实现）。测试 +6（test_reader_ledger.py：分类/空 None/文本携带/卡片行/空书/路由防御），基线 1568+381+tsc 净。M3 调参（超载阈值 6/排序键）待真实使用数据。

## 24. 问书期（2026-09-18，设计稿 `docs/next-phase/04-ask-the-book.md`，已提交 e4d1f6c）

行间手势速查：`??` 触发（AskNoteNode 手势族）→ `POST /adaptive/ask-book`——六类纯代码直答零 LLM（`services/world/ask_book.py`：线头/该揭/距离 spatial/上次出场/谁知道 belief 四值/哪章写过 jieba）→ M2 意图解析笼（LLM 只翻译+名单硬闸）→ M3 材料内合成（出处 id 校验，编造拒收）→「没查到」是一等功能。答案幽灵式浅字只读 Esc 蒸发不进正文；出处点验=章就地切/世界页深链。问题原文落 data/ask_book_metrics.jsonl（M4 分布回看）。测试 +17（test_ask_book.py：分类/六类哨兵防 LLM/硬闸/合成校验/路由/度量），基线 1585+381+tsc 净。

## 25. 幽灵改稿自动捕获与三键期（2026-09-18，设计稿 `docs/next-phase/03-ghost-edit-capture.md`，已提交 c48fc32）

deai 数据飞轮收集端零操作化 + 幽灵交互防呆：**书签位置映射**（`useGhostPairTracker`：采纳瞬间暂存 AI 原样+首尾 position 纯内存，随事务映射塌缩守原地；保存时对比并更新同幽灵只留最新版，切章定稿聚合提示+按批撤销；干净采纳跳过/塌缩=完全否决/≤100 字窗外不收）+ **三键阶梯**（Tab 采纳·Enter 暂留零承诺·Esc 丢弃+60s 找回窗；流式只打断不采纳+GHOST_DONE 400ms 缓冲窗；一期一个暂留位，暂留终局丢弃喂学习）+ **视觉**（mint 点线边界+转正段未审虚线 GhostTrack 装饰碰过即消）。pairs 后端 source 三源白名单（manual_mark/auto_ghost/capsule）。测试 +17 前端（ghostPairTracker），基线 1585+398+tsc 净。M4 度量（粮食速率/干净采纳率/暂留转化率/自动对六闸通过率）待真实写作数据。

## 26. 视觉焕新、性能与契约收编期（2026-09-16～09-19，已提交）

AGENTS.md 拆分瘦身（b48bdfb：133KB→39KB——四大领域档案 `docs/agent/*.md` 拆出按需加载 + `docs/incidents/` 施工/事故叙事体系建立）/主题白屏收口（1cd39c0：五主题暗块影子 rgb(from color-mix) 相对色语法预计算 rgba）/隐式图谱投影器原型落地（2eb895b：事件流确定性隐式关系投影，09-16 可行性结论兑现，暂无消费方，`docs/reports/implicit-graph-projection-feasibility.md`）/写作规矩（质感契约按书覆盖）收编批（6044011：系统级写作纪律从硬编码升为可编辑契约，唯一权威 `services/style/texture_contracts.py`）/N+1 批量端点收口（e6500a5：章实体关联/书级 spine/世界页重入三处页切卡顿根治）/取景器双层分立+微观空间姿态+名册正文轨（563c6d9：在场感知增强，09-16/17 双层修正残余）/API 弹窗左侧导航式重构（baba41f：左栏六项导航分区+底部连接测试）/设计令牌体系迁移+视觉焕新 P1（801c5ef：线/影/层次三族令牌全仓扫面 --line/--elev-*）/文风页「笔迹谱·双视图」v4（55befcc：前台亲民工坊+深层 Beta 实验室，09-17 降噪/渐进/视觉三批+09-18 收敛）。

## 27. GUI 自动化测试与审计收口期（2026-09-19，已提交）

GUI 自动化测试轮种子脚本（1275ff5：web-gui-tester 第一档配套——浏览器 GUI 黑盒测试起步）/09-19 审计四高置信修复（f8677ac：幽灵状态机死键×2 + 质感契约 None 分支 + 试衣间浮签坐标系 + R1 canon 收编）/02 修缮批测试补齐（124df8a：observing 停机冲账行为契约 + 涌现失败/无涌现显式区分，基线 1586 后端/398 前端+tsc 三绿）/next-phase 五批设计稿入册+领域文档同步（cfdad3d）。

## 28. 书籍备份/还原闭环期（2026-09-19，未提交批内——随本批提交）

书架「备份 → 删除 → 还原」闭环，唯一权威 `backend/services/book_archive/`。`GET /books/{id}/backup` 导出单 JSON 文件（`.vellumabook`：34 张书籍级表全部行 + `data/world_images/{book_id}/` 底图 base64 + 6 个 jsonl 台账按书过滤——collab_events 是四个机制零件的数据源必须随备份走）；`POST /books/restore` 还原——**原 ID 直复**（canon_nodes.ref_id 软关联与 world_intents.source_key 字符串内嵌 ID 按原 ID 存活，重映射即静默切断；同 ID 已存在 409 拒绝；台账滤旧再追加幂等）；`DELETE /books/{id}` 连带清理文件侧（底图目录/台账本书记录/章级 trace+prompt 日志——不清理则「删→还原」后台账双份）。三条不变量：①新增书籍级表必须进 `tables.py` 注册表（圈行谓词三类）否则备份静默漏表；②导入逐表按 `sorted_tables` 拓扑序 flush + 自引用列两阶段回填；③embedding 走 b64f32 打包、仅 PG 回填。前端 BookRestoreModal + backupPreview.ts（书架卡片入口）；冒烟 `scripts/smoke_book_backup.py` 真实库两轮全过。测试基线：后端 1598 / 前端 413 + tsc 三绿。契约详见 AGENTS.md「数据库与迁移」节。

## 29. 启动脚本环境隔离重排期（2026-09-19，未提交批内——随本批提交）

启动脚本按**环境/功能完全隔离**重排（用户拍板勿回退）：`scripts/dev/`（开发调试·后端热重载）与 `scripts/prod/`（正式生产）各四入口（后端/前端/Electron/一键三端），`scripts/monitor/`（.vbs 网页监控台+后台监督者）完全自持（dev_dashboard.py 私有副本），`scripts/macos/{dev,prod}/` 对称两模式，收摊脚本 `scripts/stop-velluma.{bat,ps1,sh}` 升 scripts 根全局通用。**每文件夹互不复用、互不引用**（宁可重复不可共享）。旧三模式收敛为两模式（原 debug 热重载形态=新 dev；原无热重载 dev 退役）。契约自检 `scripts/check_launcher_contract.py` 检查面 5→22（双平台编排核心×4 + 单服务脚本×6 + monitor 副本 + 收摊脚本 + 前端 `transport/base.ts` 判定区间），保持 CI 阻断绿。完整契约唯一权威 `scripts/README.md`，施工叙事 `docs/incidents/launcher.md`。

## 30. 语义撞车 shadow 检与 prompt 治理加固期（2026-09-22～09-24，已提交 50b6238 / 2eed4b1 / d930314；设计稿 `docs/next-phase/06-prompt-governance-hardening.md`）

MiMo V2.6 系目录上线（50b6238：v2.6-pro/flash/ultraspeed 三档入册，v2.5 系 10-21 下线倒计时标注，矩阵文档同步）/桥接后文语义撞车 shadow 检（2eed4b1：`dock-bridge-overlap-semantic`——「改写式预演」（字面重合 <4 字）是词法闸盲区，由向量比对与字面闸双跑攒校准，只落台账不丢件，embedding 未配置静默跳过；语义重叠模块的 SUFFIX 常量经 hunk 级拆分随本提交，BEAT_RUSH 定档随下批）/**prompt 治理批**（d930314，next-phase 06：①stitch 基座 17 块 SHA256 快照锁 `test_stitch_base_snapshot.py`——改一字即红，更新程序在文件头；②`scripts/prompt_snapshot.py` 纯渲染快照 + `scripts/prompt_replay.py` diff/双跑对照+闸门判分+裁决台账——prompt 改版前后效果可见可裁决；③全局 `PROMPT_VERSION`（`services/prompts/prompt_version.py`）进 stitch trace，动措辞必递增纪律入 AGENTS.md；④语义阈值实测定档：扫描 0.78→0.72、抢拍 shadow 0.80→0.78、后文撞车维持 0.80，依据 `docs/reports/semantic-threshold-calibration.md`；⑤**embedding 批量上限 20 静默失效修复**——`_request_embedding` 透明分批（该模型 >20 条/批整体 400 被吞成全空向量，语义扫描与两个 shadow 检对长文此前整体失效，系 shadow 检长期零命中根因之一）。测试基线：后端 1646 / 前端 416 / tsc 净。
