"""Загрузка тестового сценария из JSON: школа, правила, пожелания, заявки на обмен.

Это не часть ядра — просто удобный способ собрать SchedulingProblem руками,
пока нет интерфейса и базы. Формат — см. examples/school.json.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from edtable.scheduler import (
    Group,
    InvalidProblemError,
    Lesson,
    MoveRequest,
    Room,
    Schedule,
    SchedulingProblem,
    Subject,
    Teacher,
    TimeSlot,
)
from edtable.scheduler.constraints import (
    DEFAULT_HARD_CONSTRAINTS,
    DoubleLessons,
    GroupDailyLimit,
    GroupGaps,
    HomeRoom,
    LateLessons,
    Pinned,
    SplitLessons,
    SubjectDailyLimit,
    TeacherDailyLimit,
    TeacherGaps,
    Unavailable,
)
from edtable.scheduler.models import DAY_NAMES


def parse_slots(text: str, slots) -> list[TimeSlot]:
    """«пн» — весь день, «пн 2» или «пн2» — один урок, «пн 2-4» — диапазон."""
    m = re.fullmatch(r"\s*([а-яё]{2})\s*(?:(\d+)(?:\s*-\s*(\d+))?)?\s*", text.lower())
    if not m or m.group(1) not in DAY_NAMES:
        raise InvalidProblemError(f"не понимаю слот «{text}», нужно вроде «пн 2» или «ср»")
    day = DAY_NAMES.index(m.group(1))
    first = int(m.group(2)) if m.group(2) else None
    last = int(m.group(3)) if m.group(3) else first
    found = [s for s in slots if s.day == day and (first is None or first <= s.period <= last)]
    if not found:
        raise InvalidProblemError(f"слота «{text}» нет в сетке")
    return sorted(found)


def parse_slot(text: str, slots) -> TimeSlot:
    found = parse_slots(text, slots)
    if len(found) != 1:
        raise InvalidProblemError(f"«{text}» — это не один слот")
    return found[0]


def _limits(value: int | dict) -> tuple[int, dict[str, int]]:
    if isinstance(value, dict):
        rest = dict(value)
        return rest.pop("default"), rest
    return value, {}


@dataclass
class Scenario:
    problem: SchedulingProblem
    wishes: dict[str, str] = field(default_factory=dict)
    exchange: list[dict] = field(default_factory=list)

    def move_requests(self, raw: dict, schedule: Schedule, limit: int = 12) -> list[MoveRequest]:
        """Варианты заявки из JSON, от лучшего к худшему.

        Формат: {"who", "to", "reason"} плюс чем выбрать занятие — "from", "group",
        "subject" в любом сочетании. "from" и "to" — слот («вт 3») или целый день
        («пт»): «перенесите любой мой пятничный урок куда-нибудь в среду».
        Базовое расписание заранее неизвестно, поэтому заявка задаётся признаками,
        а биржа перебирает варианты, пока какой-нибудь не пройдёт.
        """
        who = raw["who"]
        targets = parse_slots(raw["to"], self.problem.slots)
        mine = schedule.for_owner(who)
        if "from" in raw:
            allowed = set(parse_slots(raw["from"], self.problem.slots))
            mine = [a for a in mine if a.slot in allowed]
        for key in ("group", "subject"):
            if key in raw:
                mine = [a for a in mine if getattr(a.lesson, key).id == raw[key]]
        options = [
            MoveRequest(who, a.lesson.id, target, raw.get("reason", ""))
            for target in targets
            for a in mine
            if a.slot != target
        ]
        if not options:
            raise InvalidProblemError(f"у {who} нет подходящего занятия для заявки {raw}")
        return options[:limit]


def load_scenario(path: str | Path) -> Scenario:
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    grid = data["grid"]
    slots = tuple(
        TimeSlot(DAY_NAMES.index(day), period)
        for day in grid["days"]
        for period in range(1, grid["periods"] + 1)
    )
    rooms = tuple(
        Room(
            r["id"], r.get("name", r["id"]), r.get("capacity", 0), frozenset(r.get("features", ()))
        )
        for r in data["rooms"]
    )
    teachers = {t["id"]: Teacher(t["id"], t["name"]) for t in data["teachers"]}
    groups = {g["id"]: Group(g["id"], g["name"], g.get("size", 0)) for g in data["groups"]}
    subjects = {
        s["id"]: Subject(s["id"], s["name"], s.get("room_feature")) for s in data["subjects"]
    }

    lessons = []
    for item in data["curriculum"]:
        for n in range(1, item["hours"] + 1):
            lessons.append(
                Lesson(
                    id=f"{item['group']}-{item['subject']}-{n}",
                    subject=subjects[item["subject"]],
                    teacher=teachers[item["teacher"]],
                    group=groups[item["group"]],
                )
            )

    rules = data.get("rules", {})
    constraints = list(DEFAULT_HARD_CONSTRAINTS)
    # Лимиты — число или словарь {"default": 7, "5a": 6, ...} с исключениями.
    for key, rule in (
        ("group_daily_limit", GroupDailyLimit),
        ("teacher_daily_limit", TeacherDailyLimit),
        ("subject_daily_limit", SubjectDailyLimit),
    ):
        if key in rules:
            constraints.append(rule(*_limits(rules[key])))
    for group_id, room_id in rules.get("home_rooms", {}).items():
        constraints.append(HomeRoom(group_id, room_id))
    if rules.get("double_lessons"):
        constraints.append(DoubleLessons(rules["double_lessons"]))
    for item in rules.get("unavailable", ()):
        busy = [s for text in item["slots"] for s in parse_slots(text, slots)]
        constraints.append(Unavailable(item["who"], busy, item.get("reason", "")))
    pinned_ids = set()
    for item in rules.get("pinned", ()):
        lesson = next(
            (
                lesson
                for lesson in lessons
                if lesson.group.id == item["group"]
                and lesson.subject.id == item["subject"]
                and lesson.id not in pinned_ids
            ),
            None,
        )
        if lesson is None:
            raise InvalidProblemError(f"нечего закреплять: {item}")
        pinned_ids.add(lesson.id)
        constraints.append(Pinned(lesson.id, parse_slot(item["slot"], slots), item.get("room")))
    if rules.get("group_gap_penalty"):
        constraints.append(GroupGaps(rules["group_gap_penalty"]))
    if rules.get("teacher_gap_penalty"):
        constraints.append(TeacherGaps(rules["teacher_gap_penalty"]))
    if rules.get("split_lessons_penalty"):
        constraints.append(SplitLessons(rules["split_lessons_penalty"]))
    if late := rules.get("late_lessons"):
        constraints.append(LateLessons(late["subjects"], late["periods"], late["penalty"]))

    problem = SchedulingProblem(tuple(lessons), rooms, slots, tuple(constraints))
    return Scenario(problem, data.get("wishes", {}), data.get("exchange", []))
