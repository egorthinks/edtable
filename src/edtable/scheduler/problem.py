"""Входные данные для алгоритма."""

from collections import Counter
from dataclasses import dataclass
from functools import cached_property

from edtable.scheduler.constraints import Constraint, DailyLimit, Pinned, UnaryConstraint
from edtable.scheduler.exceptions import InvalidProblemError
from edtable.scheduler.models import Group, Lesson, Room, Teacher, TimeSlot
from edtable.scheduler.wishes import Bid


def _duplicates(values) -> list:
    return [value for value, n in Counter(values).items() if n > 1]


@dataclass(frozen=True)
class SchedulingProblem:
    """Всё, что алгоритм получает на вход: что поставить, куда, по каким правилам
    и чего хотят участники."""

    lessons: tuple[Lesson, ...]
    rooms: tuple[Room, ...]
    slots: tuple[TimeSlot, ...]
    constraints: tuple[Constraint, ...] = ()
    bids: tuple[Bid, ...] = ()

    def __post_init__(self):
        errors = []
        if self.lessons and not (self.rooms and self.slots):
            errors.append("есть занятия, но нет аудиторий или слотов")

        for what, ids in (
            ("занятий", [lesson.id for lesson in self.lessons]),
            ("аудиторий", [room.id for room in self.rooms]),
            ("ставок", [bid.id for bid in self.bids]),
            ("слотов", self.slots),
        ):
            if dup := _duplicates(ids):
                errors.append(f"повторяются id {what}: {dup}")

        # Преподаватели и группы делят одно пространство id: и те и другие — участники.
        owners = {o for lesson in self.lessons for o in (lesson.teacher, lesson.group)}
        if dup := _duplicates(o.id for o in owners):
            errors.append(f"один id у разных участников или под одним id разные данные: {dup}")

        # Окна и «подряд» считаются по номерам уроков, поэтому дырок в сетке быть не должно.
        for day in self.days:
            periods = [s.period for s in self.day_slots(day)]
            if periods != list(range(periods[0], periods[0] + len(periods))):
                errors.append(f"в дне {day} номера уроков идут не подряд: {periods}")

        owner_ids = {o.id for o in owners}
        for bid in self.bids:
            if bid.owner not in owner_ids:
                errors.append(f"ставка {bid.id} от неизвестного участника {bid.owner}")
            if bid.points < 0:
                errors.append(f"ставка {bid.id} отрицательная")

        if errors:
            raise InvalidProblemError("; ".join(errors))

    @cached_property
    def teachers(self) -> tuple[Teacher, ...]:
        return tuple(sorted({lesson.teacher for lesson in self.lessons}, key=lambda t: t.id))

    @cached_property
    def groups(self) -> tuple[Group, ...]:
        return tuple(sorted({lesson.group for lesson in self.lessons}, key=lambda g: g.id))

    @cached_property
    def days(self) -> tuple[int, ...]:
        return tuple(sorted({slot.day for slot in self.slots}))

    def day_slots(self, day: int) -> list[TimeSlot]:
        return sorted(slot for slot in self.slots if slot.day == day)

    def lessons_of(self, owner_id: str) -> list[Lesson]:
        return [lesson for lesson in self.lessons if lesson.involves(owner_id)]

    def owner_name(self, owner_id: str) -> str:
        for owner in (*self.teachers, *self.groups):
            if owner.id == owner_id:
                return owner.name
        return owner_id

    def open_slots(self, owner_id: str) -> set[TimeSlot]:
        """Слоты, где у участника вообще может стоять хоть одно его занятие."""
        unary = [c for c in self.constraints if isinstance(c, UnaryConstraint)]
        lessons = self.lessons_of(owner_id)
        return {
            slot
            for slot in self.slots
            if any(
                all(c.allows(lesson, slot, room) for c in unary)
                for lesson in lessons
                for room in self.rooms
            )
        }

    def pinned_slots(self, owner_id: str) -> set[TimeSlot]:
        lessons = {lesson.id for lesson in self.lessons_of(owner_id)}
        return {
            c.slot for c in self.constraints if isinstance(c, Pinned) and c.lesson_id in lessons
        }

    def daily_capacity(self, owner_id: str) -> int:
        """Сколько занятий участнику можно поставить в день по жёстким правилам."""
        periods = max((len(self.day_slots(d)) for d in self.days), default=0)
        limits = [
            c.limit_for(owner_id)
            for c in self.constraints
            if isinstance(c, DailyLimit) and owner_id in c.owner_ids(self.lessons)
        ]
        return min([periods, *limits])

    def bids_of(self, owner_id: str) -> list[Bid]:
        return [bid for bid in self.bids if bid.owner == owner_id]

    @property
    def participants(self) -> list[str]:
        """Участники, у которых есть хотя бы одна ставка."""
        return sorted({bid.owner for bid in self.bids})

    def with_bids(self, bids) -> "SchedulingProblem":
        return SchedulingProblem(
            self.lessons, self.rooms, self.slots, self.constraints, tuple(bids)
        )
