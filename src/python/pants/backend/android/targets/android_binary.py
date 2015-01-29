# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE)

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.android.targets.android_target import AndroidTarget


class AndroidBinary(AndroidTarget):
  """Produces an Android binary."""

  # This target exists as a hedge for when we expand to support AndroidLibrary.
  def __init__(self, *args, **kwargs):
    super(AndroidBinary, self).__init__(*args, **kwargs)
