import pytest

from edtable.scheduler import BUDGET, Offer, run_auction, screen
from edtable.scheduler.auction import split_budget
from edtable.scheduler.wishes import AvoidSlots, MaxPerDay, NoGaps


@pytest.mark.parametrize("raw", [[1], [1, 1, 1], [9, 3], [7, 7, 7, 1], [0.1, 0.2]])
def test_split_budget_always_spends_exactly_the_budget(raw):
    assert sum(split_budget(raw)) == BUDGET


def test_split_budget_is_proportional():
    assert split_budget([9, 3]) == [75, 25]
    assert split_budget([0, 0]) == [0, 0]


def test_budget_is_equal_no_matter_how_many_wishes():
    loud = [Offer(NoGaps("a")), Offer(MaxPerDay("a", 3)), Offer(MaxPerDay("a", 4))]
    quiet = [Offer(NoGaps("b"))]

    bids = run_auction({"a": loud, "b": quiet})

    by_owner = {o: sum(b.points for b in bids if b.owner == o) for o in "ab"}
    assert by_owner == {"a": BUDGET, "b": BUDGET}


def test_explicit_points_mix_with_importance():
    offers = [Offer(NoGaps("a"), points=30), Offer(MaxPerDay("a", 3), weight=7)]

    assert [b.points for b in run_auction({"a": offers})] == [30, 70]


def test_screen_drops_impossible_wish_and_frees_its_points(school):
    everything = frozenset(school.slots)
    offers = {
        "math_t": [Offer(AvoidSlots("math_t", everything), weight=10), Offer(NoGaps("math_t"))]
    }

    kept, refused = screen(offers, school)
    bids = run_auction(kept)

    assert [r.offer.wish for r in refused] == [AvoidSlots("math_t", everything)]
    assert [(b.wish, b.points) for b in bids] == [(NoGaps("math_t"), BUDGET)]
