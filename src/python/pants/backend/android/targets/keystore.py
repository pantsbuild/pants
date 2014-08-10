# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.base.exceptions import TargetDefinitionException
from pants.base.target import Target


class KeyError(Exception):
  pass

class Keystore(Target):
  """Represents a keystore configuration"""

  def __init__(self,
               type=None,
               keystore_alias=None,
               key_store_password=None,
               key_alias_password=None,
               **kwargs):
    super(Keystore, self).__init__(**kwargs)

    self.keystore_alias = keystore_alias
    self.key_store_password = key_store_password
    self.key_alias_password=key_alias_password
    print("HEY FOOL THE YPE is %s" % type)

    if type.lower() == "debug":
      self. release = False
    else:
      if type.lower() == "release".lower():
        self.release = True
      else:
        raise KeyError("A Keystore target: {0!r} needs a 'type' field that is set to "
                       "either 'debug' or 'release'.".format(self.address))

    #print(os.path.join(self.properties_file))