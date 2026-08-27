# Velluma - Intent 统一存储迁移脚本（B2 · docs/world-kernel-construction-plan.md §3）
# AGPL-3.0
"""旧源 → world_intents 幂等复制（手动跑，不进启动链）。

用法：python scripts/migrate_to_intents.py
覆盖：plot_ledgers(open) / canon 揭示计划 / 期待账本(reader_mirror)。
不迁（作者主权）：大纲自由文本与 spine 锚点（见 intent_repository 模块头）。
重跑安全：source_key 幂等，已复制的跳过。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import AsyncSessionLocal  # noqa: E402
from backend.repositories.intent_repository import migrate_legacy_to_intents  # noqa: E402


async def main():
    async with AsyncSessionLocal() as db:
        counts = await migrate_legacy_to_intents(db)
        await db.commit()
    print(f"迁移完成（幂等，重跑零新增）：{counts}")


if __name__ == "__main__":
    asyncio.run(main())
