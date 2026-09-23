# Prompt 治理加固（设计稿）

> 状态：**✅ 已施工 2026-09-24**（F1/F2 全落；F3 校准定档落码——扫描 0.78→0.72 /
> 抢拍 0.80→0.78 / 后文撞车维持 0.80；F3 发现的 embedding 批量上限 20 生产 bug 已修
> （`embedding.py` 透明分批 + 8 项对拍 + 真实 API 冒烟 25 条通过），遗留结构性盲区见
> 报告 §6）。
> 依据：2026-09-19 两条链 prompt 敏感性调研（结论：敏感性高且被反复实证；dock 侧管理较好，
> stitch 侧基座裸奔；效果级评测设施缺位）。

---

## 0. 要修的三个薄弱点

| # | 薄弱点 | 后果 |
|---|---|---|
| F1 | **stitch 基座措辞无快照锁**（`_ADAPTIVE_SYSTEM`/续写五律/视点锁四锁/桥接铁律/五模式 user 模板） | 微调措辞不炸任何测试，行为静默改变，只能人工翻 trace 事后发现 |
| F2 | **prompt 改版无对比设施** | AI 改完 prompt，作者看不到「改了哪些字」、无法验证「变好还是变坏」，反馈与二次修改无依据 |
| F3 | **语义闸阈值未定标**（扫描 0.78 / beat_rush 0.80 均为拍脑袋占位，实测近义对分离度 0.695） | 防线拦不住也放不准，shadow 检永无转正依据 |

## F1：stitch 基座快照锁（哈希锁）

对齐质感契约 SHA256 锁先例（`texture_contracts.py`，`5f87fd9e` 锁）：

- 新测试 `backend/services/prompts/test_stitch_base_snapshot.py`：对下列常量块做 SHA256
  哈希锁定——`_ADAPTIVE_SYSTEM`、`_RULE_NEW_INFO/_RULE_TEXTURE/_RULE_BREAKPOINT/
  _RULE_ENDING/_RULE_ENDING_PARA`、`_SUBJECT_LOCK_TEXTS` 四锁、`bridge_rule` 块、
  五模式 user 模板（stitch/continue/burst/outline/open 各取代表上下文渲染）。
- 语义：**改措辞必须有意更新哈希**——测试失败即提醒「你在动 stitch 基座」，
  更新哈希的动作本身成为一次显式确认。不是不许改，是不许不知不觉地改。
- 测试文件头注释写明哈希更新程序（跑脚本/函数打印新哈希 → 人工确认 diff → 替换）。

## F2：prompt 快照对拍 + 双跑对照

### F2a 快照（纯渲染，零 LLM）

`scripts/prompt_snapshot.py`：对指定书/章，把两条链各模式的最终 prompt
（system+user 全文）编译落成 `logs/prompt_snapshots/{ts}/` 文件——纯渲染不发请求。
复用现有装配函数（dock 编译器 / stitch 五个 builder + stitch_context），只读 DB。

### F2b 对拍工作流

改 prompt 前跑快照存 baseline → AI 改 → 再跑 → `diff`：**每一字的变化可见**
（哪条链、哪个模式、哪块文案被动了）。防呆价值：AI 声称「只改了 X」时，
diff 会揭示它是否顺手动了 Y。

### F2c 双跑对照（`scripts/prompt_replay.py`，仅对快照 diff 有变化的场景烧 token）

- 同模型同参数：旧 prompt（baseline 快照原文）vs 新 prompt 各生成一次；
- **确定性闸门自动判分**：字数闸、禁词表、ghost_guard 快检——纯代码客观信号；
- 并排报告供作者裁决；裁决记录落 `data/prompt_replay_log.jsonl`
  （哪次改版/几场景/几胜几负/裁决）——这就是给 AI 二次修改的反馈证据。

### F2d 全局 prompt 版本号

dock 版本盐机制推广：新模块 `backend/services/prompts/prompt_version.py` 持有
`PROMPT_VERSION`；**动 prompt 措辞的提交必须递增**（纪律写入 AGENTS.md）；版本号进
trace 事件与快照文件——任何历史生成记录可归因到 prompt 版本，跨时间对比才有意义。

## F3：语义阈值定标

- 用 `scripts/calibrate_semantic_threshold.py` 跑真实语料（书内真实节拍×卡片），
  测分离度分布，定档 `semantic_overlap.py` 的 `BEAT_RUSH_SHADOW_THRESHOLD`（0.80 占位）
  与扫描阈值（0.78 占位）；
- **embedding 未配置则如实记录阻塞**：把校准程序修到随时可跑（自测+使用说明写进
  `docs/constraint-governance.md` §11.6），阈值保持原值不动；
- 纪律：本轮只定标，shadow 转 live 仍走原门槛（语料全对+≥20 次真实命中 FP<10%）。

## 非目标

- 不做自动 A/B 平台或评测 UI（脚本是终点，不做产品化）；
- 不动 prompt 文案本身（本轮只加锁与工具，不做调优）；
- 不把任何 shadow 检转 live；
- 不动 dock 编译器既有结构（只在其外加观测与工具）。

## 分期与验收

| 期 | 内容 | 验收 |
|---|---|---|
| M1 | F1 快照锁 + F2a 快照脚本 + F2d 版本号 | 哈希锁测试绿（改一字即红）；快照脚本对当前书章产出全文 prompt 文件；版本号进 trace/快照 |
| M2 | F2b/c 对拍与双跑 | 人造一处措辞改动→diff 可见；双跑报告含闸门判分；裁决落台账 |
| M3 | F3 定标 | 校准脚本可跑；出分离度报告→定档或如实记录阻塞；constraint-governance §11.6 同步 |

全程：后端 `pytest backend --ignore=backend/_deprecated -q` 全绿；新 .py 带 AGPL 头；
测试放被测模块旁；文档同步（AGENTS.md / testing-guide / 本稿状态）。
