"""
Pricing Engine Module for Mud & Meadows AI Concierge.

Enforces deterministic financial arithmetic using Decimal precision (ROUND_HALF_UP)
for booking calculations. Eliminates floating-point rounding drift and LLM arithmetic
hallucinations across nights, extra beds, promotional coupons, and Indian GST slabs.
"""

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from resort_client import resort_client

TWO_PLACES = Decimal("0.01")


def _to_decimal(val: Any) -> Decimal:
    """Converts numeric input to Decimal via string representation to avoid binary float noise."""
    return Decimal(str(val or 0))


def _round_currency(val: Decimal) -> float:
    """Rounds a Decimal monetary amount using financial half-up rounding to 2 decimal places."""
    return float(val.quantize(TWO_PLACES, rounding=ROUND_HALF_UP))


class AddOnItem(BaseModel):
    """An optional service added to the stay (dining, spa, experience)."""
    id: str
    name: str
    category: str = "general"
    price: float = Field(ge=0.0, description="Price in INR")
    quantity: int = Field(default=1, ge=1)


class PriceQuote(BaseModel):
    """Detailed, itemized invoice breakdown for a stay."""
    cottage_id: str
    cottage_name: str
    check_in: str
    check_out: str
    nights: int
    adults: int
    children: int
    extra_beds: int
    price_per_night: float
    base_room_rent: float
    extra_bed_total: float
    add_ons: List[AddOnItem] = []
    add_ons_total: float = 0.0
    subtotal_before_discount: float
    coupon_code: Optional[str] = None
    coupon_discount: float = 0.0
    coupon_valid: bool = False
    taxable_amount: float
    gst_percent: float
    gst_amount: float
    grand_total: float
    currency: str = "INR"


class PricingEngine:
    """Deterministic financial calculator for resort stay quotes and invoices."""

    @staticmethod
    def parse_and_validate_dates(check_in_str: str, check_out_str: str) -> int:
        """
        Validates check-in and check-out ISO dates and chronological order.
        Returns the integer number of nights.
        """
        try:
            check_in = datetime.strptime(check_in_str.strip(), "%Y-%m-%d").date()
            check_out = datetime.strptime(check_out_str.strip(), "%Y-%m-%d").date()
        except ValueError as err:
            raise ValueError(
                f"Invalid date format: '{check_in_str}' or '{check_out_str}'. Expected YYYY-MM-DD."
            ) from err

        if check_in < date.today():
            raise ValueError(
                f"Check-in date ({check_in_str}) cannot be in the past."
            )

        if check_out <= check_in:
            raise ValueError(
                f"Check-out date ({check_out_str}) must be after check-in date ({check_in_str})."
            )

        return (check_out - check_in).days

    @staticmethod
    def get_applicable_gst_percent(price_per_night: Decimal) -> Decimal:
        """
        Calculates statutory Indian hotel GST rate based on CBIC tariff brackets:
        - Room tariff <= Rs. 7,500/night: 12% GST
        - Room tariff >  Rs. 7,500/night: 18% GST
        """
        return Decimal("18.0") if price_per_night > Decimal("7500.00") else Decimal("12.0")

    async def calculate_quote(
        self,
        cottage: Dict[str, Any],
        check_in_str: str,
        check_out_str: str,
        adults: int = 2,
        children: int = 0,
        extra_beds: int = 0,
        coupon_code: Optional[str] = None,
        add_ons: Optional[List[AddOnItem]] = None,
    ) -> PriceQuote:
        """
        Generates an exact, auditable PriceQuote using Decimal arithmetic.
        """
        nights = self.parse_and_validate_dates(check_in_str, check_out_str)
        nights_dec = Decimal(nights)

        cottage_id = str(cottage.get("id") or cottage.get("_id") or "")
        cottage_name = cottage.get("name", "Resort Cottage")
        price_per_night = _to_decimal(
            cottage.get("price_per_night")
            or cottage.get("price")
            or cottage.get("offer_price")
            or 0
        )
        extra_bed_unit_price = _to_decimal(cottage.get("extra_bedding_price") or 1500)

        base_room_rent = price_per_night * nights_dec
        extra_bed_total = Decimal(max(0, extra_beds)) * extra_bed_unit_price * nights_dec

        selected_add_ons = add_ons or []
        add_ons_total = sum(
            (_to_decimal(item.price) * Decimal(item.quantity) for item in selected_add_ons),
            Decimal("0.00"),
        )

        subtotal = base_room_rent + extra_bed_total + add_ons_total

        coupon_discount = Decimal("0.00")
        coupon_valid = False
        clean_coupon = coupon_code.strip().upper() if coupon_code else None

        if clean_coupon:
            try:
                quote_resp = await resort_client.quote_coupon(clean_coupon, _round_currency(subtotal))
                if quote_resp and "discount" in quote_resp:
                    coupon_discount = _to_decimal(quote_resp["discount"])
                    coupon_valid = True
                elif quote_resp and "discount_amount" in quote_resp:
                    coupon_discount = _to_decimal(quote_resp["discount_amount"])
                    coupon_valid = True
            except Exception:
                coupon_valid = False
                coupon_discount = Decimal("0.00")

        taxable_amount = max(Decimal("0.00"), subtotal - coupon_discount)

        gst_percent = self.get_applicable_gst_percent(price_per_night)
        gst_amount = (taxable_amount * gst_percent / Decimal("100")).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )
        grand_total = taxable_amount + gst_amount

        return PriceQuote(
            cottage_id=cottage_id,
            cottage_name=cottage_name,
            check_in=check_in_str,
            check_out=check_out_str,
            nights=nights,
            adults=adults,
            children=children,
            extra_beds=extra_beds,
            price_per_night=_round_currency(price_per_night),
            base_room_rent=_round_currency(base_room_rent),
            extra_bed_total=_round_currency(extra_bed_total),
            add_ons=selected_add_ons,
            add_ons_total=_round_currency(add_ons_total),
            subtotal_before_discount=_round_currency(subtotal),
            coupon_code=clean_coupon if coupon_valid else None,
            coupon_discount=_round_currency(coupon_discount),
            coupon_valid=coupon_valid,
            taxable_amount=_round_currency(taxable_amount),
            gst_percent=float(gst_percent),
            gst_amount=_round_currency(gst_amount),
            grand_total=_round_currency(grand_total),
            currency="INR",
        )


pricing_engine = PricingEngine()
