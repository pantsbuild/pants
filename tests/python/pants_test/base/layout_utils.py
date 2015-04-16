# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import io
import logging
import os
from contextlib import contextmanager

from twitter.common.collections import maybe_list

from pants.base.config import Config, SingleFileConfig
from pants.base.layout import Layout
from pants.base.target import Target
from pants.goal.context import Context


class TestLayout(Layout):
  def __init__(self, build_root=None):
    super(TestLayout, self).__init__()
    self._build_root = build_root
  #  self._path_to_type=dict()

  #def register(self, path, *types):
  #  # TODO normalize
  #  if path in self._path_to_type:
  #    raise ValueError("path already registered: {}".format(path))
  #  self._path_to_type[path]=types

  #def types(self, path):
  #  return self._path_to_type[path]

  #def find_source_root_by_path(self, path):
