# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.backend.android.targets.build_type_mixin import BuildTypeMixin
from pants.base.exceptions import TargetDefinitionException
from pants.base.target import Target
from pants.base.build_environment import get_buildroot


class Keystore(Target, BuildTypeMixin):
  """Represents a keystore configuration"""

  def __init__(self,
               build_type=None,
               source=None,
               keystore_alias=None,
               keystore_password=None,
               key_password=None,
               **kwargs):
    """
    :param string build_type: What type of package the keystore signs. Either 'debug' or 'release'.
    :param string source: path/to/keystore
    :param string keystore_alias: The alias of this keystore.
    :param string keystore_password: The password for the keystore.
    :param string key_password: The password for the key.
    """
    super(Keystore, self).__init__(**kwargs)
    address = kwargs['address']

    # TODO (mateor) if debug location is empty, create a debug.keystore with keytool.
    self.source = source
    if source is None:
        raise TargetDefinitionException(self, "The keystore must provide a 'source' attribute.")
    self.location = os.path.join(get_buildroot(), address.spec_path, self.source)
    if not os.path.isfile(self.location):
      raise TargetDefinitionException(self, "The 'source' attribute: {0} must point to a "
                                            "file".format(self.location))
    self.keystore_alias = keystore_alias
    self.keystore_password = keystore_password
    self.key_password = key_password
    self._build_type = None
    self._keystore = build_type

  @property
  def build_type(self):
    if self._build_type is None:
      self._build_type = self.get_build_type(self._keystore)
    return self._build_type
