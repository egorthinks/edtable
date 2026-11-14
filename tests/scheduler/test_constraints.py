from edtable.scheduler import Assignment, Group, Lesson, Room, Schedule, Subject, TimeSlot, validate
from edtable.scheduler.constraints import (
    DoubleLessons,
    GroupDailyLimit,
    GroupGaps,
    HomeRoom,
    LateLessons,
    Pinned,
    RoomCapacity,
    RoomFeatures,
    SplitLessons,
    SubjectDailyLimit,
    TeacherGaps,
    Unavailable,
)


def day_of(lessons, room, periods, day=0):
    return Schedule(
        [
            Assignment(lesson, TimeSlot(day, p), room)
            for lesson, p in zip(lessons, periods, strict=True)
        ]
    )


def test_home_room_applies_to_plain_lessons_of_that_class(teacher, group, monday_first):
    home, other = Room("201", "201"), Room("202", "202")
    gym = Room("gym", "Спортзал", features=frozenset({"gym"}))
    math = Lesson("m", Subject("m", "Математика"), teacher, group)
    pe = Lesson("pe", Subject("pe", "Физкультура", "gym"), teacher, group)
    stranger = Lesson("x", Subject("m", "Математика"), teacher, Group("g2", "11Б"))
    rule = HomeRoom("g1", "201")

    assert rule.allows(math, monday_first, home)
    assert not rule.allows(math, monday_first, other)
    assert rule.allows(pe, monday_first, gym)
    assert rule.allows(stranger, monday_first, other)


def test_subject_limit_can_differ_per_subject(teacher, group, room):
    pe, rus = Subject("pe", "Физкультура"), Subject("rus", "Русский")
    two_pe = [Lesson(f"pe{i}", pe, teacher, group) for i in range(2)]
    two_rus = [Lesson(f"r{i}", rus, teacher, group) for i in range(2)]
    rule = SubjectDailyLimit(limit=2, overrides={"pe": 1})

    assert not validate(day_of(two_pe, room, [1, 2]), [rule]).is_valid
    assert validate(day_of(two_rus, room, [1, 2]), [rule]).is_valid


def test_double_lessons_must_be_adjacent_pairs(teacher, group, room):
    tech = Subject("tech", "Технология")
    pair = [Lesson(f"t{i}", tech, teacher, group) for i in range(2)]
    rule = [DoubleLessons(["tech"])]

    assert validate(day_of(pair, room, [3, 4]), rule).is_valid
    assert not validate(day_of(pair, room, [1, 3]), rule).is_valid
    split_days = Schedule(
        [Assignment(pair[0], TimeSlot(0, 1), room), Assignment(pair[1], TimeSlot(1, 1), room)]
    )
    assert not validate(split_days, rule).is_valid


def test_teacher_gaps(lessons, room):
    report = validate(day_of(lessons, room, [1, 3]), [TeacherGaps(weight=3)])

    assert report.penalty == 3 and report.is_valid


def test_late_lessons_only_for_listed_subjects(lessons, room):
    report = validate(day_of(lessons, room, [6, 7]), [LateLessons(["s1"], [6, 7], weight=5)])

    assert report.penalty == 5  # математика на 6-м, физика не в списке


def test_split_lessons(teacher, group, room):
    rus = Subject("rus", "Русский")
    two = [Lesson(f"r{i}", rus, teacher, group) for i in range(2)]

    assert validate(day_of(two, room, [2, 3]), [SplitLessons(10)]).penalty == 0
    assert validate(day_of(two, room, [2, 6]), [SplitLessons(10)]).penalty == 10


def test_room_capacity_rejects_too_small_room(lessons, monday_first):
    closet = Room("c", "Каморка", capacity=10)

    report = validate(Schedule([Assignment(lessons[0], monday_first, closet)]), [RoomCapacity()])

    assert not report.is_valid
    assert "не помещается" in report.hard_violations[0].message


def test_special_rooms_are_reserved_for_their_subjects(teacher, group, monday_first):
    gym = Room("gym", "Спортзал", 60, frozenset({"gym"}))
    plain = Room("101", "101", 30)
    pe = Lesson("pe", Subject("pe", "Физкультура", room_feature="gym"), teacher, group)
    math = Lesson("m", Subject("m", "Математика"), teacher, group)
    rule = RoomFeatures()

    assert rule.allows(pe, monday_first, gym)
    assert not rule.allows(pe, monday_first, plain)
    assert not rule.allows(math, monday_first, gym)
    assert rule.allows(math, monday_first, plain)


def test_unavailable_applies_to_teacher_and_group(lessons, room, monday_first, monday_second):
    teacher_busy = Unavailable("t1", [monday_first])
    group_busy = Unavailable("g1", [monday_first])

    for rule in (teacher_busy, group_busy):
        assert not rule.allows(lessons[0], monday_first, room)
        assert rule.allows(lessons[0], monday_second, room)


def test_pinned_lesson_only_fits_its_slot_and_room(lessons, room, monday_first, monday_second):
    rule = Pinned("l1", monday_first, room_id="r1")

    assert rule.allows(lessons[0], monday_first, room)
    assert not rule.allows(lessons[0], monday_second, room)
    assert not rule.allows(lessons[0], monday_first, Room("r2", "102"))
    assert rule.allows(lessons[1], monday_second, room)


def test_daily_limits(lessons, room):
    schedule = Schedule([Assignment(lessons[i], TimeSlot(0, i + 1), room) for i in range(2)])

    assert validate(schedule, [GroupDailyLimit(2)]).is_valid
    assert not validate(schedule, [GroupDailyLimit(1)]).is_valid


def test_subject_daily_limit(teacher, group, room):
    math = Subject("m", "Математика")
    triple = [Lesson(f"m{i}", math, teacher, group) for i in range(3)]
    schedule = Schedule(
        [Assignment(lesson, TimeSlot(0, i + 1), room) for i, lesson in enumerate(triple)]
    )

    assert not validate(schedule, [SubjectDailyLimit(2)]).is_valid
    assert validate(schedule, [SubjectDailyLimit(3)]).is_valid


def test_gaps_are_counted_per_empty_period(lessons, room):
    other_group = Group("g2", "11Б")
    third = Lesson("l3", lessons[0].subject, lessons[0].teacher, other_group)
    schedule = Schedule(
        [
            Assignment(lessons[0], TimeSlot(0, 1), room),
            Assignment(lessons[1], TimeSlot(0, 4), room),  # окна на 2 и 3 уроке
            Assignment(third, TimeSlot(0, 2), room),
        ]
    )

    report = validate(schedule, [GroupGaps(weight=10)])

    assert len(report.soft_violations) == 2
    assert report.penalty == 20
    assert report.is_valid
