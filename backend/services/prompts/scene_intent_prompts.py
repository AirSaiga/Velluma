import re
import json

from backend.models import Chapter


PACING_MICRO_INSTRUCTIONS = {
    "slow_burn": [
        "单段只推进一个小动作，不触发关系爆点",
        "增加环境或心理层面的细节垫层，避免结论跳跃",
        "冲突表达以试探、停顿、回避为主，不直接摊牌",
    ],
    "fast_paced": [
        "每段至少出现一个可见动作变化，减少铺垫冗余",
        "优先保留关键决策与结果反馈，压缩背景解释",
        "句式更短、更直接，推动信息快速抵达",
    ],
    "balanced": [
        "动作推进与情绪描写保持均衡，避免单侧堆叠",
        "每段包含一次可感知变化并补充必要动机",
        "冲突与缓冲交替出现，保持阅读节奏稳定",
    ],
}


def build_scene_intent_prompt(chapter: Chapter, beat: dict, open_hooks: list = None):
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    beat_summary = beat.get("summary", "")
    pacing_style = str(getattr(chapter, "pacing_style", "balanced") or "balanced").strip() or "balanced"
    if pacing_style not in PACING_MICRO_INSTRUCTIONS:
        pacing_style = "balanced"
    pacing_micro_lines = PACING_MICRO_INSTRUCTIONS[pacing_style]
    exit_state = str(beat.get("exit_state") or "").strip() or "停在当前 beat 的收束状态，不越界推进"
    system_prompt = """你是场景意图分析师。请根据输入剧情节拍输出 JSON。

输出结构：
{
  "intent_label": "场景标签",
  "goal": "本场景目标",
  "stakes": "失败代价或风险",
  "constraints": ["约束1", "约束2"]
}

要求：
1. goal 必须具体
2. constraints 必须是字符串数组
3. constraints 中必须包含节奏微观指令，并显式声明“停在 exit_state”
4. 不得让场景推进越过 exit_state
5. 只输出 JSON"""
    open_hooks_text = "暂无开放伏笔"
    if isinstance(open_hooks, list) and open_hooks:
        hook_lines = []
        for item in open_hooks[:6]:
            if not isinstance(item, dict):
                continue
            hook_id = str(item.get("hook_id") or item.get("ledger_key") or "").strip()
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            hook_lines.append(f"- {hook_id}: {content}" if hook_id else f"- {content}")
        if hook_lines:
            open_hooks_text = chr(10).join(hook_lines)
    user_prompt = f"""请为以下章节节拍生成 SceneIntent：

【章节名】{chapter_name}
【章节大纲】
{chapter.outline_text or '暂无大纲'}
【节拍位置】{beat.get("position", 1)}
【节拍内容】
{beat_summary}
【节拍收束状态 exit_state】
{exit_state}
【叙事节奏偏好】{pacing_style}
【节奏微观指令（必须写入 constraints）】
- {pacing_micro_lines[0]}
- {pacing_micro_lines[1]}
- {pacing_micro_lines[2]}
【开放伏笔】
{open_hooks_text}"""
    return system_prompt, user_prompt


def parse_scene_intent_result(scene_intent_raw: str, beat_summary: str):
    text = (scene_intent_raw or "").strip()
    candidates = [text] if text else []
    fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    candidates.extend(block.strip() for block in fenced_blocks if block and block.strip())
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.append(text[first_brace : last_brace + 1].strip())
    parsed_obj = None
    for candidate in candidates:
        try:
            parsed_obj = json.loads(candidate)
            break
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    if isinstance(parsed_obj, dict):
        intent_label = str(parsed_obj.get("intent_label") or "").strip() or "推进剧情"
        goal = str(parsed_obj.get("goal") or "").strip() or beat_summary or "推进剧情"
        stakes_raw = parsed_obj.get("stakes")
        stakes = str(stakes_raw).strip() if stakes_raw is not None else ""
        constraints_raw = parsed_obj.get("constraints")
        constraints = [str(item).strip() for item in constraints_raw if str(item).strip()] if isinstance(constraints_raw, list) else []
        return {
            "intent_label": intent_label,
            "goal": goal,
            "stakes": stakes or None,
            "constraints": constraints,
        }
    return {
        "intent_label": "推进剧情",
        "goal": beat_summary or "推进剧情",
        "stakes": None,
        "constraints": [],
    }
