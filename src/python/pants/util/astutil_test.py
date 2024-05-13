# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from __future__ import annotations

import ast

import pytest

from pants.util.astutil import maybe_narrow_type, narrow_type


def test_narrow_type():
    value = ast.Call(func=ast.Name(id="helloworld"), args=[], keywords=[])

    assert narrow_type(value, ast.Call) == value
    with pytest.raises(ValueError):
        narrow_type(value, ast.Name)

    assert narrow_type(value, (ast.Call, ast.Dict)) == value
    with pytest.raises(ValueError):
        narrow_type(value, (ast.Constant, ast.Name))


def test_maybe_narrow_type():
    value = ast.Call(func=ast.Name(id="helloworld"), args=[], keywords=[])

    assert maybe_narrow_type(value, ast.Call) == value
    assert maybe_narrow_type(value, ast.Name) is None

    assert maybe_narrow_type(value, (ast.Call, ast.Dict)) == value
    assert maybe_narrow_type(value, (ast.Constant, ast.Name)) is None
