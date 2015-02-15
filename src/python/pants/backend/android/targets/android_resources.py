# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.android.targets.android_target import AndroidTarget
from pants.base.exceptions import TargetDefinitionException


class AndroidResources(AndroidTarget):
  """Processes android resources to generate R.java"""

  def __init__(self,
               resource_dir=None,
               **kwargs):
    #TODO(mateor) change resource_dir from string into list
    """
    :param string resource_dir: path/to/directory containing Android resource files,
     often named 'res'.
    """
    super(AndroidResources, self).__init__(**kwargs)
    address = kwargs['address']
    try:
      self.resource_dir = os.path.join(address.spec_path, resource_dir)
    except AttributeError:
      raise TargetDefinitionException(self, 'An android_resources target must specify a '
                                            '\'resource_dir\' that contains the target\'s '
                                            'resource files.')
