# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import subprocess
from functools import lru_cache

import pytest

from pants.engine.platform import Platform

@lru_cache
def skip_if_command_errors(*args: str):
    def empty_decorator(func):
        return func

    try:
        subprocess.run(list(args), check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return pytest.mark.skip(reason="command failed")

    return empty_decorator

def skip_if_linux_arm64(func):
    """Skip the test if running on linux-arm64."""
    if Platform.create_for_localhost() == Platform.linux_arm64:
        return pytest.mark.skip(reason="Test cannot run on Linux ARM64. Skipping.")(func)
    else:
        def empty_decorator(func):
            return func
        return empty_decorator(func)

requires_go = skip_if_command_errors("go", "version")
requires_thrift = skip_if_command_errors("thrift", "-version")
