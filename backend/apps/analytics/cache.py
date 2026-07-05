"""Cache-aside for analytics reads, keyed by filter-hash, busted on that
brand's upload.

Busting increments a per-brand version counter rather than deleting keys --
old entries just become unreachable (and expire via TTL on their own) since
every cache key embeds the current version. Cheap (O(1), no SCAN) and avoids
Redis's usual pattern-delete antipattern.
"""

import hashlib
import json

from django.core.cache import cache

DEFAULT_TTL = 900  # 15 minutes; explicit bust on upload is the real freshness guarantee


def _version_key(brand_id: int) -> str:
    return f"analytics:version:{brand_id}"


def _version(brand_id: int) -> int:
    return cache.get_or_set(_version_key(brand_id), 1, timeout=None)


def bust(brand_id: int) -> None:
    """Called after a successful load + MV refresh."""
    key = _version_key(brand_id)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=None)


def _cache_key(brand_id: int, endpoint: str, filters: dict) -> str:
    version = _version(brand_id)
    filter_hash = hashlib.sha256(
        json.dumps(filters, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    return f"analytics:{brand_id}:v{version}:{endpoint}:{filter_hash}"


def get_or_compute(brand_id: int, endpoint: str, filters: dict, compute_fn, ttl: int = DEFAULT_TTL):
    """Returns (result, was_cache_hit)."""
    key = _cache_key(brand_id, endpoint, filters)
    cached = cache.get(key)
    if cached is not None:
        return cached, True
    result = compute_fn()
    cache.set(key, result, timeout=ttl)
    return result, False
