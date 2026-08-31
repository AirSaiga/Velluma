# deai 去 AI 味小模型 — 子项目与宿主集成（唯一权威）

- 立项/迁入：2026-08-31。`deai/`（仓库根）是自训「去 AI 味」小模型子项目的
  完整档案（v1 已收官），从 `D:\deai` 原样迁入（原件保留未动，可确认后删除）。
- 本文档管**宿主侧**：配置、接口、挂点、保底与升级路径。
  模型侧（任务契约/六闸判据/训练数据/评测基线）唯一权威在
  `deai/docs/contract.md`（契约 v0.2）与 `deai/docs/archive.md`（v1 归档报告）。

## 1. 任务边界（来自模型契约，宿主侧不得越界）

- 输入：≤100 字中文片段（`len()` 口径，strip 后计数）——超长**不改写**，
  原样返回（契约 C1）。这意味着卡片舱幽灵里 stitch/continue 的百字级短稿
  受益，burst/open/outline 的长稿**自动跳过**（预期行为，不是 bug）。
- 只改语言质感（措辞/句式节奏/连接方式）；事实、数字、日期、专名、引文
  一律不动；输出 ≤ 原长 120%；不新增观点。
- **契约§6 运行时保底**：模型输出过不了事实闸（数字闸/专名闸/新增事实闸）
  → 回退原文；网络/HTTP/空输出 → 回退原文；仅非事实闸失败（长度/套话/
  像人）→ 仍返回改写但带 warnings。保底逻辑移植自
  `deai/scripts/deai_rewrite.py`，闸门判据移植自
  `deai/scripts/validate_pairs.py` 的 `check_gates`（fact=None 路径）。
- v1 已知边界：训练语料为产品/公告/观点类事实卡，**叙事/小说文本未训练**
  （用户试过一段表现尚可但不保证）——v2 扩量（`deai/data/inbox/` 收集箱，
  目标含叙事类 50+ 段）是解锁写作场景质量的正路。

## 2. 配置（model_config.json 的 `deai` 节）

```json
"deai": {
  "enabled": false,
  "api_key": "",                                    // 阿里云百炼 DashScope Key
  "model": "qwen3-4b-instruct-2507-78a06917f4ca",   // 部署后的 deployed_model
  "base_url": ""                                    // 留空 = DashScope 原生端点
}
```

- **已配置判据**：`enabled` 且 `api_key` 且 `model` 三者齐备
  （`backend/services/deai/client.py::is_deai_configured`）。
- 零变化契约：未配置时 ghost 链路对 deai **零调用**，幽灵文本逐字节不变
  （同 embedding 未配置短路纪律；单测锁定）。帧形状例外：GHOST_DONE 恒增
  additive 的 `deai` 字段（旧前端安全忽略）——零变化指**文本**，不是 SSE 帧。
- 读写：`backend/core/model_config.py::get_deai_config / update_deai_config`；
  前端经 `GET/PUT /api/system/model-config`（Key 掩码往返，留空/掩码回显
  均保持原值）。
- ⚠ 调用要点（实测踩坑，勿改）：**DashScope 原生** text-generation 端点
  （百炼调优模型不支持 OpenAI 兼容入口，报 model_not_found）；model 填
  部署名（不是训练任务 ft-… ID）；`enable_thinking: false`（Qwen3 非流式
  要求）。重训/重部署后部署名会变——百炼控制台或
  `GET https://dashscope.aliyuncs.com/api/v1/deployments` 查新值，更新配置。

## 3. 宿主侧接口（backend/services/deai/）

| 组件 | 职责 |
|---|---|
| `client.polish_fragment(text, *, model, api_key, base_url, protected_names) -> DeaiResult` | 公共入口：≤100 字片段改写全链路（调用+§6 保底+宿主保名闸+usage 透传）。覆盖参数优先于配置——设置面板「试一试」用表单实时值，未保存也能测。不检查 enabled（那是调用方策略开关）。`protected_names`：**宿主侧保名闸**（超出模型契约的加护）——契约专名闸只护引文/书名内容与拉丁 token，中文名不在其内；原文出现的保护名必须在改写稿逐字保留，否则按事实失败回退。小说场景人名地名是最重要的事实，v1 又未训练叙事文本，这道闸补的就是该窗口。`DeaiResult.tokens_in/tokens_out` 透传 DashScope usage（超时 8s=挂死上限，常态 1-3s；等待发生在 GHOST_START 前，超时即保底回退） |
| `client.is_deai_configured()` | ghost 链路守门判据（见 §2） |
| `gates.runtime_gates(source, rewritten)` | 运行时闸门（六闸的 fact=None 路径移植副本）；`FORBIDDEN_WORDS` 为 deai 契约禁词表运行时副本（10 词） |
| `test_deai_client.py` | 17 项单测：闸门用例对拍 deai SELFTEST + 保底行为 + 零调用直通 |

**移植纪律**：Electron 打包只带 `backend/`，后端不能 import 仓库根的
`deai/`——`gates.py` 是**运行时移植副本**，判据唯一权威在
`deai/scripts/validate_pairs.py`。改判据流程：先改权威实现并跑其
`--selftest` → 同步 `gates.py` → 跑 `test_deai_client.py` 对拍。
改禁词表：用户确认后改 `deai/contracts/forbidden_words.txt` → 同步
`gates.FORBIDDEN_WORDS`。

