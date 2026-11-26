"""
AI Concierge Agent Module for Mud & Meadows Resort.

Executes a bounded, multi-turn ReAct tool-calling loop using Google Gemini,
backed by SQLite WAL session persistence, sliding-window context pruning,
exponential backoff retries, and deterministic pricing delegation.
"""

import asyncio
from datetime import date, timedelta
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from google import genai
from google.genai import types

from config import settings
from resort_client import resort_client
from pricing_engine import pricing_engine
from notification_service import notification_service
from session_store import session_store

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 12


class AgentResponse(BaseModel):
    """Structured response schema consumed by the Shadow DOM chat widget."""
    text: str
    cards: List[Dict[str, Any]] = []
    action: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


TOOLS_DECLARATION = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search_cottages",
            description="Search available resort cottages and villas by check-in date, check-out date, and guest count.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "check_in": types.Schema(
                        type=types.Type.STRING,
                        description="Check-in date in YYYY-MM-DD format"
                    ),
                    "check_out": types.Schema(
                        type=types.Type.STRING,
                        description="Check-out date in YYYY-MM-DD format"
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
            description="Fetch detailed specifications, amenities, and pricing for a specific cottage.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "cottage_id": types.Schema(
                        type=types.Type.STRING,
                        description="Unique cottage identifier"
                    ),
                },
                required=["cottage_id"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_resort_services",
            description="Retrieve resort amenities: dining menu, wellness/spa programs, or local experiences.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "category": types.Schema(
                        type=types.Type.STRING,
                        description="Category: 'dining', 'wellness', or 'experiences'"
                    ),
                },
                required=["category"],
            ),
        ),
        types.FunctionDeclaration(
            name="calculate_booking_quote",
            description="Compute an auditable mathematical quote including room tariff, extra bedding, GST taxes, and coupons.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "cottage_id": types.Schema(type=types.Type.STRING, description="Selected cottage ID"),
                    "check_in": types.Schema(type=types.Type.STRING, description="Check-in date YYYY-MM-DD"),
                    "check_out": types.Schema(type=types.Type.STRING, description="Check-out date YYYY-MM-DD"),
                    "adults": types.Schema(type=types.Type.INTEGER, description="Number of adults"),
                    "children": types.Schema(type=types.Type.INTEGER, description="Number of children"),
                    "extra_beds": types.Schema(type=types.Type.INTEGER, description="Requested extra beds"),
                    "coupon_code": types.Schema(type=types.Type.STRING, description="Optional promo code"),
                },
                required=["cottage_id", "check_in", "check_out"],
            ),
        ),
        types.FunctionDeclaration(
            name="lookup_guest_booking",
            description="Look up an existing reservation. Requires BOTH the registered email AND a secondary verifier (booking_reference or last 4 phone digits) to protect guest privacy.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "email": types.Schema(type=types.Type.STRING, description="Registered guest email address"),
                    "verification_token": types.Schema(
                        type=types.Type.STRING,
                        description="Either the Booking Reference ID or the last 4 digits of the registered phone number"
                    ),
                },
                required=["email", "verification_token"],
            ),
        ),
        types.FunctionDeclaration(
            name="send_whatsapp_quote",
            description="Prepare an official WhatsApp Click-to-Chat quotation link for the guest's mobile number.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "phone_number": types.Schema(
                        type=types.Type.STRING,
                        description="Guest 10-digit Indian mobile number or international format"
                    ),
                },
                required=["phone_number"],
            ),
        ),
    ]
)


