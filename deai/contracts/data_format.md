# 数据格式契约

## 1. 通用规则

- 文件编码 UTF-8（无 BOM），扩展名 `.jsonl`，每行一个独立 JSON 对象。
- 禁止空行、行内换行、行尾多余空白；校验脚本直接拒绝。
- 除下述规定字段外，内部文件允许可选 `meta` 对象用于溯源；**上传百炼的导出文件一律由导出脚本剥离 `meta`**（阶段4实现，平台对未知字段的容忍度见 docs/open_questions.md Q5）。

## 2. SFT 格式

> 注（阶段4）：`clean_sft.jsonl` 为合格 bad/good 对（每行 `{"bad","good"}`）；本节 messages 格式用于**上传文件**，由 `validate_pairs.py --format sft` 在导出阶段生成。

每行结构：

```json
{"messages":[{"role":"system","content":"..."},{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}
```

规则：

- `messages` 是数组，长度必须为 2（user, assistant）或 3（system 在首位）。单轮改写任务，暂不允许多轮；如需多轮先改本契约。
- `role` ∈ {system, user, assistant}；`content` 均为非空字符串。
- `user.content` = 待改写原文，必须满足 C1（≤100 字）。
- `assistant.content` = 改写结果，必须满足 C2（长度）、C3（保真）、C4（违禁词）。

正例（可直接用于自测）：

```json
{"messages":[{"role":"system","content":"你是中文润色助手，把用户给的片段改得更像人写的。只改语言质感，不改事实、数字、日期、专名、引文，不新增观点，输出不超过原长的120%。"},{"role":"user","content":"综上所述，本次改版显著提升了页面加载速度，为后续增长夯实了基础。"},{"role":"assistant","content":"这轮改版后，页面加载快了不少，后面的增长也有底了。"}]}

反例（校验必须拒绝）：

```json
{"messages":[{"role":"user","content":"综上所述，本次改版显著提升了页面加载速度，为后续增长夯实了基础。"},{"role":"assistant","content":"综上所述，本次改版赋能了页面加载速度的全面闭环，为后续全链路增长夯实了基础。"}]}
```
拒绝原因：assistant 含违禁词（综上所述/赋能/闭环/全链路/夯实了…），且长度超出 120%。

## 3. DPO 格式

每行结构：

```json
{"prompt":"...","chosen":"...","rejected":"..."}
```

规则：

- 三字段均为非空字符串；`prompt` 为单条待改写原文（≤100 字），**不使用 messages 数组形式**。若百炼 DPO 要求 messages 形式，由阶段7的转换脚本处理（见 docs/open_questions.md Q4），本内部契约不变。
- `chosen` 必须满足 C2/C3/C4；`rejected` 是坏样本（AI味更重、含违禁词、超长或保真破坏均可），不受 C4 限制。
- `chosen` 与 `rejected` 必须是对**同一 prompt** 的回答。

正例（可直接用于自测）：

```json
{"prompt":"三个城市的试点将在今年6月启动。","chosen":"试点定在三个城市，今年6月启动。","rejected":"综上所述，三大城市的试点将于今年6月全面启动，为规模化落地夯实基础。"}
```

## 4. 评测集格式

> 注（阶段5）：`data/eval/eval15.jsonl` 是**评测提示文件**，每行仅 `system+user`（无 assistant、无 meta），由 `make_eval_prompts.py` 从 `data/facts_eval.jsonl` 生成；溯源（id/cat/fact/template）保存在 facts_eval.jsonl，与训练 30 卡事实零重复、模板零交集（C6）。带参考答案的完整评测集在评测阶段构造。
>
> 注（阶段6）：`data/eval/eval15_bailian.xlsx` 是**百炼平台格式评测集**（官方模板：Sheet1，Prompt/Completion 两列），由 `make_eval_xlsx.py` 生成；Prompt=「原文：{bad}\n修改后：」，Completion=参考答案 good（已过六闸+facts 溯源）。官方模板副本存于 data/eval/bailian_eval_template.xlsx。

与 SFT 同构（messages），但**必填**溯源字段：

```json
{"messages":[{"role":"user","content":"..."},{"role":"assistant","content":"..."}],"meta":{"source_id":"...","template_id":"..."}}
```

- `source_id`：事实素材编号（同一段事实素材在训练/评测两侧都出现即违反 C6）。
- `template_id`：改写模板/句式编号（同模板跨集合即违反 C6）。
- 隔离校验逻辑（阶段2实现）：训练集与评测集的 source_id 集合、template_id 集合交集必须为空。训练集因此也需要可选 `meta` 溯源字段，构造数据时（阶段3）必须填写。
