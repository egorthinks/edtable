"""Мягкие ограничения администратора: за каждое нарушение начисляется штраф.

Штраф измеряется в тех же очках, что и ставки участников, поэтому weight=15
означает «одно окно у класса стоит 15 очков чьих-то пожеланий».
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import TYPE_CHECKING

from edtable.scheduler.constraints.base import Constraint, Violation
from edtable.scheduler.constraints.hard import by_group_subject
from edtable.scheduler.models import DAY_NAMES, Lesson
from edtable.scheduler.schedule import Schedule

if TYPE_CHECKING:
    from edtable.scheduler.solvers.cpsat import CpSatContext


def count_gaps(periods: list[int]) -> int:
    """Окна — пустые уроки между первым и последним занятием дня."""
    if not periods:
        return 0
    return periods[-1] - periods[0] + 1 - len(set(periods))


class SoftConstraint(Constraint):
    hard = False
    # Как назвать нарушение в отчёте для человека.
    title = ""

    def __init__(self, weight: int):
        self.weight = weight


class _Gaps(SoftConstraint):
    def owners(self, lessons: Iterable[Lesson]) -> dict[str, str]:
        """id -> имя участников, чьи окна считаем."""
        raise NotImplementedError

    def check(self, schedule: Schedule) -> list[Violation]:
        violations = []
        for owner_id, name in sorted(self.owners(a.lesson for a in schedule.assignments).items()):
            for day, periods in schedule.periods_by_day(owner_id).items():
                for _ in range(count_gaps(periods)):
                    violations.append(Violation(self, f"Окно у {name} в {DAY_NAMES[day]}"))
        return violations

    def encode(self, ctx: CpSatContext):
        gaps = []
        for owner_id in self.owners(ctx.problem.lessons):
            for day in ctx.days:
                busy = [ctx.busy(owner_id, s) for s in ctx.day_slots(day)]
                for j in range(1, len(busy) - 1):
                    gap = ctx.model.new_bool_var(f"gap[{owner_id},{day},{j}]")
                    # Окно в j, если до и после есть занятия, а в j нет.
                    for i in range(j):
                        for k in range(j + 1, len(busy)):
                            ctx.model.add(gap >= busy[i] + busy[k] - busy[j] - 1)
                    gaps.append(gap)
        return sum(gaps)


class GroupGaps(_Gaps):
    name = "group_gaps"
    title = "окна у классов"

    def __init__(self, weight: int = 15):
        super().__init__(weight)

    def owners(self, lessons: Iterable[Lesson]) -> dict[str, str]:
        return {lesson.group.id: lesson.group.name for lesson in lessons}


class TeacherGaps(_Gaps):
    """Окна у учителей. Обычно штраф маленький: учителю окно неприятно, но это
    не так страшно, как детям, которых некуда деть между уроками."""

    name = "teacher_gaps"
    title = "окна у учителей"

    def __init__(self, weight: int = 3):
        super().__init__(weight)

    def owners(self, lessons: Iterable[Lesson]) -> dict[str, str]:
        return {lesson.teacher.id: lesson.teacher.name for lesson in lessons}


class LateLessons(SoftConstraint):
    """Трудные предметы не в конце дня (по СанПиН их ставят на 2-4 урок).

    Штраф за каждый такой урок в запрещённые часы.
    """

    name = "late_lessons"
    title = "трудные предметы в конце дня"

    def __init__(self, subject_ids: Iterable[str], periods: Iterable[int], weight: int = 5):
        super().__init__(weight)
        self.subject_ids = frozenset(subject_ids)
        self.periods = frozenset(periods)

    def check(self, schedule: Schedule) -> list[Violation]:
        return [
            Violation(self, f"{a.lesson.subject.name} у {a.lesson.group.name} {a.slot} урок", (a,))
            for a in schedule.assignments
            if a.lesson.subject.id in self.subject_ids and a.slot.period in self.periods
        ]

    def encode(self, ctx: CpSatContext):
        return sum(
            ctx.at(lesson.id, slot)
            for lesson in ctx.problem.lessons
            if lesson.subject.id in self.subject_ids
            for slot in ctx.slots
            if slot.period in self.periods
        )


class SplitLessons(SoftConstraint):
    """Один предмет дважды в день вразбивку («русский на 2 и на 6 уроке»).

    Если уж два урока в день, пусть идут подряд. Штраф за каждую пару уроков
    предмета в один день, между которыми есть другие уроки.
    """

    name = "split_lessons"
    title = "один предмет дважды в день вразбивку"

    def __init__(self, weight: int = 10):
        super().__init__(weight)

    def check(self, schedule: Schedule) -> list[Violation]:
        days: dict[tuple, list[int]] = defaultdict(list)
        for a in schedule.assignments:
            days[(a.lesson.group, a.lesson.subject, a.slot.day)].append(a.slot.period)
        return [
            Violation(self, f"{subject.name} у {group.name} в {DAY_NAMES[day]}: {p} и {q} урок")
            for (group, subject, day), periods in days.items()
            for i, p in enumerate(sorted(periods))
            for q in sorted(periods)[i + 1 :]
            if q - p > 1
        ]

    def encode(self, ctx: CpSatContext):
        splits = []
        for (group_id, subject_id), lessons in by_group_subject(ctx.problem.lessons).items():
            if len(lessons) < 2:
                continue
            for day in ctx.days:
                slots = ctx.day_slots(day)
                here = [sum(ctx.at(lesson.id, s) for lesson in lessons) for s in slots]
                for i in range(len(here)):
                    for j in range(i + 2, len(here)):
                        split = ctx.model.new_bool_var(f"split[{group_id},{subject_id},{day}]")
                        ctx.model.add(split >= here[i] + here[j] - 1)
                        splits.append(split)
        return sum(splits)
