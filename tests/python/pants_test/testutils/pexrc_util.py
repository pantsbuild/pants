# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pexrc_util import (
  setup_pexrc_with_pex_python_path as setup_pexrc_with_pex_python_path,
)  # noqa
from pants_test.deprecated_testinfra import deprecated_testinfra_module


deprecated_testinfra_module('pants.testutil.pexrc_util')
