# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.python.subsystems.debugpy import DebugPy


@pytest.fixture(autouse=True)
def debugpy_dont_wait_for_client(monkeypatch):
    old_debugpy_get_args = DebugPy.get_args

    def get_debugpy_args_but_dont_wait_for_client(*args, **kwargs):
        result = list(old_debugpy_get_args(*args, **kwargs))
        result.remove("--wait-for-client")
        return tuple(result)

    monkeypatch.setattr(DebugPy, "get_args", get_debugpy_args_but_dont_wait_for_client)
