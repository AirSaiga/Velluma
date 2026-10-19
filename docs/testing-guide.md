# 测试指南与「改码后更新测试」纪律

> 唯一权威：本文档管**测试怎么写、放哪里、怎么跑、改完代码后要更新哪些测试**。
> 各模块行为契约的对拍单测条目散见 `AGENTS.md` 各节（如「同一把尺子」fingerprint 对拍），那些条目声明**行为契约**，本文档声明**测试纪律**——冲突时以 AGENTS.md 的契约条目为准并在两处同步。
>
> 建立日期 2026-09-15（全量测试补全批，见 §6）；维护规则：**每次改测试基建（配置/目录约定/运行命令）必须同步本文档。**

---

## 1. 当前覆盖面（2026-10-14 基线）

| 面 | 数量 | 运行方式 |
|---|---|---|
| 后端 pytest | **1690 项** | `.venv\Scripts\python.exe -m pytest backend --ignore=backend/_deprecated -q` |
| 前端 vitest | **434 项**（50 文件） | `cd frontend && npm run test` |
| 前端类型 | vue-tsc 零错 | `cd frontend && npm run typecheck` |

- 2026-10-14 基线变动（外来样本收回修复批）：+4 后端——`routes/style/test_samples_scope.py` 7→11 项（recall 端点：book 副本字段对拍/原行不动/本书样本 422/缺失 404×2/内容去重 409 幂等，桩补 embedding 字段）；+4 前端——`sampleBuckets.test.ts` 12→15 项（`extractPrefillCandidates` 外来样本过滤纯函数）+ `patchSampleScope.test.ts` 2→3 项（`recallSample` 独立端点对拍）。

- 2026-10-05 基线变动（文风双跑实验批）：+24 后端——`services/style/test_scene_hint.py` 18→40 项（v2 四档扩档+v3 fragment 优先两段式+显式 `scene_type` 优先链）；新增 `routes/style/test_samples_favorite.py`（favorite 落库链路，2 项）。

- 2026-10-05 基线变动（全局笔迹库 scope 批）：+16 后端净增——`test_cross_book_fallback.py` 整体改写为新语义（补位不抢位/零变化/门票迁移/卡层隔离，旧 3→6 项）；新增 `services/style/test_global_scope_vector.py`（向量流档位对拍，6 项）与 `routes/style/test_samples_scope.py`（scope 路由契约+422 双闸，7 项）；+14 前端（`features/style/__tests__/`：`sampleBuckets.test.ts` 12 项分桶纯函数+`patchSampleScope.test.ts` 2 项，48→50 文件）。

- 2026-09-24 基线变动（next-phase 06 prompt 治理批）：+28 后端（`services/prompts/test_stitch_base_snapshot.py` stitch 基座 SHA256 快照锁 17 块 +20；`services/llm/test_embedding_batching.py` embedding 20 条/批透明分批对拍 +8）；配套阈值定档落码（扫描 0.72 / 抢拍 shadow 0.78，依据 `docs/reports/semantic-threshold-calibration.md`）与新工具 `scripts/prompt_snapshot.py`/`prompt_replay.py`（快照对拍+双跑对照）。

- 2026-09-23 基线变动（语义后文闸 shadow 批）：+3 后端（`test_governance.py` registry 登记对拍 +1；`test_dock_onstage.py` 桥接语义撞车 shadow 双跑「命中落台账不丢件」+ 无 suffix 零调用 +2）；另 +1 系工作区既有 vendor_profiles 批（非本批）。前端 416/48 实测（指南原记 413/47 系基线陈旧，非本批改动——本批零前端代码）。

- 2026-09-20 基线变动（请求级链路日志批）：+16 后端（`core/test_request_observability.py`——[REQ] 完成行/X-Request-ID 头/降噪策略/异常落日志/流式不缓冲/VELLUMA_LOG_LEVEL 解析语义锁）；`test_view_rebalance.py` 的 `_FakeResult` 补 `finish_reason` 与真实 LLMResult 同形。
- 2026-09-19 基线变动（书籍备份批）：书级备份/还原/删除清理 +11 后端（`services/book_archive/test_book_archive.py` 真实 SQLite 往返对拍 + `routes/test_book_backup_routes.py` 路由冒烟）+ 前端备份预览纯逻辑 +12（`features/library/__tests__/backupPreview.test.ts`）；配套 `scripts/smoke_book_backup.py` 真实库副本冒烟（隔离承诺见脚本头）。
- 2026-09-18 基线变动（next-phase 五稿批）：候选回流修缮 +31 后端 +11 前端；埋点瘦身零增净删（拆 summary 端点与协作面板，机制测试保留）；开章卡 +6 后端（`test_reader_ledger.py`）；问书 +17 后端（`test_ask_book.py`）；幽灵三键/自动捕获 +17 前端（`ghostPairTracker.test.ts`——决策纯函数/映射三形态/覆盖语义/上膛窗）。2026-09-19 GUI 交叉验证轮：+1 后端（问书「知道」语气词回归用例，缺陷 #2 修复配套——旧断言太松假绿的教训：断言必须钉分支专属措辞）。

