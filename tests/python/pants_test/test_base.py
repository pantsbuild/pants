# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.test_base import AbstractTestGenerator as AbstractTestGenerator  # noqa
from pants.testutil.test_base import TestBase as TestBase  # noqa
from pants_test.deprecated_testinfra import deprecated_testinfra_module


deprecated_testinfra_module()
