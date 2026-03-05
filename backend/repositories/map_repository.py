from uuid import UUID

from backend.models import MapLocation
from backend.repositories.base import BaseRepository, QuerySpec


class MapLocationRepository(BaseRepository[MapLocation]):
    """
    地图/地点仓储
    """
    model = MapLocation

    async def list_by_book(self, book_id: UUID):
        spec = QuerySpec.create(MapLocation).where(MapLocation.book_id == book_id).order(MapLocation.name)
        return await self.find_all(spec=spec)
