# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.process.subprocess import Subprocess
from pants.testutil.subsystem.util import global_subsystem_instance
from pants.testutil.test_base import TestBase


class SubprocessTest(TestBase):
    def subprocess(self):
        return global_subsystem_instance(Subprocess.Factory).create()

    def test_get_subprocess_dir(self):
        self.assertTrue(self.subprocess().get_subprocess_dir().endswith("/.pids"))
