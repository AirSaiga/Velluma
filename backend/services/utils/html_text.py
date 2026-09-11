# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""画布正文 HTML → 纯文本的规范实现（唯一权威，2026-09-11 收敛）。

画布正文以编辑器 getHTML 落库（content_text 是 HTML），一切「测量」消费
（章指纹 / 负面命中 / 章节收编 / 禁词扫描 / 记忆索引）必须先剥——标签字符
混入会污染句长/字数统计，违反「同一把尺子」红线（services/style/fingerprint.py
对拍单测锁定同值）。原 routes/style._plain_text 与 rag/memory_indexing.
_html_to_plain 是逐字节双实现，本函数收敛后两者委托至此。
"""
import re
from typing import Optional


def html_to_plain(text: Optional[str]) -> str:
    """剥标签为纯文本：标签→换行、连续空行折叠至多一个、去首尾空白。"""
    plain = re.sub(r"<[^>]+>", "\n", text or "")
    return re.sub(r"\n{3,}", "\n\n", plain).strip()
