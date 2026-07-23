"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors (AGPL-3.0)
"""

"""
对话式介入点 3：成品后读者反馈（V4.3 新建）。

职责：1 次 reasoning LLM 扮演读者，对成品写叙述性反馈。

设计依据：第 6 轮——把"读者视角"外化为独立 LLM 调用

与 Refinery 诊断的区别：
- 诊断（Issue）：找"问题"（结构化、可手术）
- 读者反馈：写"感受"（叙述性、启发作者）

反馈内容（叙述性，不是清单）：
- 读到哪一段最被吸引 / 最出戏
- 对主角的感受（喜欢？厌恶？无感？）
- 读完后最好奇什么（钩子有效性）
- 哪里读着累 / 哪里想跳过
- 整体节奏感受

业务场景：
- 章节生成 + 精修完成后触发
- routes/chapter_generation/refinery.py 的 /feedback 端点
"""

import logging
from typing import Any, Dict, Optional

from backend.services.llm import call_llm_with_usage
from backend.services.observability.run_recorder import RunRecorder

logger = logging.getLogger(__name__)


READER_FEEDBACK_SYSTEM = """你是一位资深的网文读者，刚读完一章小说。

请以读者的视角写一段真实的阅读感受。不要做编辑式的"找问题"分析（那是另一道工序的事），
而是写你作为读者的**真实感受**——喜欢哪里、哪里出戏、哪里想跳过、读完后最好奇什么。

# 写作要求

1. **第一人称读者视角**（"我读到..." "我感觉..."）
2. **诚实**——不要为了客气说好听的话，但也不要刻薄
3. **具体**——引用具体的段落或细节，不要泛泛而谈
4. **叙述性**——像跟朋友聊刚看完的章节，不是写报告
5. **包含以下几方面**（自然融入，不要列清单）：
   - 哪一段最吸引你？为什么？
   - 主角给你的印象是什么？你喜欢 ta 吗？
   - 哪里让你出戏或读着累？
   - 读完后你最想知道什么？（钩子是否有效）
   - 整体节奏感受（快/慢/松紧合适？）
6. **长度**：300-600 字
7. **结尾给一句"读者期待"**——你下一章最想看到什么

不要用 markdown 标题、不要分点列清单、就是一段自然的读者独白。"""

READER_FEEDBACK_USER_TEMPLATE = """# 章节信息
- 第 {chapter_number} 章
- 主旨：{purpose}

# 章节正文

{full_text}

# 要求

写下你作为读者的真实感受。300-600 字，叙述性，第一人称。"""


async def generate_reader_feedback(
    full_text: str,
    chapter_number: int = 1,
    purpose: str = "",
    recorder: Optional[RunRecorder] = None,
) -> Dict[str, Any]:
    """生成读者反馈（1 次 reasoning LLM）。

    Args:
        full_text: 完整章节正文
        chapter_number: 章节序号
        purpose: 章节主旨
        recorder: RunRecorder

    Returns:
        {"feedback": str, "word_count": int}
    """
    if not full_text.strip():
        return {"feedback": "", "word_count": 0}

    user_prompt = READER_FEEDBACK_USER_TEMPLATE.format(
        chapter_number=chapter_number,
        purpose=purpose or "（未提供）",
        full_text=full_text[:6000],
    )

    try:
        if recorder is not None:
            async with recorder.record_call(
                stage="refinery.reader_feedback",
                model_slot="reasoning",
            ) as call_ctx:
                result = await call_llm_with_usage(
                    system_prompt=READER_FEEDBACK_SYSTEM,
                    user_prompt=user_prompt,
                    model_type="reasoning",
                    temperature=0.7,  # 读者反馈要自然，温度略高
                    max_tokens=2048,
                )
                call_ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=READER_FEEDBACK_SYSTEM,
                user_prompt=user_prompt,
                model_type="reasoning",
                temperature=0.7,
                max_tokens=2048,
            )
    except Exception as e:
        logger.warning(f"[ReaderFeedback] LLM 调用失败: {e}")
        return {"feedback": "", "word_count": 0, "error": str(e)[:200]}

    feedback = (result.content or "").strip()
    logger.info(f"[ReaderFeedback] 反馈生成完成：{len(feedback)} 字")
    return {
        "feedback": feedback,
        "word_count": len(feedback),
    }
