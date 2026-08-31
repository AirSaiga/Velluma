# 待人工确认清单

原则：以下任何一项未经确认，不写入契约、不进入脚本假设。确认后请把结论回填到本文件对应条目（标注确认日期与来源），必要时同步修改契约并升版本号。

## 项目口径类（用户确认即可）

- **Q1 字数计法**：契约暂定"Python len()，含标点空格，不含换行"（task_contract.md §3）。若你希望"只数汉字"或"不含标点"，请说明，阶段2脚本按你确认的口径实现。
- **Q2 极短输入的 120% 上限**：例如输入 5 字，输出上限仅 6 字，几乎无法改写。是否设置下限（如 max(floor(1.2×原长), 原长+3)）？暂按严格 floor 执行。
- **Q3 中文数字**：契约 R4 默认"三个→3个"算违规。是否同意？

## 百炼平台类（需查百炼文档或控制台试传确认）

- **Q4 DPO 的 prompt 字段**：百炼 DPO 数据里 `prompt` 是否要求为 messages 数组（如 `[{"role":"user",...}]`）而非纯字符串？内部契约已定为纯字符串，若平台要数组，阶段7加转换脚本。
- **Q5 未知字段容忍度**：上传文件含 `meta` 等额外字段是否报错？决定导出脚本是否必须剥离。
- **Q6 文件限制**：单文件大小/条数上限、是否支持 .jsonl 之外的打包格式。
- **Q7 SFT 的 system 消息**：是否支持、是否必填、对最终效果的建议；以及是否强制要求"每行 messages 结构一致"。

## 确认记录

- 2026-08-31 / Q7 / **已确认**：百炼 SFT 支持 system 消息（可选、置于最前），user/assistant 交替、最后一条 assistant 为期望输出；train30.jsonl 的 ChatML 结构吻合。/ 来源：https://help.aliyun.com/zh/model-studio/text-generation-tuning-data-upload-rules
- 2026-08-31 / Q5 / **已确认**：官方仅明确支持少数可选字段（如 loss_weight），明确禁止 OpenAI 的 name/weight；稳妥做法是不加未定义字段。train30.jsonl 每行仅 messages，安全。/ 来源同上
- 2026-08-31 / Q6 / **已确认**：SFT 文本训练集单文件 ≤200MB、默认最多 10 个文件；文件名（不含后缀）仅允许 a-z/A-Z/0-9/_/-；官方推荐 SFT 数据量"至少上千条"（本次 30 条属小样本验证）。/ 来源同上
- 2026-08-31 / 评测集格式（影响第3步上传） / **已确认**：百炼评测集为 xlsx 模板格式、每条为 Prompt+Completion 成对、仅支持文本生成场景；eval15.jsonl（JSONL、纯提示）不能直接当平台评测集 → 方案A 用"自动划分10%"验证，方案B 按官方模板生成带参考答案的 xlsx。/ 来源：https://help.aliyun.com/zh/model-studio/training-set-and-evaluation-set
- 2026-08-31 / 验证集 vs 评测集 / **已确认**：训练任务的验证集支持"自动切分（从训练集抽10%）"或"选择数据集（独立上传的验证数据集，下拉仅列训练集类型）"；评测集（xlsx）用于训练完成后的"模型评测"功能，不能选为验证集。已产出独立验证集 data/eval/val15.jsonl（E01–E15 messages 格式）。/ 来源：https://help.aliyun.com/zh/model-studio/model-training-on-console
- 2026-08-31 / 调优模型调用方式 / **已确认（实测+官方文档）**：百炼调优后的自定义模型 ① 必须先部署到计算资源才可调用（官方最佳实践原文），② 只支持 DashScope 原生方式调用，不支持 OpenAI 兼容入口（compatible-mode 会报 model_not_found）。eval_model.py 已默认改为 DashScope 原生接口。另：调优模型仅能由其所在业务空间的 API Key 调用。/ 来源：https://help.aliyun.com/zh/model-studio/model-training-best-practices 、https://help.aliyun.com/zh/model-studio/my-model-center 、https://help.aliyun.com/zh/model-studio/model-calling-in-sub-workspace
- Q4（DPO 的 prompt 字段格式）**仍待确认**，到 DPO 阶段（路线图阶段9）再查证。
