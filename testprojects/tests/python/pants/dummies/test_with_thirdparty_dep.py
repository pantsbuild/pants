# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing_extensions import Literal


def test_f():
  assert Literal[1] == Literal[1]
  assert Literal[1] != Literal[2]
