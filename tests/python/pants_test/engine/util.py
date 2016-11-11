# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.engine.subsystem.native import Native
from pants_test.subsystem.subsystem_util import init_subsystem


def init_native():
  """Initialize and return the `Native` subsystem."""
  init_subsystem(Native.Factory)
  return Native.Factory.global_instance().create()
