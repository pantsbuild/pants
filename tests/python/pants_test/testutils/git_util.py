# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.git_util import MIN_REQUIRED_GIT_VERSION as MIN_REQUIRED_GIT_VERSION  # noqa
from pants.testutil.git_util import git_version as git_version  # noqa
from pants.testutil.git_util import initialize_repo as initialize_repo  # noqa
from pants_test.deprecated_testinfra import deprecated_testinfra_module


deprecated_testinfra_module('pants.testutil.git_util')
