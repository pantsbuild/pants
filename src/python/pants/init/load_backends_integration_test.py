# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

import pytest

from pants.testutil.pants_integration_test import run_pants


def discover_backends() -> list[str]:
    register_pys = Path().glob("src/python/**/register.py")
    backends = {
        str(register_py.parent).replace("src/python/", "").replace("/", ".")
        for register_py in register_pys
    }
    assert len(backends) > 10
    always_activated = {"pants.core", "pants.backend.project_info"}
    return sorted(backends - always_activated)


def assert_backends_load(backends: list[str]) -> None:
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


def test_plugin_with_dependencies() -> None:
    testproject_backend_pkg_name = "test_pants_plugin"

    pants_run = run_pants(
        [
            "--no-pantsd",
            f"--backend-packages=['{testproject_backend_pkg_name}']",
            "help",
        ],
        config={"GLOBAL": {"pythonpath": ["%(buildroot)s/testprojects/pants-plugins/src/python"]}},
        extra_env={
            "_IMPORT_REQUIREMENT": "True",
        },
    )
    pants_run.assert_success()
