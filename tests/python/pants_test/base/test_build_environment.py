# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants.base.build_environment import get_pants_cachedir, get_pants_configdir
from pants.util.contextutil import environment_as
from pants.util.fileutil import temporary_file


class TestBuildEnvironment(unittest.TestCase):
  """Test class for pants.base.build_environment."""

  def test_get_configdir(self):
    with environment_as(XDG_CONFIG_HOME=''):
      self.assertEquals(os.path.expanduser('~/.config/pants'), get_pants_configdir())

  def test_get_cachedir(self):
    with environment_as(XDG_CACHE_HOME=''):
      self.assertEquals(os.path.expanduser('~/.cache/pants'), get_pants_cachedir())

  def test_set_configdir(self):
    with temporary_file() as temp:
      with environment_as(XDG_CONFIG_HOME=temp.name):
        self.assertEquals(os.path.join(temp.name, 'pants'),  get_pants_configdir())

  def test_set_cachedir(self):
    with temporary_file() as temp:
      with environment_as(XDG_CACHE_HOME=temp.name):
        self.assertEquals(os.path.join(temp.name, 'pants'), get_pants_cachedir())

  def test_expand_home_configdir(self):
    with environment_as(XDG_CONFIG_HOME='~/somewhere/in/home'):
      self.assertEquals(os.path.expanduser(os.path.join('~/somewhere/in/home', 'pants')),
                        get_pants_configdir())