- 后端测试与被测模块**同目录 colocate**：`services/style/fingerprint.py` ↔ `services/style/test_fingerprint.py`。跨模块的接缝测试也放在主要消费方目录下（如 `routes/chapter_generation/test_collab_clear.py`）。
- 前端测试**只收集 `src/**/__tests__/**/*.test.ts`**（`vitest.config.js` include）——新测试必须放 `__tests__/` 目录，放别处会被**静默跳过**（distance.test.ts 曾中招，4be1568）。
- `backend/_deprecated/` 不参与任何 import 链，测试同理不跑（全量命令必须带 `--ignore`，否则收集错误中断）。

## 2. 运行命令与已知坑

```powershell
# 后端全量（Windows；必须用 venv 解释器——裸 python 缺 aiosqlite 会报收集 ERROR 假回归）
.venv\Scripts\python.exe -m pytest backend --ignore=backend/_deprecated -q

# 后端单文件
.venv\Scripts\python.exe -m pytest backend/services/style/test_fingerprint.py -q

# 前端
cd frontend
npm run test          # vitest run 全量
npm run typecheck     # vue-tsc --noEmit
```

坑（实测踩过，勿重查）：

- **pytest 一律用 `.venv/Scripts/python.exe`**：裸 python 缺依赖，报错形态像代码坏了，其实是环境。
- **全量 pytest 必须排除 `_deprecated`**：归档引擎的旧测试无法收集（import 链已断），不排除会以 9 个收集错误中断整轮。
- **shell 里跑 vue-tsc 输出须重定向**（管道/后台），否则长输出可能挂起终端。
- **bash 的 cwd 跨调用持久化**：`cd frontend` 之后下一条命令已在 frontend 里，再 `cd frontend` 会失败；跑 git diff 见空前先 `pwd` 自查。
- vitest 是 **node 环境无 jsdom**：需要 DOM/window 的用例用 `vi.stubGlobal`（见 §4）。
- CI（`.github/workflows/ci.yml`）只跑 `py_compile` + `vue-tsc`（非阻断）+ 启动契约自检——**pytest/vitest 不在 CI 里，全绿口径靠本地跑**。改 CI 加测试步骤时同步更新本表。

## 3. 改码后测试更新纪律（核心）

**每次修改代码后，按下表更新对应测试用例，然后跑全量三绿再收工。**

| 你改了什么 | 必须更新什么 | 验证命令 |
|---|---|---|
| 纯函数 / engine / 表驱动数据（`engine/*.ts`、`services/**` 纯算法、词表/模板表） | 同目录对拍单测：改行为的更新既有断言，加新分支的加新用例；表结构（key 唯一性/字段完整性）跑表完整性对拍 | 对应 `test_*.py` / `*.test.ts` |
| Prompt 模板 / 注入块措辞 | 对应对拍（`services/prompts/test_*`：零变化契约逐字节比对、分节编译、剂量计数）——**改 prompt 不跑对拍 = 违约** | prompts 目录测试 |
| 统计口径 / 指纹算法 | 先跑「同一把尺子」对拍 `services/style/test_fingerprint.py`（锁定 fingerprint 与审计侧同值），再动两侧 | 该文件 |
| API 路由（新增/改参数/改响应字段） | `routes/` 下的路由测试补用例；schema 变更同步前端 `services/domain` 类型与相关 `.test.ts` 夹具（历史坑：cached_tokens 加字段时前端夹具漏补） | 路由测试 + vitest |
| 数据库模型 / 迁移 | `db_sqlite/` 迁移测试补迁移用例；**SQLite 冒烟必须走 `init_db_sqlite`**（直接建表会漏迁移路径） | db_sqlite 测试 |
| 前端 composable / 组件逻辑 | 放对应 feature 的 `__tests__/`；模块级单例（useEscStack/useSparkDock 等）记得 `vi.resetModules()` 隔离 | vitest |
| **删除/归档模块** | 其测试同批删除/随迁 `_deprecated`；全量数字变化记入本文档 §1 基线行 | 全量三绿 |
| 文档声明的行为契约（AGENTS.md 各节） | 契约对应的对拍单测同步改——**文档、代码、测试三者一处动两处跟** | 对应测试 |

