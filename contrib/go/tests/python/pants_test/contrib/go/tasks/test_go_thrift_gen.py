# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.thrift.lib.thrift import Thrift
from pants.base.exceptions import TaskError
from pants.testutil.task_test_base import TaskTestBase

from pants.contrib.go.tasks.go_thrift_gen import GoThriftGen


class GoThriftGenTest(TaskTestBase):
    @classmethod
    def task_type(cls):
        return GoThriftGen

    def _validate_for(self, version):
        options = {Thrift.options_scope: {"version": version}}
        self.create_task(self.context(options=options))._validate_supports_more_than_one_source()

    def test_validate_source_too_low(self):
        self.set_options(multiple_files_per_target_override=False)
        with self.assertRaises(TaskError):
            self._validate_for("0.9.0")

    def test_validate_source_too_low_but_overridden(self):
        self.set_options(multiple_files_per_target_override=True)
        self._validate_for("0.9.0")

    def test_validate_source_unparseable_but_overridden(self):
        self.set_options(multiple_files_per_target_override=True)
        self._validate_for("not_a_semver_version")

    def test_validate_source_sufficient(self):
        self.set_options(multiple_files_per_target_override=False)
        self._validate_for("0.10.1")
