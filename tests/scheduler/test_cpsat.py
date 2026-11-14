import pytest

from edtable.scheduler import (
    Bid,
    CpSatSolver,
    Group,
    Lesson,
    NoSolutionError,
    Room,
    Subject,
    Teacher,
    TimeSlot,
    run_auction,
    settle,
    validate,
)
from edtable.scheduler.auction import Offer
from edtable.scheduler.constraints import (
    DEFAULT_HARD_CONSTRAINTS,
    DoubleLessons,
    GroupGaps,
    HomeRoom,
    LateLessons,
    Pinned,
    SplitLessons,
    SubjectDailyLimit,
    TeacherGaps,
    Unavailable,
)
from edtable.scheduler.problem import SchedulingProblem
from edtable.scheduler.wishes import AnyOf, AvoidSlots, MaxDays, MaxPerDay, NoGaps
from helpers import grid, with_rules

solver = CpSatSolver(time_limit=10, workers=4)


def test_schedule_places_every_lesson_once_without_violations(school):
    result = solver.optimize(school)

    placed = sorted(a.lesson.id for a in result.schedule.assignments)
    assert placed == sorted(lesson.id for lesson in school.lessons)
    assert validate(result.schedule, school.constraints).is_valid
    assert result.optimal


def test_admin_rules_are_respected(school):
    problem = with_rules(
        school,
        Unavailable("rus_t", [s for s in school.slots if s.day == 1]),
        Pinned("g1-math-0", TimeSlot(1, 4), room_id="r2"),
    )

    schedule = solver.solve(problem)

    assert all(a.slot.day == 0 for a in schedule.for_owner("rus_t"))
    pinned = schedule.get("g1-math-0")
    assert (pinned.slot, pinned.room.id) == (TimeSlot(1, 4), "r2")
    assert validate(schedule, problem.constraints).is_valid


def test_objective_matches_what_the_schedule_actually_gives(school):
    """encode() и holds() каждого пожелания должны означать одно и то же."""
    monday = frozenset(s for s in school.slots if s.day == 0)
    offers = {
        "math_t": [
            Offer(AvoidSlots("math_t", frozenset({TimeSlot(0, 1)})), 8),
            Offer(NoGaps("math_t")),
        ],
        "rus_t": [
            Offer(AnyOf("rus_t", (AvoidSlots("rus_t", monday), MaxPerDay("rus_t", 1))), 6),
            Offer(MaxDays("rus_t", 1), 4),
        ],
        "g1": [Offer(NoGaps("g1"))],
    }
    problem = with_rules(
        school,
        GroupGaps(7),
        TeacherGaps(2),
        LateLessons(["math"], [4], weight=3),
        SplitLessons(4),
        bids=run_auction(offers),
    )
    fair = CpSatSolver(time_limit=10, workers=4, fairness=3)

    result = fair.optimize(problem)

    points = [acc.points for acc in settle(problem.bids, result.schedule).values()]
    penalty = validate(result.schedule, problem.constraints).penalty
    assert result.objective == sum(points) + 3 * min(points) - penalty


def test_new_hard_rules_hold_in_solved_schedule(school):
    problem = with_rules(
        school,
        HomeRoom("g1", "r1"),
        HomeRoom("g2", "r2"),
        DoubleLessons(["rus"]),
        SubjectDailyLimit(limit=1, overrides={"math": 2, "rus": 2}),
    )

    schedule = solver.solve(problem)

    assert validate(schedule, problem.constraints).is_valid
    assert {a.room.id for a in schedule.for_group(school.groups[0])} == {"r1"}


def test_wishes_win_when_nothing_stands_in_the_way(school):
    # 6 уроков математика в 6 оставшихся слотов — впритык, но можно.
    late = frozenset(s for s in school.slots if s.period == 4)
    problem = school.with_bids(run_auction({"math_t": [Offer(AvoidSlots("math_t", late))]}))

    schedule = solver.solve(problem)

    assert settle(problem.bids, schedule)["math_t"].points == 100


def test_fairness_does_not_let_one_person_lose_everything():
    """Учитель A хочет свободный понедельник, и тогда B и C обязаны работать в понедельник.

    Без справедливости выгоднее отдать B и C всё (200 очков), а A оставить ни с
    чем. С ней солвер выбирает 100 + 40 + 40: чуть меньше суммарно, зато никто
    не уходит с нулём.
    """
    # Два дня по два урока. У каждого класса урок A и два урока «своего» учителя:
    # если A уходит во вторник, второй вторничный слот класса один, и B (C)
    # обязательно получает урок в понедельник.
    a, b, c = Teacher("A", "A"), Teacher("B", "B"), Teacher("C", "C")
    g1, g2 = Group("g1", "1"), Group("g2", "2")
    subject = Subject("s", "Предмет")
    lessons = (
        Lesson("a1", subject, a, g1),
        Lesson("a2", subject, a, g2),
        Lesson("b1", subject, b, g1),
        Lesson("b2", subject, b, g1),
        Lesson("c1", subject, c, g2),
        Lesson("c2", subject, c, g2),
    )
    slots = grid(days=2, periods=2)
    monday = frozenset(s for s in slots if s.day == 0)
    bids = (
        Bid("A", AvoidSlots("A", monday), 100),
        Bid("B", AvoidSlots("B", monday), 60),
        Bid("B2", MaxDays("B", 2), 40),
        Bid("C", AvoidSlots("C", monday), 60),
        Bid("C2", MaxDays("C", 2), 40),
    )
    problem = SchedulingProblem(
        lessons, (Room("r1", "1"), Room("r2", "2")), slots, DEFAULT_HARD_CONSTRAINTS, bids
    )

    def points(fairness: int) -> dict[str, int]:
        schedule = CpSatSolver(time_limit=10, workers=2, fairness=fairness).solve(problem)
        return {owner: acc.points for owner, acc in settle(bids, schedule).items()}

    assert points(0) == {"A": 0, "B": 100, "C": 100}
    assert points(1) == {"A": 100, "B": 40, "C": 40}


def test_room_that_fits_nobody_is_explained(school):
    tiny = SchedulingProblem(
        school.lessons, (Room("c", "Каморка", 5),), school.slots, school.constraints
    )

    with pytest.raises(NoSolutionError, match="некуда встать.*room_capacity"):
        solver.solve(tiny)


def test_overloaded_teacher_is_explained(school):
    problem = with_rules(school, Unavailable("math_t", school.slots[:4]))

    with pytest.raises(NoSolutionError, match="Математик.*6 занятий.*4"):
        solver.solve(problem)
