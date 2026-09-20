# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""书级文件台账 IO——6 个 jsonl 台账的按书读 / 滤除 / 回填。

背景：这些台账不在数据库里，但承载真实机制状态——collab_events 是
「学着闭嘴/文风先验/意图纠正/幽灵收编」四个零件的数据源（05 瘦身后
埋点只当刽子手），不带它们还原，书的学习状态归零。备份/还原/删除
清理三侧共用本模块。

路径纪律：一律借各台账家模块的现成路径助手（usage.py:525 先例——
「借它的文件坐标，不复制路径规则」），本模块不自建路径推导，防漂移。

写回语义：
- 滤除（删书清理）与回填（导入还原）都用「临时文件 + 原子替换」
  （os.replace 在 Windows 下覆盖目标），损坏行不判归属、原样保留
  （usage.py 同款口径）。
- 回填 = 先滤除本书旧记录再追加备份记录——幂等，重复导入不双计。
- 追加只进「当前份」；collab/constraint 的轮转份 .1 只读不写
  （导出时两份合并读，回填后旧 .1 里的本书记录已被滤除）。
"""
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List

logger = logging.getLogger(__name__)


# ============================================================
# 台账清单（key = 备份 payload["event_logs"] 的键）
# ============================================================

@dataclass(frozen=True)
class LedgerSpec:
    key: str
    paths: Callable[[], List[Path]]
    write_path: Callable[[], Path]
    book_id_of: Callable[[dict], str]


def _collab_paths() -> List[Path]:
    from backend.routes.chapter_generation.adaptive.events import (
        _collab_events_path,
        _collab_events_rotated_path,
    )

    return [_collab_events_path(), _collab_events_rotated_path()]


def _constraint_paths() -> List[Path]:
    from backend.services.constraints.events import _events_path, _rotated_path

    return [_events_path(), _rotated_path()]


def _deai_pairs_paths() -> List[Path]:
    from backend.services.deai.pairs import _pairs_path

    return [_pairs_path()]


def _ask_metrics_paths() -> List[Path]:
    from backend.services.world.ask_book import _metrics_path

    return [_metrics_path()]


def _opening_card_paths() -> List[Path]:
    from backend.routes.chapter_generation.adaptive.opening_card import _metrics_path

    return [_metrics_path()]


def _style_events_paths() -> List[Path]:
    from backend.services.style.events import STYLE_EVENTS_FILE

    return [Path(STYLE_EVENTS_FILE)]


def _record_book_id(record: dict) -> str:
    return str(record.get("book_id") or "")


def _deai_pair_book_id(record: dict) -> str:
    meta = record.get("meta") if isinstance(record.get("meta"), dict) else {}
    return str((meta or {}).get("book_id") or "")


LEDGERS: tuple[LedgerSpec, ...] = (
    LedgerSpec("collab_events", _collab_paths,
               lambda: _collab_paths()[0], _record_book_id),
    LedgerSpec("constraint_events", _constraint_paths,
               lambda: _constraint_paths()[0], _record_book_id),
    LedgerSpec("deai_pairs", _deai_pairs_paths,
               lambda: _deai_pairs_paths()[0], _deai_pair_book_id),
    LedgerSpec("ask_book_metrics", _ask_metrics_paths,
               lambda: _ask_metrics_paths()[0], _record_book_id),
    LedgerSpec("opening_card_metrics", _opening_card_paths,
               lambda: _opening_card_paths()[0], _record_book_id),
    LedgerSpec("style_events", _style_events_paths,
               lambda: _style_events_paths()[0], _record_book_id),
)


# ============================================================
# 读 / 滤除 / 回填
# ============================================================

def read_book_events(spec: LedgerSpec, book_id) -> List[dict]:
    """导出侧：读该书的全部台账记录（当前份 + 轮转份合并）。"""
    out: List[dict] = []
    for path in spec.paths():
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue  # 损坏行不判归属，导出跳过
                    if isinstance(record, dict) and spec.book_id_of(record) == str(book_id):
                        out.append(record)
        except Exception as e:
            logger.warning(f"[book_archive] 台账读取失败（跳过 {path.name}）: {e}")
    return out


def filter_ledger_files(spec: LedgerSpec, book_id) -> int:
    """滤除本书记录（删书清理用），返回删除条数。"""
    return _rewrite_filter(spec, str(book_id))


def restore_book_events(spec: LedgerSpec, book_id, records: List[dict]) -> int:
    """回填本书记录（导入还原用）：先滤旧再追加，幂等。返回追加条数。"""
    _rewrite_filter(spec, str(book_id))
    if not records:
        return 0
    write_path = spec.write_path()
    try:
        write_path.parent.mkdir(parents=True, exist_ok=True)
        with write_path.open("a", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"[book_archive] 台账回填失败（{write_path.name}）: {e}")
        return 0
    return len(records)


def _rewrite_filter(spec: LedgerSpec, book_id_str: str) -> int:
    """usage.py 同款：逐行判归属，本书删除他书保留，临时文件原子替换。"""
    deleted = 0
    for path in spec.paths():
        if not path.exists():
            continue
        kept_lines: List[str] = []
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        record = json.loads(stripped)
                    except Exception:
                        kept_lines.append(line)  # 损坏行不判归属，原样保留
                        continue
                    if isinstance(record, dict) and spec.book_id_of(record) == book_id_str:
                        deleted += 1
                    else:
                        kept_lines.append(line if line.endswith("\n") else line + "\n")
        except Exception as e:
            logger.warning(f"[book_archive] 台账滤除读取失败（跳过 {path.name}）: {e}")
            continue
        try:
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text("".join(kept_lines), encoding="utf-8")
            tmp.replace(path)
        except Exception as e:
            logger.warning(f"[book_archive] 台账滤除重写失败（{path.name} 保持原样）: {e}")
    return deleted
