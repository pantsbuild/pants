# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python.subsystems.setup import RESOLVE_OPTION_KEY__NO_USER_RESOLVE, PythonSetup
from pants.core.goals.generate_lockfiles import UnrecognizedResolveNamesError
from pants.testutil.option_util import create_subsystem


def test_resolves_to_interpreter_constraints_validation() -> None:
    def create(resolves_to_ics: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
        return create_subsystem(
            PythonSetup,
            resolves={"a": "a.lock"},
            resolves_to_interpreter_constraints=resolves_to_ics,
        ).resolves_to_interpreter_constraints

    assert create({"a": ["==3.7.*"]}) == {"a": ("==3.7.*",)}
    with pytest.raises(UnrecognizedResolveNamesError):
        create({"fake": []})


def test_resolves_to_constraints_file() -> None:
    def create(resolves_to_constraints_file: dict[str, str]) -> dict[str, str]:
        return create_subsystem(
            PythonSetup,
            resolves={"a": "a.lock"},
            resolves_to_constraints_file=resolves_to_constraints_file,
        ).resolves_to_constraints_file(all_python_tool_resolve_names=("tool1", "tool2"))

    assert create({"a": "c1.txt", "tool1": "c2.txt"}) == {"a": "c1.txt", "tool1": "c2.txt"}
    assert create({"__default__": "c.txt", "tool2": "override.txt"}) == {
        "a": "c.txt",
        RESOLVE_OPTION_KEY__NO_USER_RESOLVE: "c.txt",
        "tool1": "c.txt",
        "tool2": "override.txt",
    }
    with pytest.raises(UnrecognizedResolveNamesError):
        create({"fake": "c.txt"})
