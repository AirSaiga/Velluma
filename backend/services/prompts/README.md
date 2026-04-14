# Prompts 模块索引

本目录包含所有 LLM 提示词（Prompt）模板构建函数。

## 核心文件

| 文件 | 职责 | 关键函数 |
|------|------|----------|
| `chapter_prompts.py` | 基础章节生成 | `build_chapter_prompt` |
| `draft_prompts.py` | 起草阶段主入口 | `build_draft_agent_prompt`, `build_chunk_draft_prompt`, `build_prose_draft_prompt_v25` |
| `planner_prompts.py` | 规划阶段（Story Beats） | `build_planner_agent_prompt`, `parse_planner_result` |
| `scene_intent_prompts.py` | 场景意图分析 | `build_scene_intent_prompt`, `parse_scene_intent_result` |
| `stitch_prompts.py` | 统稿阶段（片段拼接） | `build_stitch_prompt` |
| `review_prompts.py` | 审阅/精修阶段 | `build_review_agent_prompt`, `build_refine_agent_prompt`, `parse_review_result` |

## 子模块文件

| 文件 | 职责 | 说明 |
|------|------|------|
| `draft_prompts_prose.py` | 正文生成详细模板 | 被 `draft_prompts.py` 调用 |
| `draft_prompts_thinking.py` | 思考层模板（潜意识/内心独白） | 被 `draft_prompts.py` 调用 |
| `draft_prompts_subconscious.py` | 潜意识生成专用 | 独立子模块 |
| `draft_prompts_review.py` | 微审阅提示词 | QC 检查使用 |
| `draft_prompts_legacy.py` | 旧版本兼容 | 保留用于回溯 |
| `draft_prompts_utils.py` | 草稿工具函数 | 辅助函数集合 |
| `review_prompts_utils.py` | 审阅工具函数 | 审阅辅助函数 |
| `planner_prompts_parser.py` | 规划结果解析 | 解析 LLM 返回的 beats |

## 特殊用途文件

| 文件 | 职责 |
|------|------|
| `pov_prompts.py` | 视角（POV）分配 |
| `world_state_prompts.py` | 世界状态追踪 |
| `inspiration_prompts.py` | 灵感生成 |
| `critique_prompts.py` | 评论/反馈生成 |
| `format_prompts.py` | 文本格式化 |
| `test_boundary_pacing_prompts.py` | 节奏边界测试（实验性） |

## 使用方式

推荐从统一入口导入：

```python
from backend.services.prompts import (
    build_draft_agent_prompt,
    build_planner_agent_prompt,
    build_review_agent_prompt,
)
```

## 命名规范

- `build_*_prompt`: 构建提示词，返回 `(system_prompt, user_prompt)`
- `parse_*_result`: 解析 LLM 返回的结果
- `*_utils.py`: 工具函数，不直接构建提示词

## 版本历史

- **V4.0**: 基础章节生成
- **V4.0**: 引入 Agentic 工作流
- **V4.0**: 认知流式生成 (Cognitive Streaming)
- **V4.0**: 三档工作流（疾速/均衡/堡垒）
- **V4.0**: 双轨对抗架构
