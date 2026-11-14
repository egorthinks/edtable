"""Разбор пожеланий без модели, на регулярках.

Нужен, чтобы всё работало офлайн и в тестах. Понимает типовые фразы
(«не ставьте первые уроки», «свободная пятница», «без окон», «не больше 3
уроков в день», «не больше 4 дней в неделю»), всё остальное молча пропускает —
для свободного текста есть LM Studio.
"""

import re

from edtable.llm.spec import WishSpec

DAY_PATTERNS = {
    0: r"понедельн\w*|\bпн\b",
    1: r"вторн\w*|\bвт\b",
    2: r"\bсред[ауые]\w*|\bср\b",
    3: r"четверг\w*|\bчт\b",
    4: r"пятниц\w*|\bпт\b",
    5: r"суббот\w*|\bсб\b",
}

# Порядок важен: более длинные основы раньше коротких.
NUMBER_STEMS = (
    ("перв", 1),
    ("одн", 1),
    ("один", 1),
    ("втор", 2),
    ("дв", 2),
    ("трет", 3),
    ("тр", 3),
    ("четв", 4),
    ("четыр", 4),
    ("пят", 5),
    ("шест", 6),
    ("седьм", 7),
    ("сем", 7),
)

NUM = r"(\d+|[а-я]+)"
UNIT = r"(?:урок\w*|пар[аыуе]?\w*)"
NOT = re.compile(r"\bне\b|нельзя|никак")
LOW = re.compile(
    r"желательн|если можно|по возможности|хотелось бы|было бы (?:неплохо|хорошо)"
    r"|не обязательно|если получится"
)
HIGH = re.compile(r"очень|обязательн|критичн|важн|никак|ни в коем|категорическ|принципиальн")
NOTHING = re.compile(r"без разницы|нет пожеланий|вс[её] равно|пожеланий нет")


def number(word: str) -> int | None:
    if word.isdigit():
        return int(word)
    return next((n for stem, n in NUMBER_STEMS if word.startswith(stem)), None)


class RuleParser:
    name = "rules"

    def parse(self, text: str, days: list[int], periods: int) -> list[WishSpec]:
        specs = []
        for sentence in re.split(r"[.!?;\n]+|,\s*(?:а|но)\s+", text):
            sentence = sentence.strip().lower().replace("ё", "е")
            if sentence and not NOTHING.search(sentence):
                specs.extend(self._sentence(sentence, days, periods))
        return specs

    def _sentence(self, s: str, days: list[int], periods: int) -> list[WishSpec]:
        found: list[WishSpec] = []
        mentioned = [
            d for d, pattern in DAY_PATTERNS.items() if d in days and re.search(pattern, s)
        ]

        if re.search(r"без окон|без окна|подряд", s):
            found.append(WishSpec("no_gaps"))

        if m := re.search(rf"(?:не больше|не более|максимум)\s+{NUM}\s+{UNIT}", s):
            if limit := number(m.group(1)):
                found.append(WishSpec("max_per_day", limit=limit))

        m = re.search(
            rf"(?:не больше|не более|максимум)\s+{NUM}\s+(?:рабоч\w*\s+)?дн", s
        ) or re.search(rf"{NUM}\s+(?:рабоч\w*\s+)?дн\w*\s+в\s+неделю", s)
        if m and (limit := number(m.group(1))):
            found.append(WishSpec("max_days", limit=limit))

        if re.search(r"свободн\w*|выходн\w*", s) and not re.search(r"свободн\w* окн", s):
            found.append(self._free_day(s, mentioned or days))
        else:
            blocked = self._blocked_periods(s, periods)
            if blocked or (mentioned and NOT.search(s) and not found):
                found.append(WishSpec("avoid", days=mentioned, periods=sorted(blocked)))

        weight, points = self._importance(s)
        for spec in found:
            spec.weight, spec.points, spec.text = weight, points, s
        # Если в одной фразе названы очки, а пожеланий несколько, делим очки поровну.
        if points is not None and len(found) > 1:
            for spec in found:
                spec.points = points // len(found)
        return found

    def _free_day(self, s: str, candidates: list[int]) -> WishSpec:
        if len(candidates) == 1:
            return WishSpec("avoid", days=candidates)
        if " или " in s or re.search(r"\bодин\b|\bлюбой\b|\bхотя бы\b", s) or len(candidates) > 2:
            return WishSpec("any", parts=[WishSpec("avoid", days=[d]) for d in candidates])
        return WishSpec("avoid", days=candidates)

    def _blocked_periods(self, s: str, periods: int) -> set[int]:
        every = set(range(1, periods + 1))
        blocked: set[int] = set()

        if m := re.search(rf"не раньше\s+{NUM}\s+{UNIT}|\bсо?\s+{NUM}\s+{UNIT}", s):
            if n := number(m.group(1) or m.group(2)):
                blocked |= {p for p in every if p < n}
        if m := re.search(rf"не (?:позже|позднее)\s+{NUM}\s+{UNIT}", s):
            if n := number(m.group(1)):
                blocked |= {p for p in every if p > n}
        if NOT.search(s):
            if m := re.search(rf"после\s+{NUM}\s+{UNIT}", s):
                if n := number(m.group(1)):
                    blocked |= {p for p in every if p > n}
            if m := re.search(rf"перв\w*\s+{NUM}\s+{UNIT}", s):
                blocked |= set(range(1, (number(m.group(1)) or 1) + 1))
            elif re.search(rf"перв\w*\s+{UNIT}|{UNIT}\s+перв\w*", s):
                blocked.add(1)
            if re.search(rf"последн\w*\s+{UNIT}", s):
                blocked.add(periods)
        return blocked

    def _importance(self, s: str) -> tuple[float, int | None]:
        points = int(m.group(1)) if (m := re.search(r"(\d+)\s*(?:очк|балл)", s)) else None
        if LOW.search(s):
            return 3, points
        if HIGH.search(s):
            return 9, points
        return 5, points