def get_system_instruction(company_name: str, guest_profile: Optional[Dict[str, Any]] = None) -> str:
    today = date.today()
    returning_ctx = ""
    if guest_profile and (guest_profile.get("name") or guest_profile.get("preferred_cottage")):
        parts = []
        if guest_profile.get("name"):
            parts.append(f"Name: {guest_profile['name']}")
        if guest_profile.get("preferred_cottage"):
            parts.append(f"Previously viewed cottage: {guest_profile['preferred_cottage']}")
        if guest_profile.get("visit_count", 1) > 1:
            parts.append(f"Visit count: {guest_profile['visit_count']}")
        returning_ctx = f"\nRETURNING GUEST CONTEXT: {', '.join(parts)}. Greet them warmly by name if appropriate without asking repeatedly for details already known."

    return f"""
You are Shruti, the guest concierge for '{company_name}' luxury eco-resort.
Today's Date: {today.isoformat()} ({today.strftime('%A')}). Use this date whenever guests refer to relative dates like "this weekend", "tomorrow", or "next month".{returning_ctx}

STRICT DOMAIN BOUNDARIES:
- Represent ONLY '{company_name}': cottages, availability, pricing quotes, dining, wellness/spa, activities, and reservations.
- Strictly decline out-of-scope questions (politics, trivia, general programming, competitors) politely in the guest's language, guiding them back to planning their stay.
- Privacy Rule: NEVER reveal reservation details from `lookup_guest_booking` unless the guest provides BOTH their email AND either their booking ID or the last 4 digits of their phone number.

CONCIERGE GUIDELINES:
1. Warm, concise, natural hospitality tone in English or Hindi depending on how the guest addresses you.
2. Multi-step execution: Never invent tariffs or tax rates. Always invoke `search_cottages` and `calculate_booking_quote` so Python computes deterministic Indian GST (12% up to INR 7,500/night, 18% above INR 7,500/night).
3. If the guest does not specify check-in/out dates when asking for sample rates, default to upcoming dates starting two days from today ({today.isoformat()}).
4. After generating a quote card, remind the guest they can share the summary directly on WhatsApp or reserve online from the card controls.
"""


def _trim_history(history: List[types.Content], max_messages: int = MAX_HISTORY_MESSAGES) -> List[types.Content]:
    """
    Trims conversation history to bound input token usage while preserving
    valid user -> model -> function_response message boundaries.
    """
    if len(history) <= max_messages:
        return history

    sliced = history[-max_messages:]
    # Ensure the first message in context is a plain user text message,
    # never an orphaned function_response or model turn.
    for idx, content in enumerate(sliced):
        is_user_text = (
            content.role == "user"
            and content.parts
            and any(p.text for p in content.parts)
            and not any(p.function_response for p in content.parts)
        )
        if is_user_text:
            return sliced[idx:]

    return sliced[-2:] if len(sliced) >= 2 else sliced


