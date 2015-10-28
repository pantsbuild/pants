# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.target import Target


class HaskellPackage(Target):
  def __init__(self, resolver, package=None, **kwargs):
    """
    :param str package : The name of the package (i.e. "network" or "containers")
    :param str resolver: The `stack` resolver (i.e. "lts-3.1" or "nightly-2015-08-29")
    """

    self.package  = package or self.name
    self.resolver = resolver

    payload = Payload()
    payload.add_fields({
      'package': PrimitiveField(self.package),
      'resolver': PrimitiveField(self.resolver),
    })
    super(HaskellPackage, self).__init__(payload = payload, **kwargs)
