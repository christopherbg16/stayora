import json
import os
import re
import sys
from datetime import datetime
from flask import url_for
from flask_login import current_user
from models import User, Hotel, Reservation, PropertyReservation, supabase, TrendingDestination, Promotion

# ── Gemini (primary AI) ──
from google.genai import types as genai_types
from google.genai import Client

gemini_api_key = os.environ.get("GEMINI_API_KEY")
_gemini_available = bool(gemini_api_key) and gemini_api_key not in ("", "your-gemini-api-key-here")
if _gemini_available:
    _gemini_client = Client(api_key=gemini_api_key)
else:
    _gemini_client = None
    print("[Staya Gemini] No valid GEMINI_API_KEY found. AI mode disabled.", file=sys.stderr)

GEMINI_MODEL_NAME = "gemini-2.5-flash"

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


LANGUAGES = {'en': 'English', 'bg': 'Български', 'es': 'Español', 'de': 'Deutsch'}
LANG_NAMES = LANGUAGES

def _detect_lang(text):
    import re
    cyrillic = re.search(r'[а-яА-Я]', text)
    if cyrillic:
        return 'bg'
    spanish = re.search(r'[áéíóúñÁÉÍÓÚÑ¿¡]', text)
    if spanish:
        return 'es'
    german = re.search(r'[äöüßÄÖÜ]', text)
    if german:
        return 'de'
    return 'en'

_translations_cache = {}
def _load_translations(lang):
    if lang == 'en':
        return {}
    if lang not in _translations_cache:
        import json, os
        path = os.path.join(os.path.dirname(__file__), 'translations', f'{lang}.json')
        try:
            with open(path, 'r', encoding='utf-8') as f:
                _translations_cache[lang] = json.load(f)
        except:
            _translations_cache[lang] = {}
    return _translations_cache[lang]

def _t(text, lang):
    if lang == 'en':
        return text
    translations = _load_translations(lang)
    return translations.get(text, text)

