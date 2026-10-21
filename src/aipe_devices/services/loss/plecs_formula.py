"""Restricted evaluator for the gate-resistance scaling expressions stored by PLECS adapters.

The exporters never execute manufacturer formulas. Loss evaluation needs the stored
``Table and formula`` expressions only to scale a tabulated energy ``E`` with the
external gate resistance (``Rgon``/``Rgoff``). The grammar below accepts numbers,
named variables, ``+ - * / ^`` and parentheses, nothing else; ``lookup(...)`` and any
other call is rejected so that no arbitrary expression is ever evaluated.
"""

import re

_TOKEN = re.compile(r"\s*(?:(\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?|([A-Za-z_][A-Za-z0-9_]*)|(.))")


class FormulaError(ValueError):
    pass


def _tokenize(text):
    tokens = []
    position = 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if not match or match.end() == position:
            raise FormulaError(f"Unsupported formula text near {text[position : position + 10]!r}")
        position = match.end()
        number, name, other = match.groups()
        if number is not None:
            tokens.append(("number", float(match.group(0))))
        elif name is not None:
            tokens.append(("name", name))
        elif other.strip():
            if other not in "+-*/^()":
                raise FormulaError(f"Unsupported operator {other!r} in formula")
            tokens.append(("op", other))
    return tokens


class _Parser:
    def __init__(self, tokens, variables):
        self.tokens = tokens
        self.variables = variables
        self.index = 0

    def peek(self):
        return self.tokens[self.index] if self.index < len(self.tokens) else (None, None)

    def take(self):
        token = self.peek()
        self.index += 1
        return token

    def expression(self):
        value = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            _, operator = self.take()
            right = self.term()
            value = value + right if operator == "+" else value - right
        return value

    def term(self):
        value = self.power()
        while self.peek() in (("op", "*"), ("op", "/")):
            _, operator = self.take()
            right = self.power()
            if operator == "/":
                if right == 0:
                    raise FormulaError("Division by zero in formula")
                value = value / right
            else:
                value = value * right
        return value

    def power(self):
        base = self.unary()
        if self.peek() == ("op", "^"):
            self.take()
            exponent = self.power()
            return base**exponent
        return base

    def unary(self):
        if self.peek() == ("op", "-"):
            self.take()
            return -self.unary()
        if self.peek() == ("op", "+"):
            self.take()
            return self.unary()
        return self.primary()

    def primary(self):
        kind, value = self.take()
        if kind == "number":
            return value
        if kind == "name":
            if self.peek() == ("op", "("):
                raise FormulaError(f"Function calls such as {value}() are not evaluated")
            if value not in self.variables:
                raise FormulaError(f"Unknown formula variable {value}")
            return float(self.variables[value])
        if kind == "op" and value == "(":
            inner = self.expression()
            if self.take() != ("op", ")"):
                raise FormulaError("Unbalanced parentheses in formula")
            return inner
        raise FormulaError("Malformed formula")


def formula_variables(formula: str) -> set[str]:
    """Identifiers referenced by a formula (numbers such as ``8e-8`` are not identifiers)."""
    return {value for kind, value in _tokenize(formula) if kind == "name"}


def evaluate_formula(formula: str, variables: dict[str, float]) -> float:
    """Evaluate a restricted arithmetic expression; raises FormulaError for anything else."""
    tokens = _tokenize(formula)
    if not tokens:
        raise FormulaError("Empty formula")
    parser = _Parser(tokens, variables)
    value = parser.expression()
    if parser.index != len(parser.tokens):
        raise FormulaError("Unexpected trailing formula tokens")
    return value


def gate_resistance_factor(formula: str, variable: str, gate_resistance: float) -> float:
    """Return E(Rg)/E_table for a formula proportional to the tabulated energy ``E``."""
    one = evaluate_formula(formula, {"E": 1.0, variable: gate_resistance})
    two = evaluate_formula(formula, {"E": 2.0, variable: gate_resistance})
    if abs(two - 2 * one) > 1e-9 * max(1.0, abs(two)):
        raise FormulaError("Formula is not proportional to the tabulated energy")
    if one < 0:
        raise FormulaError("Formula yields a negative energy scaling factor")
    return one
