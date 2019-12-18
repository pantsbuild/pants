# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.base.context_utils import TestContext as TestContext  # noqa
from pants.testutil.base.context_utils import (
  create_context_from_options as create_context_from_options,
)  # noqa
from pants_test.deprecated_testinfra import deprecated_testinfra_module


deprecated_testinfra_module()
