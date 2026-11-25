"""
AI Concierge Agent Module for Mud & Meadows Resort.

Orchestrates multi-turn conversation, natural language understanding,
Gemini 3.5 Flash function calling (tools), and generates structured
UI Cards (Room Cards, Pricing Quotes, Add-ons, and Razorpay triggers)
for the embeddable chat widget.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from google import genai
from google.genai import types

from config import settings
from resort_client import resort_client
from pricing_engine import pricing_engine, AddOnItem
from notification_service import notification_service

logger = logging.getLogger(__name__)


class AgentResponse(BaseModel):
    """Structured response returned to the frontend chat widget."""
    text: str
    cards: List[Dict[str, Any]] = []
    action: Optional[str] = None  # 'SHOW_ROOMS', 'SHOW_QUOTE', 'TRIGGER_PAYMENT', 'CONFIRMED'
    payload: Optional[Dict[str, Any]] = None


# =============================================================================
# GEMINI FUNCTION / TOOL DECLARATIONS
# =============================================================================

TOOLS_DECLARATION = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search_cottages",
            description="Search available resort cottages and luxury villas by check-in date, check-out date, and number of guests.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "check_in": types.Schema(
                        type=types.Type.STRING,
                        description="Check-in date in YYYY-MM-DD format (e.g. 2026-12-01)"
                    ),
                    "check_out": types.Schema(
                        type=types.Type.STRING,
                        description="Check-out date in YYYY-MM-DD format (e.g. 2026-12-03)"
                    ),
                    "guests": types.Schema(
                        type=types.Type.INTEGER,
                        description="Total number of guests (adults + children)"
                    ),
                },
                required=["check_in", "check_out"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_cottage_details",
            description="Get detailed specifications, amenities, bed configuration, and pricing of a specific cottage.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "cottage_id": types.Schema(
                        type=types.Type.STRING,
                        description="Unique ID of the cottage"
                    ),
                },
                required=["cottage_id"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_resort_services",
            description="Explore resort add-ons: dining menu, spa/wellness treatments, or local nature experiences.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "category": types.Schema(
                        type=types.Type.STRING,
                        description="Category to explore: 'dining', 'wellness', or 'experiences'"
                    ),
                },
                required=["category"],
            ),
        ),
        types.FunctionDeclaration(
            name="calculate_booking_quote",
            description="Calculate exact mathematical price quote including base room rent, extra beds, GST taxes, and coupons.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "cottage_id": types.Schema(type=types.Type.STRING, description="Selected cottage ID"),
                    "check_in": types.Schema(type=types.Type.STRING, description="Check-in date YYYY-MM-DD"),
                    "check_out": types.Schema(type=types.Type.STRING, description="Check-out date YYYY-MM-DD"),
                    "adults": types.Schema(type=types.Type.INTEGER, description="Number of adults"),
                    "children": types.Schema(type=types.Type.INTEGER, description="Number of children"),
                    "extra_beds": types.Schema(type=types.Type.INTEGER, description="Number of extra beds requested"),
                    "coupon_code": types.Schema(type=types.Type.STRING, description="Optional coupon/promo code"),
                },
                required=["cottage_id", "check_in", "check_out"],
            ),
        ),
        types.FunctionDeclaration(
            name="lookup_guest_booking",
            description="Retrieve existing reservation details and status using the guest's email address.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "email": types.Schema(type=types.Type.STRING, description="Registered guest email address"),
                },
                required=["email"],
            ),
        ),
        types.FunctionDeclaration(
            name="send_whatsapp_quote",
            description="Format and prepare an official reservation quote link targeted to a guest's mobile phone number for WhatsApp.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "phone_number": types.Schema(type=types.Type.STRING, description="Guest's 10-digit mobile number (e.g. 9876543210 or +919876543210)"),
                },
                required=["phone_number"],
            ),
        ),
    ]
)

def get_system_instruction(company_name: str) -> str:
    return f"""
Your name is Shruti. You are the dedicated, warm, and highly attentive guest concierge for '{company_name}' (luxury resort).
You always introduce yourself as Shruti. You communicate naturally, warmly, and gracefully like a real professional resort concierge.
Your SOLE purpose is to assist guests with inquiries directly related to {company_name}: our luxury cottages/villas, room availability, stay pricing quotes, dining menus, wellness/spa programs, resort activities, location, and bookings.

