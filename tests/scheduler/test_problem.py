import pytest

from edtable.scheduler import Bid, Group, InvalidProblemError, Lesson, SchedulingProblem, TimeSlot
from edtable.scheduler.wishes import NoGaps

SLOTS = (TimeSlot(0, 1), TimeSlot(0, 2))


def test_valid_problem_exposes_participants(lessons, room):
    problem = SchedulingProblem(lessons, (room,), SLOTS, bids=(Bid("b", NoGaps("t1"), 100),))

    assert [t.id for t in problem.teachers] == ["t1"]
    assert [g.id for g in problem.groups] == ["g1"]
    assert problem.participants == ["t1"]


def test_duplicate_lesson_ids(lessons, room):
    with pytest.raises(InvalidProblemError, match="занятий"):
        SchedulingProblem((lessons[0], lessons[0]), (room,), SLOTS)


def test_teacher_and_group_cannot_share_an_id(lessons, room, teacher):
    clash = Lesson("l9", lessons[0].subject, teacher, Group("t1", "Группа-однофамилец"))

    with pytest.raises(InvalidProblemError, match="t1"):
        SchedulingProblem((*lessons, clash), (room,), SLOTS)


def test_grid_without_holes(lessons, room):
    with pytest.raises(InvalidProblemError, match="не подряд"):
        SchedulingProblem(lessons, (room,), (TimeSlot(0, 1), TimeSlot(0, 3)))


def test_bid_from_stranger(lessons, room):
    with pytest.raises(InvalidProblemError, match="неизвестного"):
        SchedulingProblem(lessons, (room,), SLOTS, bids=(Bid("b", NoGaps("nobody"), 100),))
