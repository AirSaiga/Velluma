# 使用说明 — 去AI味改写小模型（v1，2026-08-31）

一句话：输入 ≤100 字的中文片段，输出更像人写的版本；事实、数字、日期、专名、引文不动；输出超原长 120% 或事实被改时自动保底。

## 1. 怎么调用（推荐方式）

```bash
export DASHSCOPE_API_KEY=你的Key
python scripts/deai_rewrite.py "待改写文本"
```

或在代码里：`from deai_rewrite import rewrite; rewrite("文本")`，返回 `{output, fallback, reason, warnings}`。**fallback=true 时 output 即原文**（保底策略，契约§6），reason 给出原因。

## 2. 直接调 API 的三个要点（实测踩坑，勿省）

1. 接口用 **DashScope 原生**：`https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation`（调优模型不支持 OpenAI 兼容入口）。
2. model 填**部署后的 deployed_model**：当前为 `qwen3-4b-instruct-2507-78a06917f4ca`（不是训练任务 ft-… ID）。
3. parameters 里必须 **`enable_thinking: false`**（Qwen3 非流式调用要求）。

注意：重新部署或重训后 deployed_model 会变，用部署管理接口查询新值：
`GET https://dashscope.aliyuncs.com/api/v1/deployments`（带 Key 的 Bearer 头）。

## 3. 输入约束与保底

- 输入 >100 字：不改写，原样返回。
- 输出动了数字/专名/引文（事实闸）：回退原文，reason 说明动了什么。
- 输出仅超长或含禁词：仍返回改写但带 warnings，调用方自行决定取舍。

## 4. 回归方法（模型更新后必跑）

```bash
python scripts/eval_model.py --model <deployed_model>
```

- 基线（2026-08-31，v1）：15 条 holdout 六闸通过 **14/15（93%）**，平均输出 35.7 字。
- 报告：`logs/model_eval_report.txt`（失败样例前5条）、`logs/model_outputs.jsonl`（全量明细）。
- 低于基线 2 条以上不要上线，先看失败类型。

## 5. v1 已知短板（人工复核结论）

- "7成"可能被写成"七成"（数字形式改动，会被保底拦下，用户看到原文）；
- "本期视频/三分钟看懂"类开头句式偶尔保留；
- 极个别限定词丢失（如"校区"）；训练样本仅 30 条，长尾风格覆盖有限。

## 6. 以后升级（扩数据重训）五步

加事实卡（`facts_seed.txt`）→ 教师跑批（`make_bad_good_prompt.md`）→ `validate_pairs.py` 六闸入库 → `make_sft_messages.py` 导出 → 百炼重训重部署（batch size 记得 ≤ 数据条数）。DPO 等数据量上百再考虑。

## 7. 成本现状

训练一次性花费约十元级；部署为 Tokens 后付费，不调用不产生费用。
