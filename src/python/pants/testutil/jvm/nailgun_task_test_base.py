# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.testutil.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase


class NailgunTaskTestBase(JvmToolTaskTestBase):
    """Ensures `NailgunTask` tests use subprocess mode to stably test the task under test.

    For subclasses of NailgunTask the nailgun behavior is irrelevant to the code under test and can
    cause problems in CI environments. As such, disabling nailgunning ensures the test focus is where
    it needs to be to test the unit.

    :API: public
    """

    def setUp(self):
        """
        :API: public
        """
        super().setUp()
        self.set_options(execution_strategy=NailgunTask.ExecutionStrategy.subprocess)
