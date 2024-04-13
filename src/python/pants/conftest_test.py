# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

import pytest


def test_frozen_dataclass_checking() -> None:
    @dataclass(frozen=True)
    class MissingInitialization:
        x: str

        def __init__(self):
            pass

    with pytest.raises(AssertionError):
        MissingInitialization()

    @dataclass(frozen=True)
    class TooMuchInitialized:
        def __init__(self):
            object.__setattr__(self, "x", 1)

    with pytest.raises(AssertionError):
        TooMuchInitialized()

    # Also make sure it works with slots
    @dataclass(frozen=True)
    class MissingInitializationWithSlots:
        __slots__ = ("x",)
        x: str

        def __init__(self):
            pass

    with pytest.raises(AttributeError):
        MissingInitializationWithSlots()
