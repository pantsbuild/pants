# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.deprecated import deprecated_module
from pants.testutil.process_test_util import ProcessStillRunning as ProcessStillRunning  # noqa
from pants.testutil.process_test_util import TrackedProcessesContext as TrackedProcessesContext  # noqa
from pants.testutil.process_test_util import _make_process_table as _make_process_table  # noqa
from pants.testutil.process_test_util import (
  _safe_iter_matching_processes as _safe_iter_matching_processes,
)  # noqa
from pants.testutil.process_test_util import (
  no_lingering_process_by_command as no_lingering_process_by_command,
)  # noqa


deprecated_module(
  removal_version="1.25.0.dev0",
  hint_message="Import pants.testutil.process_test_util instead."
)
