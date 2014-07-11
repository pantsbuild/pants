# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.build_manual import manual
from pants.backend.android.targets.android_target import AndroidTarget


@manual.builddict(tags=["android"])
class AndroidResources(AndroidTarget):
  """Processes android resources to generate R.java"""

  def __init__(self,
               manifest=None,
               **kwargs):
    """
    :param manifest: path/to/manifest of target (required file name AndroidManifest.xml)
    :type manifest: string
    :param dependencies: Other targets that this target depends on.
    :type dependencies: list of target specs
    """

    self.manifest = manifest
    super(AndroidResources, self).__init__(manifest=manifest, **kwargs)
