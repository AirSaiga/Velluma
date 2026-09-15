# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""html_to_plain 单测——services/utils/html_text.py（剥 HTML 唯一权威）。

对拍口径（AGENTS「数据库卫生批」红线）：
- 一切测量消费（章指纹/负面命中/章收编/禁词扫描/记忆索引）必须先剥标签；
- `<p></p>` 空文档判空依赖本函数返回空串（from-chapters 幂等链路）；
- 记忆块陈旧检测比对的剥 HTML 必须与 memory_indexing 侧同口径——
  自写剥标签（如 str.replace 逐标签替换）因换行规则不同会产生假差异。
"""

from backend.services.utils.html_text import html_to_plain


class TestHtmlToPlain:
    def test_none_and_empty(self):
        assert html_to_plain(None) == ""
        assert html_to_plain("") == ""

    def test_plain_text_passthrough(self):
        # 纯文本（无标签）原样返回（仅首尾空白裁剪）
        assert html_to_plain("  山月不知心底事。  ") == "山月不知心底事。"

    def test_paragraph_tags_become_newlines(self):
        # 标签→换行：两段正文剥完换行分隔（连续换行折叠至多一个空行）
        assert html_to_plain("<p>第一段。</p><p>第二段。</p>") == "第一段。\n\n第二段。"

    def test_empty_paragraph_document_is_empty(self):
        # 空文档契约：<p></p> 剥完是空串（from-chapters 纯文本判空依赖）
        assert html_to_plain("<p></p>") == ""

    def test_inline_marks_leave_no_tag_chars(self):
        # 行内 mark 也按标签换行处理——测量消费只要求：无标签字符残留
        html = "<p>他推门。<strong>风雪</strong>扑面。</p>"
        out = html_to_plain(html)
        assert "<" not in out and ">" not in out
        assert "风雪" in out and "扑面" in out

    def test_consecutive_blank_lines_collapse_to_one(self):
        # 连续空段折叠至多一个空行（\n{3,} → \n\n）
        html = "<p>甲。</p><p></p><p></p><p></p><p>乙。</p>"
        assert html_to_plain(html) == "甲。\n\n乙。"

    def test_tag_attrs_stripped(self):
        # 带属性的标签（data-outline-note 等）一并剥净，不残留属性文本
        html = '<p>正文<span data-outline-note="1">胶囊</span>后文。</p>'
        out = html_to_plain(html)
        assert "<" not in out and ">" not in out
        assert "data-outline-note" not in out
        assert "胶囊" in out

    def test_nested_tags(self):
        out = html_to_plain("<p><em><strong>层层</strong>嵌套</em>。</p>")
        assert "<" not in out and ">" not in out
        assert "层层" in out and "嵌套" in out

    def test_measurement_consistency_with_word_count(self):
        # 同一把尺子：同一正文，带标签与不带标签剥完字数口径一致
        plain = "他抬头看了看天，又低下头去。"
        tagged = f"<p>{plain}</p>"
        assert len(html_to_plain(tagged)) == len(plain)
