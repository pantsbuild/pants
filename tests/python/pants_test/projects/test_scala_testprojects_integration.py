# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants_test.projects.projects_test_base import ProjectsTestBase


@pytest.mark.skip(reason="https://github.com/pantsbuild/pants/issues/9350")
class TestScalaTestprojectsIntegration(ProjectsTestBase):
    def test_scala_testprojects(self) -> None:
        self.assert_valid_projects("testprojects/src/scala::", "testprojects/tests/scala::")