**收工门槛**：后端全量 + 前端 vitest + vue-tsc 三绿；本批新增/修改的测试文件在提交说明里点名。测试失败不修复不提交（「先合再说」历史上每次都还债）。

### 勿删测试清单（契约锁定，删=回归）

- `backend/services/workflows/conftest.py`：autouse fixture 防 asyncio 事件循环污染，**跨文件跑 pytest 时删了会随机失败**（详见 AGENTS.md「测试」节）。
- `backend/services/style/test_fingerprint.py`：同一把尺子——改任一侧统计算法先跑它（19 项锁同值）。
- `backend/services/canon/test_context_contract.py`：canon 三段格式 `[private]/[public]/[hook]` 冻结契约的往返单测。
- `backend/services/context/test_chapter_style_override.py` / `test_style_injection.py`：**零变化契约**（无配置的书 prompt 逐字节不变）锁定。
- `backend/services/adaptive/test_dock_*.py` 四件 + `test_contradiction_pairs.py`：dock 槽位/接缝裁剪/别名归一的行为对拍（AGENTS 多处引用）。
- `frontend/src/features/workspace/__tests__/contextBlockFormat.test.ts`：保字不变式（字不增不删红线）是合入前置。
- 每个测试文件头部的「对拍口径」注释块：写明该文件锁什么契约，更新断言时先读它。

## 4. 测试写法规范

**后端（pytest）**

- 纯函数直接测；**LLM 一律 mock**——monkeypatch **被测模块命名空间里的符号**（`monkeypatch.setattr(extractor_mod, "call_llm", fake)`），不要 patch client 底层（历史上 mock 错层导致用例空转，见 §6 教训）。
- mock 的返回值形状必须与真实 API 一致：`call_llm` 返回裸 `str`，`call_llm_with_usage` 返回带 `.content/.prompt_tokens` 的结果对象——mock 错形状会让被测函数走异常兜底分支，测试**假绿**。
- 测「失败不阻塞」路径（降级/回退原文/兜底）与成功路径同等重要——这是本仓库的显式设计（Phase 0 失败不静默）。
- 异步用 `@pytest.mark.asyncio`；需要 DB 的用现有 fixtures（参考 `routes/test_world_kernel_routes.py`），不要自建引擎。
- 带随机性/分词依赖的模块（jieba 等）：测纯函数入口（喂 `(word, flag)` 序列而不是整句），把分词不确定性挡在测试外。

**前端（vitest，node 环境无 jsdom）**

- 只测纯逻辑层（engine/composables/utils）；组件渲染测试目前不做（历史决定：IAB 实机验证代替）。
- 需要 `window`/`document` 的：`vi.stubGlobal('window', fake)`，fake 里注意 addEventListener 第三参可能是布尔 `true` 而非 `{capture}` 对象（useEscStack 测试踩过：`opts?.capture` 对 `true` 是 undefined，监听器收不进列表、断言全空）。
- 模块级单例（栈/缓存/状态）：每个用例 `vi.resetModules()` + `await import(...)` 取新实例，否则状态跨用例泄漏。
- 事件对象 stub 要补全被消费的方法（`preventDefault`/`defaultPrevented`），缺方法会 TypeError 淹没真实断言。

## 5. 有意不测的（缺口台账，补齐前先看这里）

