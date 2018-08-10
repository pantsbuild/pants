# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import re

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.base.validation import assert_list
from pants.build_graph.target import Target


class ExternalNativeLibrary(Target):
  """A set of Conan package strings to be passed to the Conan package manager."""

  @classmethod
  def alias(cls):
    return 'external_native_library'

  def __init__(self, payload=None, packages=None, **kwargs):
    """
    :param packages: a list of Conan-style package strings

    Example:
      lzo/2.10@twitter/stable
    """
    payload = payload or Payload()

    assert_list(packages, key_arg='packages')
    payload.add_fields({
      'packages': PrimitiveField(packages),
    })
    super(ExternalNativeLibrary, self).__init__(payload=payload, **kwargs)

  @property
  def packages(self):
    return self.payload.packages

  @property
  def lib_names(self):
    return [re.match(r'^([^\/]+)\/', pkg_name).group(1) for pkg_name in self.payload.packages]
