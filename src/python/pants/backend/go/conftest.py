# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from functools import lru_cache

import pytest


@lru_cache(None)
def _go_present() -> bool:
    try:
        subprocess.run(
            ["go", "version"], check=False, env={"PATH": os.getenv("PATH") or ""}
        ).returncode
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return True


def pytest_runtest_setup(item: pytest.Item) -> None:
    if not _go_present():
        pytest.skip(reason="`go` not present on PATH")
