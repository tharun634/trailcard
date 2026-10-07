import pytest

from trailcard.quest import QUEST_SCHEMA, QuestRequest, fallback_quest, n_items_for, validate_quest


def _req(**kw):
    base = dict(place="Ridge Park", lat=47.6, lon=-122.3, habitat="forest trail", minutes=60, energy="gentle",
                season="autumn", date_iso="2026-10-07", sunset_note="Sunset about 18:36 local time.")
    base.update(kw)
    return QuestRequest(**base)


def test_item_count_scales_with_time_and_is_bounded():
    assert n_items_for(15) == 4 and n_items_for(60) == 7 and n_items_for(240) == 8


def test_validate_assigns_ids_clamps_unknown_kinds_and_truncates():
    raw = {"title": "T", "intro": "i", "sit_spot": "s", "safety_note": "n",
           "items": [{"prompt": f"item {i}", "hint": "h", "kind": "bogus" if i == 0 else "photo"} for i in range(10)]}
    card = validate_quest(raw, 6)
    assert [i["id"] for i in card["items"]] == [1, 2, 3, 4, 5, 6]
    assert card["items"][0]["kind"] == "look"
    assert card["items"][1]["photo_ok"] is True


def test_validate_rejects_thin_output():
    with pytest.raises(ValueError):
        validate_quest({"title": "T", "items": [{"prompt": "only one", "hint": "", "kind": "look"}]}, 6)
    with pytest.raises(ValueError):
        validate_quest({"title": "", "items": [{"prompt": f"p{i}", "hint": "", "kind": "look"} for i in range(5)]}, 6)


def test_schema_requires_the_fields_we_render():
    assert set(QUEST_SCHEMA["required"]) == {"title", "intro", "items", "sit_spot", "safety_note"}


@pytest.mark.parametrize("season", ["autumn", "winter", "spring", "summer"])
def test_fallback_is_valid_for_every_season_and_deterministic(season):
    a = fallback_quest(_req(season=season), 6)
    b = fallback_quest(_req(season=season), 6)
    assert a == b
    validate_quest(a, 6)  # a template card must itself pass validation


def test_validate_drops_useless_echo_hints_but_keeps_real_ones():
    raw = {"title": "T", "intro": "i", "sit_spot": "s", "safety_note": "n", "items": [
        {"prompt": "a", "hint": "Look", "kind": "look"},
        {"prompt": "b", "hint": "touch.", "kind": "touch"},
        {"prompt": "c", "hint": "Check the sunny side of tree trunks.", "kind": "look"},
        {"prompt": "d", "hint": "", "kind": "listen"},
    ]}
    hints = [i["hint"] for i in validate_quest(raw, 6)["items"]]
    assert hints == ["", "", "Check the sunny side of tree trunks.", ""]
