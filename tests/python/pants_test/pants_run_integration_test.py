# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_run_integration_test import PantsJoinHandle as PantsJoinHandle  # noqa
from pants.testutil.pants_run_integration_test import PantsResult as PantsResult  # noqa
from pants.testutil.pants_run_integration_test import (
  PantsRunIntegrationTest as PantsRunIntegrationTest,
)  # noqa
from pants.testutil.pants_run_integration_test import ensure_cached as ensure_cached  # noqa
from pants.testutil.pants_run_integration_test import ensure_daemon as ensure_daemon  # noqa
from pants.testutil.pants_run_integration_test import ensure_resolver as ensure_resolver  # noqa
from pants.testutil.pants_run_integration_test import read_pantsd_log as read_pantsd_log  # noqa
from pants.testutil.pants_run_integration_test import render_logs as render_logs  # noqa
from pants_test.deprecated_testinfra import deprecated_testinfra_module


deprecated_testinfra_module()
