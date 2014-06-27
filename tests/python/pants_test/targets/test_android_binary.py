# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.android.targets.android_binary import AndroidBinary
from pants_test.base_test import BaseTest


class AndroidBinaryTest(BaseTest):
  @property
  def alias_groups(self):
    return {
      'target_aliases': {
        'android_binary': AndroidBinary,
        },
    }