class ResortAgent:
    """Orchestrates guest sessions, ReAct reasoning steps, and backend tools."""

    def __init__(self):
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self.model_candidates = ["gemini-3.5-flash-lite", "gemini-3.5-flash"]

    async def _call_gemini_with_fallback(
        self, contents: List[types.Content], config: types.GenerateContentConfig
    ):
        """Executes Gemini API calls with jittered retries on transient 503 capacity spikes."""
        last_error: Optional[Exception] = None
        for attempt in range(3):
            for model_name in self.model_candidates:
                try:
                    return await asyncio.to_thread(
                        self.client.models.generate_content,
                        model=model_name,
                        contents=contents,
                        config=config,
                    )
                except Exception as e:
                    last_error = e
                    err_str = str(e).lower()
                    if "503" in err_str or "unavailable" in err_str:
                        logger.warning(f"Attempt {attempt + 1} with {model_name} hit 503 spike; retrying.")
                        break
                    logger.warning(f"Model {model_name} unavailable or failed: {e}")
                    continue
            await asyncio.sleep(1.2 * (attempt + 1))

        if last_error is not None:
            raise last_error
        raise RuntimeError("No active Gemini models responded.")

    async def chat(self, session_id: str, user_message: str) -> AgentResponse:
        """Processes guest input through the bounded multi-turn ReAct tool loop."""
        history, last_quote = session_store.get_session(session_id)
        guest_profile = session_store.get_guest_profile(session_id)

        user_content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_message)],
        )
        history.append(user_content)
        history = _trim_history(history)

        lower_msg = user_message.lower().strip()
        clean_greet = " ".join(lower_msg.rstrip("!?.,:;~ ").split())
        pure_greetings = {
            "hi", "hii", "hiii", "hello", "hey", "heyy", "namaste", "pranam",
            "नमस्ते", "हेलो", "good morning", "good afternoon", "good evening",
            "hi there", "hello there", "hey there",
            "hi shruti", "hello shruti", "hey shruti", "namaste shruti",
        }
        if clean_greet in pure_greetings:
            name_prefix = f" back, **{guest_profile['name']}**" if guest_profile and guest_profile.get("name") else ""
            greeting_text = (
                f"Namaste{name_prefix}! I am **Shruti**, your guest concierge at **{settings.COMPANY_NAME}**.\n\n"
                "I can help you explore our villas, calculate stay quotations with taxes, review dining and wellness programs, or confirm your booking. How may I assist you today?"
            )
            history.append(types.Content(role="model", parts=[types.Part.from_text(text=greeting_text)]))
            session_store.save_session(session_id, _trim_history(history), last_quote)
            return AgentResponse(text=greeting_text)

        system_prompt = get_system_instruction(settings.COMPANY_NAME, guest_profile=guest_profile)
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[TOOLS_DECLARATION],
            temperature=0.2,
        )

        cards: List[Dict[str, Any]] = []
        action: Optional[str] = None
        payload: Optional[Dict[str, Any]] = None
        final_text = ""

        try:
            for step in range(4):
                response = await self._call_gemini_with_fallback(
                    contents=history,
                    config=config,
                )

                candidate = response.candidates[0] if response.candidates else None
                if not candidate or not candidate.content or not candidate.content.parts:
                    break

                function_call_part = next(
                    (p for p in candidate.content.parts if p.function_call), None
                )

                if function_call_part:
                    fn = function_call_part.function_call
                    fn_name = fn.name
                    fn_args = fn.args or {}
                    logger.info(f"Step {step + 1}: Tool [{fn_name}] invoked for session [{session_id}]")

                    try:
                        tool_result, step_cards, step_action, step_payload, updated_quote = (
                            await self._execute_tool(fn_name, fn_args, last_quote=last_quote, session_id=session_id)
                        )
                    except Exception as tool_err:
                        logger.warning(f"Tool [{fn_name}] error handed back to agent: {tool_err}")
                        tool_result = {"error": str(tool_err)}
                        step_cards, step_action, step_payload, updated_quote = [], None, None, None

                    if updated_quote is not None:
                        last_quote = updated_quote
                    if step_cards:
                        cards = step_cards
                    if step_action:
                        action = step_action
                    if step_payload:
                        payload = step_payload

                    history.append(candidate.content)
                    tool_response_part = types.Part.from_function_response(
                        name=fn_name,
                        response={"result": tool_result},
                    )
                    history.append(types.Content(role="user", parts=[tool_response_part]))
                else:
                    history.append(candidate.content)
                    text_parts = [p.text for p in candidate.content.parts if p.text]
                    final_text = " ".join(text_parts).strip()
                    break

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
                        history.append(
                            types.Content(role="model", parts=[types.Part.from_text(text=final_text)])
                        )
                except Exception as e:
                    logger.warning(f"Summary generation fallback note: {e}")

        except Exception as e:
            logger.error(f"Agent execution error: {e}")
            if any(w in lower_msg for w in ["room", "villa", "cottage", "stay", "book", "cost", "price"]):
                default_in = (date.today() + timedelta(days=1)).isoformat()
                default_out = (date.today() + timedelta(days=3)).isoformat()
                _, cards, action, _, _ = await self._execute_tool(
                    "search_cottages",
                    {"check_in": default_in, "check_out": default_out, "guests": 2},
                    last_quote=last_quote,
                )
                fallback_msg = (
                    f"Here are our available villas at **{settings.COMPANY_NAME}**. "
                    "Select any accommodation below to compute an exact quotation:"
                )
                session_store.save_session(session_id, _trim_history(history), last_quote)
                return AgentResponse(text=fallback_msg, cards=cards, action=action)

            session_store.save_session(session_id, _trim_history(history), last_quote)
            return AgentResponse(
                text=f"Welcome to **{settings.COMPANY_NAME}**. How can I assist you with your villa inquiry or reservation today?"
            )

        if not final_text:
            if action == "SHOW_ROOMS":
                final_text = f"Here are the accommodations matching your requirements at **{settings.COMPANY_NAME}**:"
            elif action == "SHOW_QUOTE":
                final_text = "Here is your itemized stay quotation with applicable taxes:"
            elif action == "SHOW_DINING":
                final_text = "Here are our signature dining selections:"
            else:
                final_text = f"Welcome to **{settings.COMPANY_NAME}**. How may I assist your stay today?"

        session_store.save_session(session_id, _trim_history(history), last_quote)
        return AgentResponse(text=final_text, cards=cards, action=action, payload=payload)

    async def _execute_tool(
        self, name: str, args: Dict[str, Any], last_quote: Optional[Dict[str, Any]] = None, session_id: str = ""
    ):
        """Dispatches tool handlers, builds UI cards, and prunes bloated LLM context payloads."""
        cards: List[Dict[str, Any]] = []
        action: Optional[str] = None
        payload: Optional[Dict[str, Any]] = None
        updated_quote: Optional[Dict[str, Any]] = None

        if name == "search_cottages":
            check_in = str(args.get("check_in", ""))
            check_out = str(args.get("check_out", ""))
            guests = int(args.get("guests") or 2)

            all_cottages = await resort_client.get_cottages()
            filtered = [
                c for c in all_cottages if int(c.get("capacity_max") or c.get("capacity") or 2) >= guests
            ] or all_cottages

            for c in filtered:
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
            # Prune large image arrays & truncated descriptions before feeding to Gemini
            tool_result = {
                "count": len(filtered),
                "dates": f"{check_in} to {check_out}",
                "cottages": [
                    {
                        "id": str(c.get("id") or c.get("_id") or ""),
                        "name": c.get("name"),
                        "price_per_night": c.get("price_per_night"),
                        "capacity": c.get("capacity_max") or c.get("capacity") or 2,
                        "summary": str(c.get("description", ""))[:220],
                    }
                    for c in filtered
                ],
            }
            return tool_result, cards, action, payload, updated_quote

        elif name == "get_cottage_details":
            cottage_id = str(args.get("cottage_id", "")).strip()
            details = await resort_client.get_cottage_details(cottage_id)
            pruned_details = {
                "id": str(details.get("id") or details.get("_id") or cottage_id),
                "name": details.get("name"),
                "price_per_night": details.get("price_per_night") or details.get("price"),
                "capacity": details.get("capacity_max") or details.get("capacity"),
                "extra_bedding_price": details.get("extra_bedding_price", 1500),
                "amenities": details.get("amenities", [])[:8],
                "summary": str(details.get("description", ""))[:300],
            }
            return pruned_details, cards, action, payload, updated_quote

        elif name == "get_resort_services":
            category = str(args.get("category", "dining")).lower()
            items = []

            if "dining" in category or "food" in category:
                dining_menu = await resort_client.get_dining_menu()
                for item in dining_menu[:6]:
                    cards.append({
                        "type": "dining_card",
                        "id": str(item.get("id") or ""),
                        "name": item.get("name", ""),
                        "price": float(item.get("price") or 0.0),
                        "category": item.get("category", "General"),
                        "description": item.get("description", ""),
                        "dietary": item.get("dietary", "Veg"),
                    })
                items = [{"name": i.get("name"), "price": i.get("price"), "dietary": i.get("dietary")} for i in dining_menu[:10]]
                action = "SHOW_DINING"

            elif "wellness" in category or "spa" in category:
                wellness = await resort_client.get_wellness_programs()
                for prog in wellness:
                    cards.append({
                        "type": "wellness_card",
                        "id": str(prog.get("id") or ""),
                        "name": prog.get("name") or prog.get("title") or "Wellness Session",
                        "price": float(prog.get("price") or 0.0),
                        "duration": prog.get("duration", "60 mins"),
                        "description": prog.get("description", ""),
                    })
                items = [{"name": w.get("name") or w.get("title"), "price": w.get("price")} for w in wellness[:10]]
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
                items = [{"name": e.get("title") or e.get("name"), "price": e.get("price")} for e in experiences[:10]]
                action = "SHOW_EXPERIENCES"

            return {"category": category, "items": items}, cards, action, payload, updated_quote

        elif name == "calculate_booking_quote":
            cottage_id = str(args.get("cottage_id") or "").strip()
            if not cottage_id or cottage_id.lower() in ("none", "null"):
                return {
                    "error": "Missing or invalid cottage_id. Use the exact `id` string returned by search_cottages."
                }, cards, action, payload, updated_quote
            check_in = str(args.get("check_in") or "").strip()
            check_out = str(args.get("check_out") or "").strip()
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
            payload["whatsapp_url"] = whatsapp_url
            updated_quote = payload
            if session_id:
                session_store.upsert_guest_profile(visitor_id=session_id, preferred_cottage=quote.cottage_name)

            cards.append({
                "type": "quote_card",
                "quote": payload,
                "whatsapp_url": whatsapp_url,
            })
            return payload, cards, action, payload, updated_quote

        elif name == "send_whatsapp_quote":
            phone = str(args.get("phone_number", "")).strip()
            quote_data = last_quote
            if not quote_data:
                return {
                    "status": "no_quote",
                    "message": "No active stay quote exists in this session yet. Calculate a stay quote first before generating a WhatsApp dispatch."
                }, cards, action, payload, updated_quote

            if session_id and phone:
                session_store.upsert_guest_profile(visitor_id=session_id, phone=phone)

            wa_url = notification_service.generate_whatsapp_link(quote_data, guest_phone=phone)
            cards.append({
                "type": "whatsapp_card",
                "phone": phone,
                "whatsapp_url": wa_url,
                "cottage_name": quote_data.get("cottage_name", "Luxury Villa"),
                "total_price": quote_data.get("grand_total") or quote_data.get("total_price") or 0.0,
            })
            return {"status": "success", "phone": phone, "whatsapp_url": wa_url}, cards, "SHOW_WHATSAPP", payload, updated_quote

        elif name == "lookup_guest_booking":
            email = str(args.get("email", "")).strip()
            token = str(args.get("verification_token", "")).strip()
            if not email or not token:
                return {
                    "status": "verification_required",
                    "message": "Guest privacy requires BOTH email and either Booking ID or last 4 phone digits."
                }, cards, action, payload, updated_quote

            bookings = await resort_client.lookup_guest_bookings(email)
            verified_bookings = []
            norm_token = token.lower().lstrip("#")

            for b in bookings:
                b_id = str(b.get("id") or b.get("_id") or b.get("booking_reference") or "").lower().lstrip("#")
                b_phone = "".join(filter(str.isdigit, str(b.get("guest_phone") or b.get("phone") or "")))
                if (b_id and norm_token == b_id) or (len(b_phone) >= 4 and token.endswith(b_phone[-4:])):
                    verified_bookings.append(b)

            if not verified_bookings:
                return {
                    "status": "verification_failed",
                    "message": "No reservation matched both the email address and provided verification code/phone digits."
                }, cards, action, payload, updated_quote

            for b in verified_bookings:
                cards.append({
                    "type": "booking_status_card",
                    "booking_id": str(b.get("id") or b.get("_id") or ""),
                    "status": b.get("status", "Confirmed"),
                    "check_in": b.get("check_in", ""),
                    "check_out": b.get("check_out", ""),
                    "total_price": b.get("total_price", 0.0),
                })
            action = "SHOW_BOOKINGS"
            return {"bookings_found": len(verified_bookings)}, cards, action, payload, updated_quote

        return {"error": f"Unknown tool: {name}"}, cards, action, payload, updated_quote


agent = ResortAgent()
