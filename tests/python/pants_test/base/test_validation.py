# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from contextlib import contextmanager

import pytest

from pants.base import validation

assert_list = validation.assert_list

class FunctionCounter(object):
  def __init__(self, func):
    self.func = func
    self.counter = 0

  def __call__(self, *args, **kwargs):
    self.counter += 1
    return self.func(*args, **kwargs)
    

def test_valid_inputs():
  # list of strings gives list of strings
  assert assert_list(["file1.txt", "file2.txt"]) == ["file1.txt", "file2.txt"]
  assert assert_list(None) == []  # None is ok by default

def test_invalid_inputs():
  with pytest.raises(ValueError):
    assert_list({"file2.txt": True}) # Can't pass a dict by default
  with pytest.raises(ValueError):
     assert_list([["file2.txt"], "file2.txt"]) # Can't a list of non-string values

def test_lazyness(monkeypatch):
  mock = FunctionCounter(isinstance)
  monkeypatch.setattr(validation, 'isinstance', mock, raising=False)  # Create new module level var
  assert_list([], allowable=(list, set))
  assert mock.counter == 1  # isinstance was only called once despite allowable having two types
  mock.counter = 0
  assert_list(set(), allowable=(list, set))
  assert mock.counter == 2  # isinstance was called twice
  
  
