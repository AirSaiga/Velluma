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
正文逆向提取服务包。

职责：从已有章节正文批量提取角色/关系/地点/资产/伏笔，并落库。
由 routes/extraction.py 的两阶段端点（analyze + confirm）调用。
"""
from backend.services.extraction.content_extractor import (
    ExtractionResult,
    extract_from_chapter,
    commit_extraction,
)

__all__ = ["ExtractionResult", "extract_from_chapter", "commit_extraction"]
