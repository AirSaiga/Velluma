# 项目路线图

| 阶段 | 内容 | 产出 | 检查脚本 | 状态 |
|---|---|---|---|---|
| 1 | 目录结构 + 任务契约 + 六闸校验器 | docs/contract.md（权威契约）、contracts/*、scripts/validate_pairs.py（--selftest 自测）、README、路线图、待确认清单 | scripts/check_stage1.py + validate_pairs.py --selftest | ✅ 2026-08-31 |
| 2 | 事实种子与教师Prompt模板 | data/facts_seed.txt（30张事实卡）+ scripts/make_bad_good_prompt.md（每3条打包） | scripts/check_stage2.py | ✅ 2026-08-31 |
| 3 | 教师跑批 + 六闸入库 + SFT数据定稿 | data/raw_teacher.jsonl（10批×3对，TEACHER-KIMI 子智能体生成，N03 曾编造事实重跑过）→ data/sft/clean_sft.jsonl（30条全过闸） | scripts/validate_pairs.py（退出码0） | ✅ 2026-08-31（v1 收官口径，见 README 当前进度） |
| 4 | facts溯源复检 + 合格对定稿 | validate_pairs.py 升级（bad∪facts 溯源、pairs 输出、报告按原因分组）；clean_sft.jsonl 30条 {"bad","good"} | validate_pairs.py --selftest + 全量跑 | ✅ 2026-08-31 |
| 5 | 导出训练文件与评测提示 | data/sft/train30.jsonl（messages，user=原文：{bad}\n修改后：）、data/eval/eval15.jsonl（仅system+user）、data/facts_eval.jsonl（新15事实×5种新模板） | scripts/check_jsonl.py | ✅ 2026-08-31 |
| 6 | 上百炼SFT（人工操作） | docs/bailian_clickpath.md（点选路径+报错对照，终点=计费确认页，不点提交）；上传 train30.jsonl；评测集可传 data/eval/eval15_bailian.xlsx（方案B，按官方模板生成） | 上传前复跑 check_jsonl.py | ✅ 2026-08-31（阶段7 训练成功即已执行） |
| 7 | SFT训练（百炼控制台人工操作） | 任务 ft-202608311805-96bd；模型 qwen3-4b-instruct-2507_1c29d112（Qwen3-4B + LoRA，创建成功；batch size 128→8 为唯一偏离默认的参数，平台强制） | — | ✅ 2026-08-31 |
| 8 | 评测 | 六闸评测完成：**14/15 通过（93%）**，平均输出 35.7 字，唯一失败 F15（"7成"→"七成"，数字形式被改，契约C3判废）；人工复核项：F08 丢了"校区"二字、F04/F09/F12 残留AI开头句式。调用链：deployed_model `qwen3-4b-instruct-2507-78a06917f4ca` + DashScope原生接口 + enable_thinking=false | eval_model.py 报告含失败样例前5条 | ✅ 2026-08-31 |
| 9 | （视需要）DPO | data/dpo/train.jsonl、可能的格式转换脚本 | validate_pairs.py + 转换后校验 | ⬜ |
| 10 | 部署与回归收尾 | scripts/deai_rewrite.py（带契约§6保底的调用封装，已实测：数字被动自动回退原文）+ docs/usage.md（调用要点/回归方法/已知短板/升级路径） | eval_model.py 回归基线 93% | ✅ 2026-08-31 v1收官 |
| 11 | v2扩量：真实素材收集 | data/inbox/real_texts.txt（人工收集真实AI味片段，目标50+段，含叙事类） | 收集后我跑去重/分类检查 | ⏸ 搁置（项目归档，重启时从这开始） |
| 12 | v2扩量：数据加工与重训 | 真实片段→事实卡→教师good→六闸→与合成数据合并（目标150-300对）→导出→百炼重训重部署 | validate_pairs.py + check_jsonl.py + eval_model.py 对比93%基线（另留新holdout） | ⏸ 搁置 |
| 13 | （数据上百后可选）DPO | data/dpo/train.jsonl | validate_pairs.py + 转换后校验 | ⏸ 搁置 |

**项目于 2026-08-31 归档（v1 交付），归档报告见 [archive.md](archive.md)。** 阶段 11-13 为 v2 预留，从 data/inbox/ 收集箱重启。

## 铁律

1. 每阶段：先跑检查脚本且退出码为 0，才交付"下一步人工动作"清单。
2. 未确认的平台规则不进入契约/脚本，登记 docs/open_questions.md。
3. 评测集事实与模板双隔离，靠 meta.source_id / meta.template_id 校验。
4. 每阶段只做当前阶段，不提前训练。
