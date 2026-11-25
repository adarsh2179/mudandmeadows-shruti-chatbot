"""
Pricing Engine Module for Mud & Meadows AI Concierge.

Enforces deterministic financial arithmetic for booking calculations.
Prevents LLM math hallucinations regarding room rates, extra beds,
taxes (GST), and promotional coupon discounts.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from resort_client import resort_client


class AddOnItem(BaseModel):
    """An optional service added to the stay (dining, spa, experience)."""
    id: str
    name: str
    category: str = "general"  # 'wellness', 'dining', 'experience'
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
    """Deterministic calculator for resort stay quotes and invoices."""

    @staticmethod
    def parse_and_validate_dates(check_in_str: str, check_out_str: str) -> int:
        """
        Validates check-in and check-out date formats and chronological order.
        Returns the number of nights.
        """
        try:
            check_in = datetime.strptime(check_in_str.strip(), "%Y-%m-%d").date()
            check_out = datetime.strptime(check_out_str.strip(), "%Y-%m-%d").date()
        except ValueError as err:
            raise ValueError(
                f"Invalid date format: '{check_in_str}' or '{check_out_str}'. Expected YYYY-MM-DD."
            ) from err

        if check_out <= check_in:
            raise ValueError(
                f"Check-out date ({check_out_str}) must be after check-in date ({check_in_str})."
            )

        nights = (check_out - check_in).days
        return nights

    @staticmethod
    def get_applicable_gst_percent(price_per_night: float) -> float:
        """
        Calculates Indian Hotel GST rate based on standard government slabs:
        - Room tariff < Rs. 7,500/night: 12% GST
        - Room tariff >= Rs. 7,500/night: 18% GST
        """
        return 18.0 if price_per_night >= 7500.0 else 12.0

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
        Generates an exact, auditable PriceQuote.
        Executes strict arithmetic with zero reliance on LLM calculations.
        """
        # 1. Validate nights
        nights = self.parse_and_validate_dates(check_in_str, check_out_str)

        # 2. Extract Cottage Specs
        cottage_id = str(cottage.get("id") or cottage.get("_id") or "")
        cottage_name = cottage.get("name", "Resort Cottage")
        price_per_night = float(
            cottage.get("price_per_night")
            or cottage.get("price")
            or cottage.get("offer_price")
            or 0.0
        )
        extra_bed_unit_price = float(cottage.get("extra_bedding_price") or 1500.0)

        # 3. Base Rent & Bedding
        base_room_rent = round(price_per_night * nights, 2)
        extra_bed_total = round(extra_beds * extra_bed_unit_price * nights, 2)

        # 4. Add-ons (Spa, Dining, Experiences)
        selected_add_ons = add_ons or []
        add_ons_total = round(
            sum(item.price * item.quantity for item in selected_add_ons), 2
        )

        subtotal = round(base_room_rent + extra_bed_total + add_ons_total, 2)

        # 5. Promotional Coupon Calculation (calling Resort API)
        coupon_discount = 0.0
        coupon_valid = False
        clean_coupon = coupon_code.strip().upper() if coupon_code else None

        if clean_coupon:
            try:
                quote_resp = await resort_client.quote_coupon(clean_coupon, subtotal)
                # Resort API returns discount amount or percentage
                if quote_resp and "discount" in quote_resp:
                    coupon_discount = round(float(quote_resp["discount"]), 2)
                    coupon_valid = True
                elif quote_resp and "discount_amount" in quote_resp:
                    coupon_discount = round(float(quote_resp["discount_amount"]), 2)
                    coupon_valid = True
            except Exception:
                # If coupon is invalid or expired on backend, discount remains 0
                coupon_valid = False
                coupon_discount = 0.0

        taxable_amount = max(0.0, round(subtotal - coupon_discount, 2))

        # 6. GST Calculation
        gst_percent = self.get_applicable_gst_percent(price_per_night)
        gst_amount = round(taxable_amount * (gst_percent / 100.0), 2)
        grand_total = round(taxable_amount + gst_amount, 2)

        return PriceQuote(
            cottage_id=cottage_id,
            cottage_name=cottage_name,
            check_in=check_in_str,
            check_out=check_out_str,
            nights=nights,
            adults=adults,
            children=children,
            extra_beds=extra_beds,
            price_per_night=price_per_night,
            base_room_rent=base_room_rent,
            extra_bed_total=extra_bed_total,
            add_ons=selected_add_ons,
            add_ons_total=add_ons_total,
            subtotal_before_discount=subtotal,
            coupon_code=clean_coupon if coupon_valid else None,
            coupon_discount=coupon_discount,
            coupon_valid=coupon_valid,
            taxable_amount=taxable_amount,
            gst_percent=gst_percent,
            gst_amount=gst_amount,
            grand_total=grand_total,
            currency="INR",
        )


# Singleton instance for application-wide use
pricing_engine = PricingEngine()
