"""Алгоритмы составления расписания.

Каждый алгоритм — отдельный модуль в этой папке, наследник Solver.
"""

from edtable.scheduler.solvers.base import Solver
from edtable.scheduler.solvers.cpsat import CpSatSolver, SolveResult, diagnose

__all__ = ["CpSatSolver", "SolveResult", "Solver", "diagnose"]
