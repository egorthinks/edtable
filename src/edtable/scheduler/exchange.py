"""Биржа обменов: после базового расписания участники переносят занятия.

Участник просит «перенесите мой урок L в слот T». Биржа пробует по очереди:
1. перенос — если в T свободны и преподаватель, и группа;
2. обмен местами — если мешает ровно одно занятие B: L встаёт в T, B на место L;
3. обмен со сдвигом — мешающим занятиям время подбирает солвер;
4. перестановка — солвер может двигать любые занятия этого класса, но как
   можно меньше.

Каждый вариант проверяет солвер, и правило честности одно: обмен не отнимает
очки ни у кого, кроме инициатора, и не увеличивает штраф администратора (окна,
трудные предметы в конце дня и т.п.). Сдвинуть ради одной заявки можно не больше
max_moves занятий. У тех, чьи занятия сдвинулись, спрашивают согласие — у
человека могут быть причины, которых нет в ставках.

Обмены нужны для того, чего нет в ставках: «в среду у меня врач» человек мог
не написать, но готов ради этого уступить свои очки.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from edtable.scheduler.auction import settle
from edtable.scheduler.models import Assignment, Lesson, TimeSlot
from edtable.scheduler.problem import SchedulingProblem
from edtable.scheduler.schedule import Schedule
from edtable.scheduler.solvers.cpsat import CpSatSolver
from edtable.scheduler.validation import validate

# Слот None в перестановке означает «время подберёт солвер».
Moves = dict[str, TimeSlot | None]


@dataclass(frozen=True)
class MoveRequest:
    requester: str
    lesson_id: str
    target: TimeSlot
    reason: str = ""


@dataclass
class TradeOffer:
    """Сделка, которую биржа нашла и проверила, но ещё не провела."""

    request: MoveRequest
    kind: str
    after: Schedule
    # Чьи занятия сдвинулись, кроме инициатора, — у них спрашиваем согласие.
    counterparties: list[str]
    # Изменение выигранных очков у каждого участника.
    delta: dict[str, int]


@dataclass
class Deal:
    request: MoveRequest
    accepted: bool
    reason: str
    offer: TradeOffer | None = None
    # Дошло ли до солвера. Отказ «такое занятие уже стоит» менее интересен,
    # чем «пострадает Иванова», — из нескольких вариантов показываем второй.
    solved: bool = False


# Решение второй стороны: (кто, предложение) -> согласен ли.
Consent = Callable[[str, TradeOffer], bool]


def always_agree(owner: str, offer: TradeOffer) -> bool:
    return True


def _twins(a: Lesson, b: Lesson) -> bool:
    """Разные часы одного предмета у одного класса и учителя взаимозаменяемы."""
    return (a.subject, a.teacher, a.group) == (b.subject, b.teacher, b.group)


@dataclass
class Exchange:
    problem: SchedulingProblem
    schedule: Schedule
    solver: CpSatSolver = field(default_factory=lambda: CpSatSolver(time_limit=5))
    consent: Consent = always_agree
    # Насколько можно увеличить штраф администратора ради одного обмена.
    penalty_tolerance: int = 0
    # Сколько занятий максимум может сменить время ради одной заявки: формально
    # честная перестановка на 13 уроков всё равно никому не нужна.
    max_moves: int = 6
    history: list[Deal] = field(default_factory=list)

    def run(self, requests: list[MoveRequest]) -> list[Deal]:
        return [self.submit(r) for r in requests]

    def submit(self, request: MoveRequest) -> Deal:
        return self.submit_best([request])

    def submit_best(self, options: list[MoveRequest]) -> Deal:
        """Одна заявка в нескольких вариантах («любой пятничный урок — на среду»).

        Проверяем все, проводим лучший для инициатора: меньше всего потерянных
        очков, потом меньше всего сдвинутых занятий. Согласие спрашиваем уже
        у лучшего, а не у каждого варианта.
        """
        deals = [self._try(r) for r in options]
        passed = sorted(
            (d for d in deals if d.accepted),
            key=lambda d: (
                -d.offer.delta.get(d.request.requester, 0),
                len(d.offer.after.moved_since(self.schedule)),
            ),
        )
        result = next((d for d in deals if d.solved), deals[0])
        for deal in passed:
            refused = [o for o in deal.offer.counterparties if not self.consent(o, deal.offer)]
            if not refused:
                self.schedule = deal.offer.after
                result = deal
                break
            names = ", ".join(self.problem.owner_name(o) for o in refused)
            result = Deal(deal.request, False, f"{names}: не согласен", deal.offer)
        self.history.append(result)
        return result

    def _try(self, request: MoveRequest) -> Deal:
        current = self.schedule.get(request.lesson_id)
        if current is None:
            return Deal(request, False, f"нет занятия {request.lesson_id}")
        if not current.lesson.involves(request.requester):
            return Deal(request, False, "можно переносить только свои занятия")
        if request.target not in self.problem.slots:
            return Deal(request, False, f"слота {request.target} нет в сетке")
        if current.slot == request.target:
            return Deal(request, False, "занятие уже стоит в этом слоте")

        lesson = current.lesson
        here = self.schedule.at(request.target)
        if any(_twins(a.lesson, lesson) for a in here):
            return Deal(request, False, f"в {request.target} уже стоит такое же занятие")
        conflicts = [
            a.lesson.id
            for a in here
            if a.lesson.teacher == lesson.teacher or a.lesson.group == lesson.group
        ]
        moves: Moves = {lesson.id: request.target}

        attempts: list[tuple[str, Moves]] = []
        if not conflicts:
            attempts.append(("перенос", moves))
        if len(conflicts) == 1:
            attempts.append(("обмен местами", {**moves, conflicts[0]: current.slot}))
        if conflicts:
            attempts.append(("обмен со сдвигом", {**moves, **dict.fromkeys(conflicts)}))
        classmates = [
            a.lesson.id for a in self.schedule.for_group(lesson.group) if a.lesson != lesson
        ]
        attempts.append(
            ("перестановка", {**dict.fromkeys(conflicts), **dict.fromkeys(classmates), **moves})
        )

        failed = []
        for kind, attempt in attempts:
            deal = self._check(request, kind, attempt)
            if deal.accepted:
                return deal
            failed.append(f"{kind} — {deal.reason}")
        return Deal(request, False, "; ".join(failed), deal.offer, solved=True)

    def _check(self, request: MoveRequest, kind: str, moves: Moves) -> Deal:
        problem, schedule = self.problem, self.schedule
        before = settle(problem.bids, schedule)
        soft = [c for c in problem.constraints if not c.hard]
        penalty = validate(schedule, soft).penalty

        fair = dict(
            protect=[
                b for owner, acc in before.items() if owner != request.requester for b in acc.won
            ],
            penalty_cap=penalty + self.penalty_tolerance,
            keep_free=self._freed(request),
        )
        after = self.solver.repair(
            problem,
            schedule,
            moves,
            favor=problem.bids_of(request.requester),
            max_moves=self.max_moves,
            **fair,
        )
        if after is None:
            return Deal(request, False, self._why_not(request, moves, before, penalty, fair))

        now = settle(problem.bids, after)
        delta = {owner: now[owner].points - before[owner].points for owner in before}
        moved = after.moved_since(schedule)
        counterparties = sorted(
            {new.lesson.teacher.id for old, new in moved if old.slot != new.slot}
            - {request.requester}
        )
        return Deal(request, True, kind, TradeOffer(request, kind, after, counterparties, delta))

    def _why_not(self, request: MoveRequest, moves: Moves, before, penalty: int, fair) -> str:
        """Объясняет отказ: снимаем требования по одному, пока перестановка не найдётся."""
        problem, schedule, freed = self.problem, self.schedule, self._freed(request)
        if self.solver.repair(problem, schedule, moves, **fair) is not None:
            return f"честно получается, но пришлось бы сдвинуть больше {self.max_moves} уроков"
        loose = self.solver.repair(
            problem, schedule, moves, keep_free=freed, max_moves=self.max_moves
        )
        if loose is None:
            if self.solver.repair(problem, schedule, moves, keep_free=freed) is not None:
                return f"пришлось бы сдвинуть больше {self.max_moves} уроков"
            if self.solver.repair(problem, schedule, moves) is not None:
                return "старый слот не освобождается: туда встаёт другое ваше занятие"
            return self._why_infeasible(moves)
        for owner, account in before.items():
            lost = [b for b in account.won if not b.wish.holds(loose)]
            if owner != request.requester and lost:
                return f"пострадает {self.problem.owner_name(owner)}: «{lost[0].wish.describe()}»"
        soft = [c for c in self.problem.constraints if not c.hard]
        was = validate(self.schedule, soft).penalty_breakdown()
        now = validate(loose, soft).penalty_breakdown()
        worse = [t for t, (_, p) in now.items() if p > was.get(t, (0, 0))[1]]
        extra = sum(p for _, p in now.values()) - penalty
        return f"вырастет штраф администратора на {extra} ({', '.join(worse)})"

    def _freed(self, request: MoveRequest) -> list[tuple[str, TimeSlot]]:
        """Смысл заявки — уйти из старого слота. Если туда встанет другое занятие
        того же человека (например, такой же урок математики), сделка пустая."""
        return [(request.requester, self.schedule.get(request.lesson_id).slot)]

    def _why_infeasible(self, moves: Moves) -> str:
        fixed = {lid: slot for lid, slot in moves.items() if slot is not None}
        naive = Schedule(
            [
                Assignment(a.lesson, fixed[a.lesson.id], a.room) if a.lesson.id in fixed else a
                for a in self.schedule.assignments
                if a.lesson.id not in moves or a.lesson.id in fixed
            ]
        )
        hard = [c for c in self.problem.constraints if c.hard and c.name != "no_room_overlap"]
        problems = [v.message for v in validate(naive, hard).violations]
        return "нарушит правила: " + ("; ".join(problems[:2]) or "нет свободного времени")
