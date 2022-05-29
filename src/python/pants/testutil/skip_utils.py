# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import subprocess
from functools import lru_cache

import pytest


@lru_cache()
def skip_if_error(*args: str):
    try:
        subprocess.run(list(args), check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return pytest.mark.skip(reason="command failed")


requires_go = skip_if_error("go", "version")
requires_thrift = skip_if_error("thrift", "-version")
