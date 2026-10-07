"""Quest-card generation.

The model writes the card; this module owns everything that must be reliable:
the JSON schema we demand, validation/clamping of whatever comes back, and a
deterministic template fallback so the app still works with the model offline.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from .llm import LLMUnavailable, OllamaClient

KINDS = ["look", "listen", "touch", "smell", "photo", "sit"]
HABITATS = ["neighborhood streets", "city park", "forest trail", "coast or lake shore", "meadow or farmland", "garden"]
ENERGY = ["gentle", "moderate", "energetic"]

QUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "intro": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "hint": {"type": "string"},
                    "kind": {"type": "string", "enum": KINDS},
                },
                "required": ["prompt", "hint", "kind"],
            },
        },
        "sit_spot": {"type": "string"},
        "safety_note": {"type": "string"},
    },
    "required": ["title", "intro", "items", "sit_spot", "safety_note"],
}

SYSTEM = (
    "You write one-page outdoor quest cards that get people away from screens. "
    "The card is PRINTED and used on paper, so every item must be doable with eyes, ears, hands and "
    "nose alone. Rules: (1) Prefer observation prompts (colours, textures, sounds, shapes, light) that "
    "work in any location; never promise a specific species, trail, shop or landmark because you cannot "
    "verify the place. (2) Match the season, the habitat, the time available and the energy level. "
    "(3) Items must be safe: never ask anyone to touch, taste or pick unknown plants, mushrooms, berries "
    "or animals. (4) Warm, specific, a little playful, never preachy. (5) Each hint is one short sentence."
)


@dataclass
class QuestRequest:
    place: str
    lat: float
    lon: float
    habitat: str
    minutes: int
    energy: str
    season: str
    date_iso: str
    sunset_note: str
    weather: dict | None = None


def _user_prompt(req: QuestRequest, n_items: int) -> str:
    wx = ""
    if req.weather:
        wx = (f"Weather today: {req.weather['summary']}, high {req.weather['high_c']}C, "
              f"low {req.weather['low_c']}C, rain chance {req.weather['rain_chance_pct']}%. ")
    return (
        f"Place (as typed by the user): {req.place or 'unspecified'} (latitude {req.lat:.1f}). "
        f"Season there: {req.season}. Date: {req.date_iso}. {wx}{req.sunset_note} "
        f"Habitat: {req.habitat}. Time available: {req.minutes} minutes. Energy: {req.energy}. "
        f"Write a card with exactly {n_items} items, mixing different senses (use at least four different "
        f"kinds out of: {', '.join(KINDS)}). Include at most two items with kind 'photo' (things that are "
        f"fun to photograph and verify later). Also give a 'sit_spot' prompt: a quiet 5-10 minute "
        f"sit-and-notice task. 'safety_note' is one calm sentence tailored to the weather/daylight."
    )


def n_items_for(minutes: int) -> int:
    return max(4, min(8, round(minutes / 15) + 3))


def _clean(text: Any, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def validate_quest(raw: dict[str, Any], n_items: int) -> dict[str, Any]:
    """Coerce model output into a safe, bounded card or raise ValueError."""
    items = []
    for it in raw.get("items", []) or []:
        prompt = _clean(it.get("prompt"), 160)
        if not prompt:
            continue
        kind = it.get("kind") if it.get("kind") in KINDS else "look"
        items.append({"prompt": prompt, "hint": _clean(it.get("hint"), 160), "kind": kind})
    if len(items) < 3:
        raise ValueError("model returned fewer than 3 usable items")
    items = items[:n_items]
    for i, it in enumerate(items, 1):
        it["id"] = i
        it["photo_ok"] = it["kind"] in ("photo", "look")
    title = _clean(raw.get("title"), 80)
    if not title:
        raise ValueError("missing title")
    return {
        "title": title,
        "intro": _clean(raw.get("intro"), 320),
        "items": items,
        "sit_spot": _clean(raw.get("sit_spot"), 260),
        "safety_note": _clean(raw.get("safety_note"), 200),
    }


_FALLBACK = {
    "autumn": ["Find three leaves that are different colours and compare how they feel", "Listen for the farthest sound you can hear",
               "Spot something that is changing for the season", "Find a texture that is rough and one that is smooth",
               "Notice where the light is coming from and what it makes golden", "Smell the air: damp earth, smoke, rain, leaves?"],
    "winter": ["Find something that holds frost or damp", "Listen for sounds that are quieter in the cold",
               "Spot a bare branch pattern worth drawing", "Find anything that is still green",
               "Notice your breath and the light on the horizon", "Find tracks, nests or signs of life"],
    "spring": ["Find something that is just beginning to grow", "Listen for a bird you can hear but not see",
               "Spot three different shades of green", "Find a flower and notice its smallest detail",
               "Smell the air after a mild day", "Find something that moves in the wind"],
    "summer": ["Find the deepest shade nearby", "Listen for insects, birds or water",
               "Spot something that is in full bloom or fruit", "Find a cool surface to touch",
               "Notice the longest shadow you can find", "Smell something warm: grass, dust, flowers?"],
}
_KIND_CYCLE = ["look", "listen", "look", "touch", "photo", "smell"]


def fallback_quest(req: QuestRequest, n_items: int, rng: random.Random | None = None) -> dict[str, Any]:
    """Deterministic, model-free card. Clearly labelled by the caller as a template."""
    rng = rng or random.Random(f"{req.date_iso}-{req.place}-{req.habitat}")
    pool = list(_FALLBACK[req.season])
    rng.shuffle(pool)
    items = []
    for i in range(n_items):
        text = pool[i % len(pool)]
        items.append({"id": i + 1, "prompt": text, "hint": "", "kind": _KIND_CYCLE[i % len(_KIND_CYCLE)],
                      "photo_ok": _KIND_CYCLE[i % len(_KIND_CYCLE)] in ("photo", "look")})
    return {
        "title": f"A {req.minutes}-minute {req.season} wander",
        "intro": f"A simple {req.season} card for {req.habitat}. Leave the phone in your pocket and see how many you can find.",
        "items": items,
        "sit_spot": "Find a spot to sit for five minutes. Notice three things you have never noticed here before.",
        "safety_note": "Stay on paths, tell someone where you are going, and head back before the light fades.",
    }


def generate_quest(client: OllamaClient, req: QuestRequest) -> tuple[dict[str, Any], str]:
    """Return (card, source) where source is 'model' or 'template'."""
    n = n_items_for(req.minutes)
    try:
        raw = client.chat_json(SYSTEM, _user_prompt(req, n), QUEST_SCHEMA, temperature=0.8, max_tokens=1100)
        return validate_quest(raw, n), "model"
    except (LLMUnavailable, ValueError):
        return fallback_quest(req, n), "template"
