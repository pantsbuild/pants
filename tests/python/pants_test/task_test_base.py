# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.deprecated import deprecated_module
from pants.testutil.task_test_base import ConsoleTaskTestBase as ConsoleTaskTestBase  # noqa
from pants.testutil.task_test_base import DeclarativeTaskTestMixin as DeclarativeTaskTestMixin  # noqa
from pants.testutil.task_test_base import TaskTestBase as TaskTestBase  # noqa
from pants.testutil.task_test_base import ensure_cached as ensure_cached  # noqa
from pants.testutil.task_test_base import is_exe as is_exe  # noqa


deprecated_module(
  removal_version="1.25.0.dev0",
  hint_message="Import pants.testutil.task_test_base from the pantsbuild.pants.testutil "
               "distribution instead."
)