## 4. 挂点：stitch-ghost 呈现平面（三平面分权的模型层补充）

位置：`routes/chapter_generation/adaptive.py` 的 stitch-ghost SSE——
**字数闸之后、ghost_guard 快检之前**。口径与洗层既有不变量一致：快检扫的是
**模型层产物**（deai 的改写先于快检受检，死者开口/泄密疑点不放过抛光引入的
变化）；其后的 P1 确定性洗 / P2 带验收修补只作替换与修补、快检不重扫（P2
同为 LLM 改写且从未被快检重扫——既有行为，非本批引入）。保名闸素材取
`kg.present_names ∪ kg.dead_names`（在场/死者实体名）。

```
生成/字数闸 → deai 抛光（本层）→ ghost_guard 快检 → P1 确定性洗
→ P2 句级修补 → P4 语义 shadow → GHOST_CHUNK/GHOST_DONE
```

- 生效范围：五模式共享同一 `text`，但受 ≤100 字契约窗自然限定
  （stitch/continue 短稿为主）。
- GHOST_DONE 帧新增 `deai` 增量字段 `{applied, reason, warnings}`（向后
  兼容，旧前端忽略）——前端暂不消费，为后续「已抛光」提示/可逆学习预留。
- 遥测：trace `deai_polish`（`logs/trace_adaptive_{chapter_id}.jsonl`，含
  `tokens_in/tokens_out`——**deai 不进 generation_runs 用量聚合**：DashScope
  原生槽非 OpenAI 兼容、不走 call_llm_with_usage，预留期用量以 trace 为准）
  + style event `deai_polish`（`data/style_events.jsonl`，对账进
  `GET style/events/summary`）；`adaptive_stitch_complete` 增
  `deai_applied` 字段。
- 失败语义：整个 deai 块 try/except 包裹，任何异常原样通过、绝不阻塞
  幽灵推送（同洗层纪律）。延迟代价：启用后 GHOST_START 前多一次小模型
  调用（常态 1-3s，**超时 8s** 兜底回退；备注：该 await 不受客户端断连
  取消，作者中途关 SSE 最多多烧一次厘级调用）。

## 5. 设置面板（AppSettingsModal.vue）

「实验：去 AI 味小模型（续写短稿抛光）」折叠分区（默认收起，同向量记忆
专业级先例）：启用开关 + 部署名 + DashScope Key + 生效端点展示 +
**试一试**按钮。试一试走 `POST /api/system/deai/test`（表单实时值探测，
未保存也能测；返回原文/结果对照与保底原因；事实闸保底回退**不算失败**——
它证明闸门在工作）。系统级「连接测试」不涉及 deai（独立小节自测）。

## 5a. 训练对收集（写作台「记改前/记改后」，数据飞轮手动起点）

模型未重训期间的攒数据通路——小模型优化链路开不开都不影响使用：

- **流程**：选中卡片舱生成的原样文本 → 浮窗「记改前」（琥珀色按钮，
  暂存于 `useDeaiPairMark` 模块单例，跨选区/浮窗开合存活、换书作废）
  → 作者亲手改 → 选中改后文本 →「记改后」成对提交，成功 toast 带
  6 秒撤销胶囊（对齐黄金片段先例）。
- **端点**：`POST /api/deai/pairs`（bad/good/book_id）→ `data/deai_pairs.jsonl`
  （本地零上报，行格式与 `deai/scripts/validate_pairs.py` 输入契约逐字
  兼容）；`DELETE /api/deai/pairs/{id}` 撤销。收集侧硬校验仅三条：
  bad/good 非空、bad ≤100 字（契约 C1，超了标记也用不上）、good ≤600 字
  防误选整段——**闸门执法全部留给入库侧**（配错对/改内容的对子会被
  事实闸/像人闸天然拦下，「宁可少入库」纪律不变）。
- **入库**：`deai/scripts/ingest_behavior_pairs.py`（默认读
  `../data/deai_pairs.jsonl`）——(bad,good) 去重 + `check_gates` fact=None
  路径六闸校验（判据零私货，直接 import validate_pairs；facts 溯源层
  不适用故独立成篇）→ 合格对写 `deai/data/sft/behavior_sft.jsonl` +
  按闸分组拒收报告 `deai/logs/behavior_rejected.txt`。**合并进
  clean_sft.jsonl 正式训练集须人工过目后执行。**
- **纪律**（对作者）：bad 必须是生成的原样文本（自己先动过手的别当
  bad）；good 别顺手改内容（补信息/动事实的对子会被闸门拒收，属预期）；
  选段控制在 100 字内。

## 6. v2 升级路径（模型侧）

`deai/docs/roadmap.md` 阶段 11-13：`deai/data/inbox/real_texts.txt` 收集
真实 AI 味片段（含叙事类）→ 事实卡→教师 good→六闸→合并 150-300 对→
百炼重训重部署 → `eval_model.py` 对比 93% 基线 → **更新配置里的部署名**
（宿主侧唯一动作）。叙事覆盖改善后，可评估：句级分片（长稿拆 ≤100 字
逐句抛光，代价是多次调用延迟）、GHOST_DONE `deai` 字段的前端消费
（抛光 chip/可逆学习，对齐 wash 先例）。
