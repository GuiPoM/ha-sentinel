"""Pure tests for the Recorder-safe problem payload builder."""
from __future__ import annotations

import json
import importlib.util
from pathlib import Path


_MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "sentinel" / "problem_payload.py"
_SPEC = importlib.util.spec_from_file_location("problem_payload", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
build_problem_attributes = _MODULE.build_problem_attributes


BUDGET = 12 * 1024


def make_problem(index: int, reason: str = "Device unavailable") -> dict:
    """Build a compact problem dictionary."""
    return {
        "id": f"device_{index}",
        "name": f"Device {index}",
        "provider": "devices",
        "state": "unavailable",
        "reason": reason,
    }


def payload_size(attributes: dict) -> int:
    """Return the UTF-8 JSON size used by the pure builder."""
    return len(json.dumps(attributes, ensure_ascii=False, separators=(",", ":")).encode())


def test_large_reason_does_not_hide_later_problem() -> None:
    """A huge middle reason is truncated and later problems remain visible."""
    attributes = build_problem_attributes(
        [make_problem(0), make_problem(1, "x" * 100_000), make_problem(2)], BUDGET
    )

    assert len(attributes["problems"]) == 3
    assert attributes["problems_truncated"] is False
    assert attributes["problems"][1]["reason_truncated"] is True
    assert attributes["problems"][2]["id"] == "device_2"
    assert payload_size(attributes) <= BUDGET


def test_many_short_problems_use_size_budget() -> None:
    """Short problems are included until the byte budget is reached."""
    problems = []
    while True:
        problems.append(make_problem(len(problems)))
        attributes = build_problem_attributes(problems, BUDGET)
        if attributes["problems_truncated"]:
            break

    assert attributes["problems_total"] == len(problems)
    assert 0 < len(attributes["problems"]) < len(problems)
    assert payload_size(attributes) <= BUDGET


def test_oversized_fixed_fields_stop_the_list() -> None:
    """A problem whose fixed fields cannot fit is omitted safely."""
    problem = make_problem(0)
    problem["name"] = "x" * 20_000
    attributes = build_problem_attributes([problem], BUDGET)

    assert attributes["problems"] == []
    assert attributes["problems_total"] == 1
    assert attributes["problems_truncated"] is True
    assert payload_size(attributes) <= BUDGET
