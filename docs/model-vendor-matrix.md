# 模型厂商能力矩阵（2026-08-28 调研定稿；2026-09-10 DeepSeek、2026-09-22 MiMo 修订）

> 五家国内主流厂商 API 参数规范的全量调研记录，`backend/services/llm/vendor_profiles.py`（采样整形/模型规则）与 `reasoning_adapter.py`（思考方言）的唯一事实源。初版调研日期 2026-08-28，2026-09-10 随 DeepSeek-V4.1 Flash 发布修订 DeepSeek 节，2026-09-22 随 MiMo-V2.6 发布修订 MiMo 节；全部结论有官方文档出处；厂商协议随代际变化，**改这里必须同步改代码并跑 `test_vendor_profiles.py`**。
>
> **范围外补充（2026-09-16）**：本地端点（Ollama/vLLM/LM Studio，厂商目录 `local` 条目）不在五厂商矩阵内——思考关闭方言为 OpenAI 系顶层 `reasoning_effort:"none"`（Ollama `/v1` 实测修复，`90d0c66`，实现在 `reasoning_adapter.py`；api_key 须占位值否则判未配置回退）；槽位路由见 `docs/reports/model-slot-coverage-report.md`。
>
> 调研背景：kimi-k2.6 切换事故（采样参数 400 撞墙自适应）暴露「每换一次模型都可能踩一遍协议坑」。本矩阵把坑前置到一份档案里。

## 零、跨厂商共性（先读这个）

1. **思考方言已收敛**：DeepSeek V4 / MiMo / Kimi K2.x / GLM 4.5+ 统一走 `thinking: {"type": "enabled"|"disabled"}`（OpenAI SDK 经 `extra_body` 传）；**Qwen 是独苗** `enable_thinking`（布尔）+ `thinking_budget`（整数）。OpenAI/OpenRouter 各自是 `reasoning_effort` / 嵌套 `reasoning`。
2. **默认思考开的厂商占多数**：DeepSeek V4（默认 effort=high）、MiMo 全系（V2.5/V2.6）、Kimi K 系、GLM 4.7/5.x、Qwen 3.5+ 商业版全部默认开——「不表态=开」是常态，**显式关闭纪律（REASONING_DISABLED）是生死线**。仅 Qwen 上代商业版（qwen-plus/flash/turbo/qwen3-max）默认关。
3. **思考模式吃采样参数**：DeepSeek（文档明言不支持）、MiMo（静默锁 1.0/0.95）、Kimi K 系（schema 不含，传了 400）——思考开启时采样参数要么无效要么报错，一律不发。
4. **`max_tokens` 处于废弃进程中**（Kimi 已弃用→`max_completion_tokens`、Qwen 即将废弃），但五家 OpenAI 兼容层目前均容忍 `max_tokens`；维持发 `max_tokens`，只做记录。
5. **上下文缓存全部隐式自动**（DeepSeek 硬盘缓存 / Kimi >256 token / Qwen >1024 token / GLM 前缀复用 / MiMo KVCache）——B6 稳定前缀纪律直接受益，无需客户端配置。

## 一、DeepSeek（api.deepseek.com）（2026-09-10 修订）

