# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.base.exceptions import TargetDefinitionException
from pants.base.target import Target
from pants.base.build_environment import get_buildroot


class KeyError(Exception):
  pass

class Keystore(Target):
  """Represents a keystore configuration"""

  def __init__(self,
               type=None,
               sources=None,
               keystore_alias=None,
               keystore_password=None,
               key_password=None,
               **kwargs):
    """
    :param string type: What type of package the keystore signs. Either 'debug' or 'release'.
    :param sources: path/to/keystore
    :type sources: ``Fileset`` or list of strings.
    :param string keystore_alias: The alias of this keystore.
    :param string keystore_password: The password for the keystore.
    :param string key_password: The password for the key.
    """
    super(Keystore, self).__init__(**kwargs)

    # TODO (mateor) if debug location is empty, create a debug.keystore with keytool.
    self.sources = sources
    if len(self.sources) > 1:
      raise TargetDefinitionException(self, "The 'sources' field points only to the keystore file")
    # We have verified there is just one 'sources' file, we can now set the location.
    for source in self.sources:
      if source is None:
        raise TargetDefinitionException(self, "The keystore must provide a 'sources' attribute "
                                              "with path to the keystore file")
      else:
        self.location = os.path.join(get_buildroot(), self.address.spec_path, source)

    self.keystore_alias = keystore_alias
    self.keystore_password = keystore_password
    self.key_password=key_password

  # TODO(mateor) update docstring of Android targets.

    if type.lower() == "debug":
      self.type = 'debug'
    else:
      if type.lower() == "release":
        self.type = 'release'
      else:
        raise KeyError("A Keystore target: {0!r} needs a 'type' field that is set to "
                       "either 'debug' or 'release'.".format(self.address))

    #print(os.path.join(self.properties_file))