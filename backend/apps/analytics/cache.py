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
from django.utils import timezone

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


def get_or_compute(
    brand_id: int,
    endpoint: str,
    filters: dict,
    compute_fn,
    ttl: int = DEFAULT_TTL,
    force_refresh: bool = False,
):
    """Returns (result, was_cache_hit, cached_at). cached_at is an ISO-8601
    timestamp of when compute_fn last actually ran for this exact
    brand/endpoint/filters combination -- set on every write, read back
    unchanged on every hit, so the frontend can show "as of <time>"
    regardless of whether this particular call was a hit or a miss.

    force_refresh=True (the manual refresh button) skips the cache read
    entirely and always recomputes, same as a miss would, refreshing
    cached_at too -- it does not bump the per-brand version, so it has no
    effect on any other in-flight filter combination's cache entries.
    """
    key = _cache_key(brand_id, endpoint, filters)
    if not force_refresh:
        cached = cache.get(key)
        if cached is not None:
            return cached["data"], True, cached["cached_at"]
    result = compute_fn()
    cached_at = timezone.now().isoformat()
    cache.set(key, {"data": result, "cached_at": cached_at}, timeout=ttl)
    return result, False, cached_at
