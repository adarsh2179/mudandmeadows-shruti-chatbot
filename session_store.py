"""
State Persistence, Idempotency & Rate Limiting Module.

Provides $0.00-cost persistent storage using SQLite in WAL mode paired with
a bounded in-memory LRU read cache, plus an O(1) sliding-window rate limiter.
Survives Uvicorn multi-worker restarts while preventing unbounded RAM growth.
"""

from collections import OrderedDict, deque
from contextlib import closing
import json
import sqlite3
import threading
import time
from typing import Any, Deque, Dict, List, Optional, Tuple
from google.genai import types

from config import settings


class SessionStore:
    """
    Bounded in-memory LRU cache backed by SQLite (WAL mode) for session
    history, last quote retrieval, and payment idempotency records.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        max_cache_items: int = 500,
    ):
        self.db_path = db_path or settings.SESSION_DB_PATH
        self.ttl_seconds = ttl_seconds if ttl_seconds is not None else settings.SESSION_TTL_SECONDS
        self.max_cache_items = max_cache_items
        self._lock = threading.RLock()
        self._memory_cache: "OrderedDict[str, Tuple[List[types.Content], Optional[Dict[str, Any]], float]]" = OrderedDict()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        history_json TEXT NOT NULL,
                        last_quote_json TEXT,
                        updated_at REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS payment_orders (
                        idempotency_key TEXT PRIMARY KEY,
                        order_id TEXT NOT NULL,
                        order_json TEXT NOT NULL,
                        booking_payload_json TEXT,
                        status TEXT NOT NULL DEFAULT 'created',
                        created_at REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_payment_order_id ON payment_orders(order_id)"
                )
                conn.commit()

    def _prune_expired_sync(self, conn: sqlite3.Connection, now: float) -> None:
        cutoff = now - self.ttl_seconds
        conn.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))
        # Keep idempotency payment records for 24 hours so late webhooks reconcile
        conn.execute("DELETE FROM payment_orders WHERE created_at < ?", (now - 86400,))

    def get_session(self, session_id: str) -> Tuple[List[types.Content], Optional[Dict[str, Any]]]:
        """Retrieves non-expired session history and last calculated quote."""
        now = time.time()
        with self._lock:
            cached = self._memory_cache.get(session_id)
            if cached:
                history, last_quote, updated_at = cached
                if now - updated_at <= self.ttl_seconds:
                    self._memory_cache.move_to_end(session_id)
                    return list(history), last_quote
                self._memory_cache.pop(session_id, None)

            with closing(self._connect()) as conn, conn:
                row = conn.execute(
                    "SELECT history_json, last_quote_json, updated_at FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()

                if not row:
                    return [], None

                history_json, last_quote_json, updated_at = row
                if now - updated_at > self.ttl_seconds:
                    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
                    conn.commit()
                    return [], None

                raw_history = json.loads(history_json)
                history = [types.Content.model_validate(item) for item in raw_history]
                last_quote = json.loads(last_quote_json) if last_quote_json else None

                self._put_memory_cache(session_id, history, last_quote, updated_at)
                return list(history), last_quote

    def save_session(
        self,
        session_id: str,
        history: List[types.Content],
        last_quote: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persists trimmed session state cleanly to cache and SQLite WAL."""
        now = time.time()
        serialized_history = json.dumps(
            [c.model_dump(mode="json", exclude_none=True) for c in history]
        )
        serialized_quote = json.dumps(last_quote) if last_quote is not None else None

        with self._lock:
            self._put_memory_cache(session_id, list(history), last_quote, now)
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    """
                    INSERT INTO sessions (session_id, history_json, last_quote_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        history_json = excluded.history_json,
                        last_quote_json = COALESCE(excluded.last_quote_json, sessions.last_quote_json),
                        updated_at = excluded.updated_at
                    """,
                    (session_id, serialized_history, serialized_quote, now),
                )
                # Periodic lightweight housekeeping (~1 in 20 writes)
                if int(now) % 20 == 0:
                    self._prune_expired_sync(conn, now)
                conn.commit()

    def _put_memory_cache(
        self,
        session_id: str,
        history: List[types.Content],
        last_quote: Optional[Dict[str, Any]],
        updated_at: float,
    ) -> None:
        self._memory_cache[session_id] = (history, last_quote, updated_at)
        self._memory_cache.move_to_end(session_id)
        while len(self._memory_cache) > self.max_cache_items:
            self._memory_cache.popitem(last=False)

    # -------------------------------------------------------------------------
    # PAYMENT IDEMPOTENCY & WEBHOOK RECONCILIATION
    # -------------------------------------------------------------------------

    def get_idempotent_order(
        self, idempotency_key: str, window_seconds: int = 900
    ) -> Optional[Dict[str, Any]]:
        """Returns cached order within the 15-minute idempotency window."""
        now = time.time()
        with self._lock:
            with closing(self._connect()) as conn, conn:
                row = conn.execute(
                    "SELECT order_json, created_at FROM payment_orders WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if not row:
                    return None
                order_json, created_at = row
                if now - created_at <= window_seconds:
                    return json.loads(order_json)
                return None

    def save_payment_order(
        self,
        idempotency_key: str,
        order_id: str,
        order_data: Dict[str, Any],
        booking_payload: Optional[Dict[str, Any]] = None,
        status: str = "created",
    ) -> None:
        """Persists order details for idempotency checks and webhook booking recovery."""
        now = time.time()
        with self._lock:
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    """
                    INSERT INTO payment_orders (idempotency_key, order_id, order_json, booking_payload_json, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(idempotency_key) DO UPDATE SET
                        order_id = excluded.order_id,
                        order_json = excluded.order_json,
                        booking_payload_json = COALESCE(excluded.booking_payload_json, payment_orders.booking_payload_json),
                        status = excluded.status
                    """,
                    (
                        idempotency_key,
                        order_id,
                        json.dumps(order_data),
                        json.dumps(booking_payload) if booking_payload else None,
                        status,
                        now,
                    ),
                )
                conn.commit()

    def get_order_by_razorpay_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Fetches stored order and staged booking details by Razorpay order_id for webhook recovery."""
        with self._lock:
            with closing(self._connect()) as conn, conn:
                row = conn.execute(
                    "SELECT order_json, booking_payload_json, status FROM payment_orders WHERE order_id = ?",
                    (order_id,),
                ).fetchone()
                if not row:
                    return None
                return {
                    "order": json.loads(row[0]),
                    "booking_payload": json.loads(row[1]) if row[1] else None,
                    "status": row[2],
                }

    def mark_order_confirmed(self, order_id: str) -> None:
        """Marks an order as confirmed idempotently so duplicate webhooks don't double-book."""
        with self._lock:
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    "UPDATE payment_orders SET status = 'confirmed' WHERE order_id = ?",
                    (order_id,),
                )
                conn.commit()


class SlidingWindowRateLimiter:
    """
    Zero-cost in-memory sliding-window rate limiter keyed by client IP + route bucket.
    Prevents free-tier Gemini quota exhaustion and automated endpoint abuse.
    """

    def __init__(self, window_seconds: int = 60, max_tracked_keys: int = 2000):
        self.window_seconds = window_seconds
        self.max_tracked_keys = max_tracked_keys
        self._lock = threading.Lock()
        self._buckets: Dict[str, Deque[float]] = {}

    def is_allowed(self, key: str, max_requests: int) -> Tuple[bool, int]:
        """
        Checks if a request for `key` fits within `max_requests` per sliding window.
        Returns (allowed: bool, retry_after_seconds: int).
        """
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            if len(self._buckets) > self.max_tracked_keys:
                # Reclaim memory from expired buckets
                stale = [k for k, q in self._buckets.items() if not q or q[-1] < cutoff]
                for k in stale:
                    del self._buckets[k]

            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= max_requests:
                retry_after = max(1, int(self.window_seconds - (now - bucket[0])) + 1)
                return False, retry_after

            bucket.append(now)
            return True, 0


session_store = SessionStore()
rate_limiter = SlidingWindowRateLimiter(window_seconds=60)
