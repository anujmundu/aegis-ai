"""Tier 1 Working Memory for AegisAI Operational Reliability Platform.

Provides fast, low-latency (<2ms) volatile state storage for active incident sessions,
in-flight agent checkpoints, and operator approval locks.

Architecture:
- High-performance Redis backend when available.
- Thread-safe, self-expiring in-memory fallback for local zero-dependency operation.
"""

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from ai.agents.state import AgentState

logger = logging.getLogger("aegisai.memory.working")


class InMemoryWorkingStore:
    """Thread-safe in-memory dictionary storage with automatic TTL expiry."""

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}
        self._locks: Dict[str, str] = {}
        self._lock_expiry: Dict[str, float] = {}
        self._mu = threading.RLock()

    def _purge_expired(self) -> None:
        now = time.time()
        with self._mu:
            expired_keys = [k for k, v in self._store.items() if v.get("expires_at", 0) <= now]
            for k in expired_keys:
                del self._store[k]

            expired_locks = [k for k, exp in self._lock_expiry.items() if exp <= now]
            for k in expired_locks:
                self._locks.pop(k, None)
                self._lock_expiry.pop(k, None)

    def set(self, key: str, value: Dict[str, Any], ttl_seconds: int = 86400) -> None:
        with self._mu:
            self._purge_expired()
            expires_at = time.time() + ttl_seconds
            self._store[key] = {
                "data": value,
                "expires_at": expires_at,
                "updated_at": time.time(),
            }

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._mu:
            self._purge_expired()
            entry = self._store.get(key)
            if entry and entry["expires_at"] > time.time():
                return entry["data"]
            return None

    def delete(self, key: str) -> bool:
        with self._mu:
            existed = key in self._store
            self._store.pop(key, None)
            self._locks.pop(key, None)
            self._lock_expiry.pop(key, None)
            return existed

    def list_keys(self) -> List[str]:
        with self._mu:
            self._purge_expired()
            return list(self._store.keys())

    def acquire_lock(self, key: str, token: str, ttl_seconds: int = 300) -> bool:
        with self._mu:
            self._purge_expired()
            now = time.time()
            if key in self._locks and self._lock_expiry.get(key, 0) > now:
                # Lock already held by active token
                return self._locks[key] == token
            self._locks[key] = token
            self._lock_expiry[key] = now + ttl_seconds
            return True

    def release_lock(self, key: str, token: str) -> bool:
        with self._mu:
            self._purge_expired()
            if key in self._locks and self._locks[key] == token:
                del self._locks[key]
                self._lock_expiry.pop(key, None)
                return True
            return False


class WorkingMemory:
    """Tier 1 Working Memory manager coordinating active incident lifecycle state."""

    def __init__(self, redis_url: Optional[str] = None) -> None:
        self.redis_url = redis_url
        self._redis_client = None
        self._local_store = InMemoryWorkingStore()

        if redis_url:
            try:
                import redis
                client = redis.from_url(redis_url, decode_responses=True)
                client.ping()
                self._redis_client = client
                logger.info("Tier 1 Working Memory connected to Redis at %s", redis_url)
            except Exception as e:
                logger.warning(
                    "Redis unavailable (%s); falling back to thread-safe local Working Memory.", e
                )
                self._redis_client = None

    @property
    def is_redis_active(self) -> bool:
        """Return True if a live Redis cluster connection is active."""
        return self._redis_client is not None

    def set_state(self, state: AgentState, ttl_seconds: int = 86400) -> None:
        """Persist or update an active incident investigation state."""
        key = f"aegis:state:{state.incident_id}"
        payload = state.model_dump_json()

        if self._redis_client:
            try:
                self._redis_client.setex(key, ttl_seconds, payload)
                return
            except Exception as e:
                logger.error("Redis write failure (%s); syncing to local store.", e)

        self._local_store.set(key, json.loads(payload), ttl_seconds)

    def get_state(self, incident_id: str) -> Optional[AgentState]:
        """Retrieve active incident state by incident ID."""
        key = f"aegis:state:{incident_id}"

        if self._redis_client:
            try:
                raw = self._redis_client.get(key)
                if raw:
                    return AgentState.model_validate_json(raw)
            except Exception as e:
                logger.error("Redis read failure (%s); checking local store.", e)

        data = self._local_store.get(key)
        if data:
            return AgentState.model_validate(data)
        return None

    def update_state_patch(self, incident_id: str, patch: Dict[str, Any]) -> Optional[AgentState]:
        """Apply a partial attribute update to an active in-flight incident state."""
        current = self.get_state(incident_id)
        if not current:
            return None

        data = current.model_dump()
        data.update(patch)
        updated = AgentState.model_validate(data)
        self.set_state(updated)
        return updated

    def delete_state(self, incident_id: str) -> bool:
        """Evict an incident from active working memory (e.g. after full resolution)."""
        key = f"aegis:state:{incident_id}"
        deleted = False

        if self._redis_client:
            try:
                deleted = bool(self._redis_client.delete(key))
            except Exception as e:
                logger.error("Redis delete error: %s", e)

        local_deleted = self._local_store.delete(key)
        return deleted or local_deleted

    def acquire_approval_lock(self, incident_id: str, token: str, ttl_seconds: int = 300) -> bool:
        """Atomically lock an incident during human operator approval review."""
        lock_key = f"aegis:lock:{incident_id}"

        if self._redis_client:
            try:
                # nx=True sets only if not exists
                acquired = self._redis_client.set(lock_key, token, ex=ttl_seconds, nx=True)
                return bool(acquired)
            except Exception as e:
                logger.error("Redis lock acquisition error: %s", e)

        return self._local_store.acquire_lock(lock_key, token, ttl_seconds)

    def verify_and_release_lock(self, incident_id: str, token: str) -> bool:
        """Verify the approval token and release the operational lock."""
        lock_key = f"aegis:lock:{incident_id}"

        if self._redis_client:
            try:
                val = self._redis_client.get(lock_key)
                if val == token:
                    self._redis_client.delete(lock_key)
                    return True
                return False
            except Exception as e:
                logger.error("Redis lock release error: %s", e)

        return self._local_store.release_lock(lock_key, token)

    def list_active_incident_ids(self) -> List[str]:
        """List all incident IDs currently in active working memory."""
        if self._redis_client:
            try:
                keys = self._redis_client.keys("aegis:state:*")
                return [k.replace("aegis:state:", "") for k in keys]
            except Exception as e:
                logger.error("Redis keys scan error: %s", e)

        return [k.replace("aegis:state:", "") for k in self._local_store.list_keys()]
