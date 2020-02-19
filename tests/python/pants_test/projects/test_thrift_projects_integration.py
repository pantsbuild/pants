# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants_test.projects.projects_test_base import ProjectsTestBase


class TestThriftProjectsIntegration(ProjectsTestBase):
    def test_thrift_projects(self) -> None:
        self.assert_valid_projects("examples/src/thrift::", "testprojects/src/thrift::")
