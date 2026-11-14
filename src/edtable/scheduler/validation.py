"""Проверка готового расписания на соответствие ограничениям.

Не зависит от алгоритма: нужна и для тестов, и чтобы проверять расписание,
которое пользователь поправил руками.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from edtable.scheduler.constraints import Constraint, Violation
from edtable.scheduler.schedule import Schedule


@dataclass(frozen=True)
class ValidationReport:
    violations: tuple[Violation, ...]

    @property
    def hard_violations(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.constraint.hard)

    @property
    def soft_violations(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if not v.constraint.hard)

    @property
    def is_valid(self) -> bool:
        return not self.hard_violations

    @property
    def penalty(self) -> int:
        return sum(v.constraint.weight for v in self.soft_violations)

    def penalty_breakdown(self) -> dict[str, tuple[int, int]]:
        """Название правила -> (сколько нарушений, сколько штрафа)."""
        result: dict[str, tuple[int, int]] = {}
        for v in self.soft_violations:
            title = getattr(v.constraint, "title", "") or v.constraint.name
            count, total = result.get(title, (0, 0))
            result[title] = (count + 1, total + v.constraint.weight)
        return result

    def describe_penalty(self) -> str:
        parts = [f"{t}: {n} (-{p})" for t, (n, p) in self.penalty_breakdown().items()]
        return f"штраф {self.penalty}" + (" — " + ", ".join(parts) if parts else "")


def validate(schedule: Schedule, constraints: Iterable[Constraint]) -> ValidationReport:
    violations: list[Violation] = []
    for constraint in constraints:
        violations.extend(constraint.check(schedule))
    return ValidationReport(violations=tuple(violations))
