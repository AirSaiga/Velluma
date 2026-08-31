# 项目归档报告 — deai 中文去AI味小模型 v1

- 归档日期：2026-08-31（当日完成全部 10 个阶段）
- 归档时体检：check_stage1 ✅、check_stage2 21/21 ✅、六闸 selftest 11/11 ✅、check_jsonl 全合规 ✅

## 1. 目标与结果

目标：训练一个只处理 ≤100 字中文片段的"去AI味"改写模型（只改语言质感，不动事实/数字/日期/专名/引文），部署于阿里云百炼。

结果：**达成**。Qwen3-4B + LoRA（SFT），15 条全新事实独立评测六闸通过 14 条（93%），平均输出 35.7 字；带契约保底的生产封装实测可用。

## 2. 时间线（10 阶段）

| 阶段 | 内容 | 备注 |
|---|---|---|
| 1 | 契约（六闸）+ validate_pairs 校验器 | 六闸=数字/专名/长度/套话/新增事实/像人 |
| 2 | 30 张事实卡 + 教师 Prompt 模板 | 产品/公告/观点各10 |
| 3 | TEACHER-KIMI 子智能体跑批 30 对 | N03 教师编造"错过再等一年"被人工审读抓出重跑 |
| 4 | facts 溯源复检 | clean_sft 定稿为 {"bad","good"} |
| 5 | train30.jsonl / eval15 / check_jsonl | user 格式「原文：…\n修改后：」 |
| 6 | 百炼点选指引 | 官方查证：评测集=xlsx、SFT格式、文件限制 |
| 7 | SFT 训练 + 部署 | batch size 128→8（平台强制，唯一改默认参数）；最终选 Qwen3-4B |
| 8 | 独立评测 93% | 排障三连：原生接口 / deployed_model / enable_thinking |
| 9 | DPO | 评估后跳过（30 对不足，官方建议上百） |
| 10 | 收尾 | deai_rewrite.py 保底封装 + usage.md |

## 3. 最终资产

- **模型**：deployed_model `qwen3-4b-instruct-2507-78a06917f4ca`（训练任务 ft-202608311805-96bd，Tokens 后付费部署，不调用不扣费）。重训/重部署后此 ID 会变，用 `GET https://dashscope.aliyuncs.com/api/v1/deployments` 查询。
- **脚本**（scripts/）：validate_pairs.py、check_stage1/2.py、make_sft_messages.py、make_eval_prompts.py、make_eval_xlsx.py、check_jsonl.py、eval_model.py、deai_rewrite.py、prompts_to_send.txt、make_bad_good_prompt.md
- **数据**（data/）：三套事实卡 30+15+15（train/eval/holdout 全隔离）、raw_teacher.jsonl 30 对、clean_sft.jsonl、train30.jsonl、eval15/val15/holdout15、eval15_bailian.xlsx、inbox/ 收集箱（v2 用）
- **文档**（docs/ + contracts/）：contract.md（权威契约 v0.2）、data_format.md、roadmap.md、open_questions.md（Q4~Q7 已确认）、bailian_clickpath.md、usage.md

## 4. 平台规则实测记录（防遗忘）

1. 调优模型只支持 DashScope 原生接口，OpenAI 兼容入口报 model_not_found；
2. 调用名 = 部署后的 deployed_model，不是训练任务 ft-ID；
3. Qwen3 非流式调用必须 enable_thinking=false；
4. 平台"评测集"是 xlsx（Prompt+Completion 成对），不能选为训练任务的验证集；
5. 训练集条数必须大于 batch size（30 条 → batch 8）；
6. 官方推荐 SFT 至少上千条（v1 的 30 条属小样本验证）。

## 5. 质量与已知短板

- 评测：14/15 六闸通过；失败项 F15 把"7成"写成"七成"（数字形式，契约 C3 判废，生产中被保底拦截回退原文）。
- 人工复核项：个别限定词丢失（"校区"）、AI 开头句式偶有残留、语义级漂移（"盖过动静"→"盖过一切"）属自动闸盲区。
- 超纲：叙事/小说文本未训练（用户试过一段，表现尚可但不保证）。

## 6. 恢复指南（v2 扩量）

收集箱 data/inbox/real_texts.txt 已就绪 → 真实 AI 味片段 50+ 段（含叙事类）→ 阶段 12 管线（事实卡→教师 good→六闸→合并 150-300 对→导出→重训重部署）→ eval_model.py 对比 93% 基线 + 新 holdout。详见 roadmap.md 阶段 11-13 与 usage.md §6。
