# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.deprecated import deprecated_module
from pants.testutil.base.context_utils import TestContext as TestContext  # noqa
from pants.testutil.base.context_utils import (
  create_context_from_options as create_context_from_options,
)  # noqa


deprecated_module(
  removal_version="1.25.0.dev0",
  hint_message="Import pants.testutil.base.context_utils instead."
)
