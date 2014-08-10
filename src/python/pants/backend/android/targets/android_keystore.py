# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.base.exceptions import TargetDefinitionException
from pants.backend.android.targets.android_target import AndroidTarget


class AndroidKeystore(AndroidTarget):
  """Represents a keystore configuration"""

  def __init__(self,
               resource_dir=None,
               **kwargs):
    pass