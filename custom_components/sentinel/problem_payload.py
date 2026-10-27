"""Build Recorder-safe problem attributes without Home Assistant dependencies."""
from __future__ import annotations

import json
from typing import Any


def _json_size(value: Any) -> int:
    """Return the UTF-8 JSON size used for the payload budget."""
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def _fits(attributes: dict[str, Any], problem: dict[str, Any], budget: int) -> bool:
    """Return whether adding a problem stays within the budget."""
    attributes["problems"].append(problem)
    fits = _json_size(attributes) <= budget
    attributes["problems"].pop()
    return fits


def _minimum_problem(problem: dict[str, Any]) -> dict[str, Any]:
    """Return the smallest representation that preserves reason truncation."""
    if problem.get("reason") is None:
        return problem
    return {**problem, "reason": None, "reason_truncated": True}


def _fits_with_remaining(
    attributes: dict[str, Any],
    problem: dict[str, Any],
    remaining: list[dict[str, Any]],
    budget: int,
) -> bool:
    """Return whether a problem and minimum later entries fit together."""
    attributes["problems"].append(problem)
    added = 1
    if _json_size(attributes) > budget:
        attributes["problems"].pop()
        return False

    for candidate in remaining:
        minimum = _minimum_problem(candidate)
        attributes["problems"].append(minimum)
        added += 1
        if _json_size(attributes) > budget:
            attributes["problems"].pop()
            for _ in range(added - 1):
                attributes["problems"].pop()
            return False

    for _ in range(added):
        attributes["problems"].pop()
    return True


def _fit_reason(
    attributes: dict[str, Any],
    problem: dict[str, Any],
    remaining: list[dict[str, Any]],
    budget: int,
) -> dict[str, Any] | None:
    """Return the longest reason prefix that leaves room for later entries."""
    reason = problem.get("reason")
    if not isinstance(reason, str):
        return None

    low = 0
    high = len(reason)
    best = None
    while low <= high:
        length = (low + high) // 2
        candidate = {
            **problem,
            "reason": reason[:length] + "…",
            "reason_truncated": True,
        }
        if _fits_with_remaining(attributes, candidate, remaining, budget):
            best = candidate
            low = length + 1
        else:
            high = length - 1
    return best


def build_problem_attributes(
    problems: list[dict[str, Any]], budget: int
) -> dict[str, Any]:
    """Return Recorder-safe attributes for unhealthy problem dictionaries."""
    attributes: dict[str, Any] = {
        "problems": [],
        "problems_total": len(problems),
        "problems_truncated": False,
    }

    for index, problem in enumerate(problems):
        if _fits(attributes, problem, budget):
            attributes["problems"].append(problem)
            continue

        remaining = problems[index + 1 :]
        candidate = _fit_reason(attributes, problem, remaining, budget)
        if candidate is None:
            candidate = _minimum_problem(problem)
            if not _fits(attributes, candidate, budget):
                attributes["problems_truncated"] = True
                break
        attributes["problems"].append(candidate)

    attributes["problems_truncated"] = len(attributes["problems"]) < len(problems)
    return attributes
