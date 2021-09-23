# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

import pytest


def maybe_skip_jdk_test(func):
    return pytest.mark.skipif("PANTS_RUN_JDK_TESTS" not in os.environ, reason="Skip JDK tests")(
        func
    )
