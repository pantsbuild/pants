# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.exceptions import TargetDefinitionException

from pants.contrib.android.targets.android_target import AndroidTarget


class AndroidResources(AndroidTarget):
  """Android resources used to generate R.java."""

  def __init__(self,
               resource_dir=None,
               **kwargs):
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

  def globs_relative_to_buildroot(self):
    return {'globs': os.path.join(self.resource_dir, '**')}
