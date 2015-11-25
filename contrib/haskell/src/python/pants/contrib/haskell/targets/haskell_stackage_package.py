# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.target import Target


class HaskellStackagePackage(Target):
  """A package hosted on Stackage."""

  def __init__(self, package=None, **kwargs):
    """
    :param str package: Optional name of the package (i.e. "network" or "containers").  Defaults to `name` if omitted
    """

    self.package  = package or kwargs['name']

    payload = Payload()
    payload.add_fields({
      'package': PrimitiveField(self.package),
    })
    super(HaskellStackagePackage, self).__init__(payload = payload, **kwargs)
