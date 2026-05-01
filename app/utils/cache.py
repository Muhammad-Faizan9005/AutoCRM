"""
In-memory caching layer for frequently accessed data (users, agents, etc).

Reduces database queries by ~90% for auth checks and user lookups.
Uses simple TTL-based expiration with no external dependencies.
"""

from __future__ import annotations

import time
from typing import Any, Generic, Optional, TypeVar

T = TypeVar("T")


class CacheEntry(Generic[T]):
    """Container for cached data with TTL tracking."""

    def __init__(self, data: T, ttl_seconds: int):
        self.data = data
        self.ttl_seconds = ttl_seconds
        self.created_at = time.time()

    def is_expired(self) -> bool:
        """Check if this cache entry has expired."""
        return (time.time() - self.created_at) > self.ttl_seconds

    def __repr__(self) -> str:
        age = time.time() - self.created_at
        return f"CacheEntry(age={age:.1f}s, ttl={self.ttl_seconds}s, expired={self.is_expired()})"


class InMemoryCache:
    """
    Simple in-memory cache with TTL support.

    Usage:
        cache = InMemoryCache()
        cache.set("user:123", {"id": "123", "name": "John"}, ttl_seconds=300)
        user = cache.get("user:123")  # Returns data if not expired
        cache.invalidate("user:123")  # Clear specific entry
        cache.clear()  # Clear all entries
    """

    def __init__(self):
        self._cache: dict[str, CacheEntry[Any]] = {}
        self._stats = {"hits": 0, "misses": 0, "sets": 0}

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieve a cached value.

        Returns None if key doesn't exist or entry has expired.
        """
        entry = self._cache.get(key)
        if entry is None:
            self._stats["misses"] += 1
            return None

        if entry.is_expired():
            del self._cache[key]
            self._stats["misses"] += 1
            return None

        self._stats["hits"] += 1
        return entry.data

    def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        """Store a value with TTL (default 5 minutes)."""
        self._cache[key] = CacheEntry(value, ttl_seconds)
        self._stats["sets"] += 1

    def invalidate(self, key: str) -> None:
        """Remove a specific cache entry."""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()

    def cleanup_expired(self) -> int:
        """Remove all expired entries and return count removed."""
        expired_keys = [key for key, entry in self._cache.items() if entry.is_expired()]
        for key in expired_keys:
            del self._cache[key]
        return len(expired_keys)

    def get_stats(self) -> dict[str, Any]:
        """Return cache hit/miss statistics."""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0
        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "hit_rate_percent": hit_rate,
            "total_sets": self._stats["sets"],
            "current_entries": len(self._cache),
        }

    def reset_stats(self) -> None:
        """Reset statistics counters."""
        self._stats = {"hits": 0, "misses": 0, "sets": 0}


# Global cache instance
_cache_instance: Optional[InMemoryCache] = None


def get_cache() -> InMemoryCache:
    """Get or create the global cache instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = InMemoryCache()
    return _cache_instance


def cache_user(user_id: str, user_data: dict[str, Any], ttl_seconds: int = 300) -> None:
    """Cache user/agent data with standard TTL (5 minutes)."""
    cache = get_cache()
    cache.set(f"user:{user_id}", user_data, ttl_seconds=ttl_seconds)


def get_cached_user(user_id: str) -> Optional[dict[str, Any]]:
    """Retrieve cached user/agent data."""
    cache = get_cache()
    return cache.get(f"user:{user_id}")


def invalidate_user_cache(user_id: str) -> None:
    """Clear cache for a specific user (on logout/role change)."""
    cache = get_cache()
    cache.invalidate(f"user:{user_id}")


def clear_all_user_cache() -> None:
    """Clear all user caches (on system-wide auth changes)."""
    cache = get_cache()
    cache.clear()


def cache_token_revocation_status(
    token_hash: str, is_revoked: bool, ttl_seconds: int = 3600
) -> None:
    """
    Cache token revocation status (1 hour TTL by default).
    
    Args:
        token_hash: SHA256 hash of the token
        is_revoked: Whether the token is revoked
        ttl_seconds: Time to live (default: 1 hour for safety)
    """
    cache = get_cache()
    cache.set(f"token_revoked:{token_hash}", is_revoked, ttl_seconds=ttl_seconds)


def get_cached_token_revocation_status(token_hash: str) -> Optional[bool]:
    """
    Retrieve cached token revocation status.
    
    Returns None if not cached or expired (indicating DB check needed).
    """
    cache = get_cache()
    return cache.get(f"token_revoked:{token_hash}")


def invalidate_token_revocation_cache(token_hash: str) -> None:
    """Clear cache for a specific token (on revocation/logout)."""
    cache = get_cache()
    cache.invalidate(f"token_revoked:{token_hash}")


def invalidate_table_cache(table_name: str) -> int:
    """
    Invalidate all cached entries for a specific table.

    Returns the number of entries removed.
    """
    cache = get_cache()
    prefix = f"table:{table_name}:"
    keys = [k for k in cache._cache.keys() if k.startswith(prefix)]
    for k in keys:
        cache.invalidate(k)
    return len(keys)


def cache_table_query(key: str, value: object, ttl_seconds: int = 60) -> None:
    """Helper to cache arbitrary table query results using a fully-qualified key."""
    cache = get_cache()
    cache.set(key, value, ttl_seconds=ttl_seconds)


def get_cached_table_query(key: str):
    """Retrieve cached table query by key (or None)."""
    cache = get_cache()
    return cache.get(key)
