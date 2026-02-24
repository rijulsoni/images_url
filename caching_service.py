"""
Simple in-memory caching service for image search results.
Replace with a DB-backed implementation (e.g. database.py) for persistence.
"""

import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# In-memory cache: key = f"{prefix}:{product_name}" -> list of image entries
_cache: Dict[str, list] = {}


async def get_cached_images(
    product_name: str, prefix: str = "google"
) -> Optional[List]:
    """Return cached image candidates for a product, or None if not cached."""
    key = f"{prefix}:{product_name}"
    result = _cache.get(key)
    if result is not None:
        logger.debug(f"Cache HIT for '{key}' ({len(result)} entries)")
    return result


async def save_cached_images(
    product_name: str, candidates: list, prefix: str = "google"
) -> None:
    """Store image candidates in the cache."""
    key = f"{prefix}:{product_name}"
    _cache[key] = candidates
    logger.debug(f"Cached {len(candidates)} entries for '{key}'")
