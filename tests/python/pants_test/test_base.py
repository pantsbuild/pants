# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.deprecated import deprecated_module
from pants.testutil.test_base import AbstractTestGenerator as AbstractTestGenerator  # noqa
from pants.testutil.test_base import TestBase as TestBase  # noqa


deprecated_module(
  removal_version="1.25.0.dev0",
  hint_message="Import pants.testutil.test_base instead."
)
