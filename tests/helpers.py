"""Общие помощники для тестов (conftest — только для фикстур)."""

from edtable.scheduler import SchedulingProblem, TimeSlot


def grid(days: int = 2, periods: int = 4) -> tuple[TimeSlot, ...]:
    return tuple(TimeSlot(d, p) for d in range(days) for p in range(1, periods + 1))


def with_rules(problem: SchedulingProblem, *constraints, bids=()) -> SchedulingProblem:
    return SchedulingProblem(
        problem.lessons,
        problem.rooms,
        problem.slots,
        problem.constraints + tuple(constraints),
        tuple(bids) or problem.bids,
    )
