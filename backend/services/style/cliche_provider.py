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
禁词表统一访问入口（Phase 1 CP2.2c）。

职责：
- 从 SystemCliche 表加载启用的禁词（带内存缓存）
- 提供 validators.StyleClicheValidator 的数据源
- 缓存失效：SystemCliche 增删改时调用 invalidate_cache()

业务场景：
- StyleClicheValidator 在每次校验前调用 get_active_cliches()
- 路由 /api/system/cliches 的 POST/PUT/DELETE 后调用 invalidate_cache()

设计要点：
- 模块级单例缓存，避免每次校验都查 DB
- 失败时降级到内置种子数据（保功能不崩）
"""

import logging
from typing import Any, Dict, List, Optional

from backend.services.style.default_cliches import get_all_seed_cliches

logger = logging.getLogger(__name__)


# 模块级缓存
_cache: Optional[List[Dict[str, Any]]] = None
_cache_loaded: bool = False


async def get_active_cliches(
    db=None,
    language: Optional[str] = None,
    severity: Optional[str] = None,
    use_cache: bool = True,
) -> List[Dict[str, Any]]:
    """获取启用的禁词列表。

    优先级：
    1. 内存缓存（若 use_cache 且已加载）
    2. DB 查询（若传入 db）
    3. 降级到内置种子数据

    Args:
        db: 可选 AsyncSession。None 时只读缓存或返回种子
        language: 可选语言过滤
        severity: 可选严重性过滤
        use_cache: 是否使用缓存

    Returns:
        List[Dict]: 禁词列表，每项含 {pattern, is_regex, language, category, severity, alternative}
    """
    global _cache, _cache_loaded

    # 命中缓存
    if use_cache and _cache_loaded and _cache is not None:
        return _filter_cliches(_cache, language, severity)

    # DB 查询
    if db is not None:
        try:
            from backend.repositories import SystemClicheRepository
            repo = SystemClicheRepository(db)
            records = await repo.get_active_patterns()
            result = [
                {
                    "pattern": r.pattern,
                    "is_regex": r.is_regex,
                    "language": r.language,
                    "category": r.category,
                    "severity": r.severity,
                    "alternative": r.alternative,
                }
                for r in records
            ]
            _cache = result
            _cache_loaded = True
            return _filter_cliches(_cache, language, severity)
        except Exception as e:
            logger.warning(f"[ClicheProvider] DB 查询失败，降级到种子数据: {e}")

    # 降级到种子数据
    seeds = get_all_seed_cliches()
    return _filter_cliches(seeds, language, severity)


def _filter_cliches(
    items: List[Dict[str, Any]],
    language: Optional[str],
    severity: Optional[str],
) -> List[Dict[str, Any]]:
    """按 language/severity 过滤禁词列表。"""
    result = []
    for item in items:
        if language and item.get("language") != language:
            continue
        if severity and item.get("severity") != severity:
            continue
        result.append(item)
    return result


def invalidate_cache() -> None:
    """缓存失效。SystemCliche 增删改后调用。"""
    global _cache, _cache_loaded
    _cache = None
    _cache_loaded = False
    logger.info("[ClicheProvider] 缓存已失效")
