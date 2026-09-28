"""
Auswertung der Condition-DSL (§6.1). Autoritativ im Backend.

Die Wohlgeformtheit wird beim Speichern einer Definition geprüft
(schemas.process_definition.validate_condition); hier wird ausgewertet.
Feld-Refs sind Dot-Path-Keys direkt in die (flach gespeicherten) Ticket-Werte.
"""
from typing import Any


def evaluate(cond: dict, values: dict) -> bool:
    """Wertet einen (wohlgeformten) DSL-Ausdruck gegen die Ticket-Werte aus."""
    if not isinstance(cond, dict) or len(cond) != 1:
        return False
    op, arg = next(iter(cond.items()))
    if op == "==":
        return _ref(values, arg[0]) == arg[1]
    if op == "!=":
        return _ref(values, arg[0]) != arg[1]
    if op == "in":
        return _ref(values, arg[0]) in arg[1]
    if op == "truthy":
        return bool(_ref(values, arg))
    if op == "and":
        return all(evaluate(c, values) for c in arg)
    if op == "or":
        return any(evaluate(c, values) for c in arg)
    if op == "not":
        return not evaluate(arg, values)
    return False


def _ref(values: dict, ref: str) -> Any:
    return values.get(ref)
