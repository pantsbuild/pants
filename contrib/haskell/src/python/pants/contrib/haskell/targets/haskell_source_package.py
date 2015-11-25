# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.target import Target


class HaskellSourcePackage(Target):
  """A local or remote Haskell source package.

  If you provide the `path` field then this target points to the source archive
  located at `path`.  Otherwise, this target points to a `cabal` source tree anchored
  at the current directory.
  """

  def __init__(self, package=None, path=None, **kwargs):
    """
    :param str package: Optional name of the package (i.e. "network" or "containers").  Defaults to `name` if omitted
    :param str path: Optional path to a remote source archive in TAR or ZIP format.
    """

    self.package = package or kwargs['name']
    self.path = path

    payload = Payload()
    payload.add_fields({
      'package': PrimitiveField(self.package),
      'path': PrimitiveField(self.path),
    })
    super(HaskellSourcePackage, self).__init__(payload = payload, **kwargs)
