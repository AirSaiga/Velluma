# deai — 中文去AI味小模型（≤100字片段）

> **项目状态：v1 完成并归档（2026-08-31）**。归档报告：[docs/archive.md](docs/archive.md)。
> 日常使用：[docs/usage.md](docs/usage.md)；v2 扩量入口：[data/inbox/README.md](data/inbox/README.md)。
>
> **宿主接入（2026-08-31 迁入 Velluma，`D:\deai` 原件保留未动）**：本目录是 Velluma
> 的子项目——卡片舱（幽灵草稿）上屏前的「小模型抛光」由本模型承担。集成设计唯一
> 权威：`../docs/deai-integration.md`（配置节 `model_config.json` 的 `deai`、后端
> `backend/services/deai/`、契约§6 运行时保底已移植）；本目录脚本与契约继续独立
> 自检（检查命令见下），跑脚本请在本目录内执行（路径以本目录为根）。

在阿里云百炼上做 SFT（必要时 DPO），训练一个只处理 100 字以内中文片段的"去AI味"改写模型：只改语言质感，不改事实、数字、日期、专名、引文，不新增观点。

## 契约（先读，全项目最高约束）

- [docs/contract.md](docs/contract.md) — **权威契约 v0.2**：任务定义、允许/禁止、禁词表、六条入库闸门、失败处理
- [contracts/task_contract.md](contracts/task_contract.md) — v0.1 前身（历史保留）
- [contracts/data_format.md](contracts/data_format.md) — SFT / DPO / 评测集 JSONL 格式
- [contracts/forbidden_words.txt](contracts/forbidden_words.txt) — chosen/good 违禁词表（机器可读，10 词）

## 目录

```
contracts/   任务契约
scripts/     各阶段检查/校验脚本
data/sft/    SFT 训练数据（JSONL）
data/dpo/    DPO 训练数据（JSONL）
data/eval/   评测集（与训练集不同事实、不同模板）
docs/        路线图、待确认清单、（后续）百炼操作指引
logs/        检查脚本报告
```

## 当前进度

- [x] 阶段1：目录结构 + 任务契约 + 六闸校验器（2026-08-31）
- [x] 阶段2：事实种子 30 卡 + 教师模型 Prompt 模板（2026-08-31）
- [x] 阶段3：教师跑批（TEACHER-KIMI 10 批）→ 30 对全部过六闸（2026-08-31）
- [x] 阶段4：facts 溯源复检 → clean_sft.jsonl 定稿为 30 条 {"bad","good"}（2026-08-31）
- [x] 阶段5：train30.jsonl（messages 格式）+ eval15.jsonl（评测提示，15 条新事实）+ check_jsonl.py（2026-08-31）
- [x] 阶段6：docs/bailian_clickpath.md 百炼点选指引（终点=计费确认页）（2026-08-31）
- [x] 阶段7：百炼SFT训练成功，模型 qwen3-4b-instruct-2507_1c29d112（2026-08-31）
- [x] 阶段8：独立评测 14/15 六闸通过（93%），唯一失败为数字形式改动（2026-08-31）
- [x] 阶段9：DPO 评估后跳过（数据量不足，官方建议上百条；升级时再考虑）
- [x] 阶段10：收尾完成——deai_rewrite.py 调用封装（保底实测生效）+ docs/usage.md（2026-08-31，**项目收官，模型可用**）

日常使用与回归见 [docs/usage.md](docs/usage.md)。

## 检查

```
python scripts/check_stage1.py            # 目录与契约完整性
python scripts/check_stage2.py            # 事实卡与模板合规
python scripts/validate_pairs.py --selftest   # 六闸+facts溯源自测
python scripts/validate_pairs.py          # 校验 raw_teacher.jsonl -> clean_sft.jsonl
python scripts/check_jsonl.py             # train30/eval15 结构与统计
```
