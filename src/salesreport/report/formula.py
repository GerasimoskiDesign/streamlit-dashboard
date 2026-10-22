"""A tiny evaluator for the formulas the report writes.

openpyxl writes formulas but cannot calculate them, and a saved-but-never-opened
workbook has no cached values. ``verify`` must still check the numbers a reader will
see, so it evaluates the small formula subset the report uses: numbers, strings, cell
references, ranges inside ``SUM``, ``+ - * /``, comparisons and ``IF``. Anything else
raises, so a hand-edited exotic formula is reported rather than misread.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from openpyxl.utils.cell import (
    column_index_from_string,
    coordinate_from_string,
    get_column_letter,
)

_TOKEN = re.compile(
    r"\s*(?:(?P<number>\d+(?:\.\d+)?)|(?P<string>\"[^\"]*\")|(?P<range>\$?[A-Z]{1,3}\$?\d+:\$?[A-Z]{1,3}\$?\d+)"
    r"|(?P<cell>\$?[A-Z]{1,3}\$?\d+)|(?P<func>[A-Z]+)\(|(?P<op><>|<=|>=|[-+*/=<>(),]))"
)


DIV0 = "#DIV/0!"


class FormulaError(ValueError):
    """The formula uses syntax outside the supported subset."""


def _tokens(text: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    text = text.strip()
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match or match.end() == pos:
            raise FormulaError(f"cannot parse formula near {text[pos:]!r}")
        kind = match.lastgroup or ""
        out.append((kind, match.group(kind)))
        pos = match.end()
    return out


def _num(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    raise FormulaError(f"non-numeric value {value!r} in arithmetic")


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]], cell: Callable[[str], Any]):
        self.tokens = tokens
        self.pos = 0
        self.cell = cell

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self) -> tuple[str, str]:
        token = self.peek()
        if token is None:
            raise FormulaError("unexpected end of formula")
        self.pos += 1
        return token

    def expect(self, op: str) -> None:
        kind, value = self.take()
        if kind != "op" or value != op:
            raise FormulaError(f"expected {op!r}, got {value!r}")

    def comparison(self) -> Any:
        left = self.additive()
        token = self.peek()
        if token and token[0] == "op" and token[1] in {"=", "<>", "<", ">", "<=", ">="}:
            self.take()
            right = self.additive()
            a, b = (
                (left, right)
                if isinstance(left, str) or isinstance(right, str)
                else (_num(left), _num(right))
            )
            return {
                "=": a == b,
                "<>": a != b,
                "<": a < b,
                ">": a > b,
                "<=": a <= b,
                ">=": a >= b,
            }[token[1]]
        return left

    def additive(self) -> Any:
        value = self.term()
        while (token := self.peek()) and token[0] == "op" and token[1] in "+-":
            self.take()
            right = self.term()
            value = _num(value) + _num(right) if token[1] == "+" else _num(value) - _num(right)
        return value

    def term(self) -> Any:
        value = self.factor()
        while (token := self.peek()) and token[0] == "op" and token[1] in "*/":
            self.take()
            right = _num(self.factor())
            if token[1] == "/" and right == 0:
                # Like Excel's #DIV/0!: harmless inside the unused branch of an IF,
                # an error as soon as anything does arithmetic with it.
                value = DIV0
                continue
            value = _num(value) * right if token[1] == "*" else _num(value) / right
        return value

    def factor(self) -> Any:
        kind, value = self.take()
        if kind == "number":
            return float(value)
        if kind == "string":
            return value[1:-1]
        if kind == "cell":
            return self.cell(value.replace("$", ""))
        if kind == "op" and value == "-":
            return -_num(self.factor())
        if kind == "op" and value == "(":
            inner = self.comparison()
            self.expect(")")
            return inner
        if kind == "func":
            return self.function(value)
        raise FormulaError(f"unexpected token {value!r}")

    def function(self, name: str) -> Any:
        if name == "SUM":
            total = 0.0
            while True:
                token = self.peek()
                if token and token[0] == "range":
                    self.take()
                    total += sum(
                        _num(v) for v in self.range_values(token[1]) if not isinstance(v, str)
                    )
                else:
                    value = self.comparison()
                    total += 0.0 if isinstance(value, str) else _num(value)
                _, value = self.take()
                if value == ")":
                    return total
                if value != ",":
                    raise FormulaError("expected , or ) in SUM")
        if name == "IF":
            condition = self.comparison()
            self.expect(",")
            when_true = self.comparison()
            self.expect(",")
            when_false = self.comparison()
            self.expect(")")
            return when_true if condition else when_false
        raise FormulaError(f"unsupported function {name}")

    def range_values(self, text: str) -> list[Any]:
        first, last = text.replace("$", "").split(":")
        c1, r1 = coordinate_from_string(first)
        c2, r2 = coordinate_from_string(last)
        i1, i2 = column_index_from_string(c1), column_index_from_string(c2)
        return [
            self.cell(f"{get_column_letter(c)}{r}")
            for r in range(min(r1, r2), max(r1, r2) + 1)
            for c in range(min(i1, i2), max(i1, i2) + 1)
        ]


def evaluate(formula: str, cell: Callable[[str], Any]) -> Any:
    """Evaluate ``formula`` (with or without the leading ``=``) using ``cell`` lookups."""
    text = formula[1:] if formula.startswith("=") else formula
    parser = _Parser(_tokens(text), cell)
    value = parser.comparison()
    if parser.peek() is not None:
        raise FormulaError(f"unexpected trailing tokens in {formula!r}")
    return value


class SheetEvaluator:
    """Evaluate any cell of an openpyxl worksheet, following formula references."""

    def __init__(self, worksheet: Any):
        self.ws = worksheet
        self.cache: dict[str, Any] = {}
        self.active: set[str] = set()

    def value(self, coordinate: str) -> Any:
        if coordinate in self.cache:
            return self.cache[coordinate]
        if coordinate in self.active:
            raise FormulaError(f"circular reference at {coordinate}")
        raw = self.ws[coordinate].value
        if isinstance(raw, str) and raw.startswith("="):
            self.active.add(coordinate)
            try:
                result = evaluate(raw, self.value)
            finally:
                self.active.discard(coordinate)
        else:
            result = raw
        self.cache[coordinate] = result
        return result
