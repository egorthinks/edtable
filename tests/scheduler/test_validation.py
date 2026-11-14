from edtable.scheduler import Assignment, Schedule, validate
from edtable.scheduler.constraints import (
    DEFAULT_HARD_CONSTRAINTS,
    NoGroupOverlap,
    NoRoomOverlap,
    NoTeacherOverlap,
)


def test_empty_schedule_is_valid():
    report = validate(Schedule(), DEFAULT_HARD_CONSTRAINTS)

    assert report.is_valid
    assert report.penalty == 0


def test_lessons_in_different_slots_are_valid(lessons, room, monday_first, monday_second):
    schedule = Schedule(
        [
            Assignment(lessons[0], monday_first, room),
            Assignment(lessons[1], monday_second, room),
        ]
    )

    assert validate(schedule, DEFAULT_HARD_CONSTRAINTS).is_valid


def test_lessons_in_same_slot_clash_everywhere(lessons, room, monday_first):
    # Оба занятия у одного преподавателя, одной группы и в одной аудитории,
    # поэтому ломаются все три ограничения сразу.
    schedule = Schedule(
        [
            Assignment(lessons[0], monday_first, room),
            Assignment(lessons[1], monday_first, room),
        ]
    )

    report = validate(schedule, DEFAULT_HARD_CONSTRAINTS)

    assert not report.is_valid
    broken = {type(v.constraint) for v in report.hard_violations}
    assert broken == {NoTeacherOverlap, NoGroupOverlap, NoRoomOverlap}
