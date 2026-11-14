"""Разбор пожеланий локальной моделью через LM Studio.

LM Studio поднимает OpenAI-совместимый сервер (по умолчанию localhost:1234) и
умеет ограничивать ответ JSON-схемой, поэтому модель физически не может вернуть
мусор — только наш формат. Ходим в него обычным urllib, лишних зависимостей нет.
"""

import json
import urllib.error
import urllib.request

from edtable.llm.spec import ATOM_KINDS, KINDS, WishParserError, WishSpec
from edtable.scheduler.models import DAY_NAMES

SYSTEM_PROMPT = """\
Ты переводишь пожелания к школьному расписанию в JSON. Пишет один участник:
учитель или представитель класса. Выдели каждое отдельное пожелание. В одном
тексте их обычно несколько: «не ставьте первые уроки, и без окон» — это два
пожелания, avoid и no_gaps. Пройди текст до конца и не пропускай ни одного.

Виды пожеланий (kind):
- "avoid": не ставить занятия в указанные дни и/или уроки. days — дни, periods —
  номера уроков. Пустой days — все дни, пустой periods — весь день.
  «не ставьте первые уроки» -> days=[], periods=[1]
  «свободная пятница» -> days=["пт"], periods=[]
  «в среду не позже 4 урока» (уроков всего 6) -> days=["ср"], periods=[5, 6]
- "no_gaps": без окон, все занятия дня подряд.
- "max_per_day": не больше limit занятий в день.
- "max_days": не больше limit рабочих дней в неделю.
- "any": достаточно выполнить хотя бы одно из parts (связка «или»).
  «один свободный день, понедельник или пятница» ->
  any из двух avoid: days=["пн"] и days=["пт"]
- "all": parts нужны только все вместе (связка «и»).

importance — насколько это важно человеку, от 1 до 10: «очень нужно», «никак не
могу» — 9-10; без оценки — 5; «желательно», «если получится» — 2-3.
points — только если человек сам назвал число очков, иначе null.
quote — фраза из текста, к которой относится пожелание.
Ничего не выдумывай: если пожеланий нет, верни пустой список."""


TEXT = ("llm", "vlm")


def _schema(day_names: list[str]) -> dict:
    atom = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(ATOM_KINDS)},
            "days": {"type": "array", "items": {"type": "string", "enum": day_names}},
            "periods": {"type": "array", "items": {"type": "integer"}},
            "limit": {"type": ["integer", "null"]},
        },
        "required": ["kind", "days", "periods", "limit"],
        "additionalProperties": False,
    }
    wish = {
        "type": "object",
        "properties": {
            **atom["properties"],
            "kind": {"type": "string", "enum": list(KINDS)},
            "parts": {"type": "array", "items": atom},
            "importance": {"type": "integer"},
            "points": {"type": ["integer", "null"]},
            "quote": {"type": "string"},
        },
        "required": ["kind", "days", "periods", "limit", "parts", "importance", "points", "quote"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"wishes": {"type": "array", "items": wish}},
        "required": ["wishes"],
        "additionalProperties": False,
    }


class LMStudioParser:
    name = "lmstudio"

    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        model: str | None = None,
        timeout: float = 180.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def parse(self, text: str, days: list[int], periods: int) -> list[WishSpec]:
        if not text.strip():
            return []
        day_names = [DAY_NAMES[d] for d in days]
        grid = f"Дни: {', '.join(day_names)}. Уроков в день: {periods}."
        body = {
            "model": self._model(),
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"{grid}\n\nПожелания:\n{text}"},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "wishes", "strict": True, "schema": _schema(day_names)},
            },
        }
        reply = self._request("/chat/completions", body)
        try:
            message = reply["choices"][0]["message"]
            # «Думающие» модели (Qwen3 и т.п.) иногда кладут ответ в reasoning_content,
            # а content оставляют пустым. Схему LM Studio соблюдает и там.
            content = message.get("content") or message.get("reasoning_content") or ""
            raw = json.loads(content)["wishes"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            raise WishParserError(f"модель вернула не то, что просили: {e}") from e
        return [self._spec(item, day_names, periods) for item in raw]

    def _spec(self, item: dict, day_names: list[str], periods: int, top: bool = True) -> WishSpec:
        days = [DAY_NAMES.index(d) for d in item.get("days", []) if d in day_names]
        hours = [p for p in item.get("periods", []) if 1 <= p <= periods]
        # Пустой список значит «все дни», поэтому если модель назвала только
        # несуществующие дни или уроки, пожелание выбрасываем, а не расширяем.
        broken = (item.get("days") and not days) or (item.get("periods") and not hours)
        spec = WishSpec(
            kind="" if broken else item.get("kind", ""),
            days=days,
            periods=hours,
            limit=item.get("limit"),
        )
        if top:
            spec.parts = [
                self._spec(p, day_names, periods, top=False) for p in item.get("parts", [])
            ]
            spec.weight = min(max(item.get("importance", 5), 1), 10)
            spec.points = item.get("points")
            spec.text = item.get("quote", "")
        return spec

    def _model(self) -> str:
        """Уже загруженная текстовая модель, иначе первая скачанная.

        /v1/models отдаёт все скачанные модели, а не загруженные, поэтому сначала
        спрашиваем родной API LM Studio — там есть состояние модели.
        """
        if self.model is None:
            try:
                native = self._request("/api/v0/models", root=True).get("data", [])
            except WishParserError:
                native = []
            loaded = [
                m["id"] for m in native if m.get("state") == "loaded" and m.get("type") in TEXT
            ]
            listed = [
                m["id"]
                for m in self._request("/models").get("data", [])
                if not any(word in m["id"] for word in ("embed", "rerank"))
            ]
            if not (loaded or listed):
                raise WishParserError("в LM Studio нет ни одной текстовой модели")
            self.model = (loaded or listed)[0]
        return self.model

    def _request(self, path: str, body: dict | None = None, root: bool = False) -> dict:
        base = self.base_url.removesuffix("/v1") if root else self.base_url
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            base + path, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            raise WishParserError(f"LM Studio ответил {e.code}: {e.read().decode()[:300]}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise WishParserError(
                f"LM Studio не отвечает на {self.base_url} ({e}). "
                "Запустите сервер: вкладка Developer -> Start Server."
            ) from e
