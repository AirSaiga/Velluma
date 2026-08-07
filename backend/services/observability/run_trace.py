"""
运行级全流程 trace 日志（JSONL，实时追加）。

职责：
- 记录一次生成运行的完整过程：阶段事件 + 每次 LLM 调用的
  system/user prompt、响应全文、token 用量、延迟、异常
- 供生成质量分析与 debug（定位大纲偏移、幻觉、截断等问题的具体环节）

设计意图：
- 每个运行一个文件：logs/trace_{run_id}.jsonl，每行一个 JSON 事件，
  实时追加写盘——进程崩溃也不丢已写部分（与 prompt_log_*.json 的
  finalize 一次性写盘互补；且 prompt_logger 未接入 ADF/BS-ADF）
- contextvars 传递：route 层 create_trace()，下游模块（llm/client、
  workflow）get_trace() 零参数接入；asyncio.ensure_future 创建的 task
  会复制上下文，workflow task 内可见
- 无 trace 时 trace_event() 是 no-op（脚本/测试直调模块不产生文件）

业务场景：
- BS-ADF / ADF 生成运行的全流程记录（route 层建 trace，LLM 调用层自动埋点）

事件类型（data 结构）：
- run_start / run_complete / run_error：运行边界
- llm_call：单次 LLM 调用（model_type/model_name/prompts/content/usage/latency）
- llm_error：LLM 调用异常
- 阶段事件（BSADF_STAGE / BEAT_RENDER_PROGRESS / BEAT_DOWNGRADED / ADF_* 等，
  由 route 的 SSE 桥接透传）
- slots_built：槽位卡全量快照
- final_text：最终成稿全文

文件位置：项目根目录 logs/（已 gitignore）。文件可能较大（每章几十次
LLM 调用 × 数 KB prompt/响应 ≈ 数百 KB），属预期，定期清理即可。
"""
# Velluma - run trace logger
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import contextvars
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_current_trace: contextvars.ContextVar[Optional["RunTrace"]] = contextvars.ContextVar(
    "run_trace", default=None
)


def _find_project_root() -> Path:
    """查找项目根目录（包含 backend 目录的父目录）。"""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "backend").exists():
            return parent
    return current.parent.parent.parent


class RunTrace:
    """单运行的 trace 记录器（JSONL 追加写）。

    Attributes:
        run_id: 运行 ID（如 bsadf_xxx / adf_xxx / rerender_xxx）
        engine: 引擎名（bsadf / adf / bsadf_rerender 等）
        chapter_id: 章节 ID
        stage: 当前阶段标签（set_stage 更新，写入后续每条事件）
    """

    def __init__(self, run_id: str, engine: str, chapter_id: str, log_dir: str = "logs"):
        self.run_id = run_id
        self.engine = engine
        self.chapter_id = str(chapter_id) if chapter_id else "unknown"
        self.stage = ""
        self._start_ts = time.time()
        root = _find_project_root()
        dir_path = root / log_dir
        dir_path.mkdir(parents=True, exist_ok=True)
        # run_id 已含引擎前缀（bsadf_/adf_/rerender_），直接用
        self._path = dir_path / f"trace_{run_id}.jsonl"

    @property
    def path(self) -> Path:
        return self._path

    def set_stage(self, stage: str) -> None:
        self.stage = stage or ""

    def log(self, event: str, **data: Any) -> None:
        """追加一条事件（实时写盘，失败静默——日志绝不能阻塞生成）。"""
        record = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "elapsed_ms": int((time.time() - self._start_ts) * 1000),
            "run_id": self.run_id,
            "engine": self.engine,
            "stage": self.stage,
            "event": event,
            "data": data,
        }
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.warning(f"[RunTrace] 写入失败（不阻塞）: {e}")


def create_trace(run_id: str, engine: str, chapter_id: str) -> RunTrace:
    """创建并绑定当前协程上下文的 trace（route 层调用）。"""
    trace = RunTrace(run_id=run_id, engine=engine, chapter_id=chapter_id)
    _current_trace.set(trace)
    return trace


def get_trace() -> Optional[RunTrace]:
    """取当前协程上下文的 trace（无则 None）。"""
    return _current_trace.get()


def clear_trace() -> None:
    """解绑当前协程上下文的 trace。"""
    _current_trace.set(None)


def trace_event(event: str, **data: Any) -> None:
    """全局快捷埋点：有 trace 则记录，无则 no-op。"""
    trace = _current_trace.get()
    if trace is not None:
        trace.log(event, **data)
