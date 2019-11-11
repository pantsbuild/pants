# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.deprecated import deprecated_module
from pants.testutil.engine.util import TARGET_TABLE as TARGET_TABLE  # noqa
from pants.testutil.engine.util import MockConsole as MockConsole  # noqa
from pants.testutil.engine.util import Target as Target  # noqa
from pants.testutil.engine.util import assert_equal_with_printing as assert_equal_with_printing  # noqa
from pants.testutil.engine.util import create_scheduler as create_scheduler  # noqa
from pants.testutil.engine.util import init_native as init_native  # noqa
from pants.testutil.engine.util import (
  remove_locations_from_traceback as remove_locations_from_traceback,
)  # noqa
from pants.testutil.engine.util import run_rule as run_rule  # noqa


deprecated_module(
  removal_version="1.25.0.dev0",
  hint_message="Import pants.testutil.engine.util instead."
)
