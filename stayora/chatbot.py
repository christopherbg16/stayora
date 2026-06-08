import json
import os
from datetime import datetime
from flask import url_for
from flask_login import current_user
from models import Hotel, Reservation, PropertyReservation, supabase, TrendingDestination, Promotion

api_key = os.environ.get("OPENAI_API_KEY")
_openai_available = bool(api_key) and api_key != "your-openai-api-key-here"

if _openai_available:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
else:
    client = None

conversations: dict = {}
MAX_HISTORY = 30

def _get_user_context():
    try:
        if current_user.is_authenticated:
            return {
                "authenticated": True,
                "username": current_user.username,
                "role": getattr(current_user, "role", "user"),
            }
    except Exception:
        pass
    return {"authenticated": False}

def _build_system_prompt():
    ctx = _get_user_context()
    return f"""You are Staya, a friendly travel assistant for StayOra, a property booking platform.

YOUR ROLE:
- Help users find properties (hotels, apartments, villas, resorts)
- Recommend popular properties and profitable investment opportunities
- Answer questions about destinations, pricing, availability
- Help with bookings and reservations
- Guide users to pages on the platform

RULES:
- Be natural and conversational, don't repeat yourself
- When asked about properties in a city -> use search_hotels() to find them
- After presenting results, ALWAYS ask "Would you like to see them?" or similar
- When user agrees to see properties -> use navigate_to() to take them there
- When asked about what to buy/sell -> search trending + property counts, give specific advice
- NEVER invent property data, always use search_hotels()
- Keep responses concise but informative

USER CONTEXT: {"Authenticated as " + ctx.get("username","") + " (" + ctx.get("role","") + ")" if ctx["authenticated"] else "Not authenticated"}
Today: {datetime.now().strftime('%Y-%m-%d')}"""

def _search_hotels(destination=None, property_type=None, min_price=None, max_price=None, limit=8):
    try:
        results = Hotel.search(destination=destination, property_type=property_type, min_price=min_price, max_price=max_price)
        return [
            {"id": h.id, "name": getattr(h, "name", "Unknown"), "city": getattr(h, "city", ""),
             "country": getattr(h, "country", ""), "property_type": getattr(h, "property_type", ""),
             "price_per_night": h.display_price, "avg_rating": float(getattr(h, "avg_rating", 0) or 0)}
            for h in results[:limit]
        ]
    except Exception as e:
        return {"error": str(e)}

def _get_trending():
    try:
        dests = TrendingDestination.get_active(limit=6)
        return [d.to_dict() for d in dests]
    except Exception:
        return []

def _get_promotions():
    try:
        promos = Promotion.get_active()
        return [{"name": getattr(p, "name", ""), "description": (getattr(p, "description", "") or "")[:100]} for p in promos]
    except Exception:
        return []

def _get_bookings_info():
    if not current_user.is_authenticated:
        return {"error": "Not authenticated"}
    try:
        username = current_user.username
        room_res = Reservation.find_by_guest(username)
        prop_res = PropertyReservation.find_by_guest(username)
        return {"total": len(room_res) + len(prop_res)}
    except Exception as e:
        return {"error": str(e)}

def _get_property_counts():
    try:
        return {"total": Hotel.count(), "hotels": Hotel.count_by_type("hotel"),
                "apartments": Hotel.count_by_type("apartment"), "villas": Hotel.count_by_type("villa"),
                "resorts": Hotel.count_by_type("resort")}
    except Exception as e:
        return {"error": str(e)}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_hotels",
            "description": "Search properties by city, type, and price range",
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {"type": "string", "description": "City name"},
                    "property_type": {"type": "string", "enum": ["hotel", "apartment", "villa", "resort"]},
                    "min_price": {"type": "number", "description": "Min price per night EUR"},
                    "max_price": {"type": "number", "description": "Max price per night EUR"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trending_destinations",
            "description": "Get popular/trending travel destinations",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_active_promotions",
            "description": "Get current deals and special offers",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_bookings_info",
            "description": "Get current user's booking count (requires authentication)",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_property_type_counts",
            "description": "Get counts of each property type on the platform",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate_to",
            "description": "Navigate user to a page on StayOra. Use when user agrees to see properties, view bookings, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL path e.g. /user/stays/search?city=Sofia, /user/hotel/5, /user/my-reservations"},
                    "label": {"type": "string", "description": "Where you're taking them"},
                },
                "required": ["url", "label"],
            },
        },
    },
]

