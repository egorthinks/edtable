"""Пожелания участников и ставки на них.

Пожелание (Wish) — условие на расписание одного участника: преподавателя или
группы. Ставка (Bid) — сколько очков участник готов отдать за это условие.
Ставка выигрывается целиком или не выигрывается вовсе: «свободная пятница с
одним уроком» — это не свободная пятница.

Как и у ограничений, у пожелания две стороны: holds() проверяет готовое
расписание, encode() возвращает булеву переменную CP-SAT, из которой следует
выполнение условия. Обратная импликация не нужна: солвер сам выставит
переменную в 1, если это выгодно и возможно.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from edtable.scheduler.constraints.soft import count_gaps
from edtable.scheduler.models import DAY_NAMES, TimeSlot
from edtable.scheduler.schedule import Schedule

if TYPE_CHECKING:
    from ortools.sat.python.cp_model import IntVar

    from edtable.scheduler.problem import SchedulingProblem
    from edtable.scheduler.solvers.cpsat import CpSatContext


class Wish(ABC):
    owner: str

    @abstractmethod
    def holds(self, schedule: Schedule) -> bool: ...

    @abstractmethod
    def encode(self, ctx: CpSatContext) -> IntVar: ...

    @abstractmethod
    def describe(self) -> str: ...

    def impossible(self, problem: SchedulingProblem) -> str | None:
        """Причина, по которой пожелание невыполнимо при любых раскладах, или None.

        Это дешёвая проверка на счётах, а не полное доказательство: ловит то,
        что видно сразу, — чтобы не сжигать на такую ставку очки участника.
        """
        return None

    def _flag(self, ctx: CpSatContext) -> IntVar:
        return ctx.model.new_bool_var(f"wish_{self.owner}_{type(self).__name__}")


def _ranges(numbers: list[int], names=None) -> str:
    """[1, 2, 3, 5] -> «1-3, 5». names превращает числа в подписи (дни недели)."""
    name = names.__getitem__ if names else str
    chunks, start = [], None
    for i, n in enumerate(numbers):
        start = n if start is None else start
        if i + 1 == len(numbers) or numbers[i + 1] != n + 1:
            chunks.append(name(start) if start == n else f"{name(start)}-{name(n)}")
            start = None
    return ", ".join(chunks)


def _format_slots(slots: Iterable[TimeSlot]) -> str:
    """Дни с одинаковым набором уроков склеиваются: «пн-пт: 1; ср: 5-6»."""
    by_day: dict[int, list[int]] = {}
    for slot in sorted(slots):
        by_day.setdefault(slot.day, []).append(slot.period)
    by_periods: dict[tuple[int, ...], list[int]] = {}
    for day, periods in by_day.items():
        by_periods.setdefault(tuple(periods), []).append(day)
    return "; ".join(
        f"{_ranges(days, DAY_NAMES)}: {_ranges(list(periods))}"
        for periods, days in by_periods.items()
    )


@dataclass(frozen=True)
class AvoidSlots(Wish):
    """Ни одного занятия в этих слотах. Свободный день — частный случай."""

    owner: str
    slots: frozenset[TimeSlot]
    label: str = ""

    def holds(self, schedule: Schedule) -> bool:
        return not any(a.slot in self.slots for a in schedule.for_owner(self.owner))

    def encode(self, ctx: CpSatContext) -> IntVar:
        flag = self._flag(ctx)
        for slot in self.slots:
            ctx.model.add_implication(flag, ~ctx.busy(self.owner, slot))
        return flag

    def describe(self) -> str:
        return self.label or f"не ставить: {_format_slots(self.slots)}"

    def impossible(self, problem: SchedulingProblem) -> str | None:
        if pinned := problem.pinned_slots(self.owner) & self.slots:
            return f"администратор закрепил занятие на {_format_slots(pinned)}"
        lessons = len(problem.lessons_of(self.owner))
        left = len(problem.open_slots(self.owner) - self.slots)
        if lessons > left:
            return f"{lessons} занятий не помещаются в оставшиеся {left} слотов"
        return None


@dataclass(frozen=True)
class NoGaps(Wish):
    owner: str

    def holds(self, schedule: Schedule) -> bool:
        return all(count_gaps(p) == 0 for p in schedule.periods_by_day(self.owner).values())

    def encode(self, ctx: CpSatContext) -> IntVar:
        flag = self._flag(ctx)
        for day in ctx.days:
            busy = [ctx.busy(self.owner, s) for s in ctx.day_slots(day)]
            for i in range(len(busy)):
                for j in range(i + 1, len(busy)):
                    for k in range(j + 1, len(busy)):
                        ctx.model.add(busy[i] + busy[k] - busy[j] <= 1).only_enforce_if(flag)
        return flag

    def describe(self) -> str:
        return "без окон"


@dataclass(frozen=True)
class MaxPerDay(Wish):
    owner: str
    limit: int

    def holds(self, schedule: Schedule) -> bool:
        counts = Counter(a.slot.day for a in schedule.for_owner(self.owner))
        return all(n <= self.limit for n in counts.values())

    def encode(self, ctx: CpSatContext) -> IntVar:
        flag = self._flag(ctx)
        for day in ctx.days:
            day_load = sum(ctx.busy(self.owner, s) for s in ctx.day_slots(day))
            ctx.model.add(day_load <= self.limit).only_enforce_if(flag)
        return flag

    def describe(self) -> str:
        return f"не больше {self.limit} занятий в день"

    def impossible(self, problem: SchedulingProblem) -> str | None:
        lessons, days = len(problem.lessons_of(self.owner)), len(problem.days)
        if lessons > self.limit * days:
            return f"{lessons} занятий за {days} дней — это больше {self.limit} в день"
        return None


@dataclass(frozen=True)
class MaxDays(Wish):
    owner: str
    limit: int

    def holds(self, schedule: Schedule) -> bool:
        return len({a.slot.day for a in schedule.for_owner(self.owner)}) <= self.limit

    def encode(self, ctx: CpSatContext) -> IntVar:
        flag = self._flag(ctx)
        working = sum(ctx.day_busy(self.owner, day) for day in ctx.days)
        ctx.model.add(working <= self.limit).only_enforce_if(flag)
        return flag

    def describe(self) -> str:
        return f"не больше {self.limit} рабочих дней"

    def impossible(self, problem: SchedulingProblem) -> str | None:
        lessons, per_day = len(problem.lessons_of(self.owner)), problem.daily_capacity(self.owner)
        if lessons > self.limit * per_day:
            return f"{lessons} занятий не уложить в {self.limit} дн. по {per_day}"
        return None


@dataclass(frozen=True)
class AnyOf(Wish):
    """Связка «или»: достаточно выполнить хотя бы одно из условий."""

    owner: str
    parts: tuple[Wish, ...]

    def holds(self, schedule: Schedule) -> bool:
        return any(p.holds(schedule) for p in self.parts)

    def encode(self, ctx: CpSatContext) -> IntVar:
        flag = self._flag(ctx)
        ctx.model.add_bool_or([p.encode(ctx) for p in self.parts]).only_enforce_if(flag)
        return flag

    def describe(self) -> str:
        return " ИЛИ ".join(f"({p.describe()})" for p in self.parts)

    def impossible(self, problem: SchedulingProblem) -> str | None:
        reasons = [p.impossible(problem) for p in self.parts]
        return "; ".join(reasons) if all(reasons) else None


@dataclass(frozen=True)
class AllOf(Wish):
    """Связка «и»: условия нужны только вместе, по отдельности ничего не стоят."""

    owner: str
    parts: tuple[Wish, ...]

    def holds(self, schedule: Schedule) -> bool:
        return all(p.holds(schedule) for p in self.parts)

    def encode(self, ctx: CpSatContext) -> IntVar:
        flag = self._flag(ctx)
        for part in self.parts:
            ctx.model.add_implication(flag, part.encode(ctx))
        return flag

    def describe(self) -> str:
        return " И ".join(f"({p.describe()})" for p in self.parts)

    def impossible(self, problem: SchedulingProblem) -> str | None:
        return next((r for p in self.parts if (r := p.impossible(problem))), None)


@dataclass(frozen=True)
class Bid:
    id: str
    wish: Wish
    points: int
    # Исходная фраза участника, чтобы человеку было понятно, откуда ставка.
    text: str = ""

    @property
    def owner(self) -> str:
        return self.wish.owner
