"""Консольный прогон всего конвейера на сценарии из JSON.

python -m edtable examples/school.json
python -m edtable examples/school.json --parser lmstudio --repl
"""

import argparse
import shlex
import sys

from edtable.llm import LMStudioParser, RuleParser, WishParserError, parse_wishes
from edtable.scenario import Scenario, load_scenario, parse_slot
from edtable.scheduler import (
    BUDGET,
    CpSatSolver,
    Deal,
    Exchange,
    InvalidProblemError,
    MoveRequest,
    NoSolutionError,
    Schedule,
    SchedulingProblem,
    run_auction,
    screen,
    settle,
    validate,
)
from edtable.scheduler.models import DAY_NAMES

CELL = 18


def line(char: str = "-") -> str:
    return char * (4 + (CELL + 1) * 5)


def render_grid(problem: SchedulingProblem, schedule: Schedule, owner_id: str) -> str:
    is_group = any(g.id == owner_id for g in problem.groups)
    cells = {}
    for a in schedule.for_owner(owner_id):
        other = a.room.name[:6] if is_group else a.lesson.group.name
        cells[a.slot] = f"{a.lesson.subject.name[:CELL - len(other) - 1]} {other}"

    days = problem.days
    rows = ["    " + " ".join(DAY_NAMES[d].ljust(CELL) for d in days)]
    for period in sorted({s.period for s in problem.slots}):
        row = [
            cells.get(next((s for s in problem.day_slots(d) if s.period == period), None), "")
            for d in days
        ]
        rows.append(f"{period:>2}  " + " ".join(c.ljust(CELL) for c in row))
    return "\n".join(rows)


def show(problem: SchedulingProblem, schedule: Schedule, owner_id: str) -> None:
    print(f"\n{problem.owner_name(owner_id)}")
    print(render_grid(problem, schedule, owner_id))


def show_accounts(problem: SchedulingProblem, schedule: Schedule, before: Schedule | None = None):
    accounts = settle(problem.bids, schedule)
    old = settle(problem.bids, before) if before else {}
    order = [o.id for o in (*problem.teachers, *problem.groups) if o.id in accounts]
    for owner in order:
        account = accounts[owner]
        delta = ""
        if owner in old and old[owner].points != account.points:
            delta = f" ({account.points - old[owner].points:+d})"
        print(f"\n  {problem.owner_name(owner):<18} {account.points:>3}/{BUDGET}{delta}")
        for bid in problem.bids_of(owner):
            mark = "+" if bid in account.won else "-"
            print(f"      {mark} {bid.points:>3}  {bid.wish.describe()}")
    shares = [accounts[o].points for o in problem.participants]
    if shares:
        average = sum(shares) / len(shares)
        print(f"\n  В среднем {average:.0f} из {BUDGET}, меньше всех — {min(shares)}")


def show_deal(problem: SchedulingProblem, deal: Deal, before: Schedule) -> None:
    r = deal.request
    lesson = before.get(r.lesson_id)
    what = f"{lesson.lesson.subject.name} {lesson.lesson.group.name}"
    head = f"{problem.owner_name(r.requester)}: {what} {lesson.slot} -> {r.target}"
    if r.reason:
        head += f"  ({r.reason})"
    print(f"\n  {head}")
    if not deal.accepted:
        print(f"    ОТКАЗ: {deal.reason}")
        return
    print(f"    ПРИНЯТ: {deal.reason}")
    for old, new in deal.offer.after.moved_since(before):
        where = f"{old.slot} ауд.{old.room.name} -> {new.slot} ауд.{new.room.name}"
        print(f"      {new.lesson}: {where}")
    for owner, change in sorted(deal.offer.delta.items()):
        if change:
            print(f"      очки {problem.owner_name(owner)}: {change:+d}")


def build_bids(scenario: Scenario, parser) -> SchedulingProblem:
    problem = scenario.problem
    try:
        offers = parse_wishes(parser, scenario.wishes, problem)
    except WishParserError as e:
        print(f"! {parser.name}: {e}\n! Разбираю пожелания правилами.")
        parser = RuleParser()
        offers = parse_wishes(parser, scenario.wishes, problem)

    used = getattr(parser, "model", None) or parser.name
    print(line("="))
    print(f"ПОЖЕЛАНИЯ -> СТАВКИ (разбор: {used}, бюджет {BUDGET} очков у каждого)")
    offers, refused = screen(offers, problem)
    bids = run_auction(offers)
    for owner, text in scenario.wishes.items():
        print(f"\n  {problem.owner_name(owner)}: «{text}»")
        mine = [b for b in bids if b.owner == owner]
        for bid in mine:
            print(f"      {bid.points:>3}  {bid.wish.describe()}")
        for r in refused:
            if r.owner == owner:
                print(f"       --  {r.offer.wish.describe()}: невыполнимо, {r.reason}")
        if not mine:
            print("      (ставок нет)")
    return problem.with_bids(bids)


