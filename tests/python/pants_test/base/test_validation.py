# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import pytest

from pants.base.validation import assert_list


def test_valid_inputs():
  # list of strings gives list of strings
  assert assert_list(["file1.txt", "file2.txt"]) == ["file1.txt", "file2.txt"]
  assert assert_list(None) == []  # None is ok by default


def test_invalid_inputs():
  with pytest.raises(ValueError):
    assert_list({"file2.txt": True})  # Can't pass a dict by default
  with pytest.raises(ValueError):
    assert_list([["file2.txt"], "file2.txt"])  # All values in list must be stringy values