TOOL_IMPL = {
    "search_hotels": _search_hotels,
    "get_trending_destinations": _get_trending,
    "get_active_promotions": _get_promotions,
    "get_user_bookings_info": _get_bookings_info,
    "get_property_type_counts": _get_property_counts,
}

MODELS = ["gpt-4o-mini", "gpt-3.5-turbo"]

def process_message(message, session_id=None):
    if not _openai_available or client is None:
        return _fallback_response(message)

    conv_id = session_id or "default"
    if conv_id not in conversations:
        conversations[conv_id] = [{"role": "system", "content": _build_system_prompt()}]

    history = conversations[conv_id]
    history.append({"role": "user", "content": message})
    _trim(conv_id)

    navigate_target = None
    last_err = None

    for model in MODELS:
        for _ in range(5):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=history,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=0.7,
                    max_tokens=600,
                )
            except Exception as e:
                last_err = e
                break

            choice = resp.choices[0]
            msg = choice.message

            if choice.finish_reason == "tool_calls" and msg.tool_calls:
                history.append(msg)
                for tc in msg.tool_calls:
                    fn = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    if fn == "navigate_to":
                        navigate_target = args.get("url", "/")
                        result = json.dumps({"ok": True})
                    elif fn in TOOL_IMPL:
                        try:
                            result = json.dumps(TOOL_IMPL[fn](**args), default=str)
                        except Exception as ex:
                            result = json.dumps({"error": str(ex)})
                    else:
                        result = json.dumps({"error": "unknown function"})
                    history.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                _trim(conv_id)
                continue

            elif choice.finish_reason == "stop":
                text = msg.content or ""
                history.append({"role": "assistant", "content": text})
                _trim(conv_id)
                out = {"text": text, "intent": "openai", "quick_replies": _quick_replies(text), "actions": _actions(text)}
                if navigate_target:
                    out["navigate"] = navigate_target
                return out

        # Model failed, try next one

    # All models failed
    text = _simple_response(message)
    history.append({"role": "assistant", "content": text})
    _trim(conv_id)
    return {"text": text, "intent": "fallback", "quick_replies": _quick_replies(text), "actions": _actions(text)}

def _trim(conv_id):
    if conv_id in conversations:
        conv = conversations[conv_id]
        sys_msgs = [m for m in conv if m["role"] == "system"]
        others = [m for m in conv if m["role"] != "system"]
        if len(others) > MAX_HISTORY:
            others = others[-MAX_HISTORY:]
        conversations[conv_id] = sys_msgs + others

def _quick_replies(text):
    t = text.lower()
    if any(w in t for w in ("booking", "reservation")):
        return ["My Bookings", "Browse Stays", "Deals"]
    if any(w in t for w in ("deal", "offer", "promotion")):
        return ["View Deals", "Search Hotels", "Popular Destinations"]
    if any(w in t for w in ("destination", "trending", "place", "city")):
        return ["Hotels", "Apartments", "Villas", "Trending"]
    return ["Search Hotels", "Popular Destinations", "My Bookings", "Deals"]

def _actions(text):
    try:
        t = text.lower()
        acts = [{"label": "Browse Stays", "url": url_for("user.browse_stays"), "primary": False}]
        if any(w in t for w in ("hotel", "apartment", "villa", "resort", "property", "stay")):
            acts.insert(0, {"label": "Search Properties", "url": url_for("user.search_stays"), "primary": True})
        return acts
    except Exception:
        return []

def _simple_response(message):
    m = message.lower()
    if any(w in m for w in ("hi", "hello", "hey", "zdravei")):
        return "Hello! I'm Staya, your travel assistant. How can I help you?"
    if any(w in m for w in ("search", "find", "hotel", "apartment", "villa", "stay", "property")):
        return "I can help you find the perfect place! What city are you interested in?"
    if any(w in m for w in ("booking", "reservation")):
        if current_user.is_authenticated:
            return "You can view your bookings in your dashboard. Would you like me to take you there?"
        return "Please sign in to view your bookings."
    if any(w in m for w in ("deal", "offer", "promotion", "discount")):
        return "We have great deals available! Browse our current offers."
    return "I'm here to help! Try asking about hotels, destinations, or your bookings."

def _fallback_response(message):
    text = _simple_response(message)
    return {"text": text, "intent": "fallback", "quick_replies": _quick_replies(text), "actions": _actions(text)}

def detect_intent(message):
    return "openai"

def get_response_for_intent(intent, message=None):
    return {"text": "How can I help you?", "intent": "openai"}
