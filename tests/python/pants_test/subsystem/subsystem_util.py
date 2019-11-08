# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.deprecated import deprecated_module
from pants.testutil.subsystem.util import global_subsystem_instance as global_subsystem_instance  # noqa
from pants.testutil.subsystem.util import init_subsystem as init_subsystem  # noqa
from pants.testutil.subsystem.util import init_subsystems as init_subsystems  # noqa


deprecated_module(
  removal_version="1.25.0.dev0",
  hint_message="Import pants.testutil.subsystem.util instead."
)
