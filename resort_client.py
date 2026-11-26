"""
Resort Client Module for Mud & Meadows API.

Provides an asynchronous HTTP client with persistent TCP connection pooling
and a short-TTL read-through cache for catalog data, minimizing TLS handshake
overhead across multi-turn tool executions.
"""

import re
import time
from typing import Any, Dict, List, Optional, Tuple
import httpx

from config import settings

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class ResortAPIError(Exception):
    """Raised when the upstream Resort API returns a non-success response or transport failure."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Resort API Error [{status_code}]: {detail}")


class ResortClient:
    """Persistent async HTTP client wrapping the Mud & Meadows Cloud Run REST API."""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 15.0, catalog_ttl: float = 30.0):
        self.base_url = (base_url or settings.RESORT_API_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.catalog_ttl = catalog_ttl
        self._client: Optional[httpx.AsyncClient] = None
        self._ttl_cache: Dict[str, Tuple[Any, float]] = {}
        self._stale_cottages: List[Dict[str, Any]] = []

    async def startup(self) -> None:
        """Initializes the shared HTTP connection pool at application startup."""
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                limits=limits,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "MudAndMeadows-AI-Concierge/1.1",
                },
            )

    async def shutdown(self) -> None:
        """Closes pooled connections cleanly on server shutdown."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _get_pool(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            await self.startup()
        return self._client  # type: ignore[return-value]

    def _get_cached(self, key: str) -> Optional[Any]:
        entry = self._ttl_cache.get(key)
        if not entry:
            return None
        data, expires_at = entry
        if time.monotonic() <= expires_at:
            return data
        return None

    def _set_cached(self, key: str, data: Any) -> None:
        self._ttl_cache[key] = (data, time.monotonic() + self.catalog_ttl)

    # -------------------------------------------------------------------------
    # 1. COTTAGES, ROOMS & ACCOMMODATIONS (CACHED WITH 30s TTL)
    # -------------------------------------------------------------------------

    async def get_cottages(self) -> List[Dict[str, Any]]:
        """Fetches live cottage inventory with a 30s read-through TTL cache and stale fallback."""
        cached = self._get_cached("cottages")
        if cached is not None:
            return cached

        try:
            client = await self._get_pool()
            response = await client.get("/api/cottages/")
            if response.status_code == 200:
                data = response.json()
                if data:
                    self._stale_cottages = data
                    self._set_cached("cottages", data)
                return data
            raise ResortAPIError(response.status_code, response.text)
        except Exception as e:
            if self._stale_cottages:
                return self._stale_cottages
            raise ResortAPIError(500, f"Failed to fetch cottages: {e}") from e

    async def get_cottage_details(self, cottage_id: str) -> Dict[str, Any]:
        """Fetches detailed specifications and rate card for a specific cottage."""
        clean_id = (cottage_id or "").strip()
        if not _SAFE_ID_RE.match(clean_id) or clean_id.lower() in {"none", "null", "undefined", "nan"}:
            raise ResortAPIError(400, "Invalid cottage ID format.")

        cache_key = f"cottage:{clean_id}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        client = await self._get_pool()
        response = await client.get(f"/api/cottages/{clean_id}")
        if response.status_code != 200:
            raise ResortAPIError(response.status_code, response.text)
        data = response.json()
        self._set_cached(cache_key, data)
        return data

    async def get_amenities(self) -> List[Dict[str, Any]]:
        """Fetches resort amenities catalog."""
        cached = self._get_cached("amenities")
        if cached is not None:
            return cached

        client = await self._get_pool()
        response = await client.get("/api/cottages/amenities")
        if response.status_code != 200:
            raise ResortAPIError(response.status_code, response.text)
        data = response.json()
        self._set_cached("amenities", data)
        return data

    async def get_accommodations(self) -> List[Dict[str, Any]]:
        """Fetches all accommodation tiers."""
        cached = self._get_cached("accommodations")
        if cached is not None:
            return cached

        client = await self._get_pool()
        response = await client.get("/api/accommodations/accommodations/")
        if response.status_code != 200:
            raise ResortAPIError(response.status_code, response.text)
        data = response.json()
        self._set_cached("accommodations", data)
        return data

    # -------------------------------------------------------------------------
    # 2. RESORT EXPERIENCES, WELLNESS & DINING
    # -------------------------------------------------------------------------

    async def get_dining_menu(self) -> List[Dict[str, Any]]:
        """Fetches dining menu items."""
        cached = self._get_cached("dining")
        if cached is not None:
            return cached

        client = await self._get_pool()
        response = await client.get("/api/dining/all")
        if response.status_code != 200:
            raise ResortAPIError(response.status_code, response.text)
        data = response.json()
        self._set_cached("dining", data)
        return data

    async def get_wellness_programs(self) -> List[Dict[str, Any]]:
        """Fetches spa, yoga, and wellness programs."""
        cached = self._get_cached("wellness")
        if cached is not None:
            return cached

        client = await self._get_pool()
        response = await client.get("/api/wellness/programs")
        if response.status_code != 200:
            raise ResortAPIError(response.status_code, response.text)
        data = response.json()
        self._set_cached("wellness", data)
        return data

    async def get_experiences(self) -> List[Dict[str, Any]]:
        """Fetches curated resort activities and experiences."""
        cached = self._get_cached("experiences")
        if cached is not None:
            return cached

        client = await self._get_pool()
        response = await client.get("/api/experiences/")
        if response.status_code != 200:
            raise ResortAPIError(response.status_code, response.text)
        data = response.json()
        self._set_cached("experiences", data)
        return data

    async def get_packages(self) -> List[Dict[str, Any]]:
        """Fetches multi-day stay packages."""
        cached = self._get_cached("packages")
        if cached is not None:
            return cached

        client = await self._get_pool()
        response = await client.get("/api/packages/")
        if response.status_code != 200:
            raise ResortAPIError(response.status_code, response.text)
        data = response.json()
        self._set_cached("packages", data)
        return data

    # -------------------------------------------------------------------------
    # 3. COUPONS & PAYMENTS (NEVER CACHED)
    # -------------------------------------------------------------------------

    async def quote_coupon(self, coupon_code: str, total_amount: float) -> Dict[str, Any]:
        """Validates a promo coupon code against live backend rules."""
        client = await self._get_pool()
        payload = {"code": coupon_code.strip().upper(), "amount": total_amount}
        response = await client.post("/api/coupons/quote", json=payload)
        if response.status_code != 200:
            raise ResortAPIError(response.status_code, response.text)
        return response.json()

    async def create_razorpay_order(
        self, amount_in_rupees: float, receipt: str, notes: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Creates a Razorpay order via the upstream resort backend."""
        client = await self._get_pool()
        payload = {
            "amount": float(amount_in_rupees),
            "currency": "INR",
            "receipt": receipt,
            "notes": notes or {},
        }
        response = await client.post("/api/razorpay/order", json=payload)
        if response.status_code != 200:
            raise ResortAPIError(response.status_code, response.text)
        return response.json()

    async def verify_razorpay_payment(
        self, order_id: str, payment_id: str, signature: str
    ) -> Dict[str, Any]:
        """Verifies a Razorpay payment signature against upstream resort verification."""
        client = await self._get_pool()
        payload = {
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        }
        response = await client.post("/api/razorpay/verify", json=payload)
        if response.status_code != 200:
            raise ResortAPIError(response.status_code, response.text)
        return response.json()

    # -------------------------------------------------------------------------
    # 4. BOOKING SUBMISSION & GUEST LOOKUP
    # -------------------------------------------------------------------------

    async def create_public_booking(
        self, booking_data: Dict[str, Any], payment_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Commits a confirmed reservation to the property management system."""
        client = await self._get_pool()
        payload = {
            "booking": booking_data,
            "payment": payment_data,
            "source": "chatbot_widget",
        }
        response = await client.post("/api/bookings/public", json=payload)
        if response.status_code not in (200, 201):
            raise ResortAPIError(response.status_code, response.text)
        return response.json()

    async def lookup_guest_bookings(self, guest_email: str) -> List[Dict[str, Any]]:
        """Fetches reservations associated with a guest email for secondary verification."""
        client = await self._get_pool()
        response = await client.get(f"/api/bookings/guest/{guest_email.strip().lower()}")
        if response.status_code != 200:
            raise ResortAPIError(response.status_code, response.text)
        return response.json()

    async def get_site_settings(self) -> Dict[str, Any]:
        """Fetches resort policies and check-in/check-out windows."""
        cached = self._get_cached("site_settings")
        if cached is not None:
            return cached

        client = await self._get_pool()
        response = await client.get("/api/site-settings/main")
        if response.status_code != 200:
            raise ResortAPIError(response.status_code, response.text)
        data = response.json()
        self._set_cached("site_settings", data)
        return data


resort_client = ResortClient()
