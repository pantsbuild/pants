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
               package=None,
               **kwargs):
    """
    :param package:  java package (com.company.package) in which to generate the output java files.
    :param dependencies: Other targets that this target depends on.
    :type dependencies: list of target specs
    """

    super(AndroidResources, self).__init__(package=package, **kwargs)
    self.package = package
