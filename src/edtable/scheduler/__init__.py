"""Ядро приложения: алгоритм составления расписания.

Библиотека не знает ничего про интерфейс и хранение данных. На вход получает
SchedulingProblem (вместе со ставками участников), на выходе отдаёт Schedule.
Всё остальное приложение должно импортировать только то, что перечислено здесь.

Конвейер:
    пожелания -> run_auction -> ставки -> CpSatSolver.optimize -> базовое
    расписание -> Exchange (обмены, каждый проверяет солвер) -> итоговое.
"""

from edtable.scheduler.auction import BUDGET, Account, Offer, Refusal, run_auction, screen, settle
from edtable.scheduler.constraints import Constraint, Violation
from edtable.scheduler.exceptions import InvalidProblemError, NoSolutionError, SchedulerError
from edtable.scheduler.exchange import Deal, Exchange, MoveRequest
from edtable.scheduler.models import Assignment, Group, Lesson, Room, Subject, Teacher, TimeSlot
from edtable.scheduler.problem import SchedulingProblem
from edtable.scheduler.schedule import Schedule
from edtable.scheduler.solvers import CpSatSolver, Solver, SolveResult
from edtable.scheduler.validation import ValidationReport, validate
from edtable.scheduler.wishes import Bid, Wish

__all__ = [
    "BUDGET",
    "Account",
    "Assignment",
    "Bid",
    "Constraint",
    "CpSatSolver",
    "Deal",
    "Exchange",
    "Group",
    "InvalidProblemError",
    "Lesson",
    "MoveRequest",
    "NoSolutionError",
    "Offer",
    "Refusal",
    "Room",
    "Schedule",
    "SchedulerError",
    "SchedulingProblem",
    "SolveResult",
    "Solver",
    "Subject",
    "Teacher",
    "TimeSlot",
    "ValidationReport",
    "Violation",
    "Wish",
    "run_auction",
    "screen",
    "settle",
    "validate",
]
