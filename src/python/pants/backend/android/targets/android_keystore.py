# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.base.exceptions import TargetDefinitionException
from pants.backend.android.targets.android_target import AndroidTarget


class AndroidKeystore(AndroidTarget):
  """Represents a keystore configuration"""

  def __init__(self,
               location=None,
               properties_file=None,
               **kwargs):
    super(AndroidKeystore, self).__init__(**kwargs)
    self.properties_file = properties_file
    self.location = location
    print (self.properties_file)
    #print(os.path.join(self.properties_file))