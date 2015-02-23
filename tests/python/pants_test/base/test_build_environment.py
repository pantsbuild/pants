# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from contextlib import contextmanager

from pants.base.build_environment import get_pants_cachedir, get_pants_configdir
from pants.util.contextutil import environment_as
from pants.util.fileutil import temporary_file


class TestBuildEnvironment(unittest.TestCase):
  """Test class for pants.base.build_environment."""

  @contextmanager
  def env(self, **kwargs):
    environment = dict(PATH=None)
    environment.update(**kwargs)
    with environment_as(**environment):
      yield

  def test_get_configdir(self):
    with self.env():
      self.assertEquals(os.path.expanduser('~/.config/pants'), get_pants_configdir())

  def test_get_cachedir(self):
    with self.env():
      self.assertEquals(os.path.expanduser('~/.cache/pants'), get_pants_cachedir())

  def test_set__empty_configdir(self):
    with self.env(XDG_CONFIG_HOME=''):
      self.assertEquals(os.path.expanduser('~/.config/pants'), get_pants_configdir())

  def test_set__empty_cachedir(self):
    with self.env(XDG_CONFIG_HOME=''):
      self.assertEquals(os.path.expanduser('~/.cache/pants'), get_pants_cachedir())

  def test_wrong_configdir(self):
    with self.assertRaises(AssertionError):
      with self.env():
        self.assertEquals(os.path.expanduser('~/wrongdir/pants'), get_pants_cachedir())

  def test_set_configdir(self):
    with temporary_file() as temp:
      with self.env(XDG_CONFIG_HOME=temp.name):
        self.assertEquals(temp.name, get_pants_configdir())

  def test_set_cachedir(self):
    with temporary_file() as temp:
      with self.env(XDG_CACHE_HOME=temp.name):
        self.assertEquals(temp.name, get_pants_cachedir())
