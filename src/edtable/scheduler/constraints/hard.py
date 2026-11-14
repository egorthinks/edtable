"""Жёсткие ограничения: их задаёт администратор, нарушать нельзя."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Hashable, Iterable
from typing import TYPE_CHECKING

from edtable.scheduler.constraints.base import Constraint, UnaryConstraint, Violation
from edtable.scheduler.models import DAY_NAMES, Assignment, Lesson, Room, TimeSlot
from edtable.scheduler.schedule import Schedule

if TYPE_CHECKING:
    from edtable.scheduler.solvers.cpsat import CpSatContext


def _find_overlaps(
    constraint: Constraint,
    schedule: Schedule,
    key: Callable[[Assignment], Hashable],
    what: str,
) -> list[Violation]:
    """key возвращает сущность с полем name: преподавателя, группу или аудиторию."""
    buckets: dict[tuple, list[Assignment]] = defaultdict(list)
    for assignment in schedule.assignments:
        buckets[(assignment.slot, key(assignment))].append(assignment)

    return [
        Violation(
            constraint=constraint,
            message=f"{what} {owner.name} занят(а) дважды в {slot}",
            assignments=tuple(clashing),
        )
        for (slot, owner), clashing in buckets.items()
        if len(clashing) > 1
    ]


class NoTeacherOverlap(Constraint):
    name = "no_teacher_overlap"

    def check(self, schedule: Schedule) -> list[Violation]:
        return _find_overlaps(self, schedule, lambda a: a.lesson.teacher, "Преподаватель")

    def encode(self, ctx: CpSatContext) -> None:
        for teacher in ctx.problem.teachers:
            for slot in ctx.slots:
                ctx.at_most_one(ctx.lesson_terms(teacher.id, slot))


class NoGroupOverlap(Constraint):
    name = "no_group_overlap"

    def check(self, schedule: Schedule) -> list[Violation]:
        return _find_overlaps(self, schedule, lambda a: a.lesson.group, "Группа")

    def encode(self, ctx: CpSatContext) -> None:
        for group in ctx.problem.groups:
            for slot in ctx.slots:
                ctx.at_most_one(ctx.lesson_terms(group.id, slot))


class NoRoomOverlap(Constraint):
    name = "no_room_overlap"

    def check(self, schedule: Schedule) -> list[Violation]:
        return _find_overlaps(self, schedule, lambda a: a.room, "Аудитория")

    def encode(self, ctx: CpSatContext) -> None:
        for room in ctx.problem.rooms:
            for slot in ctx.slots:
                ctx.at_most_one(ctx.room_terms(room.id, slot))


class RoomCapacity(UnaryConstraint):
    name = "room_capacity"

    def allows(self, lesson: Lesson, slot: TimeSlot, room: Room) -> bool:
        return not room.capacity or room.capacity >= lesson.group.size

    def explain(self, a: Assignment) -> str:
        return (
            f"Группа {a.lesson.group.name} ({a.lesson.group.size} чел.) "
            f"не помещается в ауд. {a.room.name} ({a.room.capacity} мест)"
        )


class RoomFeatures(UnaryConstraint):
    """Предмету с требованием нужен кабинет с этим оснащением, а специальные
    кабинеты (с любым оснащением) отданы только своим предметам — иначе
    математика уезжает в спортзал просто потому, что он свободен."""

    name = "room_features"

    def allows(self, lesson: Lesson, slot: TimeSlot, room: Room) -> bool:
        feature = lesson.subject.room_feature
        return feature in room.features if feature else not room.features

    def explain(self, a: Assignment) -> str:
        feature = a.lesson.subject.room_feature
        if feature:
            return f"{a.lesson.subject.name} требует «{feature}», а в ауд. {a.room.name} его нет"
        return f"{a.lesson.subject.name} занимает специальный кабинет {a.room.name}"


class Unavailable(UnaryConstraint):
    """Преподаватель или группа не может заниматься в указанные слоты."""

    name = "unavailable"

    def __init__(self, owner_id: str, slots: Iterable[TimeSlot], reason: str = ""):
        self.owner_id = owner_id
        self.slots = frozenset(slots)
        self.reason = reason

    def allows(self, lesson: Lesson, slot: TimeSlot, room: Room) -> bool:
        return slot not in self.slots or not lesson.involves(self.owner_id)

    def explain(self, a: Assignment) -> str:
        why = f" ({self.reason})" if self.reason else ""
        return f"{self.owner_id} недоступен в {a.slot}{why}: стоит {a.lesson}"


class Pinned(UnaryConstraint):
    """Занятие закреплено администратором за слотом (и, если задано, аудиторией)."""

    name = "pinned"

    def __init__(self, lesson_id: str, slot: TimeSlot, room_id: str | None = None):
        self.lesson_id = lesson_id
        self.slot = slot
        self.room_id = room_id

    def allows(self, lesson: Lesson, slot: TimeSlot, room: Room) -> bool:
        if lesson.id != self.lesson_id:
            return True
        return slot == self.slot and (self.room_id is None or room.id == self.room_id)

    def explain(self, a: Assignment) -> str:
        return f"{a.lesson} закреплено за {self.slot}, а стоит в {a.slot}"


class DailyLimit(Constraint):
    """Не больше limit занятий в день у каждого участника нужного типа; у отдельных
    участников лимит свой: overrides={"5a": 6} (по СанПиН младшим меньше)."""

    what = ""

    def __init__(self, limit: int, overrides: dict[str, int] | None = None):
        self.limit = limit
        self.overrides = overrides or {}

    def limit_for(self, owner_id: str) -> int:
        return self.overrides.get(owner_id, self.limit)

    def owner_ids(self, lessons: Iterable[Lesson]) -> set[str]:
        raise NotImplementedError

    def check(self, schedule: Schedule) -> list[Violation]:
        names = {
            o.id: o.name for a in schedule.assignments for o in (a.lesson.teacher, a.lesson.group)
        }
        violations = []
        for owner_id in sorted(self.owner_ids(a.lesson for a in schedule.assignments)):
            limit = self.limit_for(owner_id)
            for day, periods in schedule.periods_by_day(owner_id).items():
                if len(periods) > limit:
                    violations.append(
                        Violation(
                            self,
                            f"{self.what} {names[owner_id]}: {len(periods)} занятий "
                            f"в {DAY_NAMES[day]}, можно не больше {limit}",
                        )
                    )
        return violations

    def encode(self, ctx: CpSatContext) -> None:
        for owner_id in self.owner_ids(ctx.problem.lessons):
            limit = self.limit_for(owner_id)
            for day in ctx.days:
                terms = [t for s in ctx.day_slots(day) for t in ctx.lesson_terms(owner_id, s)]
                if len(terms) > limit:
                    ctx.model.add(sum(terms) <= limit)


class GroupDailyLimit(DailyLimit):
    name = "group_daily_limit"
    what = "Группа"

    def owner_ids(self, lessons: Iterable[Lesson]) -> set[str]:
        return {lesson.group.id for lesson in lessons}


class TeacherDailyLimit(DailyLimit):
    name = "teacher_daily_limit"
    what = "Преподаватель"

    def owner_ids(self, lessons: Iterable[Lesson]) -> set[str]:
        return {lesson.teacher.id for lesson in lessons}


def by_group_subject(lessons: Iterable[Lesson]) -> dict[tuple[str, str], list[Lesson]]:
    """Все часы одного предмета у одного класса."""
    groups: dict[tuple[str, str], list[Lesson]] = defaultdict(list)
    for lesson in lessons:
        groups[(lesson.group.id, lesson.subject.id)].append(lesson)
    return groups


class SubjectDailyLimit(Constraint):
    """Один предмет у класса не чаще limit раз в день; для отдельных предметов
    лимит свой: overrides={"pe": 1, "rus": 2}."""

    name = "subject_daily_limit"

    def __init__(self, limit: int = 2, overrides: dict[str, int] | None = None):
        self.limit = limit
        self.overrides = overrides or {}

    def limit_for(self, subject_id: str) -> int:
        return self.overrides.get(subject_id, self.limit)

    def check(self, schedule: Schedule) -> list[Violation]:
        counts = Counter(
            (a.lesson.group, a.lesson.subject, a.slot.day) for a in schedule.assignments
        )
        return [
            Violation(self, f"У {group.name} {subject.name} {n} раза в {DAY_NAMES[day]}")
            for (group, subject, day), n in counts.items()
            if n > self.limit_for(subject.id)
        ]

    def encode(self, ctx: CpSatContext) -> None:
        for (_, subject_id), lessons in by_group_subject(ctx.problem.lessons).items():
            limit = self.limit_for(subject_id)
            if len(lessons) <= limit:
                continue
            for day in ctx.days:
                terms = [ctx.at(lesson.id, s) for lesson in lessons for s in ctx.day_slots(day)]
                ctx.model.add(sum(terms) <= limit)


class HomeRoom(UnaryConstraint):
    """У класса свой кабинет: обычные уроки только там. Предметы со спецоснащением
    (физкультура, технология) идут в свои кабинеты — их разводит RoomFeatures."""

    name = "home_room"

    def __init__(self, group_id: str, room_id: str):
        self.group_id = group_id
        self.room_id = room_id

    def allows(self, lesson: Lesson, slot: TimeSlot, room: Room) -> bool:
        if lesson.group.id != self.group_id or lesson.subject.room_feature:
            return True
        return room.id == self.room_id

    def explain(self, a: Assignment) -> str:
        return f"{a.lesson.group.name} занимается в ауд. {a.room.name}, а не в своём кабинете"


class DoubleLessons(Constraint):
    """Сдвоенные уроки: если предмет в этот день есть, то ровно два часа подряд.

    Так обычно ставят технологию и ИЗО — за один урок не успеть.
    """

    name = "double_lessons"

    def __init__(self, subject_ids: Iterable[str]):
        self.subject_ids = frozenset(subject_ids)

    def check(self, schedule: Schedule) -> list[Violation]:
        days: dict[tuple, list[int]] = defaultdict(list)
        for a in schedule.assignments:
            if a.lesson.subject.id in self.subject_ids:
                days[(a.lesson.group, a.lesson.subject, a.slot.day)].append(a.slot.period)
        return [
            Violation(self, f"У {group.name} {subject.name} в {DAY_NAMES[day]} не сдвоен: {p}")
            for (group, subject, day), p in days.items()
            if len(p) != 2 or abs(p[0] - p[1]) != 1
        ]

    def encode(self, ctx: CpSatContext) -> None:
        for (_, subject_id), lessons in by_group_subject(ctx.problem.lessons).items():
            if subject_id not in self.subject_ids:
                continue
            for day in ctx.days:
                here = [sum(ctx.at(lesson.id, s) for lesson in lessons) for s in ctx.day_slots(day)]
                pair = ctx.model.new_bool_var(f"double[{lessons[0].id},{day}]")
                ctx.model.add(sum(here) == 2 * pair)
                # Два урока в один день, и никакие два не стоят через промежуток.
                for i in range(len(here)):
                    for j in range(i + 2, len(here)):
                        ctx.model.add(here[i] + here[j] <= 1)


DEFAULT_HARD_CONSTRAINTS: tuple[Constraint, ...] = (
    NoTeacherOverlap(),
    NoGroupOverlap(),
    NoRoomOverlap(),
    RoomCapacity(),
    RoomFeatures(),
)
