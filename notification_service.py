"""
Notification Service Module for Mud & Meadows AI Concierge.

Handles 100% free multi-channel notifications:
1. Luxury HTML Email Quotations and Booking Receipts via standard SMTP.
2. WhatsApp Click-to-Chat deep links for instant 1-tap quote sharing and mobile booking.
"""

import asyncio
import email.message
import logging
import smtplib
import urllib.parse
from typing import Any, Dict, Optional

from config import settings

logger = logging.getLogger(__name__)


class NotificationService:
    """Dispatches resort booking quotes and receipts via Email and WhatsApp."""

    def __init__(self):
        self.smtp_host = settings.SMTP_HOST
        self.smtp_port = settings.SMTP_PORT
        self.smtp_user = settings.SMTP_USER
        self.smtp_password = settings.SMTP_PASSWORD
        self.from_email = settings.SMTP_FROM_EMAIL or "concierge@mudandmeadows.in"
        self.whatsapp_number = settings.RESORT_WHATSAPP_NUMBER or "919876543210"

    def generate_whatsapp_link(self, quote: Dict[str, Any], guest_phone: Optional[str] = None) -> str:
        """
        Generates a 100% free universal WhatsApp Click-to-Chat / Share link.
        Uses universal WhatsApp Web / App share endpoint so it works without invalid phone number errors.
        """
        cottage_name = quote.get("cottage_name", "Luxury Villa")
        nights = quote.get("nights", 1)
        check_in = quote.get("check_in", "Upcoming")
        check_out = quote.get("check_out", "")
        adults = quote.get("adults", 2)
        total_price = quote.get("total_price", 0.0)
        base_price = quote.get("base_price", 0.0)
        gst = quote.get("gst_amount", 0.0)

        message_text = (
            f"🌿 *Mud & Meadows Resort - Stay Quotation*\n\n"
            f"👤 *Concierge:* Shruti\n"
            f"🏨 *Villa:* {cottage_name}\n"
            f"📅 *Dates:* {check_in} to {check_out} ({nights} Nights)\n"
            f"👥 *Guests:* {adults} Adults\n"
            f"─────────────────\n"
            f"💵 *Base Rent:* ₹{base_price:,.2f}\n"
            f"📊 *GST Tax:* ₹{gst:,.2f}\n"
            f"✨ *Total Investment:* ₹{total_price:,.2f}\n"
            f"─────────────────\n"
            f"📍 *Location:* Mud & Meadows Luxury Eco-Resort\n"
            f"🌐 *Website:* https://mudandmeadows.in\n\n"
            f"Please confirm my reservation details!"
        )

        encoded_text = urllib.parse.quote(message_text)
        # If user explicitly provides a valid phone number, use it; otherwise use universal share URL
        clean_phone = "".join(filter(str.isdigit, guest_phone or ""))
        if len(clean_phone) == 10:
            clean_phone = "91" + clean_phone
        if clean_phone and len(clean_phone) >= 11:
            return f"https://api.whatsapp.com/send?phone={clean_phone}&text={encoded_text}"
        # Universal share (no invalid phone error): opens WhatsApp chat selector on phone or desktop
        return f"https://api.whatsapp.com/send?text={encoded_text}"

    def generate_mailto_link(self, quote: Dict[str, Any], to_email: Optional[str] = None) -> str:
        """Generates a universal mailto URL pre-filled with the official resort quote."""
        cottage_name = quote.get("cottage_name", "Luxury Villa")
        nights = quote.get("nights", 1)
        check_in = quote.get("check_in", "Upcoming")
        check_out = quote.get("check_out", "")
        adults = quote.get("adults", 2)
        total_price = quote.get("total_price", 0.0)
        base_price = quote.get("base_price", 0.0)
        gst = quote.get("gst_amount", 0.0)

        subject = urllib.parse.quote(f"Mud & Meadows Resort - Quotation for {cottage_name}")
        body = urllib.parse.quote(
            f"Namaste,\n\nHere is the stay quotation for {cottage_name} at Mud & Meadows Resort:\n\n"
            f"Dates: {check_in} to {check_out} ({nights} Nights)\n"
            f"Guests: {adults} Adults\n"
            f"Base Room Rent: INR {base_price:,.2f}\n"
            f"GST Tax: INR {gst:,.2f}\n"
            f"Grand Total: INR {total_price:,.2f}\n\n"
            f"Resort Website: https://mudandmeadows.in\n"
            f"Concierge: Shruti"
        )
        recipient = to_email if to_email else ""
        return f"mailto:{recipient}?subject={subject}&body={body}"

    async def send_quote_email(self, to_email: str, quote: Dict[str, Any], guest_name: str = "Valued Guest") -> Dict[str, Any]:
        """
        Sends an elegant HTML quotation / reservation email to the guest.
        Runs asynchronously via asyncio.to_thread to avoid blocking the event loop.
        """
        if not to_email or "@" not in to_email:
            return {"success": False, "error": "Invalid email address provided."}

        # If SMTP credentials are not configured, perform graceful simulation
        if not self.smtp_user or not self.smtp_password:
            logger.info(
                f"[SIMULATED EMAIL] To: {to_email} | Subject: Mud & Meadows Reservation Quote for {quote.get('cottage_name')}"
            )
            return {
                "success": True,
                "mode": "simulated",
                "to": to_email,
                "message": f"Quotation has been prepared for {to_email}. (To enable live dispatch, set SMTP_USER and SMTP_PASSWORD in .env)"
            }

        return await asyncio.to_thread(self._send_smtp_email_sync, to_email, quote, guest_name)

    def _send_smtp_email_sync(self, to_email: str, quote: Dict[str, Any], guest_name: str) -> Dict[str, Any]:
        """Synchronous SMTP worker sending MIME multipart HTML email."""
        try:
            cottage_name = quote.get("cottage_name", "Luxury Villa")
            nights = quote.get("nights", 1)
            check_in = quote.get("check_in", "Upcoming")
            check_out = quote.get("check_out", "")
            adults = quote.get("adults", 2)
            total_price = quote.get("total_price", 0.0)
            base_price = quote.get("base_price", 0.0)
            gst = quote.get("gst_amount", 0.0)

            msg = email.message.EmailMessage()
            msg["Subject"] = f"🌿 Your Luxury Stay Quotation — {cottage_name} | Mud & Meadows"
            msg["From"] = f"Shruti • Mud & Meadows <{self.from_email}>"
            msg["To"] = to_email

            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
              <meta charset="utf-8">
              <style>
                body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #f7faf7; margin: 0; padding: 20px; }}
                .card {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.06); border: 1px solid #e2ece3; }}
                .header {{ background: #1b3b2b; color: #ffffff; padding: 30px; text-align: center; }}
                .header h1 {{ margin: 0; font-size: 24px; font-weight: 700; color: #d4af37; }}
                .header p {{ margin: 5px 0 0 0; font-size: 14px; opacity: 0.9; }}
                .content {{ padding: 30px; color: #2d3748; }}
                .villa-title {{ font-size: 20px; font-weight: 700; color: #1b3b2b; margin-top: 0; }}
                .table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                .table td {{ padding: 10px 0; border-bottom: 1px solid #edf2ee; font-size: 15px; }}
                .table td.right {{ text-align: right; font-weight: 600; }}
                .total-row td {{ font-size: 18px; font-weight: 700; color: #1b3b2b; border-bottom: none; padding-top: 15px; }}
                .footer {{ background: #f3f7f4; padding: 20px 30px; text-align: center; font-size: 13px; color: #718096; }}
                .btn {{ display: inline-block; background: #c5a059; color: #1b3b2b; text-decoration: none; padding: 12px 28px; border-radius: 25px; font-weight: 700; margin-top: 20px; }}
              </style>
            </head>
            <body>
              <div class="card">
                <div class="header">
                  <h1>🌿 Mud & Meadows Resort</h1>
                  <p>Luxury Eco-Retreat Concierge Service</p>
                </div>
                <div class="content">
                  <p>Namaste <strong>{guest_name}</strong>,</p>
                  <p>It is my absolute pleasure to present your requested stay quotation for your upcoming retreat at Mud & Meadows:</p>
                  
                  <h3 class="villa-title">{cottage_name}</h3>
                  <p><strong>Check-In:</strong> {check_in} | <strong>Check-Out:</strong> {check_out} ({nights} Nights)<br>
                  <strong>Guests:</strong> {adults} Adults | Complimentary Breakfast Included</p>
                  
                  <table class="table">
                    <tr>
                      <td>Base Room Rent ({nights} nights)</td>
                      <td class="right">₹{base_price:,.2f}</td>
                    </tr>
                    <tr>
                      <td>Goods & Services Tax (GST)</td>
                      <td class="right">₹{gst:,.2f}</td>
                    </tr>
                    <tr class="total-row">
                      <td>Grand Total (INR)</td>
                      <td class="right">₹{total_price:,.2f}</td>
                    </tr>
                  </table>
                  
                  <center>
                    <a href="https://mudandmeadows.in" class="btn">View on Resort Website</a>
                  </center>
                </div>
                <div class="footer">
                  <p>Warmest regards,<br><strong>Shruti</strong> — Guest Concierge<br>
                  Mud & Meadows Luxury Resort | https://mudandmeadows.in</p>
                </div>
              </div>
            </body>
            </html>
            """
            msg.set_content(
                f"Namaste {guest_name}!\n\nHere is your requested quotation for {cottage_name} ({nights} nights: {check_in} to {check_out}).\n"
                f"Base Rent: ₹{base_price:,.2f}\nGST: ₹{gst:,.2f}\nGrand Total: ₹{total_price:,.2f}\n\nWarm regards,\nShruti • Mud & Meadows"
            )
            msg.add_alternative(html_body, subtype="html")

            server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10)
            server.starttls()
            server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)
            server.quit()

            logger.info(f"Email successfully delivered to {to_email}")
            return {"success": True, "mode": "live", "to": to_email}

        except Exception as e:
            logger.error(f"SMTP email dispatch error to {to_email}: {e}")
            return {"success": False, "error": str(e)}


notification_service = NotificationService()