| 模块 | 不测原因 | 何时补 |
|---|---|---|
| `services/adaptive/orchestrator.py`、`components/dock_generator.py` 等重 LLM 管线 | 心跳全链路的正确性靠 **trace 实测**（`logs/trace_adaptive_*.jsonl`）+ 组件级对拍（test_dock_* 已覆盖纯函数面）；mock 整条管线测不出真问题 | 组件抽纯函数时随迁测试 |
| `services/canon/impact.py` | 连锁分析前端已退役（建边零入口实证），路由保留零数据风险 | 路由重新启用时 |
| `services/utils/logging.py` / `prompt_logger.py` / `sse.py` | IO 副作用薄封装，行为由消费方间接覆盖 | 加逻辑时 |
| `services/context/loader.py`、`budget.py` 旧常量 | budget 的 allocate 机制保留但默认恒等（P5 后），已有 test_budget_allocate 锁行为 | 启用预算分配时 |
| 前端 `bulkImport.ts` / `markdown-parser.ts` / `motion.ts` / `useToast` 等 UI 绑定模块 | 薄 UI 胶水，IAB 实机验证 | 抽出纯逻辑时 |
| `_deprecated/` 全部 | 归档不参与 import 链 | 永不 |

新增「有意不测」条目必须写原因——台账不是不测的借口，是显式决策的记录。

## 6. 本批补全记录（2026-09-15）

全量缺口扫描（源模块 vs 测试文件对拍 + grep 跨名覆盖核实）后补 14 个测试文件、167 项，全部一次写完三绿收口：

**后端（8 文件 113 项）**

| 新文件 | 锁什么 |
|---|---|
| `services/utils/test_html_text.py` | 剥 HTML 唯一权威：标签→换行、空行折叠、`<p></p>`→空串（from-chapters 判空依赖）、无标签字符残留 |
| `services/utils/test_json_safe.py` | LLM JSON 容错解析三段降级（直接/剥围栏/截括号），全失败 None 不抛 |
| `services/nlg/test_text_sanitizer.py` | 确定性裁剪：黑名单/微操删除、标点收敛、rolling 比喻去重保首次、尾部截断 |
| `services/nlg/test_local_preprocessor.py` | 对话保护（引号内不抽脂）、叠修饰只留最后、>40 字硬断句只切一次、删减过半回退原文 |
| `services/nlg/test_de_ai_washer.py` | 洗涤处置分支：未触发零 LLM、失败/空回退轻裁、洗后改善/更糟分流、must_keep/负面清单注入 prompt |
| `services/style/test_extractor.py` | 提炼降级三路（无样本/LLM 异常/解析失败）永不抛、成功路径、dialogue_ratio 钳制 |
| `services/text_surgery/test_planner.py` | 手术规划纯算法：重叠/相邻合并、全局问题独立、severity 序、op_type 判定 |
| `services/text_surgery/test_surgeon.py` | 应用层纯函数（多段拆填/空段过滤/不改原 list）+ LLM 失败保原文分支 |

**前端（6 文件 54 项）**

| 新文件 | 锁什么 |
|---|---|
| `shared/utils/__tests__/defat.test.ts` | 清脂拨盘：零命中零变化、整词删净、叠标点收敛 |
| `shared/utils/__tests__/errorText.test.ts` | 错误文案分类优先序、未知错误原文透传 |
| `shared/utils/__tests__/htmlText.test.ts` | 字数口径统一（标签不虚增）、escapeHtml 四字符实体化 |
| `features/world/engine/__tests__/interpolate.test.ts` | move 弧长插值 ≠ 顶点比例（对拍判例）、端点/单点/零长防御 |
| `features/world/engine/__tests__/schemaTables.test.ts` | 三张表驱动表完整性：key/type/value 唯一、模板必填字段契约、未知类型兜底 |
| `composables/__tests__/useEscStack.test.ts` | Esc 栈纪律：只关栈顶、defaultPrevented 让位、栈空摘监听、remove 幂等 |

**本批实测教训（写新测试前扫一眼）**：

1. mock 形状错（`call_llm` 该返回裸 str 却给了对象）→ 被测函数走异常兜底 → 测试**假绿**（hybrid ±30% 门三个用例曾全部空转）。
2. 短文快路径门槛（<50 字直返）会吃掉你以为会触发的 LLM 调用——测「调用了 LLM」的用例先确认输入过门槛。
3. 模块级单例 + 模块级 `listenerAttached` 类标志：跨用例泄漏,必须 `resetModules`。
4. 写断言前先跑一遍真实行为（`.venv/Scripts/python.exe -c "..."`）——本批 5 处「想当然断言」与实际行为不符（html_to_plain 行内标签也换行、全黑名单段残留标点、全局问题排序恒居首等），**测试锁的是现有契约，不是想象中的契约**；若现行为本身可疑，报给维护者而不是在测试里替它圆场。
