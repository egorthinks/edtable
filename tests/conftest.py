import pytest

from edtable.scheduler import (
    Group,
    Lesson,
    Room,
    SchedulingProblem,
    Subject,
    Teacher,
    TimeSlot,
)
from edtable.scheduler.constraints import DEFAULT_HARD_CONSTRAINTS
from helpers import grid


@pytest.fixture
def teacher():
    return Teacher(id="t1", name="Иванова А. П.")


@pytest.fixture
def group():
    return Group(id="g1", name="10А", size=25)


@pytest.fixture
def room():
    return Room(id="r1", name="101", capacity=30)


@pytest.fixture
def lessons(teacher, group):
    math = Subject(id="s1", name="Математика")
    physics = Subject(id="s2", name="Физика")
    return (
        Lesson(id="l1", subject=math, teacher=teacher, group=group),
        Lesson(id="l2", subject=physics, teacher=teacher, group=group),
    )


@pytest.fixture
def monday_first():
    return TimeSlot(day=0, period=1)


@pytest.fixture
def monday_second():
    return TimeSlot(day=0, period=2)


@pytest.fixture
def school():
    """Маленькая школа: два учителя, два класса, два дня по четыре урока.

    У каждого класса 3 математики и 2 русского — 5 уроков на 8 слотов, так что
    простор для пожеланий есть, но не бесконечный.
    """
    math_t = Teacher("math_t", "Математик")
    rus_t = Teacher("rus_t", "Русист")
    math, rus = Subject("math", "Математика"), Subject("rus", "Русский")
    lessons = []
    for g in (Group("g1", "5А", 20), Group("g2", "5Б", 20)):
        lessons += [Lesson(f"{g.id}-math-{i}", math, math_t, g) for i in range(3)]
        lessons += [Lesson(f"{g.id}-rus-{i}", rus, rus_t, g) for i in range(2)]
    return SchedulingProblem(
        lessons=tuple(lessons),
        rooms=(Room("r1", "101", 30), Room("r2", "102", 30)),
        slots=grid(),
        constraints=DEFAULT_HARD_CONSTRAINTS,
    )
