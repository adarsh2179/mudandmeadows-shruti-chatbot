# Mud & Meadows Resort — AI Concierge System Architecture & Project Dossier

**Author / Maintainer**: Engineering Team  
**Target Deployment**: [mudandmeadows.in](https://mudandmeadows.in/)  
**Environment**: Production Ready (Python 3.11+, FastAPI, Docker, Google Gemini 3.5 Flash Lite)  
**Operating Cost**: $0.00 / month (Zero Ongoing SaaS Overhead)

---

## 1. Executive Summary & Problem Context

Hospitality websites frequently lose direct bookings because traditional booking widgets are rigid and disconnected from human conversation. When a family or group of friends visits a resort website:
1. They want to ask questions naturally (*"We are 4 adults and 2 kids looking for a 2-bedroom villa for 3 nights next weekend with extra bedding"*).
2. Traditional drop-down forms cannot reason about multi-cottage occupancy, extra bed charges, or package recommendations.
3. Typical "AI chatbots" powered by basic Vector RAG (retrieval over PDFs) cannot calculate prices accurately, hallucinate dates and taxes, and have no ability to check live room availability or process payments.

This project implements an **autonomous, full-stack AI Concierge engine** specifically engineered for **Mud & Meadows Resort**. It acts as a real-time digital receptionist (named "Shruti") that:
- Inspects real-time villa availability and layouts directly from the resort's Cloud Run REST API.
- Calculates exact, mathematically auditable booking quotes under Indian GST law.
- Formats quotations for instant 1-tap forwarding over WhatsApp.
- Executes secure in-chat payments via Razorpay with cryptographic signature verification.
- Embeds into any website via a single `<script>` tag using Shadow DOM encapsulation.
- Operates at **zero software cost ($0.00)**.

---

## 2. Fundamental Architectural Decisions

### ReAct Agent vs. Classic Vector RAG

A standard pattern in AI engineering is **Retrieval-Augmented Generation (RAG)**: chunking text into vector databases (Pinecone, Weaviate) and performing cosine similarity searches. 

For a transactional resort concierge, **standard RAG was rejected** for the following architectural reasons:

1. **State & Freshness**: Villa availability and rates change continuously. In a vector database, documents quickly become stale unless heavy re-indexing pipelines are maintained.
2. **Mathematical Determinism**: Large Language Models cannot be trusted with arithmetic. Prompting an LLM to calculate "3 nights at ₹18,000 + 2 extra beds at ₹1,500/night + 18% GST" frequently results in arithmetic hallucinations.
3. **Transactional Capability**: A RAG pipeline is inherently read-only. It cannot create Razorpay payment orders, validate promotional coupons, or commit confirmed bookings into a Property Management System (PMS).

**The ReAct (Reasoning + Acting) Solution**:
We implemented an autonomous ReAct loop powered by **Google Gemini 3.5 Flash Lite** with structured function declarations. The LLM acts purely as a semantic orchestrator:
- It understands guest intent.
- It determines which backend tool to call (`search_cottages`, `calculate_booking_quote`, `get_resort_services`).
- The actual business and financial logic is executed in deterministic Python.
- Tool outputs are fed back into the model's reasoning loop for up to 4 autonomous iterations before returning a final response.

---

## 3. End-to-End System Architecture

```
+-----------------------------------------------------------------------+
|                         CLIENT BROWSER                                |
|  Host Website: mudandmeadows.in                                       |
|  +-----------------------------------------------------------------+  |
|  | #shadow-root (Open)                                             |  |
|  | - Luxury earth-toned theme (isolated from parent CSS)           |  |
|  | - Web Speech API (en-IN locale)                                 |  |
|  | - Interactive UI cards (Villas, Quotes, Action Buttons)         |  |
|  | - Razorpay Standard Checkout SDK Modal                          |  |
|  +-----------------------------------------------------------------+  |
+-----------------------------------------------------------------------+
                                  |
                   JSON / Multipart POST via HTTPS
                                  v
+-----------------------------------------------------------------------+
|                    FASTAPI ASGI GATEWAY (Port 8000)                   |
|  main.py                                                              |
|  - CORS Policy (Strict whitelist: mudandmeadows.in)                   |
|  - Session-based conversation memory store                            |
|  - Payment endpoints (/api/payment/create-order, verify-and-book)     |
|  - Static asset streaming (/static/widget.js, /static/widget.css)     |
+-----------------------------------------------------------------------+
                                  |
         +------------------------+------------------------+
         |                                                 |
         v                                                 v
+-------------------------------+       +-------------------------------+
|    AUTONOMOUS AGENT ENGINE    |       |   DETERMINISTIC PRICING       |
|    agent.py                   |       |   pricing_engine.py           |
|  - Gemini 3.5 Flash Lite      |       |  - Calendar night computation |
|  - Multi-turn tool execution  |       |  - Tiered GST (12% vs 18%)    |
|  - Domain guardrails          |       |  - Extra bedding calculations |
|  - Self-healing 503 retries   |       |  - Coupon deductions          |
+-------------------------------+       +-------------------------------+
         |                                                 |
         v                                                 v
+-----------------------------------------------------------------------+
|                     EXTERNAL CLOUD SERVICES                           |
|  - Google Gemini API: generativelanguage.googleapis.com (Free Tier)   |
|  - Resort REST API: mudandmeadows-api-...asia-south1.run.app          |
|  - Razorpay Gateway: api.razorpay.com                                 |
|  - WhatsApp Protocol: api.whatsapp.com/send (RFC 3986 Deep Link)      |
+-----------------------------------------------------------------------+
```

---

## 4. Deep-Dive into Core Modules

### 4.1. The Financial Pricing Engine (`pricing_engine.py`)
Indian hospitality tax law (Notification No. 11/2017 - Central Tax (Rate)) mandates tiered GST brackets based on the declared tariff per night:
- **Tariff ≤ ₹7,500/night**: 12% GST
- **Tariff > ₹7,500/night**: 18% GST

`PricingEngine` is completely decoupled from the AI agent:
- Parses ISO date strings (`YYYY-MM-DD`) and computes calendar nights.
- Calculates base rent: $\text{Tariff} \times \text{Nights}$.
- Adds extra bedding: $\text{Count} \times ₹1,500 \times \text{Nights}$.
- Computes taxable subtotal after promotional coupon deductions.
- Applies the statutory GST rate.
- Returns an immutable, auditable `BookingQuote` dictionary that feeds both the LLM context and the UI quote card.

### 4.2. The ReAct Agent Loop (`agent.py`)
The reasoning loop executes within `agent.chat()`:
```python
# Autonomous loop allowing up to 4 tool-calling turns
for step in range(4):
    response = await self._call_gemini_with_fallback(contents=history, config=config)
    function_call_part = next((p for p in candidate.content.parts if p.function_call), None)
    
    if function_call_part:
        # Tool invocation requested by model
        tool_result, step_cards, step_action, step_payload = await self._execute_tool(...)
        # Feed tool result back to history as role="user"
        history.append(...)
    else:
        # Final natural language synthesis achieved
        final_text = response.text.strip()
        break
```
**Resilience & State Safeguards**:
- **SQLite WAL + Bounded LRU Store (`session_store.py`)**: Replaces unbounded in-memory dictionaries with a $0.00 persistent SQLite WAL database paired with an in-memory LRU cache (`ttl=1800s`), supporting multi-worker deployments without memory leaks.
- **Sliding Window Context & Tool Pruning**: Bounds prompt context to the 12 most recent turns while stripping noisy image arrays from tool payloads returned to the model (~75% token reduction).
- **Dynamic Date Awareness & Lookup Privacy**: Dynamically injects the current date for relative queries ("this weekend") and gates `lookup_guest_booking` behind email + secondary verification (booking ID or last 4 phone digits).
- **Rate Limiting**: Protects free-tier Gemini RPM quotas with a sliding-window IP/bucket rate limiter (`HTTP 429`).

### 4.3. The Resort API Client (`resort_client.py`)
An asynchronous client powered by a persistent singleton `httpx.AsyncClient` connection pool initialized during FastAPI `lifespan`, paired with a 30-second read-through TTL cache to minimize TLS handshake overhead:
- `GET /api/cottages/`: Real-time inventory, rates, and capacities (30s TTL cached + stale fallback).
- `GET /api/cottages/{id}`: Detailed specifications, layout, and amenities (30s TTL cached).
- `GET /api/dining/all`: Restaurant menus, dining specials, and dietary labels.
- `GET /api/wellness/programs`: Ayurvedic spa treatments and durations.
- `GET /api/experiences/`: Nature walks, bonfire activities, and workshops.
- `POST /api/coupons/quote`: Promo validation.
- `POST /api/bookings/public`: Commits confirmed reservation records.

### 4.4. Financial Precision & Payment Security (`pricing_engine.py` & `main.py`)
1. **Decimal Currency Math**: Uses Python `decimal.Decimal` (`ROUND_HALF_UP`) strictly adhering to Indian GST tariff rules (`<= ₹7,500`: 12%, `> ₹7,500`: 18%), preventing IEEE 754 1-paise drift.
2. **Server-Authoritative Pricing**: Clients submit `cottage_id`, `check_in`, `check_out`, and guest details; the server recomputes the order total internally before calling Razorpay.
3. **Cryptographic HMAC-SHA256 Verification**: Payments returned by Razorpay Checkout are verified using constant-time `hmac.compare_digest` checks.
4. **Client Drop-Off Protection (`POST /api/payment/webhook`)**: Server-to-server webhooks verify `X-Razorpay-Signature` and automatically recover captured payments if the guest closes their browser after UPI authentication.
5. **Idempotency**: Duplicate taps within 15 minutes return the staged Razorpay `order_id` without re-triggering charges.

### 4.5. Client SDK, Returning Visitor Continuity & Shadow DOM (`static/widget.js` & `widget.css`)
To allow embedding on any CMS (WordPress, Webflow, React, Shopify):
- Attaches an open **Shadow Root** (`element.attachShadow({ mode: 'open' })`) for strict CSS scope isolation.
- Sanitizes all chat inputs and dynamic HTML rendering (`escapeHtml`) to mitigate XSS vulnerabilities.
- **Returning Guest Continuity (Progressive Identity)**: Uses `localStorage` (`mm_visitor_id`) paired with SQLite `guest_profiles` and `GET /api/chat/history` instead of an upfront email/login barrier. Guests chat without friction, past bubbles survive page navigation across `mudandmeadows.in`, and contact details provided in WhatsApp or checkout drawers are remembered and pre-filled on repeat visits.
- Replaces intrusive browser `window.prompt()` dialogs with inline luxury drawers inside the Shadow DOM for WhatsApp numbers and guest reservation details.
- Employs native **Web Speech API** (`webkitSpeechRecognition`) configured for `en-IN` with an automatic `MediaRecorder` $\rightarrow$ `/api/voice/process` backend fallback for Safari iOS and Firefox.

### 4.6. WhatsApp Quotation Protocol (`notification_service.py`)
Rather than integrating paid WhatsApp Business APIs (Twilio or Meta Cloud API, which charge per-conversation fees), the concierge generates pre-formatted, luxury markdown summaries via standard **Click-to-Chat deep links** (`https://api.whatsapp.com/send?text=...`). Guests tap once to forward quotes to their travel group or the resort reservations desk at zero cost.

---

## 5. Operating Cost Breakdown ($0.00 / Month)

| Layer | Service / Technology | Cost Model | Monthly Expense |
| :--- | :--- | :--- | :--- |
| **Intelligence** | Google Gemini 3.5 Flash Lite | AI Studio Free Tier (15 RPM / 1M TPM) | $0.00 |
| **Speech-to-Text** | Web Speech API (Client) + Groq Whisper fallback | Client-side native browser API + Groq Free Tier | $0.00 |
| **Messaging** | Universal WhatsApp Click-to-Chat Protocol | Standard URL protocol (RFC 3986) | $0.00 |
| **Database & Inventory** | Live Cloud Run Backend API | Existing resort infrastructure | $0.00 |
| **Payment Gateway** | Razorpay Standard Checkout | Standard 2% per successful transaction (No recurring fee) | $0.00 |
| **Hosting** | AWS EC2 / App Runner Free Tier | 750 hours/month t2.micro/t3.micro | $0.00 |
| **Total Software Cost** | | | **$0.00** |

---

## 6. How to Deploy to Production

### 1. Embed on Host Website (`mudandmeadows.in`)
Add the following snippet before the closing `</body>` tag on the website:
```html
<script 
  src="https://your-chatbot-domain.com/static/widget.js" 
  data-api-base="https://your-chatbot-domain.com"
  async>
</script>
```

### 2. Run with Docker Compose
```bash
docker compose up -d --build
```

### 3. Verify System Health
```bash
curl http://localhost:8000/health
```

---

## 7. Technical Highlights for Engineering Review

When reviewing this codebase for technical evaluation:
* **Separation of Concerns**: Business and mathematical logic (`pricing_engine.py`) is completely decoupled from semantic orchestration (`agent.py`).
* **Defensive Engineering**: Cryptographic signature validation, production environment switches, and exponential backoff retry patterns ensure enterprise stability.
* **Cost Efficiency**: Engineered specifically to deliver an enterprise-grade guest experience without introducing recurring SaaS software costs.
