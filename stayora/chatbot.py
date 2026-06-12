import json
import os
import re
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


def _search_hotels(destination=None, property_type=None, min_price=None, max_price=None, stars=None, limit=8):
    try:
        results = Hotel.search(destination=destination, property_type=property_type,
                               min_price=min_price, max_price=max_price, stars=stars)
        return [
            {"id": h.id, "name": getattr(h, "name", "Unknown"), "city": getattr(h, "city", ""),
             "country": getattr(h, "country", ""), "property_type": getattr(h, "property_type", ""),
             "price_per_night": getattr(h, "price_per_night", 0) or 0, "avg_rating": float(getattr(h, "avg_rating", 0) or 0),
             "stars": getattr(h, "stars", 0) or 0}
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
    if _openai_available and client is not None:
        result = _try_openai(message, session_id)
        if result is not None:
            return result

    return _db_response(message, session_id)


def _try_openai(message, session_id=None):
    conv_id = session_id or "default"
    if conv_id not in conversations:
        conversations[conv_id] = [{"role": "system", "content": _build_system_prompt()}]

    history = conversations[conv_id]
    history.append({"role": "user", "content": message})
    _trim(conv_id)

    navigate_target = None
    last_err = None

    for model in MODELS:
        for _ in range(2):
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

    return None


def _trim(conv_id):
    if conv_id in conversations:
        conv = conversations[conv_id]
        sys_msgs = [m for m in conv if m["role"] == "system"]
        others = [m for m in conv if m["role"] != "system"]
        if len(others) > MAX_HISTORY:
            others = others[-MAX_HISTORY:]
        conversations[conv_id] = sys_msgs + others


# ── ENTITY DEFINITIONS ──────────────────────────────────────────────

CITIES = {
    "sofia": "Sofia", "bansko": "Bansko", "plovdiv": "Plovdiv", "varna": "Varna",
    "paris": "Paris", "venice": "Venice", "tokyo": "Tokyo", "santorini": "Santorini",
    "new york": "New York", "london": "London", "dubai": "Dubai", "barcelona": "Barcelona",
    "bali": "Bali", "samokov": "Samokov", "burgas": "Burgas", "ubud": "Ubud",
}

COUNTRIES = {
    "italy": "Italy", "france": "France", "japan": "Japan", "greece": "Greece",
    "spain": "Spain", "indonesia": "Indonesia", "bulgaria": "Bulgaria",
    "england": "United Kingdom", "uk": "United Kingdom", "britain": "United Kingdom",
    "uae": "United Arab Emirates", "usa": "USA", "america": "USA", "united states": "USA",
}

TYPES = {"apartment": "apartment", "apartments": "apartment",
         "hotel": "hotel", "hotels": "hotel",
         "villa": "villa", "villas": "villa",
         "resort": "resort", "resorts": "resort"}

GREET_WORDS = ("hi", "hello", "hey", "zdravei", "good morning", "good evening", "morning", "evening")
BOOKING_WORDS = ("booking", "reservation", "my trip", "my bookings", "my reservation", "my reservations")
TRENDING_WORDS = ("trending", "popular", "destination", "best place", "recommend", "where to go", "top rated", "best")
AVAILABILITY_WORDS = ("available", "availability", "book", "check availability", "availability for", "available from", "available until")
BUDGET_WORDS = ("cheap", "budget", "affordable", "cheapest", "low price", "under", "economy", "inexpensive", "low cost")
LUXURY_WORDS = ("luxury", "luxurious", "premium", "high end", "fancy", "exclusive", "top", "expensive", "highest price", "most expensive")
HELP_WORDS = ("help", "what can you", "what do you", "how", "?", "capabilities")
THANKS_WORDS = ("thanks", "thank you", "thanks a lot", "appreciate", "thx")
COUNT_WORDS = ("how many", "count", "total", "available", "all properties", "everything")
CHEAPEST_WORDS = ("cheapest", "lowest price", "most affordable")
TOPRATED_WORDS = ("top rated", "highest rated", "best rated", "highest rating", "best reviews")
STAR_WORDS = {"5 star": 5, "5-star": 5, "five star": 5, "5 stars": 5,
              "4 star": 4, "4-star": 4, "four star": 4, "4 stars": 4,
              "3 star": 3, "3-star": 3, "three star": 3, "3 stars": 3}

conversations_db: dict = {}
session_property_cache: dict = {}

def _normalize_date_string(date_str):
    from datetime import datetime
    parts = re.split(r'[./]', date_str)
    if len(parts) != 3:
        return None
    day, month, year = parts
    try:
        day = int(day)
        month = int(month)
        year = int(year)
        if year < 100:
            year += 2000
        dt = datetime(year, month, day)
        return dt.strftime('%Y-%m-%d')
    except Exception:
        return None
# ── ENTITY EXTRACTION ─────────────────────────────────────────────

def _extract_entities(m):
    entities = {
        "has_greeting": False, "cities": [], "countries": [], "property_types": set(),
        "price_min": None, "price_max": None, "stars": [], "wants_booking": False,
        "wants_trending": False, "wants_help": False, "wants_thanks": False,
        "wants_count": False, "price_intent": None, "wants_cheapest": False, "wants_toprated": False,
        "check_in": None, "check_out": None, "wants_availability": False, "raw": m,
    }
    import re

    # Use word-boundary regex to avoid accidental substring matches (e.g. 'show' matching 'how')
    for w in GREET_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", m):
            entities["has_greeting"] = True
            break

    for kw, city in CITIES.items():
        if re.search(r"\b" + re.escape(kw) + r"\b", m):
            entities["cities"].append(city)

    for kw, country in COUNTRIES.items():
        if re.search(r"\b" + re.escape(kw) + r"\b", m):
            entities["countries"].append(country)

    for kw, ptype in TYPES.items():
        if re.search(r"\b" + re.escape(kw) + r"\b", m):
            entities["property_types"].add(ptype)

    for phrase, stars in STAR_WORDS.items():
        if re.search(r"\b" + re.escape(phrase) + r"\b", m):
            entities["stars"].append(stars)

    for w in BOOKING_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", m):
            entities["wants_booking"] = True
            break

    for w in TRENDING_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", m):
            entities["wants_trending"] = True
            break

    for w in BUDGET_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", m):
            # Mark a budget intent but do not force a max price unless the user specified one
            entities["price_intent"] = "budget"
            break

    for w in LUXURY_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", m):
            entities["price_intent"] = "luxury"
            entities["price_min"] = 200
            break

    for w in CHEAPEST_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", m):
            entities["wants_cheapest"] = True
            break

    for w in TOPRATED_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", m):
            entities["wants_toprated"] = True
            break

    for w in HELP_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", m):
            entities["wants_help"] = True
            break

    for w in THANKS_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", m):
            entities["wants_thanks"] = True
            break

    for w in COUNT_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", m):
            entities["wants_count"] = True
            break

    for w in AVAILABILITY_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", m):
            entities["wants_availability"] = True
            break

    date_range = re.search(r'(\d{1,2}[./]\d{1,2}[./]\d{2,4})\s*(?:until|to|through|thru|-)\s*(\d{1,2}[./]\d{1,2}[./]\d{2,4})', m)
    if date_range:
        start = _normalize_date_string(date_range.group(1))
        end = _normalize_date_string(date_range.group(2))
        if start and end:
            entities["check_in"] = start
            entities["check_out"] = end

    if not entities["check_in"] or not entities["check_out"]:
        date_strings = re.findall(r'(\d{1,2}[./]\d{1,2}[./]\d{2,4})', m)
        if len(date_strings) >= 2:
            start = _normalize_date_string(date_strings[0])
            end = _normalize_date_string(date_strings[1])
            if start and end:
                entities["check_in"] = start
                entities["check_out"] = end

    return entities
    price_pattern = re.findall(r'(?:under|below|less than|max|up to)\s*(\d+)', m)
    if price_pattern:
        val = int(price_pattern[-1])
        if entities["price_max"] is None or val < entities["price_max"]:
            entities["price_max"] = val

    price_pattern = re.findall(r'(?:over|above|more than|min|from|at least)\s*(\d+)', m)
    if price_pattern:
        val = int(price_pattern[-1])
        if entities["price_min"] is None or val > entities["price_min"]:
            entities["price_min"] = val

    range_match = re.findall(r'(?:between\s+)?(\d+)\s*(?:and|-|to)\s*(\d+)', m)
    if range_match:
        lo, hi = int(range_match[-1][0]), int(range_match[-1][1])
        entities["price_min"] = lo
        entities["price_max"] = hi
        entities["price_intent"] = "range"

    return entities

# ── INTENT SCORING ───────────────────────────────────────────────

def _score_intents(e):
    intents = []

    if e["wants_cheapest"] and e["property_types"]:
        intents.append(("cheapest_type", 115, e))

    if e["wants_toprated"] and e["property_types"]:
        intents.append(("toprated_type", 115, e))

    if e["property_types"] and e["countries"]:
        intents.append(("search_type_country", 100 + len(e["property_types"]) * 3, e))

    if e["property_types"] and e["cities"]:
        intents.append(("search_type_city", 95 + len(e["property_types"]) * 3, e))

    if e["property_types"] and (e["price_min"] is not None or e["price_max"] is not None) and e["countries"]:
        intents.append(("search_full", 110, e))

    if e["check_in"] and e["check_out"]:
        intents.append(("availability", 120, e))
    elif e["wants_availability"]:
        intents.append(("availability", 90, e))

    if e["countries"] and e["price_min"] is not None:
        intents.append(("search_country_luxury" if e.get("price_intent") == "luxury" else "search_country_budget", 90, e))

    if e["countries"]:
        intents.append(("search_country", 80, e))

    if e["cities"] and (e["price_min"] is not None or e["price_max"] is not None):
        intents.append(("search_city_price", 85, e))

    if e["cities"]:
        intents.append(("search_city", 75, e))

    if e["property_types"] and (e["price_min"] is not None or e["price_max"] is not None):
        intents.append(("search_type_price", 80, e))

    if e["property_types"]:
        intents.append(("search_type", 70, e))

    if e["price_intent"] == "budget":
        intents.append(("budget", 55, e))
    elif e["price_intent"] == "luxury":
        intents.append(("luxury", 55, e))

    if e["wants_trending"]:
        intents.append(("trending", 50, e))

    if e["wants_booking"]:
        intents.append(("booking", 60, e))

    if e["wants_count"]:
        intents.append(("count", 40, e))

    if e["wants_help"]:
        intents.append(("help", 30, e))

    if e["wants_thanks"]:
        intents.append(("thanks", 20, e))

    if e["has_greeting"] and not any(e[k] for k in ("cities", "countries", "property_types") if e[k]) and not e["wants_booking"] and not e["wants_help"] and not e["wants_trending"] and not e["wants_count"]:
        intents.append(("greeting", 5, e))

    intents.sort(key=lambda x: -x[1])
    return intents

# ── CONVERSATION MEMORY ──────────────────────────────────────────

def _save_context(session_id, message):
    if not session_id:
        return
    if session_id not in conversations_db:
        conversations_db[session_id] = []
    conversations_db[session_id].append(message)
    if len(conversations_db[session_id]) > 10:
        conversations_db[session_id] = conversations_db[session_id][-10:]


def _store_session_properties(session_id, properties):
    if not session_id or not isinstance(properties, list):
        return
    session_property_cache[session_id] = properties


def _get_session_properties(session_id):
    return session_property_cache.get(session_id, [])


def _find_property_in_session(session_id, message):
    properties = _get_session_properties(session_id)
    if not properties:
        return None
    normalized = message.lower()

    # Allow choosing by ordinal position in the last list
    ordinal = re.search(r"\b(?:first|second|third|1st|2nd|3rd)\b", normalized)
    if ordinal:
        text = ordinal.group(0)
        if "first" in text or "1st" in text:
            return properties[0] if len(properties) > 0 else None
        if "second" in text or "2nd" in text:
            return properties[1] if len(properties) > 1 else None
        if "third" in text or "3rd" in text:
            return properties[2] if len(properties) > 2 else None

    number = re.search(r"(?<![\d./])\b(\d+)\b(?![\d./])(?:\s+(?:hotel|property|result|choice))?", normalized)
    if number:
        idx = int(number.group(1)) - 1
        if 0 <= idx < len(properties):
            return properties[idx]

    explicit_id = re.search(r"\b(?:hotel|property)\s*(?:id\s*)?#?(\d+)\b", normalized)
    if explicit_id:
        pid = int(explicit_id.group(1))
        for prop in properties:
            if prop.get("id") == pid:
                return prop

    for prop in properties:
        if prop.get("name") and prop["name"].lower() in normalized:
            return prop

    # Fallback to the first property when the user refers to "this" or "that" after a property listing
    if any(word in normalized for word in ("this property", "this hotel", "that hotel", "that property", "selected")):
        return properties[0]

    return None


def _load_context(session_id):
    if session_id and session_id in conversations_db:
        return conversations_db[session_id]
    return []

# ── INTENT EXECUTORS ─────────────────────────────────────────────

def _exec_greeting(e, session_id=None):
    if current_user.is_authenticated:
        return _make_response(
            f"Welcome back, {current_user.username}. Systems online. How can I assist with your travels?",
            ["Search Hotels", "My Bookings", "Popular Destinations", "Deals"]
        )
    return _make_response(
        "Good day. I'm Staya, your travel intelligence system. Looking for a place to stay?",
        ["Search Hotels", "Popular Destinations", "Sign In", "Deals"]
    )

def _exec_search_city(e, session_id):
    ctx = _load_context(session_id)
    city = e["cities"][0]
    if not city:
        city = _extract_city_from_context(ctx)
    if not city:
        return _make_response("Which city are you interested in?", ["Popular Destinations", "Browse All Properties"])

    hotels = _search_hotels(destination=city)
    if not isinstance(hotels, list) or not hotels:
        return _make_response(
            f"Scanned {city} — no properties found. Try a different city?",
            ["Browse All Properties", "Popular Destinations"]
        )
    _store_session_properties(session_id, hotels)

    lines = [f"Here are **{len(hotels)} properties** found in {city}."]
    for h in hotels[:4]:
        stars = "★" * h.get("stars", 3)
        lines.append(f"> {stars} **{h['name']}** — EUR{h['price_per_night']}/night — ⭐ {h['avg_rating']}/5")
    if len(hotels) > 4:
        lines.append(f"\n{len(hotels) - 4} more available.")
    lines.append("\nWould you like me to check availability for these?")

    qr = ["Check dates", "Show all", "Popular Destinations"]
    nav = f"/user/stays/search?destination={city}"
    if e.get("price_intent") == "budget":
        nav += "&sort_by=price_asc"
    elif e.get("price_intent") == "luxury":
        nav += "&sort_by=price_desc"
    return _make_response("\n".join(lines), qr, navigate=nav, properties=_props_for(hotels))

def _exec_search_country(e, session_id):
    ctx = _load_context(session_id)
    country = e["countries"][0] if e["countries"] else None
    if not country:
        country = _extract_country_from_context(ctx)
    if not country:
        return _make_response("Which country are you looking at?", ["Popular Destinations", "Browse All Properties"])

    hotels = _search_hotels(destination=country)
    if not isinstance(hotels, list) or not hotels:
        return _make_response(
            f"No properties found in {country} yet. Try a nearby destination?",
            ["Browse All Properties", "Popular Destinations"]
        )
    _store_session_properties(session_id, hotels)

    cities_list = list(dict.fromkeys(h["city"] for h in hotels if h.get("city")))
    cities_line = f" Spread across **{', '.join(cities_list[:5])}**." if cities_list else ""

    price_range = f"EUR{min(h['price_per_night'] for h in hotels)}–EUR{max(h['price_per_night'] for h in hotels)}/night"
    avg_rating = round(sum(h["avg_rating"] for h in hotels) / len(hotels), 1)

    lines = [f"Here are **{len(hotels)} properties** in {country}.{cities_line}"]
    lines.append(f"Price range: {price_range} | Avg rating: {avg_rating}/5\n")
    for h in hotels[:3]:
        lines.append(f"> **{h['name']}** — {h['city']} — EUR{h['price_per_night']}/night — ⭐ {h['avg_rating']}/5")
    if len(hotels) > 3:
        lines.append(f"\n+ {len(hotels) - 3} more properties.")
    lines.append("\nWould you like me to check availability for these?")

    nav = f"/user/stays/search?destination={country}"
    if e.get("price_intent") == "budget":
        nav += "&sort_by=price_asc"
    elif e.get("price_intent") == "luxury":
        nav += "&sort_by=price_desc"
    return _make_response("\n".join(lines), ["Show all", "Filter by type", "Popular Destinations"],
                          navigate=nav, properties=_props_for(hotels))

def _exec_search_type(e, session_id):
    ctx = _load_context(session_id)
    ptypes = e["property_types"]
    if not ptypes:
        pt = _extract_type_from_context(ctx)
        ptypes = {pt} if pt else set()
    if not ptypes:
        counts = _get_property_counts()
        if isinstance(counts, dict):
            return _make_response(
                f"What type? We have {counts.get('hotels', 0)} hotels, {counts.get('apartments', 0)} apartments, {counts.get('villas', 0)} villas, {counts.get('resorts', 0)} resorts.",
                ["Hotels", "Apartments", "Villas", "Resorts"]
            )
        return _make_response("Which type? Hotels, apartments, villas, or resorts?", ["Hotels", "Apartments", "Villas", "Resorts"])

    ptype = next(iter(ptypes))
    dest = None
    if e["cities"]:
        dest = e["cities"][0]
    elif e["countries"]:
        dest = e["countries"][0]
    else:
        for ctx_msg in reversed(ctx):
            ce = _extract_entities(ctx_msg.lower())
            if ce["cities"]:
                dest = ce["cities"][0]
                break
            if ce["countries"]:
                dest = ce["countries"][0]
                break

    stars = e.get("stars", []) or []
    hotels = _search_hotels(destination=dest, property_type=ptype, stars=stars if stars else None,
                             min_price=e.get("price_min"), max_price=e.get("price_max"))

    if not isinstance(hotels, list) or not hotels:
        filters = []
        if e.get("price_max"):
            filters.append(f"under EUR{e['price_max']}")
        if e.get("price_min"):
            filters.append(f"over EUR{e['price_min']}")
        if e.get("stars"):
            filters.append(f"{e['stars'][0]}-star")
        filter_str = f" ({', '.join(filters)})" if filters else ""

        # Check if the location exists with other types
        all_in_loc = _search_hotels(destination=dest) if dest else []
        if isinstance(all_in_loc, list) and all_in_loc:
            other_types = list(dict.fromkeys(h["property_type"] for h in all_in_loc if h.get("property_type") != ptype))
            msg = f"No {ptype}s in {dest}{filter_str}. "
            if other_types:
                other_plural = [t + "s" for t in other_types[:3]]
                msg += f"However, there are {', '.join(other_plural)} available in {dest}. Want to try those?"
            else:
                msg += f"The properties in {dest} start from EUR{min(h['price_per_night'] for h in all_in_loc)}/night. Try a higher budget?"
            nav = f"/user/stays/search?destination={dest}" if dest else "/user/stays/search"
            return _make_response(msg, ["Adjust Filters", "Browse All"], navigate=nav, properties=_props_for(all_in_loc))

        # No results at all in this location
        loc_str = f" in {dest}" if dest else ""
        return _make_response(
            f"No {ptype}s found{loc_str}{filter_str}. Try a different location or property type?",
            ["Browse All Properties", "Popular Destinations"], navigate="/user/stays/search",
            properties=_props_for([])
        )

    loc_str = f" in {dest}" if dest else ""
    type_label = ptype if len(hotels) == 1 else f"{ptype}s"
    lines = [f"Here are **{len(hotels)} {type_label}{loc_str}** matching your criteria:\n"]
    for h in hotels[:4]:
        star_str = "★" * h.get("stars", 3) if h.get("stars") else ""
        lines.append(f"> {star_str} **{h['name']}** — {h['city']} — EUR{h['price_per_night']}/night — ⭐ {h['avg_rating']}/5")
    if len(hotels) > 4:
        lines.append(f"\n+ {len(hotels) - 4} more.")
    lines.append(f"\nHere are the results. Would you like me to check availability?")
    _store_session_properties(session_id, hotels)

    # Build a navigate URL that always includes the property type and applicable sorting/filters
    nav = f"/user/stays/search?property_type={ptype}"
    if dest:
        nav += f"&destination={dest}"

    # Add sorting based on price intent (show cheapest/luxury first)
    if e.get("price_intent") == "budget":
        nav += "&sort_by=price_asc"
    elif e.get("price_intent") == "luxury":
        nav += "&sort_by=price_desc"

    # Add explicit price filters if the user provided numeric values
    if e.get("price_min"):
        nav += f"&min_price={e['price_min']}"
    if e.get("price_max"):
        nav += f"&max_price={e['price_max']}"

    qr = ["Check dates", "Show all results"]
    if not dest:
        qr.append("Search by City")
    return _make_response("\n".join(lines), qr, navigate=nav, properties=_props_for(hotels))

def _exec_budget(e, session_id):
    max_p = e.get("price_max") or 100
    hotels = _search_hotels(max_price=max_p)
    if not isinstance(hotels, list) or not hotels:
        return _make_response(
            f"Nothing under EUR{max_p}/night right now. Try a higher budget?",
            ["Browse All Properties", "Popular Destinations"]
        )
    _store_session_properties(session_id, hotels)
    lines = [f"**Budget picks — under EUR{max_p}/night:**\n"]
    for h in hotels[:5]:
        lines.append(f"> **{h['name']}** — {h['city']}, {h['country']} — EUR{h['price_per_night']}/night")
    lines.append(f"\nGreat value options. Ready to explore more?")
    return _make_response("\n".join(lines), ["Show All Budget", "Search Hotels"], navigate=f"/user/stays/search?max_price={max_p}&sort_by=price_asc", properties=_props_for(hotels))

def _exec_luxury(e, session_id):
    min_p = e.get("price_min") or 200
    hotels = _search_hotels(min_price=min_p)
    if not isinstance(hotels, list) or not hotels:
        return _make_response(
            f"Nothing over EUR{min_p}/night currently. Try a different range?",
            ["Browse All Properties", "Popular Destinations"]
        )
    _store_session_properties(session_id, hotels)
    lines = [f"**Premium selection — EUR{min_p}+/night:**\n"]
    for h in hotels[:5]:
        star_str = "★" * h.get("stars", 3)
        lines.append(f"> {star_str} **{h['name']}** — {h['city']} — EUR{h['price_per_night']}/night — ⭐ {h['avg_rating']}/5")
    lines.append("\nExperience the finest. Ready to book?")
    return _make_response("\n".join(lines), ["Show All Luxury", "Search Hotels"], navigate=f"/user/stays/search?min_price={min_p}&sort_by=price_desc", properties=_props_for(hotels))

def _exec_trending(e, session_id):
    all_h = _search_hotels()
    if not isinstance(all_h, list) or not all_h:
        return _make_response("No properties available to recommend right now.", ["Browse Later"])
    top = sorted(all_h, key=lambda h: h.get("avg_rating", 0), reverse=True)[:6]
    _store_session_properties(session_id, top)
    lines = ["**Trending destinations — top rated right now:**\n"]
    for h in top:
        lines.append(f"> ⭐ **{h['name']}** — {h['city']}, {h['country']} — {h['avg_rating']}/5 — EUR{h['price_per_night']}/night")
    lines.append("\nAny of these catch your eye?")
    return _make_response("\n".join(lines), ["Browse All", "Cheapest First", "Top Rated"], navigate="/user/stays/search?sort_by=rating_desc", properties=_props_for(top))

def _exec_cheapest_type(e, session_id):
    ctx = _load_context(session_id)
    ptypes = e["property_types"]
    if not ptypes:
        pt = _extract_type_from_context(ctx)
        ptypes = {pt} if pt else set()
    if not ptypes:
        return _make_response(
            "Which type? We have hotels, apartments, villas, and resorts.",
            ["Hotels", "Apartments", "Villas", "Resorts"]
        )

    ptype = next(iter(ptypes))
    hotels = _search_hotels(property_type=ptype, limit=50)
    
    if not isinstance(hotels, list) or not hotels:
        return _make_response(
            f"No {ptype}s available right now. Try a different type?",
            ["Hotels", "Apartments", "Villas", "Resorts"], navigate="/user/stays/search"
        )
    
    # Sort by price (lowest first)
    hotels_sorted = sorted(hotels, key=lambda h: h.get("price_per_night", 0))
    
    lines = [f"Here are the **cheapest {ptype}s** — sorted by price:\n"]
    for h in hotels_sorted[:5]:
        stars = "★" * h.get("stars", 3) if h.get("stars") else ""
        lines.append(f"> {stars} **{h['name']}** — {h['city']} — EUR{h['price_per_night']}/night — ⭐ {h['avg_rating']}/5")
    
    if len(hotels_sorted) > 5:
        lines.append(f"\n+ {len(hotels_sorted) - 5} more affordable options.")
    
    lines.append(f"\nHere are the best bargains. Would you like me to check availability?")
    
    return _make_response("\n".join(lines), ["Show All", "Filter by City", "Other Types"], 
                          navigate=f"/user/stays/search?property_type={ptype}&sort_by=price_asc",
                          properties=_props_for(hotels_sorted))

def _exec_toprated_type(e, session_id):
    ctx = _load_context(session_id)
    ptypes = e["property_types"]
    if not ptypes:
        pt = _extract_type_from_context(ctx)
        ptypes = {pt} if pt else set()
    if not ptypes:
        return _make_response(
            "Which type? We have hotels, apartments, villas, and resorts.",
            ["Hotels", "Apartments", "Villas", "Resorts"]
        )

    ptype = next(iter(ptypes))
    hotels = _search_hotels(property_type=ptype, limit=50)
    
    if not isinstance(hotels, list) or not hotels:
        return _make_response(
            f"No {ptype}s available right now. Try a different type?",
            ["Hotels", "Apartments", "Villas", "Resorts"], navigate="/user/stays/search"
        )
    
    # Sort by rating (highest first)
    hotels_sorted = sorted(hotels, key=lambda h: h.get("avg_rating", 0), reverse=True)
    
    lines = [f"Here are the **top rated {ptype}s** — highest guest ratings:\n"]
    for h in hotels_sorted[:5]:
        stars = "★" * h.get("stars", 3) if h.get("stars") else ""
        lines.append(f"> {stars} **{h['name']}** — {h['city']} — ⭐ {h['avg_rating']}/5 — EUR{h['price_per_night']}/night")
    
    if len(hotels_sorted) > 5:
        lines.append(f"\n+ {len(hotels_sorted) - 5} more excellent options.")
    
    lines.append(f"\nHere are the top rated stays. Would you like me to check availability?")
    _store_session_properties(session_id, hotels_sorted)
    return _make_response("\n".join(lines), ["Show All", "Filter by City", "Other Types"], 
                          navigate=f"/user/stays/search?property_type={ptype}&sort_by=rating_desc",
                          properties=_props_for(hotels_sorted))


def _exec_availability(e, session_id):
    property_selected = _find_property_in_session(session_id, e["raw"]) if session_id else None
    if not property_selected and session_id:
        cached = _get_session_properties(session_id)
        if cached and isinstance(cached, list):
            property_selected = cached[0]

    if not property_selected:
        return _make_response(
            "Which property would you like to check availability for? Say 'first property', 'second hotel', or mention the hotel name.",
            ["First property", "Second hotel", "Search Hotels"]
        )

    if not e["check_in"] or not e["check_out"]:
        return _make_response(
            f"What dates should I check for {property_selected['name']}? Please use a range like 12.08.2026 to 14.08.2026.",
            ["12.08.2026 to 14.08.2026", "Next weekend", "Search Hotels"]
        )

    url = f"/user/hotel/{property_selected['id']}?check_in={e['check_in']}&check_out={e['check_out']}"
    return _make_response(
        f"I found availability for {property_selected['name']} from {e['check_in']} to {e['check_out']}. Redirecting you to the property page.",
        ["View Property", "Browse More Stays"], navigate=url,
        properties=[property_selected]
    )


def _exec_booking(e, session_id):
    if not current_user.is_authenticated:
        return _make_response(
            "You need to sign in to access your bookings.",
            ["Sign In", "Create Account"], navigate="/auth/login"
        )
    info = _get_bookings_info()
    if isinstance(info, dict) and info.get("total", 0) > 0:
        return _make_response(
            f"You have **{info['total']} active booking{'s' if info['total'] > 1 else ''}** on your account. Need details or changes?",
            ["My Bookings", "Browse Stays"], navigate="/user/my-reservations"
        )
    return _make_response(
        "No active bookings found. Ready to plan your next trip?",
        ["Search Hotels", "Popular Destinations"], navigate="/user/stays/search"
    )

def _exec_help(e, session_id):
    return _make_response(
        "**Staya — Command Reference**\n\n"
        "> **Find stays** — \"hotels in Paris\", \"apartments in Bulgaria\"\n"
        "> **By budget** — \"cheap villas\", \"luxury resorts\"\n"
        "> **By rating** — \"5-star hotels\", \"top rated\"\n"
        "> **Bookings** — \"my bookings\", \"my reservations\"\n"
        "> **Explore** — \"trending destinations\", \"everything available\"\n\n"
        "What are you looking for?",
        ["Search Hotels", "Popular Destinations", "My Bookings", "Deals"]
    )

def _exec_thanks(e, session_id):
    return _make_response(
        "Happy to help. Let me know if you need anything else.",
        ["Search Hotels", "My Bookings", "Popular Destinations"]
    )

def _exec_count(e, session_id):
    counts = _get_property_counts()
    if not isinstance(counts, dict) or "total" not in counts:
        return _make_response("Could not retrieve property counts.", ["Browse All"])
    all_h = _search_hotels(limit=50)
    prices = [h["price_per_night"] for h in all_h] if isinstance(all_h, list) else []
    price_str = ""
    if prices:
        price_str = f" | EUR{min(prices)}–EUR{max(prices)}/night"
    return _make_response(
        f"**{counts['total']} properties** worldwide: {counts['hotels']} hotels, "
        f"{counts['apartments']} apartments, {counts['villas']} villas, "
        f"{counts['resorts']} resorts across 12 countries.{price_str}\n\nReady to browse?",
        ["Browse All", "Cheapest First", "Search by City"], navigate="/user/stays/search?sort_by=recommended"
    )

def _exec_fallback(e, session_id):
    all_h = _search_hotels(limit=50)
    counts = _get_property_counts()
    total = counts.get("total", len(all_h)) if isinstance(counts, dict) else len(all_h)
    if isinstance(all_h, list) and all_h:
        cheap_h = min(all_h, key=lambda h: h.get("price_per_night", 0))
        top_h = max(all_h, key=lambda h: h.get("avg_rating", 0))
        return _make_response(
            f"I'm not sure I understood that. Here's what's happening on StayOra:\n\n"
            f"✨ **Best rated**: {top_h['name']} in {top_h['city']} (⭐ {top_h['avg_rating']}/5, EUR{top_h['price_per_night']}/night)\n"
            f"💰 **Best value**: {cheap_h['name']} from EUR{cheap_h['price_per_night']}/night\n"
            f"🌍 **{total} properties** across 12 countries\n\n"
            f"Try: 'Hotels in Paris', 'cheap apartments', or 'my bookings'",
            ["Browse All", "Popular Destinations", "Search by City", "Help"]
        )
    return _make_response(
        "I'm Staya. Ask me about hotels, destinations, or your bookings.",
        ["Search Hotels", "Popular Destinations", "Help"]
    )

# ── CONTEXT HELPERS ──────────────────────────────────────────────

def _extract_city_from_context(ctx):
    for msg in reversed(ctx):
        e = _extract_entities(msg.lower())
        if e["cities"]:
            return e["cities"][0]
    return None

def _extract_country_from_context(ctx):
    for msg in reversed(ctx):
        e = _extract_entities(msg.lower())
        if e["countries"]:
            return e["countries"][0]
    return None

def _extract_type_from_context(ctx):
    for msg in reversed(ctx):
        e = _extract_entities(msg.lower())
        if e["property_types"]:
            return next(iter(e["property_types"]))
    return None

# ── MAIN DB RESPONSE ENGINE ──────────────────────────────────────

INTENT_MAP = {
    "greeting": _exec_greeting,
    "search_city": _exec_search_city,
    "search_country": _exec_search_country,
    "search_city_price": _exec_search_city,
    "search_country_budget": _exec_search_country,
    "search_country_luxury": _exec_search_country,
    "search_type": _exec_search_type,
    "search_type_city": _exec_search_type,
    "search_type_country": _exec_search_type,
    "search_type_price": _exec_search_type,
    "search_full": _exec_search_type,
    "budget": _exec_budget,
    "luxury": _exec_luxury,
    "trending": _exec_trending,
    "cheapest_type": _exec_cheapest_type,
    "toprated_type": _exec_toprated_type,
    "booking": _exec_booking,
    "availability": _exec_availability,
    "help": _exec_help,
    "thanks": _exec_thanks,
    "count": _exec_count,
}

def _db_response(message, session_id=None):
    _save_context(session_id, message)
    m = message.lower().strip()
    e = _extract_entities(m)

    intents = _score_intents(e)
    if intents:
        intent_name = intents[0][0]
        executor = INTENT_MAP.get(intent_name, _exec_fallback)
        result = executor(e, session_id)
        return result

    return _exec_fallback(e, session_id)

# ── LEGACY HELPERS ───────────────────────────────────────────────

def _make_response(text, quick_replies=None, navigate=None, properties=None):
    resp = {"text": text, "intent": "db", "actions": _actions(text)}
    if quick_replies:
        resp["quick_replies"] = quick_replies
    if navigate:
        resp["navigate"] = navigate
    if properties is not None:
        resp["properties"] = properties
    return resp

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


def _props_for(hotels, limit=8):
    if not isinstance(hotels, list):
        return []
    out = []
    for h in hotels[:limit]:
        out.append({
            "id": h.get("id"),
            "name": h.get("name"),
            "city": h.get("city"),
            "country": h.get("country"),
            "property_type": h.get("property_type"),
            "price_per_night": h.get("price_per_night"),
            "avg_rating": h.get("avg_rating")
        })
    return out

def detect_intent(message):
    return "openai"

def get_response_for_intent(intent, message=None):
    return {"text": "How can I help you?", "intent": "openai"}
