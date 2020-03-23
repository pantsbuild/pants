# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.jvm.nailgun_task_test_base import NailgunTaskTestBase

from pants.contrib.errorprone.tasks.errorprone import ErrorProne


class ErrorProneTest(NailgunTaskTestBase):
    @classmethod
    def task_type(cls):
        return ErrorProne

    def test_no_sources(self):
        task = self.prepare_execute(self.context())
        self.assertEqual(None, task.execute())
