"""Ограничения, которым должно удовлетворять расписание.

Жёсткие (hard) нарушать нельзя — такое расписание невалидно.
Мягкие (soft) нарушать можно, но за каждое нарушение начисляется штраф.
"""

from edtable.scheduler.constraints.base import Constraint, UnaryConstraint, Violation
from edtable.scheduler.constraints.hard import (
    DEFAULT_HARD_CONSTRAINTS,
    DailyLimit,
    DoubleLessons,
    GroupDailyLimit,
    HomeRoom,
    NoGroupOverlap,
    NoRoomOverlap,
    NoTeacherOverlap,
    Pinned,
    RoomCapacity,
    RoomFeatures,
    SubjectDailyLimit,
    TeacherDailyLimit,
    Unavailable,
)
from edtable.scheduler.constraints.soft import GroupGaps, LateLessons, SplitLessons, TeacherGaps

__all__ = [
    "DEFAULT_HARD_CONSTRAINTS",
    "DailyLimit",
    "Constraint",
    "DoubleLessons",
    "GroupDailyLimit",
    "GroupGaps",
    "HomeRoom",
    "LateLessons",
    "SplitLessons",
    "TeacherGaps",
    "NoGroupOverlap",
    "NoRoomOverlap",
    "NoTeacherOverlap",
    "Pinned",
    "RoomCapacity",
    "RoomFeatures",
    "SubjectDailyLimit",
    "TeacherDailyLimit",
    "UnaryConstraint",
    "Unavailable",
    "Violation",
]
