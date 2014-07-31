# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.android.targets.android_target import AndroidTarget


class AndroidDex(AndroidTarget):
  """Generates an Android dex file (Dalvik executable) from java class files"""

  def __init__(self,
               **kwargs):
    super(AndroidDex, self).__init__(**kwargs)
