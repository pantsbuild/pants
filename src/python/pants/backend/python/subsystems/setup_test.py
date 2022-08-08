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
