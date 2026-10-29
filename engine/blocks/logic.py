"""Tiny safe count expressions: no Python evaluation or executable payloads."""
from __future__ import annotations

import operator
import re
from collections.abc import Callable
from dataclasses import dataclass

COMPARISONS: dict[str, Callable[[float, float], bool]] = {
    ">=": operator.ge, "<=": operator.le, "==": operator.eq,
    "!=": operator.ne, ">": operator.gt, "<": operator.lt,
}
RULE = re.compile(r"^\s*count\s*(>=|<=|==|!=|>|<)\s*(\d+(?:\.\d+)?)\s*$")


@dataclass(frozen=True)
class CountRule:
    operation: str
    threshold: float

    def matches(self, count: int) -> bool:
        return COMPARISONS[self.operation](count, self.threshold)


def parse_rule(expression: str) -> CountRule:
    match = RULE.fullmatch(expression)
    if not match:
        raise ValueError("Rule must be 'count <operator> <nonnegative number>'; Python is not allowed")
    return CountRule(operation=match.group(1), threshold=float(match.group(2)))
