# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.python.rules.python_test_runner import get_timeout_seconds_for_target


@pytest.mark.parametrize(
  "target_timeout,default_timeout,maximum_timeout,result",
  [
    (10, 1, 2, 2), # configured timeout greater than maximum --> maximum
    (2, 1, 2, 2), # configured timeout OK --> configured timeout
    (None, 1, 2, 1), # target has no configured timeout --> default
    (None, 10, 2, 2), # target has no configured timeout and default is greater than maximum --> maximum
  ])
def test_get_timeout_seconds_for_target(target_timeout, default_timeout, maximum_timeout, result):
  assert get_timeout_seconds_for_target(target_timeout, default_timeout, maximum_timeout) == result
