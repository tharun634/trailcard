"""FastAPI application. Everything here runs on the user's own machine."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from . import __version__
from .astro import daylight_note, season, sun_times
from .config import Settings
from .identify import check_photo, prepare_photo, write_journal
from .llm import OllamaClient
from .quest import ENERGY, HABITATS, QuestRequest, generate_quest
from .store import Store
from .weather import fetch_weather

HERE = Path(__file__).parent
MAX_UPLOAD = 12 * 1024 * 1024
QID = re.compile(r"^[a-f0-9]{10}$")


class QuestIn(BaseModel):
    place: str = Field("", max_length=80)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    habitat: str = Field("city park")
    minutes: int = Field(60, ge=15, le=240)
    energy: str = Field("gentle")
    use_weather: bool = False
    utc_offset_min: int = Field(0, ge=-840, le=840)
    on: date | None = None


class ReturnIn(BaseModel):
    outside_minutes: int = Field(..., ge=0, le=24 * 60)
    screen_seconds: int = Field(0, ge=0, le=24 * 3600)
    notes: str = Field("", max_length=600)


def create_app(settings: Settings | None = None, client: OllamaClient | None = None) -> FastAPI:
    settings = settings or Settings()
    client = client or OllamaClient(settings.ollama_host, settings.model, settings.llm_timeout_s)
    store = Store(settings.db_path)
    settings.photo_dir.mkdir(parents=True, exist_ok=True)
    templates = Jinja2Templates(directory=str(HERE / "templates"))

    app = FastAPI(title="Trailcard", version=__version__)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    def _quest_or_404(qid: str) -> dict:
        if not QID.match(qid):
            raise HTTPException(404, "No such quest")
        q = store.get_quest(qid)
        if q is None:
            raise HTTPException(404, "No such quest")
        return q

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(HERE / "static" / "index.html")

    @app.get("/api/health")
    def health() -> dict:
        return {**client.health(), "version": __version__, "habitats": HABITATS, "energy": ENERGY}

    @app.post("/api/quests")
    def create_quest(body: QuestIn) -> dict:
        habitat = body.habitat if body.habitat in HABITATS else "city park"
        energy = body.energy if body.energy in ENERGY else "gentle"
        on = body.on or (datetime.now(timezone.utc) + timedelta(minutes=body.utc_offset_min)).date()
        _, sunset = sun_times(body.lat, body.lon, on)
        note = daylight_note(sunset, body.utc_offset_min)
        wx = fetch_weather(body.lat, body.lon, on) if body.use_weather else None
        req = QuestRequest(place=body.place.strip(), lat=body.lat, lon=body.lon, habitat=habitat,
                           minutes=body.minutes, energy=energy, season=season(body.lat, on),
                           date_iso=on.isoformat(), sunset_note=note, weather=wx)
        card, source = generate_quest(client, req)
        card["meta"] = {"date": on.isoformat(), "season": req.season, "habitat": habitat, "minutes": body.minutes,
                        "energy": energy, "sunset_note": note, "weather": wx, "model": settings.model}
        qid = store.create_quest(req.place, card, source)
        return store.get_quest(qid)  # type: ignore[return-value]

    @app.get("/api/quests/{qid}")
    def get_quest(qid: str) -> dict:
        return _quest_or_404(qid)

    @app.get("/card/{qid}", response_class=HTMLResponse)
    def print_card(request: Request, qid: str):
        return templates.TemplateResponse(request=request, name="card.html", context={"q": _quest_or_404(qid)})

    @app.post("/api/quests/{qid}/finds")
    def record_find(
        qid: str,
        item_id: Annotated[int, Form()],
        found: Annotated[bool, Form()] = False,
        note: Annotated[str, Form(max_length=300)] = "",
        photo: Annotated[UploadFile | None, File()] = None,
    ) -> dict:
        q = _quest_or_404(qid)
        item = next((i for i in q["items"] if i["id"] == item_id), None)
        if item is None:
            raise HTTPException(404, "No such item on this card")
        photo_name = matches = what = ai_note = None
        if photo is not None and photo.filename:
            data = photo.file.read(MAX_UPLOAD + 1)
            if len(data) > MAX_UPLOAD:
                raise HTTPException(413, "Photo is larger than 12 MB")
            try:
                jpeg = prepare_photo(data)
            except Exception as exc:  # PIL raises many types for bad images
                raise HTTPException(400, "That file is not a readable image") from exc
            photo_name = f"{qid}-{item_id}.jpg"
            (settings.photo_dir / photo_name).write_bytes(jpeg)
            verdict = check_photo(client, item["prompt"], item["hint"], jpeg)
            matches, what, ai_note = verdict["matches"], verdict["what_i_see"], verdict["note"]
            if matches in ("yes", "partly"):
                found = True
        store.record_find(qid, item_id, found=found, note=note.strip(), photo=photo_name,
                          matches=matches, what_i_see=what, ai_note=ai_note)
        return next(i for i in store.get_quest(qid)["items"] if i["id"] == item_id)  # type: ignore[index]

    @app.get("/api/photos/{qid}/{item_id}")
    def photo(qid: str, item_id: int) -> FileResponse:
        _quest_or_404(qid)
        path = settings.photo_dir / f"{qid}-{item_id}.jpg"
        if not path.is_file():
            raise HTTPException(404, "No photo")
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/api/quests/{qid}/return")
    def finish(qid: str, body: ReturnIn) -> dict:
        q = _quest_or_404(qid)
        finds = [{"prompt": i["prompt"], "found": i["found"], "note": i["note"],
                  "matches": i["matches"], "what_i_see": i["what_i_see"]} for i in q["items"]]
        entry, src = write_journal(client, q["place"], q["title"], finds, body.notes)
        store.complete(qid, body.outside_minutes, body.screen_seconds, entry, src)
        return store.get_quest(qid)  # type: ignore[return-value]

    @app.get("/api/journal")
    def journal() -> dict:
        return {"outings": store.journal(), "totals": store.totals()}

    return app
