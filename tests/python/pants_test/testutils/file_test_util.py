# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.file_test_util import check_file_content as check_file_content  # noqa
from pants.testutil.file_test_util import check_symlinks as check_symlinks  # noqa
from pants.testutil.file_test_util import contains_exact_files as contains_exact_files  # noqa
from pants.testutil.file_test_util import exact_files as exact_files  # noqa
from pants_test.deprecated_testinfra import deprecated_testinfra_module


deprecated_testinfra_module('pants.testutil.file_test_util')
