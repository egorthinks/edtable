"""Весь конвейер на примерах из examples/: то же, что делает консоль."""

from functools import cache
from pathlib import Path

import pytest

from edtable.llm import RuleParser, parse_wishes
from edtable.scenario import load_scenario
from edtable.scheduler import (
    CpSatSolver,
    Exchange,
    InvalidProblemError,
    run_auction,
    screen,
    settle,
    validate,
)

EXAMPLES = Path(__file__).parent.parent / "examples"


@cache
def run(name: str):
    scenario = load_scenario(EXAMPLES / name)
    offers, _ = screen(
        parse_wishes(RuleParser(), scenario.wishes, scenario.problem), scenario.problem
    )
    problem = scenario.problem.with_bids(run_auction(offers))
    result = CpSatSolver(time_limit=20).optimize(problem)

    exchange = Exchange(problem, result.schedule)
    deals = []
    for raw in scenario.exchange:
        # Базовое расписание от запуска к запуску разное, и у заявки может не
        # найтись подходящего урока — консоль в этом случае тоже её пропускает.
        try:
            options = scenario.move_requests(raw, exchange.schedule)
        except InvalidProblemError:
            continue
        deals.append(exchange.submit_best(options))
    return problem, result, exchange, deals


@pytest.mark.parametrize("name", ["school.json", "tight.json", "realistic.json"])
def test_example_end_to_end(name):
    problem, result, exchange, deals = run(name)

    assert result.optimal
    assert len(result.schedule.assignments) == len(problem.lessons)
    assert validate(result.schedule, problem.constraints).is_valid
    assert validate(exchange.schedule, problem.constraints).is_valid
    for deal in deals:
        if deal.accepted:
            others = {o: d for o, d in deal.offer.delta.items() if o != deal.request.requester}
            assert all(d >= 0 for d in others.values()), deal


def test_tight_school_makes_bids_compete():
    problem, result, _, _ = run("tight.json")

    points = [acc.points for acc in settle(problem.bids, result.schedule).values()]
    assert min(points) < 100
