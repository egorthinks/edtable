from edtable.llm import WishSpec, to_offers
from edtable.scheduler import TimeSlot
from edtable.scheduler.wishes import AnyOf, AvoidSlots, MaxPerDay
from helpers import grid

SLOTS = grid(days=2, periods=3)


def wishes(*specs):
    return [o.wish for o in to_offers("t", list(specs), SLOTS)]


def test_avoid_empty_lists_mean_everything():
    [day] = wishes(WishSpec("avoid", days=[1]))
    [first] = wishes(WishSpec("avoid", periods=[1]))

    assert day.slots == {TimeSlot(1, p) for p in (1, 2, 3)}
    assert first.slots == {TimeSlot(0, 1), TimeSlot(1, 1)}


def test_bundle_of_one_is_just_that_wish():
    assert wishes(WishSpec("any", parts=[WishSpec("max_per_day", limit=2)])) == [MaxPerDay("t", 2)]


def test_bundle_with_days_but_no_parts_is_avoid():
    [wish] = wishes(WishSpec("any", days=[0]))

    assert isinstance(wish, AvoidSlots) and {s.day for s in wish.slots} == {0}


def test_meaningless_specs_are_dropped():
    assert wishes(WishSpec("max_per_day"), WishSpec("avoid", days=[5]), WishSpec("")) == []


def test_any_keeps_alternatives():
    [wish] = wishes(
        WishSpec("any", parts=[WishSpec("avoid", days=[0]), WishSpec("avoid", days=[1])])
    )

    assert isinstance(wish, AnyOf) and len(wish.parts) == 2
