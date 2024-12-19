# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from typing import List

import pytest

from pants.testutil.pants_integration_test import run_pants


def discover_backends() -> List[str]:
    register_pys = Path().glob("src/python/**/register.py")
    backends = {
        str(register_py.parent).replace("src/python/", "").replace("/", ".")
        for register_py in register_pys
    }
    assert len(backends) > 10
    always_activated = {"pants.core", "pants.backend.project_info"}
    return sorted(backends - always_activated)


def assert_backends_load(backends: List[str]) -> None:
    run_pants(
        ["--no-verify-config", "help-all"], config={"GLOBAL": {"backend_packages": backends}}
    ).assert_success(f"Failed to load: {backends}")


def test_no_backends_loaded() -> None:
    assert_backends_load([])


def test_all_backends_loaded() -> None:
    """This should catch all ambiguity issues."""
    all_backends = discover_backends()
    assert_backends_load(all_backends)


@pytest.mark.parametrize("backend", discover_backends())
def test_each_distinct_backend_loads(backend) -> None:
    """This should catch graph incompleteness errors, i.e. when a required rule is not
    registered."""
    # The `typescript` backend uses rules from the `javascript` backend, and it therefore
    # should be loaded together with it for the relevant rules to be discovered.
    if "typescript" in backend:
        backend = ["pants.backend.experimental.javascript", "pants.backend.experimental.typescript"]
    else:
        backend = [backend]
    assert_backends_load(backend)
