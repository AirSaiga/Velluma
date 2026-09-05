# Prompts 模块索引

本目录包含所有 LLM 提示词（Prompt）模板构建函数。改后即时生效，无需重建。

> 2026-09-05 重写：旧版索引大面积失准（列出的 planner/scene_intent/pov/inspiration/
> draft_prompts_thinking 等文件已不存在于在役目录）。V3 生成链 prompt 全家
> （chapter_prompts / draft_prompts 全家 / clarification_prompts / review_prompts 死函数）
> 已归档至 `backend/_deprecated/services/prompts/`（global_sys_prompt 死线退役，
> 见该目录 README 2026-09-05 节）。

## 在役文件

| 文件 | 职责 | 主要消费方 |
|------|------|-----------|
| `adaptive_prompts.py` | ★ NLE-ADF 3.0 自适应流全部 prompt（五模式/dock/感知/沉淀等） | `routes/chapter_generation/adaptive.py` + `services/adaptive/` |
| `adf_prompts.py` | ADF（V3.2）引擎 prompt（前端无 UI 入口，引擎本体保留） | `services/workflows/adf/` |
| `nle_prompts.py` | NLE 引擎配套模板 | adaptive 相关工作流 |
| `refinery_prompts.py` | Refinery（V4.1）独立精修 | `services/refinery/` |
| `review_prompts.py` | 仅剩 `build_refine_agent_prompt`（精修重写 prompt；2026-09-05 精简） | `services/workflows/refining.py`（章节优化路由） |
| `review_prompts_utils.py` | 边界基线渲染/审查结果解析工具 | `review_prompts.py` |
| `audit_prompts.py` | LLM 级审计（质量报告双层） | `services/validation/` + quality-report 路由 |
| `critique_prompts.py` | 毒舌编辑审阅 | `routes/critique.py` |
| `format_prompts.py` | 全文格式整理 | 编辑器「全文格式整理」 |
| `style_extract_prompts.py` | 文风样本提炼 | `services/style/extractor.py` |
| `character_extraction.py` | 角色抽取 | 沉淀/提取链 |
| `content_extraction.py` | 内容抽取 | 沉淀/提取链 |
| `world_event_prompts.py` | 世界事件解析（速记/事件侦察） | world 域服务 |
| `world_state_prompts.py` | 世界状态追踪 | world 域服务 |
| `test_*.py`（5 件） | prompt 契约对拍单测 | `python -m pytest` |

## 使用方式

统一入口（barrel 只重导出在役且跨域消费的函数）：

```python
from backend.services.prompts import build_refine_agent_prompt, build_formatting_prompt
```

其余按模块直接导入（如 `from backend.services.prompts.adaptive_prompts import ...`）。

## 命名规范

- `build_*_prompt`: 构建提示词，返回 `(system_prompt, user_prompt)`
- `parse_*_result`: 解析 LLM 返回的结果
- `*_utils.py`: 工具函数，不直接构建提示词

## 版本历史

- **V3.x 生成链**（chapter/draft/review 全家）：已随 global_sys_prompt 死线归档（2026-09-05）
- **V4.0 双轨对抗**：已废弃，stitch/sketch 等模板随引擎归档
- **现役**：NLE-ADF 3.0（adaptive）为唯一写作主线