| 项 | 值 |
|---|---|
| base_url | `https://api.deepseek.com`（现行文档不带 `/v1`；旧 `/v1` 写法容忍） |
| 模型 | **`deepseek-flash`（=V4.1 Flash，2026-09-10 发布，现行规范 id）**：原生多模态视觉；1M ctx/384K out；并发 2500。**`deepseek-v4-pro` 有序下线中：2026-09-14 12:00 起、V4.1 Pro 上线前，请求全部路由到 V4.1 Flash 并按 Flash 单价计费**（并发 500）。旧名 `deepseek-v4-flash`/`deepseek-v4-flash-vision-exp` 暂时路由到 V4.1 Flash；`deepseek-chat`/`deepseek-reasoner` 已于 2026-07-24 弃用 |
| 思考 | `thinking: {"type": enabled/disabled}`（同一模型双模，默认**开**）；`reasoning_effort`: low/high/**max**（默认 high；映射 minimal→low / medium→high / xhigh→high / ultra→max）。另认 Anthropic 格式 `reasoning.effort`（none=关）与 Responses API `output_config.effort`——本应用走 OpenAI 兼容 `extra_body`，维持 thinking 格式 |
| 采样 | temperature [0,2]（创意写作官方推荐 1.5）；**思考模式：temperature 与双 penalty 静默无效（设了不报错也不生效），top_p 生效但下限 0.95（低于自动抬升）**；**非思考模式：top_p 恒为 1.0、传入值被忽略** |
| penalty | frequency/presence_penalty **已 DEPRECATED**（传了不生效）——一律不发 |
| response_format | text / json_object（提示词须含 "json" 字样） |
| 定价（元/M，闲/峰=1:2；高峰=工作日 9-12、14-18 点；flash 价 2026-09-10 调整） | flash：命中 0.02/0.04，未命中 1/2，输出 4/8；pro（下线前现价）：命中 0.15/0.30，未命中 4.5/9.0，输出 13.5/27 |

## 二、智谱 GLM（open.bigmodel.cn）

| 项 | 值 |
|---|---|
| base_url | `https://open.bigmodel.cn/api/paas/v4` |
| 模型 | `glm-5.3`（1M，旗舰，2026-08-19）、`glm-5.2`（1M，推荐，MIT 开源）、`glm-5.1`（200K）、`glm-5`/`glm-5-turbo`（200K）、`glm-4.7`/`glm-4.7-flashx`（200K）、**`glm-4.7-flash`/`glm-4.5-flash` 免费**。5 系无免费文本档（`glm-5.3-flash` 是多模态付费档） |
| 思考 | `thinking: {"type": enabled/disabled, "clear_thinking": bool}`；`reasoning_effort` **仅 5.2+** 认 low/high/max（5.2 另收 medium/xhigh/minimal/none 带映射）。4.7/5.x 默认**开**。**`glm-5.3`/`glm-5.3-flash` 强制思考：传 disabled 直接报错**，正确姿势是不发 thinking 参数 |
| 采样 | temperature **[0, 1.0]**（5.x 默认 1.0；比别家严，超限需钳制）/ top_p [0.01, 1.0]（默认 0.95）；`do_sample=false` 时两者被忽略 |
| penalty | 现行 API 参考未定义双 penalty——不发 |
| response_format | text / json_object |
| 定价（docs.z.ai 美元价/M） | 5.3/5.2/5.1：$1.40/$0.26 命中/$4.40；5：$1.00/$0.20/$3.20；4.7/4.6/4.5：$0.60/$0.11/$2.20；5.3-flash：$0.15/$0.03/$0.50（9-09 前 5 折）。人民币价官方页 JS 渲染抓不到（5.2 三方转载约 8/2/28 元）。缓存命中≈标准价 50% |

## 三、Kimi / 月之暗面（api.moonshot.cn）

| 项 | 值 |
|---|---|
| base_url | `https://api.moonshot.cn/v1`（文档站已迁 platform.kimi.com，**API 域名未变**；国际站 api.moonshot.ai） |
| 模型 | `kimi-k3`（1M，旗舰，恒思考）、`kimi-k2.6`（256K，通用，思考默认开**可关**）、`kimi-k2.7-code`（256K，恒思考）、`kimi-k2.5`（**2026-08-31 下线**）、moonshot-v1 系（**2026-08-31 下线**） |
| 思考 | k2.6/k2.5：`thinking: {"type": enabled/disabled, "keep": null/"all"}`；**k3 无 thinking 参数**，只有顶层 `reasoning_effort` low/high/**max**（默认 max，不可关思考）；k2.7-code 只认 enabled |
| 采样 | **K 系 schema 根本不含 temperature/top_p/n/双 penalty——传任何值 400**（报错 `invalid X: only Y is allowed`）。k2.6 思考态温度恒 1.0、非思考态恒 0.6。moonshot-v1 老系可调（temp [0,1]）但即将下线 |
| penalty | 同上，K 系不发 |
| response_format | text / json_object / **json_schema**（strict 默认 true） |
| 缓存 | 全自动隐式（>256 token 入缓存）；命中率档：k3 命中价=未命中 10%，k2.6≈17% |
| 定价（元/M） | k3：2/20/**100**（贵）；k2.6：1.1/6.5/27；k2.7-code：1.3/6.5/27。Batch 6 折（k3 不支持） |

## 四、Qwen / 阿里百炼（dashscope.aliyuncs.com）

| 项 | 值 |
|---|---|
| base_url | `https://dashscope.aliyuncs.com/compatible-mode/v1`（有效）；新版 `{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`。**Key 按地域绑定，跨地域 401** |
| 模型 | `qwen3.8-max`（1M，旗舰，2.4T MoE）、`qwen3.8-flash`（1M，2026-08-26 上架）、`qwen3.7-plus`（1M，主力）、`qwen3.7-flash`/`qwen3.7-max`、经典 `qwen-plus`/`qwen-flash`/`qwen-turbo`（默认不思考）。无 "Qwen4" |
| 思考 | `enable_thinking`（布尔，extra_body）+ `thinking_budget`（1-32768）；**qwen3.8-max 另有 `reasoning_effort` xhigh/medium/low，与 thinking_budget 互斥**。3.5+ 商业版默认**开**，经典版默认关。仅思考模型（qwq 系、qwen3.7-max 部分快照）不可关 |
| 采样 | temperature [0,2)（不建议 0）/ top_p (0,1]；无锁定（3.8-max 思考态低于 0.6 会钳到 0.6）；presence_penalty [-2,2] 支持、frequency_penalty 已从参数表消失（错误码文档仍认 [-2,2]） |
| 流式 | **开源模型思考模式仅支持流式**（非流式报 `parameter.enable_thinking only support stream call`）；商业版思考模型支持非流式。非流式超 300s 切断 |
| response_format | json_object（提示词须含 "JSON" 字样）/ json_schema（仅 3.7-Plus/3.7-Flash/3.7-Max/3.8-Flash/3.8-Max）。思考模式+JSON 可能不规范 |
| 缓存 | 隐式自动（≥1024 token 前缀），命中=input 单价 20%（3.8 系例外未公布） |
| 定价（元/M，北京） | 3.8-max：12/36；3.7-plus：2/8（思考 8/8，256K-1M 阶梯翻倍）；3.8-flash：0.8/2.7；3.7-flash：0.2-1.2/0.8-4.8；qwen-flash 最便宜 0.15/1.5。免费形式=每模型 100 万 token 90 天赠额 |

## 五、小米 MiMo（api.xiaomimimo.com）（2026-09-22 修订）

| 项 | 值 |
|---|---|
| base_url | `https://api.xiaomimimo.com/v1`（文档站 mimo.mi.com，控制台 platform.xiaomimimo.com） |
| 模型 | 2026-09-21 V2.6 系发布：`mimo-v2.6-pro`（1M ctx/128K out，全模态，开源旗舰）、`mimo-v2.6-flash`（1M/128K，官方称全面超 v2.5-pro）、`mimo-v2.6-pro-ultraspeed`（推理提速至 20×，限流需联系商务，无批量 API）。**v2.5/v2.5-pro 将于 2026-10-21 10:00 下线（与 V2.6 同价，直接换名迁移）**；v2 系已 2026-06-30 下线；V3 未发布 |
| 思考 | `thinking: {"type": enabled/disabled}`（唯一方言，实测+官方双证）；**默认开**；无 effort/budget 字段（思考长度只能靠 max_completion_tokens 总闸） |
| 采样 | temperature [0, 1.5] 默认 1.0 / top_p [0.01, 1.0] 默认 0.95 / 双 penalty [-2,2]；**思考模式下温度/top_p 静默锁 1.0/0.95** |
| token 参数 | 官方表用 `max_completion_tokens`（pro 默认 131072，含思考 token）；`max_tokens` 被兼容层容忍（实测在用） |
| response_format | text / json_object |
| 定价（元/M） | V2.6 与 V2.5 持价：pro 档（v2.6-pro/v2.5-pro）命中 0.025/未命中 3.0/输出 6.0；flash 档（v2.6-flash/v2.5）0.02/1.0/2.0；v2.6-pro-ultraspeed 0.25/30/60（10 倍价买速度）。V2.6 pro/flash 另支持批量 API 半价（ultraspeed 与 V2.5 系不支持）。KVCache 服务端自动，官方称平均命中率 93% |

## 六、对代码的三条直接指令

1. **采样整形前置**（`vendor_profiles.shape_sampling_params`）：Kimi K 系全删采样参数；DeepSeek 删双 penalty（全模式）+ 思考态删 temperature + 非思考态删 top_p（恒 1.0 忽略；思考态 top_p 生效、下限 0.95 由服务端抬升，原样透传）；MiMo 删采样（思考态）；GLM 温度钳 ≤1.0 + 不发双 penalty；Qwen 温度 <2 / top_p ≤1 钳制。`client.py` 的 400 自适应缓存降级为最后防线（新厂商/档案过期兜底）。
2. **思考方言补全**（`reasoning_adapter`）：新增 GLM/KIMI 分支；强制思考模型（glm-5.3\*、kimi-k3、kimi-k2.7-code）收到「关闭」请求时**不发参数**（发 disabled 会 400/无效）；effort 枚举归一（medium→high 映射到只认 low/high/max 的厂商）。
3. **前端厂商预设**（`/system/model-catalog`）：选厂商自动填 base_url + 模型候选清单 + 能力提示（采样锁定/强制思考/弃用警告），模型名保持可自由输入。

## 来源

- DeepSeek：[api-docs.deepseek.com](https://api-docs.deepseek.com/quick_start/pricing)（pricing / thinking_mode / create-chat-completion / updates；2026-09-10 修订依据 [更新日志](https://api-docs.deepseek.com/zh-cn/updates/) V4.1 Flash 发布条 + thinking_mode 指南）
- GLM：[docs.bigmodel.cn](https://docs.bigmodel.cn/cn/guide/start/concept-param)（concept-param / 对话补全 API 参考 / thinking-mode / migrate-to-glm-new）+ [docs.z.ai 定价](https://docs.z.ai/guides/overview/pricing)
- Kimi：[platform.kimi.com](https://platform.kimi.com/docs/api/chat)（chat / models-overview / use-thinking-models / pricing/chat-k26）
- Qwen：[help.aliyun.com](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)（OpenAI 兼容 / deep-thinking / context-cache / model-pricing）
- MiMo：[mimo.mi.com](https://mimo.mi.com/docs/zh-CN/api/chat/openai-api)（openai-api / deep-thinking / pay-as-you-go / model）
