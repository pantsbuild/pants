# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python.subsystems.setup import PythonSetup
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
            resolves={"a": "a.lock", "tool1": "tool1.lock", "tool2": "tool2.lock"},
            resolves_to_constraints_file=resolves_to_constraints_file,
        ).resolves_to_constraints_file()

    assert create({"a": "c1.txt", "tool1": "c2.txt"}) == {"a": "c1.txt", "tool1": "c2.txt"}
    assert create({"__default__": "c.txt", "tool2": "override.txt"}) == {
        "a": "c.txt",
        "tool1": "c.txt",
        "tool2": "override.txt",
    }
    with pytest.raises(UnrecognizedResolveNamesError):
        create({"fake": "c.txt"})


def test_resolves_to_no_binary_and_only_binary() -> None:
    def create(resolves_to_projects: dict[str, list[str]]) -> dict[str, list[str]]:
        subsystem = create_subsystem(
            PythonSetup,
            resolves={"a": "a.lock", "tool1": "tool1.lock", "tool2": "tool2.lock"},
            resolves_to_no_binary=resolves_to_projects,
            resolves_to_only_binary=resolves_to_projects,
        )
        only_binary = subsystem.resolves_to_only_binary()
        no_binary = subsystem.resolves_to_no_binary()
        assert only_binary == no_binary
        return only_binary

    assert create({"a": ["p1"], "tool1": ["p2"]}) == {
        "a": ["p1"],
        "tool1": ["p2"],
    }
    assert create({"__default__": ["p1"], "tool2": ["override"]}) == {
        "a": ["p1"],
        "tool1": ["p1"],
        "tool2": ["override"],
    }
    # Test that we don't fail on :all:.
    assert create({"a": [":all:"], "tool1": [":all:"]}) == {
        "a": [":all:"],
        "tool1": [":all:"],
    }
    # Test name canonicalization.
    assert create({"a": ["foo.BAR"], "tool1": ["Baz_Qux"]}) == {
        "a": ["foo-bar"],
        "tool1": ["baz-qux"],
    }
    with pytest.raises(UnrecognizedResolveNamesError):
        create({"fake": []})
