"""SQLite persistence. Everything stays in one local file plus a photos folder."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS quests (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    returned_at REAL,
    place TEXT NOT NULL,
    payload TEXT NOT NULL,          -- the full card as JSON
    source TEXT NOT NULL,           -- 'model' or 'template'
    outside_minutes INTEGER,
    screen_seconds INTEGER,
    journal_entry TEXT,
    journal_source TEXT
);
CREATE TABLE IF NOT EXISTS finds (
    quest_id TEXT NOT NULL REFERENCES quests(id),
    item_id INTEGER NOT NULL,
    found INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    photo TEXT,
    matches TEXT,
    what_i_see TEXT,
    ai_note TEXT,
    PRIMARY KEY (quest_id, item_id)
);
"""


class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def create_quest(self, place: str, payload: dict[str, Any], source: str) -> str:
        qid = uuid.uuid4().hex[:10]
        with self._conn() as c:
            c.execute("INSERT INTO quests (id, created_at, place, payload, source) VALUES (?,?,?,?,?)",
                      (qid, time.time(), place, json.dumps(payload), source))
            c.executemany("INSERT INTO finds (quest_id, item_id) VALUES (?,?)",
                          [(qid, it["id"]) for it in payload["items"]])
        return qid

    def get_quest(self, qid: str) -> dict[str, Any] | None:
        with self._conn() as c:
            q = c.execute("SELECT * FROM quests WHERE id=?", (qid,)).fetchone()
            if q is None:
                return None
            finds = c.execute("SELECT * FROM finds WHERE quest_id=? ORDER BY item_id", (qid,)).fetchall()
        card = json.loads(q["payload"])
        by_id = {f["item_id"]: dict(f) for f in finds}
        for it in card["items"]:
            f = by_id.get(it["id"], {})
            it["found"] = bool(f.get("found"))
            it["note"] = f.get("note", "")
            it["photo"] = f.get("photo")
            it["matches"] = f.get("matches")
            it["what_i_see"] = f.get("what_i_see")
            it["ai_note"] = f.get("ai_note")
        return {
            "id": q["id"], "created_at": q["created_at"], "returned_at": q["returned_at"], "place": q["place"],
            "source": q["source"], "outside_minutes": q["outside_minutes"], "screen_seconds": q["screen_seconds"],
            "journal_entry": q["journal_entry"], "journal_source": q["journal_source"], **card,
        }

    def record_find(self, qid: str, item_id: int, *, found: bool, note: str = "", photo: str | None = None,
                    matches: str | None = None, what_i_see: str | None = None, ai_note: str | None = None) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE finds SET found=?, note=?, photo=COALESCE(?, photo), matches=COALESCE(?, matches), "
                "what_i_see=COALESCE(?, what_i_see), ai_note=COALESCE(?, ai_note) WHERE quest_id=? AND item_id=?",
                (int(found), note, photo, matches, what_i_see, ai_note, qid, item_id))

    def complete(self, qid: str, outside_minutes: int, screen_seconds: int, entry: str, entry_source: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE quests SET returned_at=?, outside_minutes=?, screen_seconds=?, journal_entry=?, "
                      "journal_source=? WHERE id=?", (time.time(), outside_minutes, screen_seconds, entry, entry_source, qid))

    def journal(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as c:
            ids = [r["id"] for r in c.execute("SELECT id FROM quests ORDER BY created_at DESC LIMIT ?", (limit,))]
        return [q for q in (self.get_quest(i) for i in ids) if q]

    def totals(self) -> dict[str, int]:
        with self._conn() as c:
            r = c.execute("SELECT COUNT(*) n, COALESCE(SUM(outside_minutes),0) out, COALESCE(SUM(screen_seconds),0) scr "
                          "FROM quests WHERE returned_at IS NOT NULL").fetchone()
            found = c.execute("SELECT COUNT(*) FROM finds f JOIN quests q ON q.id=f.quest_id "
                              "WHERE f.found=1 AND q.returned_at IS NOT NULL").fetchone()[0]
        return {"outings": r["n"], "outside_minutes": r["out"], "screen_seconds": r["scr"], "things_found": found}