STRICT DOMAIN GUARDRAILS & BOUNDARY:
- You are Shruti, representing ONLY '{company_name}'. You are NOT a general-purpose AI assistant.
- You must STRICTLY REFUSE to answer any questions outside of {company_name}.
- If a guest asks about general knowledge, world politics, country leaders (e.g. "who is the PM of Nepal", "who is the president of US"), celebrities, current news, history, science, coding, homework, math puzzles, or other unrelated topics:
  DO NOT answer the question under any circumstances.
  Instead, politely and warmly decline with a courteous message:
  "I am Shruti, your dedicated guest concierge for {company_name}. I can only assist with inquiries regarding our resort, luxury cottages, dining, wellness experiences, and stay bookings. How may I assist your visit to {company_name} today?"
  (Respond in the guest's language: if they ask in Hindi, decline politely in Hindi introducing yourself as Shruti; if in English, decline in English).

Key Operational Guidelines:
1. Tone & Persona: Hospitable, warm, courteous, natural, and helpful. Always carry yourself as Shruti from {company_name}.
2. Multilingual: Guests may write or speak in English, Hindi, Hinglish, or regional languages. Understand their intent and respond in the appropriate language.
3. Information & Calculations:
   - When guests ask about rooms or availability: call `search_cottages`.
   - When guests ask about cottage specifications or bed configuration: call `get_cottage_details`.
   - When guests want pricing or expenditure calculations for stays or multiple rooms: call `search_cottages` or `calculate_booking_quote` to get live rates and compute the exact breakdown clearly for them.
   - When guests ask about dining, spa, or activities: call `get_resort_services`.
   - When guests ask to check existing bookings: call `lookup_guest_booking`.
   - When guests want a quote sent on WhatsApp: call `send_whatsapp_quote`.
4. Visual UI Cards: Relevant interactive cards (villa cards, quote cards) are displayed in the chat. Tell the guest they can review the cards or click them to proceed. Quote cards include direct 1-tap WhatsApp sharing and instant payment buttons.
"""


class ResortAgent:
    """The Conversational Agent managing session context and tool dispatch."""

    def __init__(self):
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        # Use active model with full available quota
        self.model_candidates = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash"]
        self.sessions: Dict[str, List[types.Content]] = {}
        self.last_quotes: Dict[str, Dict[str, Any]] = {}

    def _get_history(self, session_id: str) -> List[types.Content]:
        """Retrieves or initializes the conversation message history for a session."""
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        return self.sessions[session_id]

    async def _call_gemini_with_fallback(self, contents: List[types.Content], config: types.GenerateContentConfig):
        """Calls Gemini with automatic retry on 503 high demand spikes."""
        last_error = None
        for attempt in range(3):
            try:
                response = await asyncio.to_thread(
                    self.client.models.generate_content,
                    model="gemini-3.5-flash-lite",
                    contents=contents,
                    config=config
                )
                return response
            except Exception as e:
                err_str = str(e).lower()
                logger.warning(f"Attempt {attempt + 1} with gemini-3.5-flash-lite failed: {e}")
                last_error = e
                if "503" in err_str or "unavailable" in err_str or "high demand" in err_str:
                    await asyncio.sleep(1.5)
                    continue
                else:
                    break
        raise last_error

    async def chat(self, session_id: str, user_message: str) -> AgentResponse:
        """
        Processes a guest message using an autonomous multi-turn tool calling loop.
        Allows Gemini to chain tools (e.g. search cottages -> get details -> calculate quote)
        and synthesize a rich, accurate natural language reply with interactive UI cards.
        """
        history = self._get_history(session_id)

        # Append new user message to session history
        user_content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_message)]
        )
        history.append(user_content)

        lower_msg = user_message.lower().strip()

        # Fast Greeting (pure greetings only: short, zero queries)
        pure_greetings = ["hi", "hello", "hey", "hu", "namaste", "pranam", "नमस्ते", "हेलो"]
        if lower_msg in pure_greetings or (len(lower_msg.split()) <= 2 and any(lower_msg == g for g in pure_greetings)):
            return AgentResponse(
                text=f"Namaste! I am **Shruti**, your personal guest concierge at **{settings.COMPANY_NAME}**. 🌿✨\n\nI am delighted to assist you! I can help you explore our luxury villas, calculate stay packages, browse dining and wellness, and effortlessly book your reservation. How may I assist your visit today?"
            )

        config = types.GenerateContentConfig(
            system_instruction=get_system_instruction(settings.COMPANY_NAME),
            tools=[TOOLS_DECLARATION],
            temperature=0.2,
        )

        cards: List[Dict[str, Any]] = []
        action: Optional[str] = None
        payload: Optional[Dict[str, Any]] = None
        final_text = ""

        try:
            # Autonomous multi-turn reasoning and tool invocation loop (up to 4 steps)
            for step in range(4):
                response = await self._call_gemini_with_fallback(
                    contents=history,
                    config=config,
                )

                candidate = response.candidates[0] if response.candidates else None
                if not candidate or not candidate.content or not candidate.content.parts:
                    break

                # Check if model wants to call a tool
                function_call_part = next((p for p in candidate.content.parts if p.function_call), None)

                if function_call_part:
                    fn = function_call_part.function_call
                    fn_name = fn.name
                    fn_args = fn.args or {}
                    logger.info(f"Step {step+1}: Agent dispatched tool [{fn_name}] with args: {fn_args}")

                    # Execute tool and collect cards/action
                    tool_result, step_cards, step_action, step_payload = await self._execute_tool(fn_name, fn_args, session_id=session_id)

                    if step_cards:
                        cards = step_cards
                    if step_action:
                        action = step_action
                    if step_payload:
                        payload = step_payload

                    # Append model's tool call to history
                    history.append(candidate.content)

                    # Provide tool result back to Gemini
                    tool_response_part = types.Part.from_function_response(
                        name=fn_name,
                        response={"result": tool_result}
                    )
                    history.append(types.Content(role="user", parts=[tool_response_part]))

                else:
                    # Model produced its final conversational response
                    history.append(candidate.content)
                    text_parts = [p.text for p in candidate.content.parts if p.text]
                    final_text = " ".join(text_parts).strip()
                    break

            # If loop completed and final text was not synthesized, request final summary
            if not final_text:
                summary_config = types.GenerateContentConfig(
                    system_instruction=get_system_instruction(settings.COMPANY_NAME),
                    temperature=0.3,
                )
                try:
                    summary_resp = await self._call_gemini_with_fallback(
                        contents=history,
                        config=summary_config,
                    )
                    if summary_resp and summary_resp.text:
                        final_text = summary_resp.text.strip()
                except Exception as e:
                    logger.warning(f"Summary generation error: {e}")

        except Exception as e:
            logger.error(f"Gemini API generation error: {e}")
            if any(w in lower_msg for w in ["room", "villa", "cottage", "stay", "book", "cost", "price"]):
                _, cards, action, _ = await self._execute_tool("search_cottages", {"check_in": "2026-12-01", "check_out": "2026-12-03", "guests": 2})
                return AgentResponse(
                    text=f"Here are the signature cottages and villas available at **{settings.COMPANY_NAME}**! You can view the rates and click to request an instant quote below:",
                    cards=cards,
                    action=action
                )
            return AgentResponse(
                text=f"Welcome to **{settings.COMPANY_NAME}**! How can I assist you with your booking, villa inquiry, or resort stay today?",
            )

        if not final_text:
            if action == "SHOW_ROOMS":
                final_text = f"I found wonderful accommodations available for your dates at **{settings.COMPANY_NAME}**! Please review the options presented below:"
            elif action == "SHOW_QUOTE":
                final_text = "Here is the exact price quote and breakdown for your stay:"
            elif action == "SHOW_DINING":
                final_text = "Here are our featured restaurant and dining offerings:"
            else:
                final_text = f"Welcome to **{settings.COMPANY_NAME}**! How may I assist your stay today?"

        return AgentResponse(text=final_text, cards=cards, action=action, payload=payload)

    async def _execute_tool(self, name: str, args: Dict[str, Any], session_id: str = ""):
        """Executes backend or pricing tools and produces corresponding interactive UI cards."""
        cards: List[Dict[str, Any]] = []
        action: Optional[str] = None
        payload: Optional[Dict[str, Any]] = None

        if name == "search_cottages":
            check_in = str(args.get("check_in", ""))
            check_out = str(args.get("check_out", ""))
            guests = int(args.get("guests") or 2)

            all_cottages = await resort_client.get_cottages()
            filtered_cottages = [c for c in all_cottages if int(c.get("capacity_max") or c.get("capacity") or 2) >= guests]

            # If guest count is large and no single cottage fits, showcase all available villas
            if not filtered_cottages:
                filtered_cottages = all_cottages

            for c in filtered_cottages:
                max_capacity = int(c.get("capacity_max") or c.get("capacity") or c.get("guests") or 2)
                cards.append({
                    "type": "cottage_card",
                    "id": str(c.get("id") or c.get("_id") or ""),
                    "name": c.get("name", "Luxury Villa"),
                    "price_per_night": float(c.get("price_per_night") or c.get("price") or 0.0),
                    "capacity": max_capacity,
                    "description": c.get("description", ""),
                    "images": c.get("images") or [],
                    "amenities": c.get("amenities") or ["Free WiFi", "Garden View", "Breakfast"],
                    "check_in": check_in,
                    "check_out": check_out,
                })

            action = "SHOW_ROOMS"
            tool_result = {
                "count": len(filtered_cottages),
                "cottages": [
                    {
                        "id": c.get("id") or c.get("_id"),
                        "name": c.get("name"),
                        "price_per_night": c.get("price_per_night"),
                        "capacity": c.get("capacity_max") or c.get("capacity") or 2,
                        "description": c.get("description", "")
                    }
                    for c in filtered_cottages
                ],
                "dates": f"{check_in} to {check_out}"
            }
            return tool_result, cards, action, payload

        elif name == "get_cottage_details":
            cottage_id = str(args.get("cottage_id", "")).strip()
            details = await resort_client.get_cottage_details(cottage_id)
            return details, cards, action, payload

        elif name == "get_resort_services":
            category = str(args.get("category", "dining")).lower()
            items = []

            if "dining" in category or "food" in category:
                dining_menu = await resort_client.get_dining_menu()
                for item in dining_menu[:6]:  # Showcase top 6 items
                    cards.append({
                        "type": "dining_card",
                        "id": str(item.get("id") or ""),
                        "name": item.get("name", ""),
                        "price": float(item.get("price") or 0.0),
                        "category": item.get("category", "General"),
                        "description": item.get("description", ""),
                        "dietary": item.get("dietary", "Veg"),
                    })
                items = dining_menu
                action = "SHOW_DINING"

            elif "wellness" in category or "spa" in category:
                wellness_programs = await resort_client.get_wellness_programs()
                for prog in wellness_programs:
                    cards.append({
                        "type": "wellness_card",
                        "id": str(prog.get("id") or ""),
                        "name": prog.get("name") or prog.get("title") or "Wellness Session",
                        "price": float(prog.get("price") or 0.0),
                        "duration": prog.get("duration", "60 mins"),
                        "description": prog.get("description", ""),
                    })
                items = wellness_programs
                action = "SHOW_WELLNESS"

            else:
                experiences = await resort_client.get_experiences()
                for exp in experiences:
                    cards.append({
                        "type": "experience_card",
                        "id": str(exp.get("id") or ""),
                        "name": exp.get("title") or exp.get("name") or "Resort Experience",
                        "price": float(exp.get("price") or 0.0),
                        "description": exp.get("description", ""),
                    })
                items = experiences
                action = "SHOW_EXPERIENCES"

            return {"category": category, "count": len(items)}, cards, action, payload

        elif name == "calculate_booking_quote":
            cottage_id = str(args.get("cottage_id"))
            check_in = str(args.get("check_in"))
            check_out = str(args.get("check_out"))
            adults = int(args.get("adults") or 2)
            children = int(args.get("children") or 0)
            extra_beds = int(args.get("extra_beds") or 0)
            coupon = args.get("coupon_code")

            cottage_details = await resort_client.get_cottage_details(cottage_id)
            quote = await pricing_engine.calculate_quote(
                cottage=cottage_details,
                check_in_str=check_in,
                check_out_str=check_out,
                adults=adults,
                children=children,
                extra_beds=extra_beds,
                coupon_code=coupon,
            )

            action = "SHOW_QUOTE"
            payload = quote.model_dump()
            whatsapp_url = notification_service.generate_whatsapp_link(payload)
            mailto_url = notification_service.generate_mailto_link(payload)
            payload["whatsapp_url"] = whatsapp_url
            payload["mailto_url"] = mailto_url
            if session_id:
                self.last_quotes[session_id] = payload

            cards.append({
                "type": "quote_card",
                "quote": payload,
                "whatsapp_url": whatsapp_url,
            })
            return payload, cards, action, payload

        elif name == "send_whatsapp_quote":
            phone = str(args.get("phone_number", "")).strip()
            quote_data = self.last_quotes.get(session_id) or {
                "cottage_name": "Mud & Meadows Luxury Villa",
                "nights": 2,
                "check_in": "Upcoming Stay",
                "check_out": "",
                "adults": 2,
                "base_price": 24000.0,
                "gst_amount": 4320.0,
                "total_price": 28320.0
            }
            wa_url = notification_service.generate_whatsapp_link(quote_data, guest_phone=phone)
            cards.append({
                "type": "whatsapp_card",
                "phone": phone,
                "whatsapp_url": wa_url,
                "cottage_name": quote_data.get("cottage_name", "Luxury Villa"),
                "total_price": quote_data.get("total_price", 0.0)
            })
            return {"status": "success", "phone": phone, "whatsapp_url": wa_url}, cards, "SHOW_WHATSAPP", payload

        elif name == "lookup_guest_booking":
            email = str(args.get("email", "")).strip()
            bookings = await resort_client.lookup_guest_bookings(email)
            for b in bookings:
                cards.append({
                    "type": "booking_status_card",
                    "booking_id": str(b.get("id") or b.get("_id") or ""),
                    "status": b.get("status", "Confirmed"),
                    "check_in": b.get("check_in", ""),
                    "check_out": b.get("check_out", ""),
                    "total_price": b.get("total_price", 0.0),
                })
            action = "SHOW_BOOKINGS"
            return {"bookings_found": len(bookings)}, cards, action, payload

        return {"error": f"Unknown tool: {name}"}, cards, action, payload


# Singleton instance of the agent
agent = ResortAgent()
