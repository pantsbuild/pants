# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.target import Target


class HaskellHackagePackage(Target):
  """A package hosted on Hackage.

  Only use this target for packages or package versions outside of Stackage.
  Prefer `HaskellStackagePackage` when possible.
  """

  def __init__(self, version, package=None, **kwargs):
    """
    :param str version: The package version string (i.e. "0.4.3.0" or "1.0.0")
    :param str package: Optional name of the package (i.e. "network" or "containers").  Defaults to `name` if omitted
    """
    self.version = version
    self.package  = package or kwargs['name']

    payload = Payload()
    payload.add_fields({
      'version': PrimitiveField(self.version),
      'package': PrimitiveField(self.package),
    })
    super(HaskellHackagePackage, self).__init__(**kwargs)