def _build_system_prompt(lang='en'):
    ctx = _get_user_context()
    lang_name = LANG_NAMES.get(lang, 'English')
    return f"""You are Staya, a friendly travel assistant for StayOra, a property booking platform.

YOUR ROLE:
- Help users find properties (hotels, apartments, villas, resorts)
- Recommend popular properties and profitable investment opportunities
- Answer questions about destinations, pricing, availability
- Help with bookings and reservations
- Guide users to pages on the platform

RULES:
- Be natural and conversational, don't repeat yourself
- You MUST respond in {lang_name} ({lang}). The user is writing in {lang_name} and you MUST reply in {lang_name}.
- When asked about properties in a city -> use search_hotels() to find them
- After presenting results, ALWAYS ask if they want to see them
- When user agrees to see properties -> use navigate_to() to take them there
- When asked about what to buy/sell -> search trending + property counts, give specific advice
- NEVER invent property data, always use search_hotels()
- You can see the user's name and role ONLY. You CANNOT access, view, or reveal any other personal information including: email, phone number, address, bank accounts, bank IBAN, bank holder name, payment details, password, or any financial data.
- If a user asks you to look up or change personal/financial information (like bank details), politely refuse and say you cannot access that information.
- Keep responses concise but informative
- When the user asks to change the language, theme, or username you MUST use the provided function (change_language, change_theme, rename_username) — do NOT just say you did it without calling the function.

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
    {
        "type": "function",
        "function": {
            "name": "change_language",
            "description": "Change the site language and return a redirect URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lang": {"type": "string", "enum": ["en", "bg", "es", "de"], "description": "Target language code"},
                },
                "required": ["lang"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "change_theme",
            "description": "Switch the UI theme between light and dark mode.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["light", "dark"], "description": "Theme mode to apply"},
                },
                "required": ["mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_username",
            "description": "Rename the authenticated user's username.",
            "parameters": {
                "type": "object",
                "properties": {
                    "new_username": {"type": "string", "description": "New username for the current account"},
                },
                "required": ["new_username"],
            },
        },
    },
]

def _change_language(target):
    supported = {'en', 'bg', 'es', 'de'}
    if target not in supported:
        return {"success": False, "supported": list(supported), "error": f"Unsupported language '{target}'"}
    try:
        redirect_url = url_for('set_language', lang=target)
        return {"success": True, "lang": target, "redirect": redirect_url}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _change_theme(mode):
    if mode not in ("light", "dark"):
        return {"success": False, "error": f"Unsupported theme '{mode}'"}
    return {"success": True, "theme": mode}

def _rename_username(new_username):
    if not current_user.is_authenticated:
        return {"success": False, "error": "You must be logged in to change your username."}
    new_username = new_username.strip()
    if not new_username or len(new_username) < 2:
        return {"success": False, "error": "Username must be at least 2 characters."}
    if len(new_username) > 30:
        return {"success": False, "error": "Username must be 30 characters or less."}
    try:
        existing = User.find_by_username(new_username)
        if existing and existing.id != current_user.id:
            return {"success": False, "error": f"Username '{new_username}' is already taken."}
        current_user.update(username=new_username)
        return {"success": True, "message": f"Your username has been changed to '{new_username}'.", "new_username": new_username}
    except Exception as e:
        return {"success": False, "error": str(e)}

TOOL_IMPL = {
    "search_hotels": _search_hotels,
    "get_trending_destinations": _get_trending,
    "get_active_promotions": _get_promotions,
    "get_user_bookings_info": _get_bookings_info,
    "get_property_type_counts": _get_property_counts,
    "change_language": lambda lang: _change_language(lang),
    "change_theme": lambda mode: _change_theme(mode),
    "rename_username": lambda new_username: _rename_username(new_username),
}


def _openai_to_gemini_tools():
    """Convert OpenAI-style TOOLS to Gemini FunctionDeclaration list."""
    type_map = {
        "string": genai_types.Type.STRING,
        "number": genai_types.Type.NUMBER,
        "integer": genai_types.Type.INTEGER,
        "boolean": genai_types.Type.BOOLEAN,
        "object": genai_types.Type.OBJECT,
        "array": genai_types.Type.ARRAY,
    }
    declarations = []
    for tool_def in TOOLS:
        func = tool_def["function"]
        params = func.get("parameters", {})
        properties = params.get("properties", {})
        required = params.get("required", [])

        gemini_props = {}
        for name, prop in properties.items():
            prop_type = prop.get("type", "string")
            gemini_props[name] = genai_types.Schema(
                type=type_map.get(prop_type, genai_types.Type.STRING),
                description=prop.get("description", ""),
            )

        declarations.append(genai_types.FunctionDeclaration(
            name=func["name"],
            description=func.get("description", ""),
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties=gemini_props,
                required=required,
            ),
        ))
    return [genai_types.Tool(function_declarations=declarations)]


def process_message(message, session_id=None, lang='en'):
    if _gemini_available:
        result = _try_gemini(message, session_id, lang)
        if result is not None:
            return result

    return _db_response(message, session_id, lang)


def _try_gemini(message, session_id=None, lang='en'):
    detected = _detect_lang(message)
    if detected != 'en':
        lang = detected
    conv_id = session_id or "default"
    system_prompt = _build_system_prompt(lang)
    gemini_tools = _openai_to_gemini_tools()

    if conv_id not in conversations:
        conversations[conv_id] = []

    history = conversations[conv_id]

    contents = []
    for msg in history:
        role = msg["role"]
        if role == "system":
            continue
        if role == "assistant":
            parts = []
            if msg.get("content"):
                parts.append({"text": msg["content"]})
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    parts.append({
                        "function_call": {
                            "name": tc["function"]["name"],
                            "args": json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"],
                        }
                    })
            contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            try:
                resp_data = json.loads(msg["content"]) if isinstance(msg["content"], str) else msg["content"]
            except Exception:
                resp_data = {"result": msg["content"]}
            contents.append({
                "role": "function",
                "parts": [{
                    "function_response": {
                        "name": msg.get("name", ""),
                        "response": resp_data,
                    }
                }],
            })
        else:
            content = msg.get("content", "")
            contents.append({"role": role, "parts": [{"text": content}]})

    contents.append({"role": "user", "parts": [{"text": message}]})

    navigate_target = None
    tool_results = []

    for round_num in range(5):
        try:
            response = _gemini_client.models.generate_content(
                model=GEMINI_MODEL_NAME,
                contents=contents,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    tools=gemini_tools,
                    temperature=0.7,
                    max_output_tokens=600,
                ),
            )
        except Exception as e:
            print(f"[Staya Gemini] {type(e).__name__}: {e}", file=sys.stderr)
            return None

        candidate = response.candidates[0]

        has_function_call = False
        for part in candidate.content.parts:
            fc = part.function_call
            if fc is None:
                continue
            has_function_call = True
            fn = fc.name
            args = {k: v for k, v in fc.args.items()}

            if fn == "navigate_to":
                navigate_target = args.get("url", "/")
                result_data = {"success": True, "url": navigate_target}
            elif fn in TOOL_IMPL:
                try:
                    result_data = TOOL_IMPL[fn](**args)
                except Exception as ex:
                    result_data = {"success": False, "error": str(ex)}
            else:
                result_data = {"success": False, "error": "unknown function"}

            tool_results.append({"name": fn, "args": args, "result": result_data})
            contents.append(candidate.content)
            contents.append({
                "role": "function",
                "parts": [{
                    "function_response": {
                        "name": fn,
                        "response": result_data,
                    }
                }],
            })

        if has_function_call:
            continue

        text = ""
        for part in candidate.content.parts:
            if part.text:
                text += part.text

        conversations[conv_id].append({"role": "user", "content": message})
        conversations[conv_id].append({"role": "assistant", "content": text})
        _trim(conv_id)

        out = {"text": text, "intent": "gemini", "quick_replies": _quick_replies(text), "actions": _actions(text)}
        if navigate_target:
            out["navigate"] = navigate_target

        for tool_call in tool_results:
            name = tool_call.get("name")
            result = tool_call.get("result") or {}
            if name == "change_language" and result.get("success"):
                out["navigate"] = result.get("redirect")
                out["language"] = result.get("lang")
            if name == "change_theme" and result.get("success"):
                out["theme"] = result.get("theme")
            if name == "rename_username":
                out["rename_username"] = result

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
    # Bulgarian
    "софия": "Sofia", "банско": "Bansko", "пловдив": "Plovdiv", "варна": "Varna",
    "бургас": "Burgas", "самоков": "Samokov",
    # Spanish
    "londres": "London", "parís": "Paris", "nueva york": "New York", "venecia": "Venice",
    "barcelona": "Barcelona",
    # German
    "paris": "Paris", "venedig": "Venice", "london": "London", "barcelona": "Barcelona",
}

COUNTRIES = {
    "italy": "Italy", "france": "France", "japan": "Japan", "greece": "Greece",
    "spain": "Spain", "indonesia": "Indonesia", "bulgaria": "Bulgaria",
    "england": "United Kingdom", "uk": "United Kingdom", "britain": "United Kingdom",
    "uae": "United Arab Emirates", "usa": "USA", "america": "USA", "united states": "USA",
    # Bulgarian
    "италия": "Italy", "франция": "France", "япония": "Japan", "гърция": "Greece",
    "испания": "Spain", "индонезия": "Indonesia", "българия": "Bulgaria",
    "англия": "United Kingdom", "съединени щати": "USA",
    # Spanish
    "italia": "Italy", "francia": "France", "españa": "Spain", "grecia": "Greece",
    "inglaterra": "United Kingdom", "reino unido": "United Kingdom",
    "estados unidos": "USA",
    # German
    "italien": "Italy", "frankreich": "France", "griechenland": "Greece",
    "spanien": "Spain", "england": "United Kingdom", "vereinigtes königreich": "United Kingdom",
}

TYPES = {"apartment": "apartment", "apartments": "apartment",
         "hotel": "hotel", "hotels": "hotel",
         "villa": "villa", "villas": "villa",
         "resort": "resort", "resorts": "resort",
         # Bulgarian
         "апартамент": "apartment", "апартаменти": "apartment",
         "хотел": "hotel", "хотели": "hotel",
         "вила": "villa", "вили": "villa",
         "курорт": "resort", "курорти": "resort",
         # Spanish
         "apartamento": "apartment", "apartamentos": "apartment",
         "hotel": "hotel", "hoteles": "hotel",
         "villa": "villa", "villas": "villa",
         # German
         "wohnung": "apartment", "wohnungen": "apartment",
         "hotel": "hotel", "hotels": "hotel",
         "villa": "villa", "villen": "villa",
         "resort": "resort", "resorts": "resort",
}

GREET_WORDS = ("hi", "hello", "hey", "zdravei", "good morning", "good evening", "morning", "evening",
               # Bulgarian
               "здравей", "здравейте", "здрасти", "добро утро", "добър ден", "добър вечер",
               # Spanish
               "hola", "buenos días", "buenas tardes", "buenas noches", "buen día",
               # German
               "hallo", "guten morgen", "guten tag", "guten abend", "servus", "moin")
BOOKING_WORDS = ("booking", "reservation", "my trip", "my bookings", "my reservation", "my reservations")
TRENDING_WORDS = ("trending", "popular", "destination", "best place", "recommend", "where to go", "top rated", "best")
AVAILABILITY_WORDS = ("available", "availability", "book", "check availability", "availability for", "available from", "available until")
BUDGET_WORDS = ("cheap", "budget", "affordable", "cheapest", "low price", "under", "economy", "inexpensive", "low cost")
LUXURY_WORDS = ("luxury", "luxurious", "premium", "high end", "fancy", "exclusive", "top", "expensive", "highest price", "most expensive")
HELP_WORDS = ("help", "what can you", "what do you", "how", "?", "capabilities")
THANKS_WORDS = ("thanks", "thank you", "thanks a lot", "appreciate", "thx")
COUNT_WORDS = ("how many", "count", "total", "available", "all properties", "everything")
THEME_WORDS = ("dark mode", "light mode", "switch to dark", "switch to light", "change theme", "toggle theme", "dark theme", "light theme", "enable dark", "enable light", "turn on dark", "turn on light", "go dark", "go light",
               # Bulgarian
               "светла тема", "тъмна тема", "светъл режим", "тъмен режим",
               "смени на светла", "смени на тъмна", "смениш на светла", "смениш на тъмна",
               "превключи на светла", "превключи на тъмна", "превключиш на светла", "превключиш на тъмна",
               "промени темата", "промениш темата",
               "включи светла", "включи тъмна", "включиш светла", "включиш тъмна")
LANG_WORDS = ("change language", "switch language", "change to english", "change to bulgarian", "change to spanish", "change to german", "switch to english", "switch to bulgarian", "switch to spanish", "switch to german",
              # Bulgarian
              "смени езика", "смениш езика", "промени езика", "промениш езика", "смени на български", "смениш на български", "смени на английски", "смениш на английски", "смени на испански", "смениш на испански", "смени на немски", "смениш на немски", "на български език", "на английски език", "говори на български", "говори на английски", "превключи езика")
RENAME_WORDS = ("rename me", "rename my account", "change my name", "change username", "change the username", "new username", "rename my username", "rename username", "change my username", "i want a new name", "change account name", "can you change", "i want to change",
                # Bulgarian
                "промени името", "смени името", "смени моето име", "ново потребителско име", "искам ново име", "преименувай ме", "смени потребителското име")
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
        "check_in": None, "check_out": None, "wants_availability": False,
        "wants_theme": False, "wants_language": False, "wants_rename": False,
        "_theme_mode": None, "_language_target": None, "_rename_target": None, "raw": m,
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

    for w in THEME_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", m.lower()):
            entities["wants_theme"] = True
            if re.search(r"\b(?:dark|тъмн)", m.lower()):
                entities["_theme_mode"] = "dark"
            elif re.search(r"\b(?:light|светл)", m.lower()):
                entities["_theme_mode"] = "light"
            break

    for w in LANG_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", m.lower()):
            entities["wants_language"] = True
            lang_names = {'english': 'en', 'bulgarian': 'bg', 'bălgarski': 'bg', 'български': 'bg', 'английски': 'en', 'spanish': 'es', 'español': 'es', 'espanol': 'es', 'испански': 'es', 'german': 'de', 'deutsch': 'de', 'немски': 'de'}
            for name, code in lang_names.items():
                if re.search(r"\b" + re.escape(name) + r"\b", m.lower()):
                    entities["_language_target"] = code
                    break
            if not entities["_language_target"]:
                for code in LANGUAGES:
                    if re.search(r"(?<!\w)" + re.escape(code) + r"(?!\w)", m.lower()):
                        entities["_language_target"] = code
                        break
            break

    for w in RENAME_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", m.lower()):
            entities["wants_rename"] = True
            parts = m.lower().split()
            for i, p in enumerate(parts):
                if p in ("to", "as", "на") and i + 1 < len(parts):
                    entities["_rename_target"] = parts[i + 1].strip(",.!?")
                    break
            else:
                for i, p in enumerate(parts):
                    if p in ("rename", "name", "username", "call", "име", "името", "преименувай") and i + 1 < len(parts):
                        candidate = parts[i + 1].strip(",.!?")
                        if candidate not in ("to", "as", "my", "me", "the", "new", "на", "моето"):
                            entities["_rename_target"] = candidate
                            break
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

    if e["wants_theme"]:
        intents.append(("theme", 65, e))

    if e["wants_language"]:
        intents.append(("language", 65, e))

    if e["wants_rename"]:
        intents.append(("rename", 65, e))

    if e["has_greeting"] and not any(e[k] for k in ("cities", "countries", "property_types") if e[k]) and not e["wants_booking"] and not e["wants_help"] and not e["wants_trending"] and not e["wants_count"] and not e["wants_theme"] and not e["wants_language"] and not e["wants_rename"]:
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
    lang = e.get("_lang", "en")
    if current_user.is_authenticated:
        return _make_response(
            f"{_t('Welcome back', lang)}, {current_user.username}. {_t('Systems online. How can I assist with your travels?', lang)}",
            [_t("Search Hotels", lang), _t("My Bookings", lang), _t("Popular Destinations", lang), _t("Deals", lang)]
        )
    return _make_response(
        _t("Good day. I'm Staya, your travel intelligence system. Looking for a place to stay?", lang),
        [_t("Search Hotels", lang), _t("Popular Destinations", lang), _t("Sign In", lang), _t("Deals", lang)]
    )

def _exec_search_city(e, session_id):
    lang = e.get("_lang", "en")
    ctx = _load_context(session_id)
    city = e["cities"][0]
    if not city:
        city = _extract_city_from_context(ctx)
    if not city:
        return _make_response(
            _t("Which city are you interested in?", lang),
            [_t("Popular Destinations", lang), _t("Browse All Properties", lang)]
        )

    hotels = _search_hotels(destination=city)
    if not isinstance(hotels, list) or not hotels:
        return _make_response(
            _t("Scanned {city} — no properties found. Try a different city?", lang).format(city=city),
            [_t("Browse All Properties", lang), _t("Popular Destinations", lang)]
        )
    _store_session_properties(session_id, hotels)

    lines = [_t("Here are **{count} properties** found in {city}.", lang).format(count=len(hotels), city=city)]
    for h in hotels[:4]:
        stars = "★" * h.get("stars", 3)
        lines.append(f"> {stars} **{h['name']}** — EUR{h['price_per_night']}/night — ⭐ {h['avg_rating']}/5")
    if len(hotels) > 4:
        lines.append("\n" + _t("{count} more available.", lang).format(count=len(hotels) - 4))
    lines.append("\n" + _t("Would you like me to check availability for these?", lang))

    qr = [_t("Check dates", lang), _t("Show all", lang), _t("Popular Destinations", lang)]
    nav = f"/user/stays/search?destination={city}"
    if e.get("price_intent") == "budget":
        nav += "&sort_by=price_asc"
    elif e.get("price_intent") == "luxury":
        nav += "&sort_by=price_desc"
    return _make_response("\n".join(lines), qr, navigate=nav, properties=_props_for(hotels))

def _exec_search_country(e, session_id):
    lang = e.get("_lang", "en")
    ctx = _load_context(session_id)
    country = e["countries"][0] if e["countries"] else None
    if not country:
        country = _extract_country_from_context(ctx)
    if not country:
        return _make_response(
            _t("Which country are you looking at?", lang),
            [_t("Popular Destinations", lang), _t("Browse All Properties", lang)]
        )

    hotels = _search_hotels(destination=country)
    if not isinstance(hotels, list) or not hotels:
        return _make_response(
            _t("No properties found in {country} yet. Try a nearby destination?", lang).format(country=country),
            [_t("Browse All Properties", lang), _t("Popular Destinations", lang)]
        )
    _store_session_properties(session_id, hotels)

    cities_list = list(dict.fromkeys(h["city"] for h in hotels if h.get("city")))
    cities_line = f" {_t('Spread across', lang)} **{', '.join(cities_list[:5])}**." if cities_list else ""

    price_range = f"EUR{min(h['price_per_night'] for h in hotels)}–EUR{max(h['price_per_night'] for h in hotels)}/night"
    avg_rating = round(sum(h["avg_rating"] for h in hotels) / len(hotels), 1)

    lines = [_t("Here are **{count} properties** in {country}.", lang).format(count=len(hotels), country=country) + cities_line]
    lines.append(_t("Price range: {range} | Avg rating: {rating}/5", lang).format(range=price_range, rating=avg_rating) + "\n")
    for h in hotels[:3]:
        lines.append(f"> **{h['name']}** — {h['city']} — EUR{h['price_per_night']}/night — ⭐ {h['avg_rating']}/5")
    if len(hotels) > 3:
        lines.append("\n" + _t("+ {count} more properties.", lang).format(count=len(hotels) - 3))
    lines.append("\n" + _t("Would you like me to check availability for these?", lang))

    nav = f"/user/stays/search?destination={country}"
    if e.get("price_intent") == "budget":
        nav += "&sort_by=price_asc"
    elif e.get("price_intent") == "luxury":
        nav += "&sort_by=price_desc"
    return _make_response("\n".join(lines), [_t("Show all", lang), _t("Filter by type", lang), _t("Popular Destinations", lang)],
                          navigate=nav, properties=_props_for(hotels))

def _exec_search_type(e, session_id):
    lang = e.get("_lang", "en")
    ctx = _load_context(session_id)
    ptypes = e["property_types"]
    if not ptypes:
        pt = _extract_type_from_context(ctx)
        ptypes = {pt} if pt else set()
    if not ptypes:
        counts = _get_property_counts()
        if isinstance(counts, dict):
            return _make_response(
                _t("What type? We have {h} hotels, {a} apartments, {v} villas, {r} resorts.", lang).format(
                    h=counts.get('hotels', 0), a=counts.get('apartments', 0),
                    v=counts.get('villas', 0), r=counts.get('resorts', 0)),
                [_t("Hotels", lang), _t("Apartments", lang), _t("Villas", lang), _t("Resorts", lang)]
            )
        return _make_response(
            _t("Which type? Hotels, apartments, villas, or resorts?", lang),
            [_t("Hotels", lang), _t("Apartments", lang), _t("Villas", lang), _t("Resorts", lang)]
        )

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
            filters.append(_t("under EUR{max}", lang).format(max=e['price_max']))
        if e.get("price_min"):
            filters.append(_t("over EUR{min}", lang).format(min=e['price_min']))
        if e.get("stars"):
            filters.append(_t("{star}-star", lang).format(star=e['stars'][0]))
        filter_str = f" ({', '.join(filters)})" if filters else ""

        all_in_loc = _search_hotels(destination=dest) if dest else []
        if isinstance(all_in_loc, list) and all_in_loc:
            other_types = list(dict.fromkeys(h["property_type"] for h in all_in_loc if h.get("property_type") != ptype))
            msg = _t("No {ptype}s in {dest}{filters}.", lang).format(ptype=ptype, dest=dest, filters=filter_str) + " "
            if other_types:
                other_plural = [t + "s" for t in other_types[:3]]
                msg += _t("However, there are {types} available in {dest}. Want to try those?", lang).format(types=', '.join(other_plural), dest=dest)
            else:
                msg += _t("The properties in {dest} start from EUR{min_price}/night. Try a higher budget?", lang).format(dest=dest, min_price=min(h['price_per_night'] for h in all_in_loc))
            nav = f"/user/stays/search?destination={dest}" if dest else "/user/stays/search"
            return _make_response(msg, [_t("Adjust Filters", lang), _t("Browse All", lang)], navigate=nav, properties=_props_for(all_in_loc))

        loc_str = f" {_t('in', lang)} {dest}" if dest else ""
        return _make_response(
            _t("No {ptype}s found{location}{filters}. Try a different location or property type?", lang).format(ptype=ptype, location=loc_str, filters=filter_str),
            [_t("Browse All Properties", lang), _t("Popular Destinations", lang)], navigate="/user/stays/search",
            properties=_props_for([])
        )

    type_label = ptype if len(hotels) == 1 else f"{ptype}s"
    if dest:
        lines = [_t("Here are **{count} {type}** in {dest}:", lang).format(count=len(hotels), type=type_label, dest=dest) + "\n"]
    else:
        lines = [_t("Here are **{count} {type}**:", lang).format(count=len(hotels), type=type_label) + "\n"]
    for h in hotels[:4]:
        star_str = "★" * h.get("stars", 3) if h.get("stars") else ""
        lines.append(f"> {star_str} **{h['name']}** — {h['city']} — EUR{h['price_per_night']}/night — ⭐ {h['avg_rating']}/5")
    if len(hotels) > 4:
        lines.append("\n" + _t("+ {count} more.", lang).format(count=len(hotels) - 4))
    lines.append("\n" + _t("Would you like me to check availability?", lang))
    _store_session_properties(session_id, hotels)

    nav = f"/user/stays/search?property_type={ptype}"
    if dest:
        nav += f"&destination={dest}"

    if e.get("price_intent") == "budget":
        nav += "&sort_by=price_asc"
    elif e.get("price_intent") == "luxury":
        nav += "&sort_by=price_desc"

    if e.get("price_min"):
        nav += f"&min_price={e['price_min']}"
    if e.get("price_max"):
        nav += f"&max_price={e['price_max']}"

    qr = [_t("Check dates", lang), _t("Show all results", lang)]
    if not dest:
        qr.append(_t("Search by City", lang))
    return _make_response("\n".join(lines), qr, navigate=nav, properties=_props_for(hotels))

def _exec_budget(e, session_id):
    lang = e.get("_lang", "en")
    max_p = e.get("price_max") or 100
    hotels = _search_hotels(max_price=max_p)
    if not isinstance(hotels, list) or not hotels:
        return _make_response(
            _t("Nothing under EUR{max}/night right now. Try a higher budget?", lang).format(max=max_p),
            [_t("Browse All Properties", lang), _t("Popular Destinations", lang)]
        )
    _store_session_properties(session_id, hotels)
    lines = [_t("**Budget picks — under EUR{max}/night:**", lang).format(max=max_p) + "\n"]
    for h in hotels[:5]:
        lines.append(f"> **{h['name']}** — {h['city']}, {h['country']} — EUR{h['price_per_night']}/night")
    lines.append("\n" + _t("Great value options. Ready to explore more?", lang))
    return _make_response("\n".join(lines), [_t("Show All Budget", lang), _t("Search Hotels", lang)], navigate=f"/user/stays/search?max_price={max_p}&sort_by=price_asc", properties=_props_for(hotels))

def _exec_luxury(e, session_id):
    lang = e.get("_lang", "en")
    min_p = e.get("price_min") or 200
    hotels = _search_hotels(min_price=min_p)
    if not isinstance(hotels, list) or not hotels:
        return _make_response(
            _t("Nothing over EUR{min}/night currently. Try a different range?", lang).format(min=min_p),
            [_t("Browse All Properties", lang), _t("Popular Destinations", lang)]
        )
    _store_session_properties(session_id, hotels)
    lines = [_t("**Premium selection — EUR{min}+/night:**", lang).format(min=min_p) + "\n"]
    for h in hotels[:5]:
        star_str = "★" * h.get("stars", 3)
        lines.append(f"> {star_str} **{h['name']}** — {h['city']} — EUR{h['price_per_night']}/night — ⭐ {h['avg_rating']}/5")
    lines.append("\n" + _t("Experience the finest. Ready to book?", lang))
    return _make_response("\n".join(lines), [_t("Show All Luxury", lang), _t("Search Hotels", lang)], navigate=f"/user/stays/search?min_price={min_p}&sort_by=price_desc", properties=_props_for(hotels))

def _exec_trending(e, session_id):
    lang = e.get("_lang", "en")
    all_h = _search_hotels()
    if not isinstance(all_h, list) or not all_h:
        return _make_response(_t("No properties available to recommend right now.", lang), [_t("Browse Later", lang)])
    top = sorted(all_h, key=lambda h: h.get("avg_rating", 0), reverse=True)[:6]
    _store_session_properties(session_id, top)
    lines = [_t("**Trending destinations — top rated right now:**", lang) + "\n"]
    for h in top:
        lines.append(f"> ⭐ **{h['name']}** — {h['city']}, {h['country']} — {h['avg_rating']}/5 — EUR{h['price_per_night']}/night")
    lines.append("\n" + _t("Any of these catch your eye?", lang))
    return _make_response("\n".join(lines), [_t("Browse All", lang), _t("Cheapest First", lang), _t("Top Rated", lang)], navigate="/user/stays/search?sort_by=rating_desc", properties=_props_for(top))

def _exec_cheapest_type(e, session_id):
    lang = e.get("_lang", "en")
    ctx = _load_context(session_id)
    ptypes = e["property_types"]
    if not ptypes:
        pt = _extract_type_from_context(ctx)
        ptypes = {pt} if pt else set()
    if not ptypes:
        return _make_response(
            _t("Which type? We have hotels, apartments, villas, and resorts.", lang),
            [_t("Hotels", lang), _t("Apartments", lang), _t("Villas", lang), _t("Resorts", lang)]
        )

    ptype = next(iter(ptypes))
    hotels = _search_hotels(property_type=ptype, limit=50)
    
    if not isinstance(hotels, list) or not hotels:
        return _make_response(
            _t("No {ptype}s available right now. Try a different type?", lang).format(ptype=ptype),
            [_t("Hotels", lang), _t("Apartments", lang), _t("Villas", lang), _t("Resorts", lang)], navigate="/user/stays/search"
        )
    
    hotels_sorted = sorted(hotels, key=lambda h: h.get("price_per_night", 0))
    
    lines = [_t("Here are the **cheapest {ptype}s** — sorted by price:", lang).format(ptype=ptype) + "\n"]
    for h in hotels_sorted[:5]:
        stars = "★" * h.get("stars", 3) if h.get("stars") else ""
        lines.append(f"> {stars} **{h['name']}** — {h['city']} — EUR{h['price_per_night']}/night — ⭐ {h['avg_rating']}/5")
    
    if len(hotels_sorted) > 5:
        lines.append("\n" + _t("+ {count} more affordable options.", lang).format(count=len(hotels_sorted) - 5))
    
    lines.append("\n" + _t("Here are the best bargains. Would you like me to check availability?", lang))
    
    return _make_response("\n".join(lines), [_t("Show All", lang), _t("Filter by City", lang), _t("Other Types", lang)], 
                          navigate=f"/user/stays/search?property_type={ptype}&sort_by=price_asc",
                          properties=_props_for(hotels_sorted))

def _exec_toprated_type(e, session_id):
    lang = e.get("_lang", "en")
    ctx = _load_context(session_id)
    ptypes = e["property_types"]
    if not ptypes:
        pt = _extract_type_from_context(ctx)
        ptypes = {pt} if pt else set()
    if not ptypes:
        return _make_response(
            _t("Which type? We have hotels, apartments, villas, and resorts.", lang),
            [_t("Hotels", lang), _t("Apartments", lang), _t("Villas", lang), _t("Resorts", lang)]
        )

    ptype = next(iter(ptypes))
    hotels = _search_hotels(property_type=ptype, limit=50)
    
    if not isinstance(hotels, list) or not hotels:
        return _make_response(
            _t("No {ptype}s available right now. Try a different type?", lang).format(ptype=ptype),
            [_t("Hotels", lang), _t("Apartments", lang), _t("Villas", lang), _t("Resorts", lang)], navigate="/user/stays/search"
        )
    
    hotels_sorted = sorted(hotels, key=lambda h: h.get("avg_rating", 0), reverse=True)
    
    lines = [_t("Here are the **top rated {ptype}s** — highest guest ratings:", lang).format(ptype=ptype) + "\n"]
    for h in hotels_sorted[:5]:
        stars = "★" * h.get("stars", 3) if h.get("stars") else ""
        lines.append(f"> {stars} **{h['name']}** — {h['city']} — ⭐ {h['avg_rating']}/5 — EUR{h['price_per_night']}/night")
    
    if len(hotels_sorted) > 5:
        lines.append("\n" + _t("+ {count} more excellent options.", lang).format(count=len(hotels_sorted) - 5))
    
    lines.append("\n" + _t("Here are the top rated stays. Would you like me to check availability?", lang))
    _store_session_properties(session_id, hotels_sorted)
    return _make_response("\n".join(lines), [_t("Show All", lang), _t("Filter by City", lang), _t("Other Types", lang)], 
                          navigate=f"/user/stays/search?property_type={ptype}&sort_by=rating_desc",
                          properties=_props_for(hotels_sorted))


def _exec_availability(e, session_id):
    lang = e.get("_lang", "en")
    property_selected = _find_property_in_session(session_id, e["raw"]) if session_id else None
    if not property_selected and session_id:
        cached = _get_session_properties(session_id)
        if cached and isinstance(cached, list):
            property_selected = cached[0]

    if not property_selected:
        return _make_response(
            _t("Which property would you like to check availability for? Say 'first property', 'second hotel', or mention the hotel name.", lang),
            [_t("First property", lang), _t("Second hotel", lang), _t("Search Hotels", lang)]
        )

    if not e["check_in"] or not e["check_out"]:
        return _make_response(
            _t("What dates should I check for {name}? Please use a range like 12.08.2026 to 14.08.2026.", lang).format(name=property_selected['name']),
            [_t("12.08.2026 to 14.08.2026", lang), _t("Next weekend", lang), _t("Search Hotels", lang)]
        )

    url = f"/user/hotel/{property_selected['id']}?check_in={e['check_in']}&check_out={e['check_out']}"
    return _make_response(
        _t("I found availability for {name} from {check_in} to {check_out}. Redirecting you to the property page.", lang).format(name=property_selected['name'], check_in=e['check_in'], check_out=e['check_out']),
        [_t("View Property", lang), _t("Browse More Stays", lang)], navigate=url,
        properties=[property_selected]
    )


def _exec_booking(e, session_id):
    lang = e.get("_lang", "en")
    if not current_user.is_authenticated:
        return _make_response(
            _t("You need to sign in to access your bookings.", lang),
            [_t("Sign In", lang), _t("Create Account", lang)], navigate="/auth/login"
        )
    info = _get_bookings_info()
    if isinstance(info, dict) and info.get("total", 0) > 0:
        return _make_response(
            _t("You have **{count} active booking(s)** on your account. Need details or changes?", lang).format(count=info['total']),
            [_t("My Bookings", lang), _t("Browse Stays", lang)], navigate="/user/my-reservations"
        )
    return _make_response(
        _t("No active bookings found. Ready to plan your next trip?", lang),
        [_t("Search Hotels", lang), _t("Popular Destinations", lang)], navigate="/user/stays/search"
    )

def _exec_help(e, session_id):
    lang = e.get("_lang", "en")
    return _make_response(
        _t("How can I help you? Try asking about hotels, apartments, or destinations.", lang),
        [_t("Search Hotels", lang), _t("Popular Destinations", lang), _t("My Bookings", lang), _t("Deals", lang)]
    )

def _exec_thanks(e, session_id):
    lang = e.get("_lang", "en")
    return _make_response(
        _t("Happy to help. Let me know if you need anything else.", lang),
        [_t("Search Hotels", lang), _t("My Bookings", lang), _t("Popular Destinations", lang)]
    )

def _exec_count(e, session_id):
    lang = e.get("_lang", "en")
    counts = _get_property_counts()
    if not isinstance(counts, dict) or "total" not in counts:
        return _make_response(_t("Could not retrieve property counts.", lang), [_t("Browse All", lang)])
    all_h = _search_hotels(limit=50)
    prices = [h["price_per_night"] for h in all_h] if isinstance(all_h, list) else []
    price_str = ""
    if prices:
        price_str = f" | EUR{min(prices)}–EUR{max(prices)}/night"
    return _make_response(
        _t("**{total} properties** worldwide: {h} hotels, {a} apartments, {v} villas, {r} resorts across 12 countries.{price}", lang).format(
            total=counts['total'], h=counts['hotels'], a=counts['apartments'],
            v=counts['villas'], r=counts['resorts'], price=price_str) + "\n\n" + _t("Ready to browse?", lang),
        [_t("Browse All", lang), _t("Cheapest First", lang), _t("Search by City", lang)], navigate="/user/stays/search?sort_by=recommended"
    )

def _exec_fallback(e, session_id):
    lang = e.get("_lang", "en")
    all_h = _search_hotels(limit=50)
    counts = _get_property_counts()
    total = counts.get("total", len(all_h)) if isinstance(counts, dict) else len(all_h)
    if isinstance(all_h, list) and all_h:
        cheap_h = min(all_h, key=lambda h: h.get("price_per_night", 0))
        top_h = max(all_h, key=lambda h: h.get("avg_rating", 0))
        return _make_response(
            _t("I'm not sure I understood that. Here's what's happening on StayOra:", lang) +
            f"\n\n✨ **{_t('Best rated', lang)}**: {top_h['name']} in {top_h['city']} (⭐ {top_h['avg_rating']}/5, EUR{top_h['price_per_night']}/night)\n"
            f"💰 **{_t('Best value', lang)}**: {cheap_h['name']} from EUR{cheap_h['price_per_night']}/night\n"
            f"🌍 **{total} {_t('properties', lang)}** {_t('across 12 countries', lang)}\n\n"
            + _t("Try: 'Hotels in Paris', 'cheap apartments', or 'my bookings'", lang),
            [_t("Browse All", lang), _t("Popular Destinations", lang), _t("Search by City", lang), _t("Help", lang)]
        )
    return _make_response(
        _t("I'm Staya. Ask me about hotels, destinations, or your bookings.", lang),
        [_t("Search Hotels", lang), _t("Popular Destinations", lang), _t("Help", lang)]
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

def _exec_theme(e, session_id):
    lang = e.get("_lang", "en")
    mode = e.get("_theme_mode") or "dark"
    result = _change_theme(mode)
    if result.get("success"):
        mode_label = _t(mode, lang) if lang != 'en' else mode
        return {"text": _t("Switching to {mode} mode.", lang).format(mode=mode_label), "intent": "db", "theme": mode, "actions": _actions("")}
    return {"text": _t("Could not change theme.", lang), "intent": "db"}

def _exec_language(e, session_id):
    lang = e.get("_lang", "en")
    target = e.get("_language_target") or "en"
    result = _change_language(target)
    if result.get("success"):
        name = LANGUAGES.get(target, target)
        return {"text": _t("Switching language to {name}.", lang).format(name=name), "intent": "db", "language": target, "actions": _actions("")}
    supported = ", ".join(result.get("supported", []))
    return {"text": _t("Unsupported language. Choose from: {list}", lang).format(list=supported), "intent": "db"}

def _exec_rename(e, session_id):
    lang = e.get("_lang", "en")
    new_name = e.get("_rename_target") or ""
    if not new_name:
        return {"text": _t("What username would you like? Say something like 'rename me to John'.", lang), "intent": "db"}
    result = _rename_username(new_name)
    if result.get("success"):
        return {"text": result.get("message", "Username updated."), "intent": "db", "rename_username": result}
    return {"text": result.get("error", "Could not rename."), "intent": "db", "rename_username": result}

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
    "theme": _exec_theme,
    "language": _exec_language,
    "rename": _exec_rename,
}

def _db_response(message, session_id=None, lang='en'):
    _save_context(session_id, message)
    m = message.lower().strip()
    e = _extract_entities(m)
    detected = _detect_lang(message)
    e["_lang"] = detected if detected != 'en' else lang

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
    return "gemini"

def get_response_for_intent(intent, message=None):
    return {"text": "How can I help you?", "intent": "openai"}
