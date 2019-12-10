# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.task_test_base import ConsoleTaskTestBase as ConsoleTaskTestBase  # noqa
from pants.testutil.task_test_base import DeclarativeTaskTestMixin as DeclarativeTaskTestMixin  # noqa
from pants.testutil.task_test_base import TaskTestBase as TaskTestBase  # noqa
from pants.testutil.task_test_base import ensure_cached as ensure_cached  # noqa
from pants.testutil.task_test_base import is_exe as is_exe  # noqa
from pants_test.deprecated_testinfra import deprecated_testinfra_module


deprecated_testinfra_module()
