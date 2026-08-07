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

from .logging import (
    ServiceLogger,
    LOG_PREFIX_RAG,
    LOG_PREFIX_PROMPT_LOGGER,
    LOG_PREFIX_EMBEDDING,
    LOG_PREFIX_SUMMARY,
    LOG_PREFIX_WORKFLOW,
    LOG_PREFIX_SYSTEM,
    log_info,
    log_warning,
    log_error,
    log_debug,
)
from .sse import (
    build_sse_event,
    build_sse_metric_frame,
    build_sse_text_chunk,
    build_sse_done,
    build_sse_error,
)
from .timeout import (
    timed,
    with_timeout,
    TimeoutManager,
)
from .sanitizer import (
    sanitize_user_content,
    sanitize_json_field,
    sanitize_markdown,
    sanitize_prompt_variable,
)
from .prompt_logger import (
    PromptLogger,
    create_logger,
    get_logger,
    clear_logger,
)

__all__ = [
    # Logging
    "ServiceLogger",
    "LOG_PREFIX_RAG",
    "LOG_PREFIX_PROMPT_LOGGER",
    "LOG_PREFIX_EMBEDDING",
    "LOG_PREFIX_SUMMARY",
    "LOG_PREFIX_WORKFLOW",
    "LOG_PREFIX_SYSTEM",
    "log_info",
    "log_warning",
    "log_error",
    "log_debug",
    # SSE
    "build_sse_event",
    "build_sse_metric_frame",
    "build_sse_text_chunk",
    "build_sse_done",
    "build_sse_error",
    # Timeout
    "timed",
    "with_timeout",
    "TimeoutManager",
    # Sanitizer
    "sanitize_user_content",
    "sanitize_json_field",
    "sanitize_markdown",
    "sanitize_prompt_variable",
    # Prompt Logger
    "PromptLogger",
    "create_logger",
    "get_logger",
    "clear_logger",
]
