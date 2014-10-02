# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE)

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.android.targets.android_target import AndroidTarget
from pants.backend.android.targets.build_type_mixin import BuildTypeMixin


class AndroidBinary(AndroidTarget, BuildTypeMixin):
  """Produces an Android binary."""

  def __init__(self,
               build_type=None,
               *args,
               **kwargs):
    """
    :param string build_type: One of [debug, release]. The keystore to sign the package with.
      Set as 'debug' by default.
    """
    super(AndroidBinary, self).__init__(*args, **kwargs)
    self._build_type = None
    # default to 'debug' builds for now.
    self._keystore = build_type if build_type else 'debug'

  @property
  def build_type(self):
    if self._build_type is None:
      self._build_type = self.get_build_type(self._keystore)
    return self._build_type
