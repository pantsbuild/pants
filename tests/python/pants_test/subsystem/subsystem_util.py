# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.subsystem.util import global_subsystem_instance as global_subsystem_instance  # noqa
from pants.testutil.subsystem.util import init_subsystem as init_subsystem  # noqa
from pants.testutil.subsystem.util import init_subsystems as init_subsystems  # noqa
from pants_test.deprecated_testinfra import deprecated_testinfra_module


deprecated_testinfra_module('pants.testutil.subsystem.util')