def repl(problem: SchedulingProblem, exchange: Exchange) -> None:
    print(line("="))
    print(
        "Команды: g [группа] | t [учитель] | p — очки | "
        "m <кто> <откуда> <куда> — перенос (пример: m popov вт3 ср2) | q — выход"
    )
    while True:
        try:
            parts = shlex.split(input("\n> "))
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not parts:
            continue
        cmd, args = parts[0], parts[1:]
        try:
            if cmd == "q":
                return
            elif cmd in ("g", "t"):
                owners = problem.groups if cmd == "g" else problem.teachers
                for owner in owners:
                    if not args or owner.id in args:
                        show(problem, exchange.schedule, owner.id)
            elif cmd == "p":
                show_accounts(problem, exchange.schedule)
            elif cmd == "m" and len(args) == 3:
                who, src, dst = args
                src_slot = parse_slot(src, problem.slots)
                lesson = next(
                    (a for a in exchange.schedule.for_owner(who) if a.slot == src_slot), None
                )
                if lesson is None:
                    print(f"У {who} нет занятия в {src_slot}")
                    continue
                before = exchange.schedule
                request = MoveRequest(who, lesson.lesson.id, parse_slot(dst, problem.slots))
                show_deal(problem, exchange.submit(request), before)
            else:
                print("Не понял команду.")
        except InvalidProblemError as e:
            print(e)


def ask_consent(problem: SchedulingProblem):
    def consent(owner, offer) -> bool:
        change = offer.delta.get(owner, 0)
        answer = input(
            f"  {problem.owner_name(owner)}, согласны на обмен (очки {change:+d})? [y/n] "
        )
        return answer.strip().lower() in ("y", "д", "да", "yes")

    return consent


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure") and not sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = argparse.ArgumentParser(prog="edtable", description=__doc__.split("\n")[0])
    args.add_argument("scenario", help="JSON со сценарием, например examples/school.json")
    args.add_argument("--parser", choices=["rules", "lmstudio"], default="rules")
    args.add_argument("--model", help="модель в LM Studio (по умолчанию — первая загруженная)")
    args.add_argument("--lmstudio-url", default="http://localhost:1234/v1")
    args.add_argument("--time-limit", type=float, default=30, help="секунд на базовое расписание")
    args.add_argument("--fairness", type=int, default=3)
    args.add_argument("--workers", type=int, default=8)
    args.add_argument("--teachers", action="store_true", help="показать сетки учителей")
    args.add_argument("--no-exchange", action="store_true")
    args.add_argument("--repl", action="store_true", help="интерактивная биржа после расчёта")
    args.add_argument("--ask", action="store_true", help="спрашивать согласие на обмены")
    opts = args.parse_args(argv)

    try:
        scenario = load_scenario(opts.scenario)
    except (InvalidProblemError, KeyError, ValueError) as e:
        print(f"Сценарий не загрузился: {e}")
        return 2

    parser = (
        LMStudioParser(opts.lmstudio_url, opts.model) if opts.parser == "lmstudio" else RuleParser()
    )
    problem = build_bids(scenario, parser)

    solver = CpSatSolver(time_limit=opts.time_limit, fairness=opts.fairness, workers=opts.workers)
    print(line("="))
    print(f"БАЗОВОЕ РАСПИСАНИЕ (CP-SAT, до {opts.time_limit:.0f} с)")
    try:
        result = solver.optimize(problem)
    except NoSolutionError as e:
        print(e)
        return 1

    guarantee = (
        "оптимум доказан"
        if result.optimal
        else f"лучше найденного не более чем на {result.gap:.1%}"
    )
    print(
        f"  {result.status}, {result.seconds:.1f} с: цель {result.objective:.0f}, "
        f"граница {result.bound:.0f} — {guarantee}"
    )
    report = validate(result.schedule, problem.constraints)
    print(f"  Жёстких нарушений: {len(report.hard_violations)}, {report.describe_penalty()}")

    for group in problem.groups:
        show(problem, result.schedule, group.id)
    if opts.teachers:
        for teacher in problem.teachers:
            show(problem, result.schedule, teacher.id)

    print("\n" + line())
    print("ИТОГ АУКЦИОНА")
    show_accounts(problem, result.schedule)

    exchange = Exchange(problem, result.schedule, solver=CpSatSolver(workers=opts.workers))
    if opts.ask:
        exchange.consent = ask_consent(problem)

    if scenario.exchange and not opts.no_exchange:
        print(line("="))
        print("БИРЖА ОБМЕНОВ")
        for raw in scenario.exchange:
            try:
                options = scenario.move_requests(raw, exchange.schedule)
            except InvalidProblemError as e:
                print(f"\n  ! {e}")
                continue
            before = exchange.schedule
            deal = exchange.submit_best(options)
            show_deal(problem, deal, before)
            if len(options) > 1:
                verdict = "выбран лучший для инициатора" if deal.accepted else "ни один не прошёл"
                print(f"    (вариантов: {len(options)}, {verdict})")

        moved = exchange.schedule.moved_since(result.schedule)
        print(f"\n{line('=')}\nИТОГОВОЕ РАСПИСАНИЕ: изменилось занятий — {len(moved)}")
        final = validate(exchange.schedule, problem.constraints)
        print(f"  Жёстких нарушений: {len(final.hard_violations)}, {final.describe_penalty()}")
        show_accounts(problem, exchange.schedule, before=result.schedule)

    if opts.repl:
        repl(problem, exchange)
    return 0


if __name__ == "__main__":
    sys.exit(main())
