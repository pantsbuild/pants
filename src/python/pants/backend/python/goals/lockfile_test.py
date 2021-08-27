# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python.goals.lockfile import (
    PythonLockfileRequest,
    UnrecognizedResolveNamesError,
    determine_resolves_to_generate,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.util.ordered_set import FrozenOrderedSet


def test_determine_resolves_to_generate() -> None:
    def create_request(name: str) -> PythonLockfileRequest:
        return PythonLockfileRequest(
            FrozenOrderedSet(),
            InterpreterConstraints(),
            resolve_name=name,
            lockfile_dest=f"{name}.txt",
        )

    tool1 = create_request("tool1")
    tool2 = create_request("tool2")
    tool3 = create_request("tool3")

    def assert_chosen(requested: list[str], expected: list[PythonLockfileRequest]) -> None:
        assert list(determine_resolves_to_generate([tool1, tool2, tool3], requested)) == expected

    assert_chosen([tool2.resolve_name], [tool2])
    assert_chosen([tool1.resolve_name, tool3.resolve_name], [tool1, tool3])

    # If none are specifically requested, return all possible.
    assert_chosen([], [tool1, tool2, tool3])

    with pytest.raises(UnrecognizedResolveNamesError) as exc:
        assert_chosen(["fake"], [])
    assert (
        "Unrecognized resolve name from the option `[generate-lockfiles].resolves`: fake\n\n"
        "All valid resolve names: ['tool1', 'tool2', 'tool3']"
    ) in str(exc.value)

    with pytest.raises(UnrecognizedResolveNamesError) as exc:
        assert_chosen(["fake1", "fake2"], [])
    assert (
        "Unrecognized resolve names from the option `[generate-lockfiles].resolves`: "
        "['fake1', 'fake2']"
    ) in str(exc.value)
