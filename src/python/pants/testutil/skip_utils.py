# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import subprocess
from functools import lru_cache

import pytest


@lru_cache
def skip_if_command_errors(*args: str):
    def empty_decorator(func):
        return func

    try:
        subprocess.run(list(args), check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return pytest.mark.skip(reason="command failed")

    return empty_decorator


requires_go = skip_if_command_errors("go", "version")
requires_thrift = skip_if_command_errors("thrift", "-version")
