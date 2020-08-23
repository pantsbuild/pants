# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional

from pants.backend.project_info import list_roots
from pants.backend.project_info.list_roots import Roots
from pants.testutil.test_base import TestBase


class RootsTest(TestBase):
    @classmethod
    def rules(cls):
        return [*super().rules(), *list_roots.rules()]

    def assert_roots(
        self,
        configured: List[str],
        *,
        marker_files: Optional[List[str]] = None,
        expected: Optional[List[str]] = None,
    ) -> None:
        result = self.run_goal_rule(
            Roots,
            args=[
                f"--source-root-patterns={configured}",
                f"--source-marker-filenames={marker_files or []}",
            ],
        )
        assert result.stdout.splitlines() == sorted(expected or configured)

    def test_single_source_root(self) -> None:
        self.create_dir("fakeroot")
        self.assert_roots(["fakeroot"])

    def test_multiple_source_roots(self) -> None:
        self.create_dir("fakerootA")
        self.create_dir("fakerootB")
        self.assert_roots(["fakerootA", "fakerootB"])

    def test_buildroot_is_source_root(self) -> None:
        self.assert_roots(["/"], expected=["."])

    def test_marker_file(self) -> None:
        self.create_file("fakerootA/SOURCE_ROOT")
        self.create_file("fakerootB/setup.py")
        self.assert_roots(
            configured=[],
            marker_files=["SOURCE_ROOT", "setup.py"],
            expected=["fakerootA", "fakerootB"],
        )
