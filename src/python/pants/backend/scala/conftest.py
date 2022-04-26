# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.testutil.lockfile_fixture import JvmLockfilePlugin


def pytest_configure(config):
    config.pluginmanager.register(JvmLockfilePlugin())
