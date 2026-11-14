from edtable.scheduler import Assignment, Schedule, TimeSlot


def test_time_slots_sort_by_day_then_period():
    slots = [TimeSlot(1, 1), TimeSlot(0, 3), TimeSlot(0, 1)]

    assert sorted(slots) == [TimeSlot(0, 1), TimeSlot(0, 3), TimeSlot(1, 1)]


def test_schedule_filters_by_group(lessons, room, monday_first, group):
    schedule = Schedule()
    schedule.add(Assignment(lessons[0], monday_first, room))

    assert schedule.for_group(group) == schedule.assignments
