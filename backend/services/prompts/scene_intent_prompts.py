import re
import json

from backend.models import Chapter


def build_scene_intent_prompt(chapter: Chapter, beat: dict, open_hooks: list = None):
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    beat_summary = beat.get("summary", "")
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
3. 只输出 JSON"""
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
