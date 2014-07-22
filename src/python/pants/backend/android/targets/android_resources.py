# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.backend.android.targets.android_target import AndroidTarget


class AndroidResources(AndroidTarget):
  """Processes android resources to generate R.java"""

  def __init__(self,
               address=None,
               resource_dir='res',
               **kwargs):
    """
    :param resource_dir: path/to/directory containing Android target's resource files.
      Set to 'res' by default.
    :type resource_dir: string.
    :param dependencies: Other targets that this target depends on.
    :type dependencies: list of target specs
    """

    #Is there a way to easily grab this full path without exposing address?
    self.resource_dir = os.path.join(address.spec_path, resource_dir)
    super(AndroidResources, self).__init__(address=address, **kwargs)

