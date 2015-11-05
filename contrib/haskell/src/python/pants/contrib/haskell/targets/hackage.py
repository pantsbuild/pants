# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.contrib.haskell.targets.haskell_package import HaskellPackage


class Hackage(HaskellPackage):
  """A package hosted on Hackage.

  Only use this target for packages or package versions outside of Stackage.  All
  Stackage dependencies are already implicitly covered by the `resolver` field.
  """

  def __init__(self, version, **kwargs):
    """
    :param str version: The package version string (i.e. "0.4.3.0" or "1.0.0")
    """
    self.version = version
    super(Hackage, self).__init__(**kwargs)
