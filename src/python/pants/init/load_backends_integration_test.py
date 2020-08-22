# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from typing import List

from pants.testutil.pants_integration_test import PantsIntegrationTest


class LoadBackendsIntegrationTest(PantsIntegrationTest):
    """Ensure that the rule graph can be loaded properly for each backend."""

    @staticmethod
    def discover_backends() -> List[str]:
        register_pys = Path().glob("src/python/**/register.py")
        backends = {
            str(register_py.parent).replace("src/python/", "").replace("/", ".")
            for register_py in register_pys
        }
        always_activated = {"pants.core", "pants.backend.project_info", "pants.backend.pants_info"}
        return sorted(backends - always_activated)

    def assert_backends_load(self, backends: List[str]) -> None:
        result = self.run_pants(
            ["--no-verify-config", "--version"], config={"GLOBAL": {"backend_packages": backends}}
        )
        self.assert_success(result, msg=f"Failed to load: {backends}")

    def test_no_backends_loaded(self) -> None:
        self.assert_backends_load([])

    def test_all_backends_loaded(self) -> None:
        """This should catch all ambiguity issues."""
        all_backends = self.discover_backends()
        self.assert_backends_load(all_backends)

    def test_each_distinct_backend_loads(self) -> None:
        """This should catch graph incompleteness errors, i.e. when a required rule is not
        registered."""
        for backend in self.discover_backends():
            self.assert_backends_load([backend])
