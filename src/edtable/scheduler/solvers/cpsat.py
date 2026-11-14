"""Солвер на OR-Tools CP-SAT.

Модель: булева переменная на каждый допустимый вариант «занятие — слот —
аудитория». Жёсткие правила становятся ограничениями, ставки участников —
слагаемыми целевой функции с весом в очках, мягкие правила администратора —
штрафами в тех же очках.

Целевая функция:
    сумма выигранных очков + fairness * (очки самого обделённого) - штрафы

Второе слагаемое не даёт солверу «скормить» одного человека остальным: при
fairness=3 солвер согласен потерять до трёх очков общего выигрыша, чтобы
самому обделённому участнику досталось на очко больше.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from ortools.sat.python import cp_model

from edtable.scheduler.auction import BUDGET
from edtable.scheduler.constraints import DailyLimit, UnaryConstraint
from edtable.scheduler.exceptions import NoSolutionError
from edtable.scheduler.models import Assignment, Lesson, Room, TimeSlot
from edtable.scheduler.problem import SchedulingProblem
from edtable.scheduler.schedule import Schedule
from edtable.scheduler.solvers.base import Solver
from edtable.scheduler.wishes import Bid

Domains = dict[str, list[tuple[TimeSlot, Room]]]


class CpSatContext:
    """Модель CP-SAT плюс удобные доступы к переменным для правил и пожеланий."""

    def __init__(self, problem: SchedulingProblem, domains: Domains):
        self.problem = problem
        self.model = cp_model.CpModel()
        self.slots = sorted(problem.slots)
        self.days = list(problem.days)
        self._day_slots = {day: problem.day_slots(day) for day in self.days}

        self.place: dict[tuple[str, TimeSlot, str], cp_model.IntVar] = {}
        self._at: dict[tuple[str, TimeSlot], cp_model.IntVar] = {}
        self._owner_slot: dict[tuple[str, TimeSlot], list] = defaultdict(list)
        self._room_slot: dict[tuple[str, TimeSlot], list] = defaultdict(list)
        self._busy: dict[tuple[str, TimeSlot], cp_model.IntVar] = {}
        self._day_busy: dict[tuple[str, int], cp_model.IntVar] = {}

        self.false = self.model.new_bool_var("false")
        self.model.add(self.false == 0)

        for lesson in problem.lessons:
            self._add_lesson(lesson, domains[lesson.id])

    def _add_lesson(self, lesson: Lesson, options: list[tuple[TimeSlot, Room]]) -> None:
        by_slot: dict[TimeSlot, list] = defaultdict(list)
        for slot, room in options:
            var = self.model.new_bool_var(f"x[{lesson.id},{slot},{room.id}]")
            self.place[(lesson.id, slot, room.id)] = var
            by_slot[slot].append(var)
            self._room_slot[(room.id, slot)].append(var)

        for slot, variants in by_slot.items():
            if len(variants) == 1:
                at = variants[0]
            else:
                at = self.model.new_bool_var(f"at[{lesson.id},{slot}]")
                self.model.add(sum(variants) == at)
            self._at[(lesson.id, slot)] = at
            self._owner_slot[(lesson.teacher.id, slot)].append(at)
            self._owner_slot[(lesson.group.id, slot)].append(at)

        self.model.add_exactly_one(self._at[(lesson.id, s)] for s in by_slot)

    def day_slots(self, day: int) -> list[TimeSlot]:
        return self._day_slots[day]

    def at(self, lesson_id: str, slot: TimeSlot) -> cp_model.IntVar:
        return self._at.get((lesson_id, slot), self.false)

    def lesson_terms(self, owner_id: str, slot: TimeSlot) -> list:
        return self._owner_slot.get((owner_id, slot), [])

    def room_terms(self, room_id: str, slot: TimeSlot) -> list:
        return self._room_slot.get((room_id, slot), [])

    def at_most_one(self, terms: list) -> None:
        if len(terms) > 1:
            self.model.add_at_most_one(terms)

    def busy(self, owner_id: str, slot: TimeSlot) -> cp_model.IntVar:
        """Есть ли у участника хоть одно занятие в слоте."""
        key = (owner_id, slot)
        if key not in self._busy:
            self._busy[key] = self._any(
                self.lesson_terms(owner_id, slot), f"busy[{owner_id},{slot}]"
            )
        return self._busy[key]

    def day_busy(self, owner_id: str, day: int) -> cp_model.IntVar:
        """Работает ли участник в этот день."""
        key = (owner_id, day)
        if key not in self._day_busy:
            terms = [self.busy(owner_id, s) for s in self.day_slots(day)]
            self._day_busy[key] = self._any(terms, f"works[{owner_id},{day}]")
        return self._day_busy[key]

    def _any(self, terms: list, name: str) -> cp_model.IntVar:
        terms = [t for t in terms if t is not self.false]
        if not terms:
            return self.false
        if len(terms) == 1:
            return terms[0]
        var = self.model.new_bool_var(name)
        self.model.add_max_equality(var, terms)
        return var


@dataclass
class SolveResult:
    schedule: Schedule
    status: str
    objective: float
    # Верхняя граница, которую доказал солвер: лучше этого расписания не бывает.
    bound: float
    seconds: float

    @property
    def optimal(self) -> bool:
        return self.status == "OPTIMAL"

    @property
    def gap(self) -> float:
        """Насколько, в худшем случае, найденное хуже оптимума (доля от границы)."""
        if not self.bound:
            return 0.0
        return max(0.0, (self.bound - self.objective) / abs(self.bound))


class CpSatSolver(Solver):
    name = "cp-sat"

    def __init__(
        self,
        time_limit: float = 30.0,
        workers: int = 8,
        fairness: int = 3,
        seed: int = 0,
        log: bool = False,
    ):
        self.time_limit = time_limit
        self.workers = workers
        self.fairness = fairness
        self.seed = seed
        self.log = log

    def solve(self, problem: SchedulingProblem) -> Schedule:
        return self.optimize(problem).schedule

    def optimize(self, problem: SchedulingProblem) -> SolveResult:
        domains = full_domains(problem)
        if any(not options for options in domains.values()):
            raise NoSolutionError(_explain(diagnose(problem, domains)))

        ctx = self._build(problem, domains)
        model = ctx.model

        won: dict[str, list] = defaultdict(list)
        for bid in problem.bids:
            won[bid.owner].append(bid.points * bid.wish.encode(ctx))

        penalty = sum(c.weight * c.encode(ctx) for c in problem.constraints if not c.hard)

        objective = sum(sum(terms) for terms in won.values()) - penalty
        if won and self.fairness:
            poorest = model.new_int_var(0, BUDGET, "poorest")
            for terms in won.values():
                model.add(poorest <= sum(terms))
            objective += self.fairness * poorest
        model.maximize(objective)

        solver, status, seconds = self._run(model, self.time_limit)
        if status == cp_model.INFEASIBLE:
            raise NoSolutionError(_explain(diagnose(problem, domains)))
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise NoSolutionError(
                f"За {self.time_limit:.0f} с не нашлось ни одного расписания "
                f"(статус {solver.status_name(status)}). Попробуйте увеличить время."
            )

        return SolveResult(
            schedule=_extract(ctx, solver),
            status=solver.status_name(status),
            objective=solver.objective_value,
            bound=solver.best_objective_bound,
            seconds=seconds,
        )

    def repair(
        self,
        problem: SchedulingProblem,
        schedule: Schedule,
        moves: dict[str, TimeSlot | None],
        protect: Iterable[Bid] = (),
        penalty_cap: int | None = None,
        keep_free: Iterable[tuple[str, TimeSlot]] = (),
        favor: Iterable[Bid] = (),
        max_moves: int | None = None,
        time_limit: float = 5.0,
    ) -> Schedule | None:
        """Переставляет занятия по moves, время остальных не трогает.

        Слот None — «куда угодно», его выберет солвер. Аудитории в затронутых
        слотах можно перераспределять, чтобы обмен не срывался из-за кабинетов.

        protect — ставки, которые обязаны остаться выигранными; penalty_cap —
        потолок штрафа администратора; keep_free — пары (участник, слот), где у
        участника не должно остаться занятий; max_moves — сколько занятий
        максимум могут сменить время. Из подходящих вариантов выбирает
        тот, где ставки favor выигрывают больше очков, а при равенстве — где
        меньше занятий меняют время или кабинет. None — такой перестановки нет.
        """
        current = {a.lesson.id: a for a in schedule.assignments}
        touched = {current[lid].slot for lid in moves} | {s for s in moves.values() if s}
        unary = _unary(problem)

        domains: Domains = {}
        for lesson in problem.lessons:
            here = current[lesson.id]
            if lesson.id in moves and moves[lesson.id] is None:
                options = [(s, r) for s in sorted(problem.slots) for r in problem.rooms]
            else:
                slot = moves.get(lesson.id, here.slot)
                rooms = problem.rooms if slot in touched else (here.room,)
                options = [(slot, r) for r in rooms]
            domains[lesson.id] = [
                (s, r) for s, r in options if all(c.allows(lesson, s, r) for c in unary)
            ]
            if not domains[lesson.id]:
                return None

        ctx = self._build(problem, domains)
        model = ctx.model
        for bid in protect:
            model.add(bid.wish.encode(ctx) == 1)
        if penalty_cap is not None:
            model.add(
                sum(c.weight * c.encode(ctx) for c in problem.constraints if not c.hard)
                <= penalty_cap
            )

        for owner_id, slot in keep_free:
            model.add(ctx.busy(owner_id, slot) == 0)
        if max_moves is not None:
            model.add(
                sum(
                    var
                    for (lesson_id, slot, _), var in ctx.place.items()
                    if slot != current[lesson_id].slot
                )
                <= max_moves
            )

        # Сменить время хуже, чем сменить кабинет.
        changes = sum(
            (3 if slot != current[lesson_id].slot else 1) * var
            for (lesson_id, slot, room_id), var in ctx.place.items()
            if (slot, room_id) != (current[lesson_id].slot, current[lesson_id].room.id)
        )
        gain = sum(bid.points * bid.wish.encode(ctx) for bid in favor)
        # Очко ставки дороже любого числа перестановок: их меньше, чем 3 * len(place).
        model.maximize(3 * len(ctx.place) * gain - changes)

        solver, status, _ = self._run(model, time_limit)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None
        return _extract(ctx, solver)

    def _build(self, problem: SchedulingProblem, domains: Domains) -> CpSatContext:
        ctx = CpSatContext(problem, domains)
        for constraint in problem.constraints:
            if constraint.hard:
                constraint.encode(ctx)
        return ctx

    def _run(self, model: cp_model.CpModel, time_limit: float):
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit
        solver.parameters.num_workers = self.workers
        solver.parameters.random_seed = self.seed
        solver.parameters.log_search_progress = self.log
        started = time.perf_counter()
        status = solver.solve(model)
        return solver, status, time.perf_counter() - started


def _unary(problem: SchedulingProblem) -> list[UnaryConstraint]:
    return [c for c in problem.constraints if isinstance(c, UnaryConstraint)]


def full_domains(problem: SchedulingProblem) -> Domains:
    unary = _unary(problem)
    return {
        lesson.id: [
            (slot, room)
            for slot in sorted(problem.slots)
            for room in problem.rooms
            if all(c.allows(lesson, slot, room) for c in unary)
        ]
        for lesson in problem.lessons
    }


def _extract(ctx: CpSatContext, solver: cp_model.CpSolver) -> Schedule:
    lessons = {lesson.id: lesson for lesson in ctx.problem.lessons}
    rooms = {room.id: room for room in ctx.problem.rooms}
    return Schedule(
        sorted(
            (
                Assignment(lessons[lesson_id], slot, rooms[room_id])
                for (lesson_id, slot, room_id), var in ctx.place.items()
                if solver.boolean_value(var)
            ),
            key=lambda a: (a.slot, a.lesson.group.id),
        )
    )


def diagnose(problem: SchedulingProblem, domains: Domains | None = None) -> list[str]:
    """Человеческие подсказки, почему расписания может не существовать.

    Это не доказательство, а самые частые причины: им проверить быстрее, чем
    искать минимальное противоречивое подмножество правил.
    """
    domains = domains if domains is not None else full_domains(problem)
    hints = []

    for lesson in problem.lessons:
        if domains[lesson.id]:
            continue
        blockers = [
            c.name
            for c in _unary(problem)
            if not any(c.allows(lesson, s, r) for s in problem.slots for r in problem.rooms)
        ]
        why = ", ".join(blockers) or "сочетание правил"
        hints.append(f"Занятию «{lesson}» некуда встать (мешает: {why})")

    for owner in (*problem.teachers, *problem.groups):
        lessons = problem.lessons_of(owner.id)
        free = {slot for lesson in lessons for slot, _ in domains[lesson.id]}
        if len(lessons) > len(free):
            hints.append(f"У «{owner.name}» {len(lessons)} занятий, а доступных слотов {len(free)}")

    for constraint in problem.constraints:
        if not isinstance(constraint, DailyLimit):
            continue
        for owner_id in constraint.owner_ids(problem.lessons):
            limit = constraint.limit_for(owner_id)
            capacity = limit * len(problem.days)
            n = len(problem.lessons_of(owner_id))
            if n > capacity:
                hints.append(
                    f"У «{problem.owner_name(owner_id)}» {n} занятий, а при лимите "
                    f"{limit} в день помещается {capacity}"
                )
    return hints


def _explain(hints: list[str]) -> str:
    if not hints:
        return "Жёсткие ограничения противоречат друг другу, простых причин не нашлось."
    return "Расписание не существует:\n  - " + "\n  - ".join(hints)
