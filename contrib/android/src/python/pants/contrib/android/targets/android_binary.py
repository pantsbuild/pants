# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.exceptions import TargetDefinitionException
from pants.util.memo import memoized_property

from pants.contrib.android.targets.android_target import AndroidTarget


class AndroidBinary(AndroidTarget):
  """An Android binary."""

  def __init__(self, *args, **kwargs):
    super(AndroidBinary, self).__init__(*args, **kwargs)

  @memoized_property
  def target_sdk(self):
    """Return the SDK version to use when compiling this target."""
    if not self.manifest.target_sdk:
      raise TargetDefinitionException(self, "AndroidBinary targets must declare targetSdkVersion "
                                            "in the AndroidManifest.xml.")
    return self.manifest.target_sdk
