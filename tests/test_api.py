import io

from PIL import Image

from conftest import GOOD_CARD, jpeg_bytes

PLAN = {"place": "Ridge Park", "lat": 47.6, "lon": -122.3, "habitat": "forest trail", "minutes": 60,
        "energy": "gentle", "utc_offset_min": -420, "on": "2026-10-07"}


def test_health_reports_model_pulled(client):
    d = client.get("/api/health").json()
    assert d["ok"] is True and d["model"] == "gemma4:e4b" and "city park" in d["habitats"]


def test_health_when_ollama_down(client, fake):
    fake.fail = True
    d = client.get("/api/health").json()
    assert d["ok"] is False and d["reachable"] is False


def test_create_quest_uses_model_and_sends_context(client, fake):
    q = client.post("/api/quests", json=PLAN).json()
    assert q["source"] == "model" and q["title"] == GOOD_CARD["title"]
    assert len(q["items"]) == 7 and q["items"][0]["id"] == 1
    assert q["meta"]["season"] == "autumn" and "Sunset about" in q["meta"]["sunset_note"]
    sent = fake.calls[0]["messages"][1]["content"]
    assert "autumn" in sent and "forest trail" in sent and "60 minutes" in sent
    assert fake.calls[0]["think"] is False and fake.calls[0]["format"]["type"] == "object"


def test_create_quest_falls_back_to_template_when_model_down(client, fake):
    fake.fail = True
    q = client.post("/api/quests", json=PLAN).json()
    assert q["source"] == "template" and len(q["items"]) == 7


def test_create_quest_falls_back_when_model_returns_junk(client, fake):
    fake.card = {"title": "x", "intro": "", "items": [], "sit_spot": "", "safety_note": ""}
    assert client.post("/api/quests", json=PLAN).json()["source"] == "template"


def test_invalid_input_is_rejected(client):
    assert client.post("/api/quests", json={**PLAN, "lat": 123}).status_code == 422
    assert client.post("/api/quests", json={**PLAN, "minutes": 5}).status_code == 422


def test_print_card_renders_items_and_escapes_html(client, fake):
    fake.card = {**GOOD_CARD, "title": "<script>alert(1)</script>"}
    q = client.post("/api/quests", json=PLAN).json()
    html = client.get(f"/card/{q['id']}").text
    assert "Find three leaves in three different colours" in html
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_unknown_or_malformed_ids_404(client):
    assert client.get("/api/quests/deadbeef00").status_code == 404
    assert client.get("/api/quests/..%2F..%2Fetc").status_code == 404
    assert client.get("/card/not-an-id").status_code == 404


def test_photo_find_is_checked_marked_found_and_exif_free(client, fake):
    q = client.post("/api/quests", json=PLAN).json()
    im = Image.new("RGB", (900, 600), (10, 120, 10))
    exif = Image.Exif(); exif[0x010F] = "SecretCam"
    buf = io.BytesIO(); im.save(buf, format="JPEG", exif=exif)
    r = client.post(f"/api/quests/{q['id']}/finds", data={"item_id": "1"},
                    files={"photo": ("leaf.jpg", buf.getvalue(), "image/jpeg")}).json()
    assert r["found"] is True and r["matches"] == "yes" and "maple" in r["what_i_see"]
    vision = [c for c in fake.calls if "images" in c["messages"][1]]
    assert len(vision) == 1 and "Find three leaves" in vision[0]["messages"][1]["content"]
    stored = client.get(f"/api/photos/{q['id']}/1")
    assert stored.status_code == 200
    saved = Image.open(io.BytesIO(stored.content))
    assert max(saved.size) <= 768 and 0x010F not in saved.getexif()


def test_photo_verdict_no_does_not_mark_found(client, fake):
    fake.verdict = {"what_i_see": "A parked car.", "matches": "no", "note": "Not quite."}
    q = client.post("/api/quests", json=PLAN).json()
    r = client.post(f"/api/quests/{q['id']}/finds", data={"item_id": "2"},
                    files={"photo": ("x.jpg", jpeg_bytes(), "image/jpeg")}).json()
    assert r["found"] is False and r["matches"] == "no" and r["photo"]


def test_photo_check_degrades_gracefully_when_model_down(client, fake):
    q = client.post("/api/quests", json=PLAN).json()
    fake.fail = True
    r = client.post(f"/api/quests/{q['id']}/finds", data={"item_id": "1"},
                    files={"photo": ("x.jpg", jpeg_bytes(), "image/jpeg")}).json()
    assert r["matches"] == "cannot_tell" and r["found"] is False


def test_bad_uploads_and_items_are_rejected(client):
    q = client.post("/api/quests", json=PLAN).json()
    bad = client.post(f"/api/quests/{q['id']}/finds", data={"item_id": "1"},
                      files={"photo": ("x.jpg", b"not an image", "image/jpeg")})
    assert bad.status_code == 400
    assert client.post(f"/api/quests/{q['id']}/finds", data={"item_id": "99"}).status_code == 404


def test_manual_tick_then_return_writes_journal_and_totals(client, fake):
    q = client.post("/api/quests", json=PLAN).json()
    client.post(f"/api/quests/{q['id']}/finds", data={"item_id": "1", "found": "true", "note": "a red one"})
    done = client.post(f"/api/quests/{q['id']}/return",
                       json={"outside_minutes": 75, "screen_seconds": 140, "notes": "cold but good"}).json()
    assert done["journal_source"] == "model" and "ridge" in done["journal_entry"]
    journal_call = fake.calls[-1]["messages"][1]["content"]
    assert "Find three leaves in three different colours -> found" in journal_call and "cold but good" in journal_call
    j = client.get("/api/journal").json()
    assert j["totals"] == {"outings": 1, "outside_minutes": 75, "screen_seconds": 140, "things_found": 1}
    assert j["outings"][0]["id"] == q["id"]


def test_return_falls_back_to_template_entry(client, fake):
    q = client.post("/api/quests", json=PLAN).json()
    fake.fail = True
    done = client.post(f"/api/quests/{q['id']}/return", json={"outside_minutes": 10, "screen_seconds": 5}).json()
    assert done["journal_source"] == "template" and "0 of 7" in done["journal_entry"]


def test_weather_is_opt_in(client, monkeypatch):
    seen = []
    monkeypatch.setattr("trailcard.server.fetch_weather", lambda lat, lon, on: seen.append((lat, lon)) or
                        {"summary": "rain", "high_c": 11, "low_c": 6, "rain_chance_pct": 80})
    client.post("/api/quests", json=PLAN)
    assert seen == []
    q = client.post("/api/quests", json={**PLAN, "use_weather": True}).json()
    assert seen and q["meta"]["weather"]["summary"] == "rain"
