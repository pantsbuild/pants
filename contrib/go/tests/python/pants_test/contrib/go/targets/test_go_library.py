# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.test_base import TestBase
from pants_test.contrib.go.targets.go_local_source_test_base import GoLocalSourceTestBase

from pants.contrib.go.targets.go_library import GoLibrary


class GoLibraryTest(GoLocalSourceTestBase, TestBase):
    @property
    def target_type(self):
        return GoLibrary
