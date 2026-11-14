from edtable.scheduler import Assignment, Schedule, TimeSlot
from edtable.scheduler.constraints import Pinned
from edtable.scheduler.wishes import AllOf, AnyOf, AvoidSlots, MaxDays, MaxPerDay, NoGaps
from helpers import with_rules


def placed(lessons, room, *slots):
    pairs = zip(lessons, slots, strict=True)
    return Schedule([Assignment(lesson, slot, room) for lesson, slot in pairs])


def test_avoid_slots(lessons, room):
    schedule = placed(lessons, room, TimeSlot(0, 1), TimeSlot(0, 2))

    assert AvoidSlots("t1", frozenset({TimeSlot(1, 1)})).holds(schedule)
    assert not AvoidSlots("t1", frozenset({TimeSlot(0, 2)})).holds(schedule)
    # Пожелание другого участника на чужие занятия не смотрит.
    assert AvoidSlots("t9", frozenset({TimeSlot(0, 2)})).holds(schedule)


def test_no_gaps(lessons, room):
    assert NoGaps("t1").holds(placed(lessons, room, TimeSlot(0, 2), TimeSlot(0, 3)))
    assert not NoGaps("t1").holds(placed(lessons, room, TimeSlot(0, 1), TimeSlot(0, 3)))
    # Разные дни — не окно.
    assert NoGaps("t1").holds(placed(lessons, room, TimeSlot(0, 1), TimeSlot(1, 4)))


def test_max_per_day_and_max_days(lessons, room):
    same_day = placed(lessons, room, TimeSlot(0, 1), TimeSlot(0, 2))
    two_days = placed(lessons, room, TimeSlot(0, 1), TimeSlot(1, 1))

    assert not MaxPerDay("t1", 1).holds(same_day)
    assert MaxPerDay("t1", 1).holds(two_days)
    assert MaxDays("t1", 1).holds(same_day)
    assert not MaxDays("t1", 1).holds(two_days)


def test_bundles(lessons, room):
    schedule = placed(lessons, room, TimeSlot(0, 1), TimeSlot(0, 2))
    free_monday = AvoidSlots("t1", frozenset({TimeSlot(0, 1), TimeSlot(0, 2)}))
    free_tuesday = AvoidSlots("t1", frozenset({TimeSlot(1, 1), TimeSlot(1, 2)}))

    assert AnyOf("t1", (free_monday, free_tuesday)).holds(schedule)
    assert not AllOf("t1", (free_monday, free_tuesday)).holds(schedule)


def test_impossible_wishes_are_detected(school):
    monday = frozenset(s for s in school.slots if s.day == 0)
    tuesday = frozenset(s for s in school.slots if s.day == 1)

    # У математика 6 уроков на 8 слотов.
    assert AvoidSlots("math_t", monday).impossible(school)
    assert AvoidSlots("math_t", frozenset({TimeSlot(0, 1)})).impossible(school) is None
    assert MaxPerDay("math_t", 2).impossible(school)
    assert MaxPerDay("math_t", 3).impossible(school) is None
    assert MaxDays("math_t", 1).impossible(school)
    assert AnyOf(
        "math_t", (AvoidSlots("math_t", monday), AvoidSlots("math_t", tuesday))
    ).impossible(school)

    pinned = with_rules(school, Pinned("g1-rus-0", TimeSlot(0, 1)))
    assert AvoidSlots("rus_t", frozenset({TimeSlot(0, 1)})).impossible(pinned)
