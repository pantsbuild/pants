# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.android.targets.android_target import AndroidTarget
from pants.base.exceptions import TargetDefinitionException


class AndroidBinary(AndroidTarget):
  """Produces an Android binary."""

  def __init__(self, *args, **kwargs):
    super(AndroidBinary, self).__init__(*args, **kwargs)
    self._target_sdk = None

  @property
  def target_sdk(self):
    """Return the SDK version to use when compiling this target."""
    # This is an optional attribute for AndroidLibrary but required for AndroidBinary.
    if self._target_sdk is None:
      self._target_sdk = self.manifest.target_sdk
      if not self._target_sdk:
        raise TargetDefinitionException(self, "AndroidBinary targets must declare targetSdkVersion"
                                              " in the AndroidManifest.xml.")
    return self._target_sdk
