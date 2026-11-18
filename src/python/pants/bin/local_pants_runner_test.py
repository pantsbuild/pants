# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from types import SimpleNamespace
from typing import Any, cast

from pants.bin.local_pants_runner import LocalPantsRunner


def _options(goals: tuple[str, ...], builtin_or_auxiliary_goal: str | None = None) -> Any:
    return SimpleNamespace(goals=list(goals), builtin_or_auxiliary_goal=builtin_or_auxiliary_goal)


def test_requested_goals() -> None:
    assert LocalPantsRunner._requested_goals(_options(("lint", "test")), None) == ("lint", "test")
    assert LocalPantsRunner._requested_goals(_options((), "help"), None) == ("help",)

    ng_invocation = cast(Any, SimpleNamespace(goals=lambda: ["check"]))
    assert LocalPantsRunner._requested_goals(_options(("lint",)), ng_invocation) == ("check",)
