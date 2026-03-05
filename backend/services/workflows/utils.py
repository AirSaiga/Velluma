import json


def clean_llm_output(text: str) -> str:
    if not text:
        return ""
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                for key in ["content", "text", "body", "chunk", "draft"]:
                    if key in data and isinstance(data[key], str):
                        return data[key].strip()
        except json.JSONDecodeError:
            pass
    if text.startswith("```"):
        lines = text.split("\n")
        if len(lines) >= 2:
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            return "\n".join(lines).strip()
    return text
