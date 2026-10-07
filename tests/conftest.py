"""Shared fixtures: a fake Ollama served through httpx.MockTransport (no GPU, no network)."""

from __future__ import annotations

import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from trailcard.config import Settings
from trailcard.llm import OllamaClient
from trailcard.server import create_app

GOOD_CARD = {
    "title": "Amber Hour on the Ridge",
    "intro": "Golden light and cold air. Let's see what the afternoon is hiding.",
    "items": [
        {"prompt": "Find three leaves in three different colours", "hint": "Compare how each feels.", "kind": "touch"},
        {"prompt": "Listen for the farthest sound you can hear", "hint": "Close your eyes for ten seconds.", "kind": "listen"},
        {"prompt": "Spot a shadow longer than you are", "hint": "Low sun makes them.", "kind": "photo"},
        {"prompt": "Smell the air: damp, smoky or sweet?", "hint": "", "kind": "smell"},
        {"prompt": "Find something moving in the wind", "hint": "", "kind": "look"},
        {"prompt": "Notice a patch of light on the ground", "hint": "", "kind": "sit"},
        {"prompt": "Find a rough texture and a smooth one", "hint": "", "kind": "touch"},
    ],
    "sit_spot": "Sit for five minutes and count the sounds.",
    "safety_note": "Dusk comes early now, so head back with some light to spare.",
}


class FakeOllama:
    """Records requests and replies based on whether the call carries images."""

    def __init__(self):
        self.calls: list[dict] = []
        self.fail = False
        self.card = GOOD_CARD
        self.verdict = {"what_i_see": "A red maple leaf on wet pavement.", "matches": "yes", "note": "Lovely colour."}

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            raise httpx.ConnectError("ollama is down")
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "gemma4:e4b"}]})
        body = json.loads(request.content)
        self.calls.append(body)
        props = body["format"]["properties"]
        if "matches" in props:
            out = self.verdict
        elif "entry" in props:
            out = {"entry": "I wandered up the ridge and found three leaves. Next time, look for the long shadows."}
        else:
            out = self.card
        return httpx.Response(200, json={"message": {"role": "assistant", "content": json.dumps(out)}})


@pytest.fixture
def fake() -> FakeOllama:
    return FakeOllama()


@pytest.fixture
def client(tmp_path, fake) -> TestClient:
    settings = Settings(data_dir=tmp_path)
    llm = OllamaClient("http://ollama.test", "gemma4:e4b", transport=httpx.MockTransport(fake.handler))
    return TestClient(create_app(settings, llm))


def jpeg_bytes(size=(1600, 1200), colour=(200, 40, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="JPEG")
    return buf.getvalue()
