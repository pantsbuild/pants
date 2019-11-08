# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.deprecated import deprecated_module
from pants.testutil.pexrc_util import (
  setup_pexrc_with_pex_python_path as setup_pexrc_with_pex_python_path,
)  # noqa


deprecated_module(
  removal_version="1.25.0.dev0",
  hint_message="Import pants.testutil.pexrc_util instead."
)
