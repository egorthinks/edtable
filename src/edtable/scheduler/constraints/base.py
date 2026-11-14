from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from edtable.scheduler.models import Assignment, Lesson, Room, TimeSlot

if TYPE_CHECKING:
    from edtable.scheduler.schedule import Schedule
    from edtable.scheduler.solvers.cpsat import CpSatContext


@dataclass(frozen=True)
class Violation:
    constraint: Constraint
    message: str
    assignments: tuple[Assignment, ...] = ()


class Constraint(ABC):
    """Правило расписания.

    У каждого правила две стороны: check() проверяет готовое расписание, encode()
    переводит правило в модель CP-SAT. Обе живут рядом, чтобы смысл правила был
    описан в одном месте, а тесты могли сверять одно с другим.
    """

    name: str = ""
    hard: bool = True
    # Штраф за одно нарушение, имеет смысл только для мягких ограничений.
    weight: int = 1

    @abstractmethod
    def check(self, schedule: Schedule) -> list[Violation]: ...

    def encode(self, ctx: CpSatContext):
        """Жёсткое правило добавляет ограничения в модель и ничего не возвращает.

        Мягкое возвращает линейное выражение — число нарушений, — его солвер
        умножит на weight и вычтет из целевой функции.
        """
        raise NotImplementedError(f"{type(self).__name__} не поддерживает CP-SAT")


class UnaryConstraint(Constraint):
    """Правило про одно занятие само по себе: куда его вообще можно ставить.

    Солвер не создаёт переменных для запрещённых вариантов, поэтому encode()
    здесь пустой — это заметно уменьшает модель.
    """

    @abstractmethod
    def allows(self, lesson: Lesson, slot: TimeSlot, room: Room) -> bool: ...

    def explain(self, assignment: Assignment) -> str:
        return (
            f"{assignment.lesson} нельзя ставить в {assignment.slot}, ауд. {assignment.room.name}"
        )

    def check(self, schedule: Schedule) -> list[Violation]:
        return [
            Violation(self, self.explain(a), (a,))
            for a in schedule.assignments
            if not self.allows(a.lesson, a.slot, a.room)
        ]

    def encode(self, ctx: CpSatContext) -> None:
        pass
