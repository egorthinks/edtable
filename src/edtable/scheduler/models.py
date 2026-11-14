"""Предметная область: из чего строится расписание.

Все сущности неизменяемые (frozen), чтобы их можно было класть в множества и
использовать как ключи словарей.
"""

from dataclasses import dataclass, field

DAY_NAMES = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


@dataclass(frozen=True)
class Teacher:
    id: str
    name: str


@dataclass(frozen=True)
class Group:
    """Учебная группа (класс), у которой общее расписание."""

    id: str
    name: str
    size: int = 0


@dataclass(frozen=True)
class Room:
    id: str
    name: str
    # 0 — вместимость неизвестна, не ограничиваем.
    capacity: int = 0
    # Оснащение: "gym", "lab", "computers" и т.п.
    features: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class Subject:
    id: str
    name: str
    # Если задано, занятие можно провести только в аудитории с таким оснащением.
    room_feature: str | None = None


@dataclass(frozen=True, order=True)
class TimeSlot:
    """Ячейка сетки расписания: день недели (0 — понедельник) и номер урока с 1."""

    day: int
    period: int

    def __str__(self) -> str:
        return f"{DAY_NAMES[self.day]} {self.period}"


@dataclass(frozen=True)
class Lesson:
    """Одно занятие, которое нужно поставить в расписание.

    Если предмет идёт несколько раз в неделю, это несколько Lesson с разными id.
    """

    id: str
    subject: Subject
    teacher: Teacher
    group: Group

    def involves(self, owner_id: str) -> bool:
        """Касается ли занятие участника: преподавателя или группы."""
        return owner_id in (self.teacher.id, self.group.id)

    def __str__(self) -> str:
        return f"{self.subject.name} / {self.group.name} / {self.teacher.name}"


@dataclass(frozen=True)
class Assignment:
    """Занятие, поставленное в конкретное время и аудиторию."""

    lesson: Lesson
    slot: TimeSlot
    room: Room
