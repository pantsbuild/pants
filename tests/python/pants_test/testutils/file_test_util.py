# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.deprecated import deprecated_module
from pants.testutil.file_test_util import check_file_content as check_file_content  # noqa
from pants.testutil.file_test_util import check_symlinks as check_symlinks  # noqa
from pants.testutil.file_test_util import contains_exact_files as contains_exact_files  # noqa
from pants.testutil.file_test_util import exact_files as exact_files  # noqa


deprecated_module(
  removal_version="1.25.0.dev0",
  hint_message="Import pants.testutil.file_test_util instead."
)
