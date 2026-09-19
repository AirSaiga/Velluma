# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
deai 训练对收集账本（data/deai_pairs.jsonl，零上报——桌面应用隐私边界内）。

写作台「记改前/记改后」手动配对的落盘侧（docs/deai-integration.md §5a）。
行为数据飞轮的手动起点：bad = 卡片舱生成的原样文本，good = 作者亲手改定
的版本——域内的、作者个人分布的训练对。

格式与 deai/scripts/validate_pairs.py 的输入契约逐字兼容（每行
{"id","bad","good","meta"}，多余键被其 parse_input 忽略）；
deai/scripts/ingest_behavior_pairs.py 消费本文件做六闸入库（事实闸/像人闸
天然拦下配错对与改内容的对子——收集侧只做硬性不可用检查，其余交给闸门，
「宁可少入库」纪律不变）。
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

DEAI_PAIRS_FILE = "data/deai_pairs.jsonl"

# 契约 C1（deai/docs/contract.md）：输入 ≤100 字（len() 口径，strip 后计数）。
# 超过即训练不可用，收集侧直接拒绝——v2 若放宽契约窗，改这里与前端守卫两处。
BAD_MAX_CHARS = 100
# good 的收集侧硬顶：远超改写语义的乱投（如整段误选）挡在账本外；
# 120% 长度契约留给入库闸门判，这里不重复执法。
GOOD_MAX_CHARS = 600


class PairValidationError(ValueError):
    """收集侧硬性校验失败（人读 message 直接上 toast）。"""


def _pairs_path() -> Path:
    return Path(DEAI_PAIRS_FILE)


def _read_all(path: Path) -> List[dict]:
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                records.append(obj)
        except json.JSONDecodeError:
            # 单行损坏不拖垮整个账本（本地文件，保守跳过并留日志）
            logger.warning(f"[deai-pairs] 跳过损坏行: {line[:80]}")
    return records


def save_pair(
    bad: str,
    good: str,
    book_id: Optional[str] = None,
    chapter_id: Optional[str] = None,
    source: str = "manual_mark",
) -> dict:
    """写入一对训练样本。返回 {"id", "total"}。

    副作用：追加一行到 data/deai_pairs.jsonl（不存在则创建）。
    抛 PairValidationError：bad/good 为空、bad 超 100 字、good 超硬顶。
    source（03 下一阶段 §5）：manual_mark=手动两步 / auto_ghost=书签自动捕获 /
    capsule=细纲扩写采纳——入库侧分组统计质量用；白名单外回退 manual_mark。
    """
    bad = (bad or "").strip()
    good = (good or "").strip()
    if not bad:
        raise PairValidationError("改前文本为空")
    if not good:
        raise PairValidationError("改后文本为空")
    if len(bad) > BAD_MAX_CHARS:
        raise PairValidationError(
            f"改前 {len(bad)} 字超过 {BAD_MAX_CHARS} 字契约窗，标记了也进不了训练集"
        )
    if len(good) > GOOD_MAX_CHARS:
        raise PairValidationError(
            f"改后 {len(good)} 字异常（上限 {GOOD_MAX_CHARS}），请确认选中的是改后那一段"
        )
    if source not in ("manual_mark", "auto_ghost", "capsule"):
        source = "manual_mark"

    record = {
        "id": "m" + uuid.uuid4().hex[:10],
        "bad": bad,
        "good": good,
        "meta": {
            "source": source,
            "book_id": book_id or "",
            "chapter_id": chapter_id or "",
            "ts": datetime.now(timezone.utc).isoformat(),
            "bad_len": len(bad),
            "good_len": len(good),
        },
    }
    path = _pairs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    total = len(_read_all(path))
    logger.info(f"[deai-pairs] 已存对子 {record['id']}（bad {len(bad)} 字 → good {len(good)} 字，账本共 {total} 对）")
    return {"id": record["id"], "total": total}


def delete_pair(pair_id: str) -> bool:
    """按 id 删除一对（6 秒撤销胶囊用）。返回是否删到。

    副作用：重写整个账本文件（本地小文件，单用户桌面场景无并发顾虑）。
    """
    path = _pairs_path()
    if not path.is_file():
        return False
    records = _read_all(path)
    kept = [r for r in records if r.get("id") != pair_id]
    if len(kept) == len(records):
        return False
    with path.open("w", encoding="utf-8") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return True


def count_pairs() -> int:
    return len(_read_all(_pairs_path()))
