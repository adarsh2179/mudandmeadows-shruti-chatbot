"""
Notification Service Module for Mud & Meadows AI Concierge.

Provides universal RFC 3986 WhatsApp Click-to-Chat deep links for zero-cost
instant stay quotation sharing without Twilio or Meta Business API charges.
"""

import urllib.parse
from typing import Any, Dict, Optional

from config import settings


class NotificationService:
    """Formats resort stay quotations into universal WhatsApp share links."""

    def __init__(self):
        self.whatsapp_number = settings.RESORT_WHATSAPP_NUMBER or ""

    def generate_whatsapp_link(
        self, quote: Dict[str, Any], guest_phone: Optional[str] = None
    ) -> str:
        """
        Generates an RFC 3986 WhatsApp Click-to-Chat URL containing the full quote breakdown.
        Handles both `PriceQuote` field names (`base_room_rent`, `grand_total`) and legacy
        aliases (`base_price`, `total_price`).
        """
        cottage_name = quote.get("cottage_name", "Luxury Villa")
        nights = quote.get("nights", 1)
        check_in = quote.get("check_in", "Upcoming")
        check_out = quote.get("check_out", "")
        adults = quote.get("adults", 2)
        children = quote.get("children", 0)
        extra_beds = quote.get("extra_beds", 0)

        base_price = float(quote.get("base_room_rent") or quote.get("base_price") or 0.0)
        extra_bed_total = float(quote.get("extra_bed_total") or 0.0)
        gst_amount = float(quote.get("gst_amount") or 0.0)
        gst_percent = quote.get("gst_percent", "")
        total_price = float(quote.get("grand_total") or quote.get("total_price") or 0.0)

        guest_summary = f"{adults} Adults" + (f", {children} Children" if children else "")
        gst_label = f"GST ({gst_percent}%)" if gst_percent else "GST Tax"

        lines = [
            f"*Mud & Meadows Resort - Stay Quotation*",
            f"",
            f"*Concierge:* Shruti",
            f"*Villa:* {cottage_name}",
            f"*Dates:* {check_in} to {check_out} ({nights} Nights)" if check_out else f"*Dates:* {check_in} ({nights} Nights)",
            f"*Guests:* {guest_summary}",
            f"-----------------",
            f"*Base Room Rent:* INR {base_price:,.2f}",
        ]
        if extra_bed_total > 0:
            lines.append(f"*Extra Bedding ({extra_beds}):* INR {extra_bed_total:,.2f}")
        lines.extend([
            f"*{gst_label}:* INR {gst_amount:,.2f}",
            f"*Grand Total:* INR {total_price:,.2f}",
            f"-----------------",
            f"*Website:* https://mudandmeadows.in",
            f"",
            f"Please confirm my reservation details.",
        ])

        encoded_text = urllib.parse.quote("\n".join(lines))

        clean_phone = "".join(filter(str.isdigit, guest_phone or ""))
        if len(clean_phone) == 10:
            clean_phone = "91" + clean_phone
        if clean_phone and len(clean_phone) >= 11:
            return f"https://api.whatsapp.com/send?phone={clean_phone}&text={encoded_text}"

        return f"https://api.whatsapp.com/send?text={encoded_text}"


notification_service = NotificationService()
