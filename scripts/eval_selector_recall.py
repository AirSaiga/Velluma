# Velluma - 选择器召回金标准评测（B0.3 · docs/world-kernel-construction-plan.md §1）
# AGPL-3.0
"""知识平面选择器的 recall/precision 评测（可证伪性验收，WCA §10）。

两步用法：
1. 生成标注模板：python scripts/eval_selector_recall.py --make-template
   → tmp_research/golden_annotations.json：每章一条断点（章尾 80 字）+
   预填「当前选择器实际选中」的 expected_keys（作者改写为**应选**集合——
   这是金标准的人工环节，预填只是降低抄写成本）。
2. 评测：python scripts/eval_selector_recall.py --eval
   → 对每条断点重跑 build/select，算 recall/precision，列出漏选键。

门槛（docs/world-kernel-foundation.md 继承）：场景锚定相关条目 recall ≥95%。
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import AsyncSessionLocal  # noqa: E402
from backend.services.context.settings_bundle import load_chapter_settings_bundle  # noqa: E402
from backend.services.context.knowledge_plane import (  # noqa: E402
    build_knowledge_entries, select_knowledge,
)

ANNOTATION_PATH = Path("tmp_research/golden_annotations.json")


async def _make_template():
    out = []
    from sqlalchemy import select as _select
    from backend.models import Chapter as _Chapter
    async with AsyncSessionLocal() as db:
        chapters = (await db.execute(_select(_Chapter).order_by(_Chapter.created_at))).scalars().all()
        for ch in chapters:
            text = (ch.content_text or "").strip()
            if len(text) < 200:
                continue
            bundle = await load_chapter_settings_bundle(str(ch.id), db)
            entries = build_knowledge_entries(bundle)
            selected, _, _mentions = select_knowledge(entries, bundle, bundle.content_text or "")
            out.append({
                "chapter_id": str(ch.id),
                "chapter_title": ch.title,
                "breakpoint": text[-80:],
                # 作者改写此集合为「这一断点上应选的条目」（增删均可）
                "expected_keys": [e.key for e in selected],
            })
    ANNOTATION_PATH.parent.mkdir(exist_ok=True)
    ANNOTATION_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"模板已生成：{ANNOTATION_PATH}（{len(out)} 条断点，请作者改写 expected_keys）")


async def _eval():
    items = json.loads(ANNOTATION_PATH.read_text(encoding="utf-8"))
    recalls, precisions = [], []
    print(f"{'章节':<14} recall precision  漏选")
    async with AsyncSessionLocal() as db:
        for it in items:
            expected = set(it.get("expected_keys") or [])
            if not expected:
                continue
            bundle = await load_chapter_settings_bundle(it["chapter_id"], db)
            entries = build_knowledge_entries(bundle)
            selected, _, _mentions = select_knowledge(entries, bundle, bundle.content_text or "")
            got = {e.key for e in selected}
            inter = expected & got
            rec = len(inter) / len(expected)
            prec = len(inter) / len(got) if got else 0.0
            recalls.append(rec)
            precisions.append(prec)
            missed = "、".join(sorted(expected - got))[:60] or "无"
            print(f"{it['chapter_title'][:12]:<14} {rec:6.0%} {prec:9.0%}  {missed}")
    if recalls:
        print(f"\n宏平均：recall {sum(recalls)/len(recalls):.0%}"
              f"  precision {sum(precisions)/len(precisions):.0%}"
              f"（门槛：场景锚定相关 recall ≥95%）")


if __name__ == "__main__":
    if "--make-template" in sys.argv:
        asyncio.run(_make_template())
    else:
        asyncio.run(_eval())
