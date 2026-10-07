"""Vision check of a photo against a quest item, plus the closing field-journal entry.

Honesty is a design constraint: the model is told to describe what it sees and to say when it
cannot tell. Identification is never offered as a basis for eating or touching anything.
"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageOps

from .llm import LLMUnavailable, OllamaClient

CHECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "what_i_see": {"type": "string"},
        "matches": {"type": "string", "enum": ["yes", "partly", "no", "cannot_tell"]},
        "note": {"type": "string"},
    },
    "required": ["what_i_see", "matches", "note"],
}

CHECK_SYSTEM = (
    "You check a photo a person took outdoors against the task on their paper quest card. "
    "Describe plainly what is visible. Answer 'yes' only if the task is clearly satisfied, 'partly' if "
    "close, 'no' if clearly not, and 'cannot_tell' when the photo is too dark, blurry or ambiguous. "
    "Be encouraging but never invent details you cannot see. If a plant, fungus or animal appears, "
    "you may name what it most likely is with hedged language, but never say anything is safe to eat, "
    "touch or handle. 'note' is one friendly sentence."
)

JOURNAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"entry": {"type": "string"}},
    "required": ["entry"],
}

JOURNAL_SYSTEM = (
    "You write a short field-journal entry (3 to 5 sentences, first person, past tense, warm and "
    "concrete) from a person's outdoor outing. Use ONLY the facts given: the place, the quest, the "
    "things they found and their own notes. Do not invent sightings, weather or feelings that are not "
    "implied. End with one small thing worth noticing next time."
)


def prepare_photo(data: bytes, max_side: int = 768) -> bytes:
    """Auto-rotate, strip metadata (incl. GPS) and downscale to a JPEG before storing or sending."""
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((max_side, max_side))
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=85)  # re-encoding drops EXIF, so GPS never persists
        return out.getvalue()


def check_photo(client: OllamaClient, prompt: str, hint: str, photo_jpeg: bytes) -> dict[str, Any]:
    user = f"Quest task: {prompt}\nHint on the card: {hint or 'none'}\nDoes the attached photo satisfy the task?"
    try:
        out = client.chat_json(CHECK_SYSTEM, user, CHECK_SCHEMA, images=[photo_jpeg], temperature=0.0, max_tokens=300)
    except LLMUnavailable:
        return {"what_i_see": "", "matches": "cannot_tell", "note": "The local model was not reachable, so this one is on the honour system.", "model_ok": False}
    out["matches"] = out.get("matches") if out.get("matches") in ("yes", "partly", "no", "cannot_tell") else "cannot_tell"
    out["what_i_see"] = " ".join(str(out.get("what_i_see", "")).split())[:300]
    out["note"] = " ".join(str(out.get("note", "")).split())[:240]
    out["model_ok"] = True
    return out


def write_journal(client: OllamaClient, place: str, title: str, finds: list[dict[str, Any]], notes: str) -> tuple[str, str]:
    """Return (entry, source). Falls back to a plain factual summary if the model is unavailable."""
    lines = [f"- {f['prompt']} -> {'found' if f['found'] else 'not found'}"
             + (f" (photo check: {f['matches']}; saw: {f['what_i_see']})" if f.get("what_i_see") else "")
             + (f" Their note: {f['note']}" if f.get("note") else "")
             for f in finds]
    user = f"Place: {place or 'somewhere outside'}\nQuest: {title}\nItems:\n" + "\n".join(lines) + f"\nTheir own notes: {notes or 'none'}"
    try:
        out = client.chat_json(JOURNAL_SYSTEM, user, JOURNAL_SCHEMA, temperature=0.7, max_tokens=400)
        entry = " ".join(str(out.get("entry", "")).split())
        if entry:
            return entry[:900], "model"
    except LLMUnavailable:
        pass
    done = sum(1 for f in finds if f["found"])
    return f"Went out at {place or 'somewhere outside'} and found {done} of {len(finds)} things on the card. " + (notes or ""), "template"
