# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from typing import List

from pants.testutil.pants_integration_test import run_pants


def discover_backends() -> List[str]:
    register_pys = Path().glob("src/python/**/register.py")
    backends = {
        str(register_py.parent).replace("src/python/", "").replace("/", ".")
        for register_py in register_pys
        # TODO: See https://github.com/pantsbuild/pants/issues/10683.
        if register_py != Path("src/python/pants/backend/codegen/protobuf/python/register.py")
    }
    always_activated = {"pants.core", "pants.backend.project_info", "pants.backend.pants_info"}
    return sorted(backends - always_activated)


def assert_backends_load(backends: List[str]) -> None:
    run_pants(
        ["--no-verify-config", "--version"], config={"GLOBAL": {"backend_packages": backends}}
    ).assert_success(f"Failed to load: {backends}")


def test_no_backends_loaded() -> None:
    assert_backends_load([])


def test_all_backends_loaded() -> None:
    """This should catch all ambiguity issues."""
    all_backends = discover_backends()
    assert_backends_load(all_backends)


def test_each_distinct_backend_loads() -> None:
    """This should catch graph incompleteness errors, i.e. when a required rule is not
    registered."""
    for backend in discover_backends():
        assert_backends_load([backend])
