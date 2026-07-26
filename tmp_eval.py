import sys, asyncio
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'D:/qoder/Velluma')
from types import SimpleNamespace as NS
import asyncpg

CH_ID = '07136b7a-83cb-4e24-8329-272219bb1ac6'
BOOK_ID = 'e12830c2-edad-48a5-b1df-ec7d85e0d2ba'

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/storyweaver')
    ch = await conn.fetchrow("SELECT draft_text FROM chapters WHERE id=$1", CH_ID)
    text = ch['draft_text'] or ''
    run = await conn.fetchrow(
        "SELECT run_id, MAX(created_at) AS t FROM generation_runs WHERE chapter_id=$1 GROUP BY run_id ORDER BY t DESC LIMIT 1", CH_ID)
    rows = await conn.fetch(
        "SELECT stage, model_slot, prompt_tokens, completion_tokens, thinking_tokens, latency_ms, degraded FROM generation_runs WHERE chapter_id=$1 AND run_id=$2 ORDER BY created_at ASC",
        CH_ID, run['run_id'])
    print(f"=== 最新 run {run['run_id']}：{len(rows)} 次调用 ===")
    for r in rows:
        deg = f" DEGRADED={str(r['degraded'])[:100]}" if r['degraded'] else ""
        print(f"  {r['stage']:42s} {(r['model_slot'] or '?'):9s} in={r['prompt_tokens'] or 0:6d} out={r['completion_tokens'] or 0:5d} think={r['thinking_tokens'] or 0:5d} {(r['latency_ms'] or 0)//1000:3d}s{deg}")

    chars = await conn.fetch("SELECT name, aliases FROM characters WHERE book_id=$1", BOOK_ID)
    locs = await conn.fetch("SELECT name FROM map_locations WHERE book_id=$1", BOOK_ID)
    assets = await conn.fetch("SELECT name, aliases FROM assets WHERE book_id=$1", BOOK_ID)
    await conn.close()

    print(f"\n=== 文本指标（{len(text)} 字）===")
    from backend.services.nlg.ai_taste_meter import measure_ai_taste, short_sentence_ratio
    import re
    rep = measure_ai_taste(text)
    print(f"AI味综合分: {rep.overall_score}, 触发: {rep.triggered}")
    sr = short_sentence_ratio(text); print(f"碎句率(≤5字): {sr}")
    paras = [p for p in text.split('\n\n') if p.strip()]
    single = sum(1 for p in paras if len(re.split(r'[。！？!?…]', p.strip())) <= 2)
    print(f"段落数: {len(paras)}, 单句段占比: {single/len(paras):.1%}")
    rev = len(re.findall(r'不是[^。！？\n]{1,30}[，,][^。！？\n]{0,10}是', text))
    print(f"反转句(不是X，是Y): 约 {rev} 处")

    from backend.services.workflows.adf.dedup_guard import remove_duplicate_blocks
    new_text, removed = remove_duplicate_blocks(text)
    print(f"重复块检测: {removed if removed else '无'}")

    from backend.services.workflows.adf.name_registry import build_name_registry, scan_name_anomalies
    entities = [NS(character=NS(name=c['name'], aliases=c['aliases'] or [])) for c in chars]
    locations = [NS(location=NS(name=l['name'], aliases=[])) for l in locs]
    asset_objs = [NS(asset=NS(name=a['name'], aliases=a['aliases'] or [])) for a in assets]
    registry = build_name_registry(entities=entities, locations=locations, assets=asset_objs, canon_context="")
    suspects = scan_name_anomalies(text, registry)
    print(f"专名 suspects: {[s['name'] for s in suspects] if suspects else '无'}")
    md = len(re.findall(r'(?<!\d)\*[^\s*]', text))
    sp = len(re.findall(r'[。！？] ', text))
    print(f"markdown残留: {md} 处, 句号后空格: {sp} 处")

asyncio.run(main())
