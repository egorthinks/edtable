class SchedulerError(Exception):
    """Базовая ошибка библиотеки расписания."""


class InvalidProblemError(SchedulerError):
    """Входные данные некорректны, решать нечего."""


class NoSolutionError(SchedulerError):
    """Алгоритм не смог составить расписание, удовлетворяющее жёстким ограничениям."""
