"""Результат работы алгоритма."""

from collections import defaultdict
from dataclasses import dataclass, field

from edtable.scheduler.models import Assignment, Group, Room, Teacher, TimeSlot


@dataclass
class Schedule:
    assignments: list[Assignment] = field(default_factory=list)

    def add(self, assignment: Assignment) -> None:
        self.assignments.append(assignment)

    def for_group(self, group: Group) -> list[Assignment]:
        return [a for a in self.assignments if a.lesson.group == group]

    def for_teacher(self, teacher: Teacher) -> list[Assignment]:
        return [a for a in self.assignments if a.lesson.teacher == teacher]

    def for_room(self, room: Room) -> list[Assignment]:
        return [a for a in self.assignments if a.room == room]

    def for_owner(self, owner_id: str) -> list[Assignment]:
        return [a for a in self.assignments if a.lesson.involves(owner_id)]

    def get(self, lesson_id: str) -> Assignment | None:
        return next((a for a in self.assignments if a.lesson.id == lesson_id), None)

    def at(self, slot: TimeSlot) -> list[Assignment]:
        return [a for a in self.assignments if a.slot == slot]

    def periods_by_day(self, owner_id: str) -> dict[int, list[int]]:
        """Номера занятых уроков участника по дням, отсортированные."""
        days: dict[int, list[int]] = defaultdict(list)
        for a in self.for_owner(owner_id):
            days[a.slot.day].append(a.slot.period)
        return {day: sorted(periods) for day, periods in days.items()}

    def copy(self) -> "Schedule":
        return Schedule(list(self.assignments))

    def moved_since(self, before: "Schedule") -> list[tuple[Assignment, Assignment]]:
        """Пары (было, стало) для занятий, у которых поменялось время или аудитория."""
        old = {a.lesson.id: a for a in before.assignments}
        return [
            (old[a.lesson.id], a)
            for a in self.assignments
            if a.lesson.id in old and old[a.lesson.id] != a
        ]
