"""Биржа на крошечной задаче, где всё видно глазами.

Один класс, два учителя, понедельник из трёх уроков:
    1 — урок учителя A, 2 — урок учителя B, 3 — свободно.
"""

import pytest

from edtable.scheduler import (
    Assignment,
    Bid,
    CpSatSolver,
    Exchange,
    Group,
    Lesson,
    MoveRequest,
    Room,
    Schedule,
    SchedulingProblem,
    Subject,
    Teacher,
    TimeSlot,
)
from edtable.scheduler.constraints import DEFAULT_HARD_CONSTRAINTS, GroupGaps
from edtable.scheduler.wishes import AvoidSlots

MON1, MON2, MON3 = TimeSlot(0, 1), TimeSlot(0, 2), TimeSlot(0, 3)
group = Group("g", "5А", 20)
room = Room("r", "101", 30)
a_lesson = Lesson("a", Subject("m", "Математика"), Teacher("A", "Учитель A"), group)
b_lesson = Lesson("b", Subject("r", "Русский"), Teacher("B", "Учитель B"), group)


def make_exchange(*extra, bids=(), **kwargs) -> Exchange:
    problem = SchedulingProblem(
        (a_lesson, b_lesson), (room,), (MON1, MON2, MON3), DEFAULT_HARD_CONSTRAINTS + extra, bids
    )
    schedule = Schedule([Assignment(a_lesson, MON1, room), Assignment(b_lesson, MON2, room)])
    return Exchange(problem, schedule, solver=CpSatSolver(time_limit=5, workers=2), **kwargs)


def slots(exchange: Exchange) -> dict[str, TimeSlot]:
    return {a.lesson.id: a.slot for a in exchange.schedule.assignments}


def b_avoids(*avoid) -> tuple[Bid, ...]:
    return (Bid("B#1", AvoidSlots("B", frozenset(avoid)), 100),)


def test_move_to_free_slot():
    exchange = make_exchange()

    deal = exchange.submit(MoveRequest("A", "a", MON3))

    assert deal.accepted and deal.reason == "перенос"
    assert slots(exchange) == {"a": MON3, "b": MON2}


def test_plain_swap_asks_the_other_side():
    exchange = make_exchange()

    deal = exchange.submit(MoveRequest("A", "a", MON2))

    assert deal.accepted and deal.reason == "обмен местами"
    assert deal.offer.counterparties == ["B"]
    assert slots(exchange) == {"a": MON2, "b": MON1}


def test_swap_that_hurts_the_other_side_becomes_a_shift():
    # B выиграл «не ставить на 1 урок», поэтому обмен местами нельзя,
    # но можно отправить его урок на третий.
    exchange = make_exchange(bids=b_avoids(MON1))

    deal = exchange.submit(MoveRequest("A", "a", MON2))

    assert deal.accepted and deal.reason == "обмен со сдвигом"
    assert slots(exchange) == {"a": MON2, "b": MON3}
    assert deal.offer.delta == {"B": 0}


def test_nobody_but_the_requester_loses_points():
    exchange = make_exchange(bids=b_avoids(MON1, MON3))

    deal = exchange.submit(MoveRequest("A", "a", MON2))

    assert not deal.accepted
    assert "пострадает Учитель B" in deal.reason
    assert slots(exchange) == {"a": MON1, "b": MON2}


def test_other_side_can_refuse():
    exchange = make_exchange(consent=lambda owner, offer: False)

    deal = exchange.submit(MoveRequest("A", "a", MON2))

    assert not deal.accepted and "не согласен" in deal.reason


def test_move_that_opens_a_gap_is_fixed_by_reshuffle():
    # Если B уйдёт на 3 урок, у класса появится окно; солвер подтягивает урок A.
    exchange = make_exchange(GroupGaps(10))

    deal = exchange.submit(MoveRequest("B", "b", MON3))

    assert deal.accepted and deal.reason == "перестановка"
    assert slots(exchange) == {"a": MON2, "b": MON3}
    assert deal.offer.counterparties == ["A"]


def test_reshuffle_size_is_capped():
    # Та же ситуация с окном, но сдвигать можно только одно занятие — сам урок B.
    exchange = make_exchange(GroupGaps(10), max_moves=1)

    deal = exchange.submit(MoveRequest("B", "b", MON3))

    assert not deal.accepted and "больше 1 уроков" in deal.reason


def test_requester_must_actually_leave_the_old_slot():
    # Второй урок того же учителя в том же классе: формально «обмен местами»
    # возможен, но учитель так и остаётся занят на 1 уроке — это не сделка.
    twin = Lesson("a2", a_lesson.subject, a_lesson.teacher, group)
    problem = SchedulingProblem(
        (a_lesson, twin, b_lesson), (room,), (MON1, MON2, MON3), DEFAULT_HARD_CONSTRAINTS
    )
    schedule = Schedule(
        [
            Assignment(a_lesson, MON1, room),
            Assignment(twin, MON2, room),
            Assignment(b_lesson, MON3, room),
        ]
    )
    exchange = Exchange(problem, schedule, solver=CpSatSolver(time_limit=5, workers=2))

    deal = exchange.submit(MoveRequest("A", "a", MON2))

    assert not deal.accepted and "такое же занятие" in deal.reason


def test_best_option_for_the_requester_wins():
    # A готов на 2 или 3 урок, но 2 стоит ему ставки «не ставить на 2 урок».
    exchange = make_exchange(bids=(Bid("A#1", AvoidSlots("A", frozenset({MON2})), 100),))

    deal = exchange.submit_best([MoveRequest("A", "a", MON2), MoveRequest("A", "a", MON3)])

    assert deal.accepted and deal.request.target == MON3
    assert slots(exchange) == {"a": MON3, "b": MON2}


@pytest.mark.parametrize(
    ("request_", "reason"),
    [
        (MoveRequest("B", "a", MON3), "только свои"),
        (MoveRequest("A", "a", MON1), "уже стоит"),
        (MoveRequest("A", "a", TimeSlot(4, 1)), "нет в сетке"),
        (MoveRequest("A", "zzz", MON3), "нет занятия"),
    ],
)
def test_bad_requests(request_, reason):
    deal = make_exchange().submit(request_)

    assert not deal.accepted and reason in deal.reason
