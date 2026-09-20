# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
文本格式整理路由模块 - V4.0

职责：提供文本格式整理 API，支持 LLM 智能格式化和规则引擎两种模式。

V4.0 更新：
- 长文本采用分段处理，避免 LLM Token 限制
- 短文本（<3000字）使用 LLM 智能格式化
- 长文本使用增强规则引擎

业务场景：
- AI 生成内容格式混乱时的自动整理
- 用户手动输入后的格式规范化
- 导出前的最终排版
"""

import logging
import re
from fastapi import APIRouter
from backend.schemas import FormatTextRequest
from backend.services.workflows.formatting_utils import rule_based_formatting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["text_formatting"])

# 字符数阈值：约 5000 汉字 ≈ 7500 tokens，接近模型 8192 上限
# 警告：接近 5000 字的文本可能导致输出被截断，建议分批处理
LLM_FORMATTING_MAX_CHARS = 5000


def enhanced_rule_formatting(text: str) -> str:
    """
    增强规则引擎 - 比基础规则更智能的小说格式化。
    
    针对长文本设计，无需 LLM 即可完成较好的格式化效果：
    - 识别对话并独立成段
    - 检测场景切换（时间/地点标记）
    - 长段落按句号拆分
    """
    if not text or not text.strip():
        return ""
    
    # 步骤 1: 基础标点规范化
    text = _normalize_punctuation(text)
    
    # 步骤 2: 识别并处理对话
    text = _format_dialogues(text)
    
    # 步骤 3: 检测场景切换并分段
    text = _detect_scene_changes(text)
    
    # 步骤 4: 长段落拆分
    text = _split_long_paragraphs(text, max_length=200)
    
    # 步骤 5: 清理多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()


def _normalize_punctuation(text: str) -> str:
    """标点规范化（中英文标点统一）。"""
    # 保护数字中的小数点
    text = re.sub(r'(?<=\d)\.(?=\d)', '\x00', text)
    
    # 基础标点替换（排除 URL 中的冒号）
    text = re.sub(r'(?<!http)(?<!https)(?<!\w):\s*', '：', text)
    text = text.replace(',', '，')
    text = text.replace('.', '。')
    text = text.replace('!', '！')
    text = text.replace('?', '？')
    text = text.replace('(', '（')
    text = text.replace(')', '）')
    
    # 恢复数字小数点
    text = text.replace('\x00', '.')
    
    # 合并连续标点
    text = re.sub(r'，+', '，', text)
    text = re.sub(r'。+', '。', text)
    
    return text


def _format_dialogues(text: str) -> str:
    """
    识别对话并格式化。
    
    规则：
    - "..." 他说。 -> 对话独立成段
    - 他说："..." -> 对话独立成段
    """
    # 模式1: "内容" 动作。 -> 拆分为两段
    text = re.sub(
        r'([^。\n"]*?)"([^"]{2,50}?)"\s*([^"\n]{1,30}?)([。！？])',
        r'\1\n\n"\2"\3\4\n\n',
        text
    )
    
    # 模式2: 动作："内容" -> 拆分为两段
    text = re.sub(
        r'([^"\n]{1,20}?)[：:]\s*"([^"]{2,50}?)"',
        r'\1：\n\n"\2"\n\n',
        text
    )
    
    # 清理多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text


def _detect_scene_changes(text: str) -> str:
    """
    检测场景切换标记并分段。
    
    切换标记：时间词、地点词、视角切换词
    """
    # 时间切换词
    time_markers = r'(第二天|次日|清晨|黄昏|夜晚|片刻后|与此同时|不久|随后|突然)'
    text = re.sub(rf'({time_markers})', r'\n\n\1', text)
    
    # 地点切换词
    location_markers = r'(在.*?[上内里]|回到|来到|走进|离开)'
    text = re.sub(rf'({location_markers})', r'\n\n\1', text)
    
    # 清理多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text


def _split_long_paragraphs(text: str, max_length: int = 200) -> str:
    """
    将超过 max_length 的段落按句号拆分。
    """
    paragraphs = text.split('\n\n')
    result = []
    
    for para in paragraphs:
        if len(para) <= max_length:
            result.append(para)
            continue
        
        # 按句号拆分，但保留句号
        sentences = re.split(r'([。！？])', para)
        current_chunk = ""
        
        for i in range(0, len(sentences), 2):
            sentence = sentences[i]
            # 加上标点
            if i + 1 < len(sentences):
                sentence += sentences[i + 1]
            
            if not sentence.strip():
                continue
            
            # 如果当前块加上这句会超限，先保存当前块
            if len(current_chunk) + len(sentence) > max_length and current_chunk:
                result.append(current_chunk)
                current_chunk = sentence
            else:
                current_chunk += sentence
        
        if current_chunk:
            result.append(current_chunk)
    
    return '\n\n'.join(result)


@router.post("/format_text")
async def format_text(request: FormatTextRequest):
    """整理文本格式（分段、标点、对话排版等）- V4.0 智能版。

    V4.0 更新：
    - 短文本（<3000字）使用 LLM 智能格式化
    - 长文本使用增强规则引擎（避免 Token 限制）

    业务目的：将原始文本整理为符合阅读习惯的格式

    处理逻辑：
    1. 文本 < 3000 字：使用 LLM 智能格式化（配置从 model_config.json 读取）
    2. 文本 >= 3000 字：使用增强规则引擎

    参数来源：
    - request.text: 待整理的原始文本
    - request.text: 待整理的原始文本

    边界处理：
    - 空文本直接返回空字符串
    - 文本少于 50 字直接返回原文
    """
    if not request.text.strip():
        return {"formatted_text": ""}
    
    text = request.text.strip()
    
    # 如果文本较短，直接返回（无需格式化）
    if len(text) < 50:
        return {"formatted_text": text}
    
    # 长文本使用增强规则引擎（避免 LLM Token 限制）
    if len(text) > LLM_FORMATTING_MAX_CHARS:
        logger.warning("[format_text] 文本过长（%d 字），走增强规则引擎", len(text))
        formatted_text = enhanced_rule_formatting(text)
        return {"formatted_text": formatted_text}
    
    # 短文本优先使用 LLM 智能格式化
    try:
        from backend.services.llm.formatting import llm_based_formatting
        
        formatted_text = await llm_based_formatting(
            text=text,
        )
        
        # 简化验证：只要结果不为空且长度合理（±50%）就接受
        original_len = len(text)
        result_len = len(formatted_text)
        
        if formatted_text and (original_len * 0.5 <= result_len <= original_len * 1.5):
            return {"formatted_text": formatted_text}

        logger.warning(
            "[format_text] LLM 结果异常（%d vs %d 字），走增强规则引擎",
            result_len, original_len,
        )

    except Exception as e:
        logger.warning("[format_text] LLM 失败: %s，走增强规则引擎", e)
    
    # 回退到增强规则引擎
    formatted_text = enhanced_rule_formatting(text)
    return {"formatted_text": formatted_text}


@router.post("/format_text/rule_based")
async def format_text_rule_based(request: FormatTextRequest):
    """规则引擎格式整理（无 LLM 调用）。
    
    适用于：
    - 不想产生 API 费用
    - 只需要简单的标点规范化
    - 网络不稳定无法调用 LLM
    """
    if not request.text.strip():
        return {"formatted_text": ""}
    
    formatted_text = rule_based_formatting(request.text)
    return {"formatted_text": formatted_text}
