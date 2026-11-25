"""
Resort Client Module for Mud & Meadows API.

Provides an asynchronous HTTP client to interact with all public endpoints of
the resort backend: cottages, accommodations, dining, wellness, experiences,
coupon quoting, Razorpay orders, and public booking confirmation.
"""

from typing import Any, Dict, List, Optional
import httpx
from config import settings


class ResortAPIError(Exception):
    """Custom exception raised when the Resort API returns an error."""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Resort API Error [{status_code}]: {detail}")


class ResortClient:
    """Asynchronous client for interacting with the Mud & Meadows Resort API."""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 15.0):
        self.base_url = (base_url or settings.RESORT_API_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._cached_cottages: List[Dict[str, Any]] = []

    def _get_client(self) -> httpx.AsyncClient:
        """Creates an AsyncClient with standard headers and connection pooling."""
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={
                "Accept": "application/json",
                "User-Agent": "MudAndMeadows-AI-Concierge/1.0",
            },
        )

    # =========================================================================
    # 1. COTTAGES, ROOMS & ACCOMMODATIONS
    # =========================================================================

    async def get_cottages(self) -> List[Dict[str, Any]]:
        """Fetch all cottages with pricing, capacity, and amenities. Uses memory cache as fallback."""
        try:
            async with self._get_client() as client:
                response = await client.get("/api/cottages/")
                if response.status_code == 200:
                    data = response.json()
                    if data:
                        self._cached_cottages = data
                    return data
        except Exception as e:
            if self._cached_cottages:
                return self._cached_cottages
            raise ResortAPIError(500, f"Failed to fetch cottages: {e}")
        return self._cached_cottages

    async def get_cottage_details(self, cottage_id: str) -> Dict[str, Any]:
        """Fetch detailed information for a specific cottage."""
        async with self._get_client() as client:
            response = await client.get(f"/api/cottages/{cottage_id}")
            if response.status_code != 200:
                raise ResortAPIError(response.status_code, response.text)
            return response.json()

    async def get_amenities(self) -> List[Dict[str, Any]]:
        """Fetch resort amenities list with icons and descriptions."""
        async with self._get_client() as client:
            response = await client.get("/api/cottages/amenities")
            if response.status_code != 200:
                raise ResortAPIError(response.status_code, response.text)
            return response.json()

    async def get_accommodations(self) -> List[Dict[str, Any]]:
        """Fetch all accommodation types (stays)."""
        async with self._get_client() as client:
            response = await client.get("/api/accommodations/accommodations/")
            if response.status_code != 200:
                raise ResortAPIError(response.status_code, response.text)
            return response.json()

    # =========================================================================
    # 2. RESORT EXPERIENCES, WELLNESS & DINING (ADD-ONS & UP-SELLS)
    # =========================================================================

    async def get_dining_menu(self) -> List[Dict[str, Any]]:
        """Fetch all restaurant dining menu items and categories."""
        async with self._get_client() as client:
            response = await client.get("/api/dining/all")
            if response.status_code != 200:
                raise ResortAPIError(response.status_code, response.text)
            return response.json()

    async def get_wellness_programs(self) -> List[Dict[str, Any]]:
        """Fetch spa, yoga, and wellness treatment programs."""
        async with self._get_client() as client:
            response = await client.get("/api/wellness/programs")
            if response.status_code != 200:
                raise ResortAPIError(response.status_code, response.text)
            return response.json()

    async def get_experiences(self) -> List[Dict[str, Any]]:
        """Fetch curated resort experiences (nature walks, campfires, pottery)."""
        async with self._get_client() as client:
            response = await client.get("/api/experiences/")
            if response.status_code != 200:
                raise ResortAPIError(response.status_code, response.text)
            return response.json()

    async def get_packages(self) -> List[Dict[str, Any]]:
        """Fetch all special stay packages and multi-day retreat offers."""
        async with self._get_client() as client:
            response = await client.get("/api/packages/")
            if response.status_code != 200:
                raise ResortAPIError(response.status_code, response.text)
            return response.json()

    # =========================================================================
    # 3. COUPONS & QUOTE CALCULATION
    # =========================================================================

    async def quote_coupon(self, coupon_code: str, total_amount: float) -> Dict[str, Any]:
        """
        Validate and calculate discount for a promo coupon code.
        Endpoint: POST /api/coupons/quote
        Payload: { "code": coupon_code, "amount": total_amount }
        """
        async with self._get_client() as client:
            payload = {"code": coupon_code.strip().upper(), "amount": total_amount}
            response = await client.post("/api/coupons/quote", json=payload)
            if response.status_code != 200:
                raise ResortAPIError(response.status_code, response.text)
            return response.json()

    # =========================================================================
    # 4. PAYMENTS & ORDER CREATION (RAZORPAY)
    # =========================================================================

    async def create_razorpay_order(
        self, amount_in_rupees: float, receipt: str, notes: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Creates a Razorpay order via resort backend.
        Amount is converted to paise (amount * 100) if required by the API.
        Endpoint: POST /api/razorpay/order
        """
        async with self._get_client() as client:
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
        """
        Verifies the Razorpay payment signature via resort backend.
        Endpoint: POST /api/razorpay/verify
        """
        async with self._get_client() as client:
            payload = {
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": signature,
            }
            response = await client.post("/api/razorpay/verify", json=payload)
            if response.status_code != 200:
                raise ResortAPIError(response.status_code, response.text)
            return response.json()

    # =========================================================================
    # 5. BOOKING SUBMISSION & GUEST LOOKUP
    # =========================================================================

    async def create_public_booking(
        self, booking_data: Dict[str, Any], payment_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Confirms and creates a booking after successful payment.
        Endpoint: POST /api/bookings/public
        Payload: { "booking": { ... }, "payment": { ... }, "source": "public_web" }
        """
        async with self._get_client() as client:
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
        """Fetch all existing bookings for a given guest email address."""
        async with self._get_client() as client:
            response = await client.get(f"/api/bookings/guest/{guest_email.strip().lower()}")
            if response.status_code != 200:
                raise ResortAPIError(response.status_code, response.text)
            return response.json()

    async def get_site_settings(self) -> Dict[str, Any]:
        """Fetch resort policies, terms, and check-in / check-out times."""
        async with self._get_client() as client:
            response = await client.get("/api/site-settings/main")
            if response.status_code != 200:
                raise ResortAPIError(response.status_code, response.text)
            return response.json()


# Singleton instance of the client for reuse across the app
resort_client = ResortClient()
