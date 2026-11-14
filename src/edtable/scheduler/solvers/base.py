from abc import ABC, abstractmethod

from edtable.scheduler.problem import SchedulingProblem
from edtable.scheduler.schedule import Schedule


class Solver(ABC):
    """Общий интерфейс для всех алгоритмов.

    Приложение зависит только от этого интерфейса, поэтому алгоритм можно
    заменить или сравнить несколько, не трогая остальной код.
    """

    name: str = ""

    @abstractmethod
    def solve(self, problem: SchedulingProblem) -> Schedule:
        """Составляет расписание.

        Бросает NoSolutionError, если не удалось выполнить жёсткие ограничения.
        """
