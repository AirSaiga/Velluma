import asyncio
from backend.database import AsyncSessionLocal
from sqlalchemy import select
from backend.models import Chapter, MemoryChunk

async def main():
    async with AsyncSessionLocal() as db:
        print("Checking Chapters...")
        result = await db.execute(select(Chapter))
        chapters = result.scalars().all()
        for c in chapters:
            print(f"Chapter {c.chapter_number}: Summary exists? {bool(c.summary)}")
            if c.summary:
                print(f"  Summary length: {len(c.summary)}")
        
        print("\nChecking MemoryChunks...")
        result = await db.execute(select(MemoryChunk))
        memories = result.scalars().all()
        print(f"Total memories: {len(memories)}")
        for m in memories:
            print(f"  Memory: {m.chunk_text[:50]}...")

if __name__ == "__main__":
    asyncio.run(main())
