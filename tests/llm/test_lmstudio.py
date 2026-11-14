import json

import pytest

from edtable.llm import LMStudioParser, WishParserError, to_offers
from helpers import grid


def reply(wishes: list[dict]) -> dict:
    return {"choices": [{"message": {"content": json.dumps({"wishes": wishes})}}]}


def atom(kind, days=(), periods=(), limit=None):
    return {"kind": kind, "days": list(days), "periods": list(periods), "limit": limit}


def test_model_answer_is_converted_to_specs(monkeypatch):
    sent = {}

    def fake_request(path, body=None, root=False):
        if path == "/api/v0/models":
            return {
                "data": [
                    {"id": "big-model", "type": "llm", "state": "not-loaded"},
                    {"id": "text-embedding-x", "type": "embeddings", "state": "loaded"},
                    {"id": "qwen-local", "type": "llm", "state": "loaded"},
                ]
            }
        if path == "/models":
            return {"data": [{"id": "big-model"}, {"id": "qwen-local"}]}
        sent.update(body)
        return reply(
            [
                {
                    **atom("avoid", ["пт"], [5, 6, 99]),
                    "parts": [],
                    "importance": 14,
                    "points": None,
                    "quote": "в пятницу пораньше",
                },
                {
                    **atom("any"),
                    "parts": [atom("avoid", ["пн"]), atom("avoid", ["вс"])],
                    "importance": 5,
                    "points": 40,
                    "quote": "свободный день",
                },
            ]
        )

    parser = LMStudioParser()
    monkeypatch.setattr(parser, "_request", fake_request)

    first, second = parser.parse("какой-то текст", days=[0, 1, 2, 3, 4], periods=6)

    # Берём загруженную текстовую модель, а не первую скачанную и не эмбеддинги.
    assert sent["model"] == "qwen-local"
    assert sent["response_format"]["type"] == "json_schema"
    assert (first.kind, first.days, first.periods, first.weight) == ("avoid", [4], [5, 6], 10)
    assert second.points == 40
    # «вс» нет в сетке: часть выбрасывается, а не превращается в «все дни».
    offers = to_offers("t", [second], grid(days=5, periods=6))
    assert offers[0].wish == to_offers("t", [second.parts[0]], grid(days=5, periods=6))[0].wish


def test_thinking_model_answer_in_reasoning_content(monkeypatch):
    parser = LMStudioParser(model="m")
    answer = {**atom("no_gaps"), "parts": [], "importance": 5, "points": None, "quote": ""}
    message = {"content": "", "reasoning_content": json.dumps({"wishes": [answer]})}
    monkeypatch.setattr(parser, "_request", lambda *a, **k: {"choices": [{"message": message}]})

    [spec] = parser.parse("Без окон", [0], 6)

    assert spec.kind == "no_gaps"


def test_garbage_answer_is_an_error(monkeypatch):
    parser = LMStudioParser(model="m")
    monkeypatch.setattr(parser, "_request", lambda *a, **k: {"choices": []})

    with pytest.raises(WishParserError, match="не то"):
        parser.parse("текст", [0], 6)


def test_server_down_is_a_clear_error():
    parser = LMStudioParser("http://127.0.0.1:9/v1", model="m", timeout=2)

    with pytest.raises(WishParserError, match="Start Server"):
        parser.parse("текст", [0], 6)
