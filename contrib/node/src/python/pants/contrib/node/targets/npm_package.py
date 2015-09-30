# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.target import Target


class NpmPackage(Target):
  """Represents an abstract NPM package.

  All NPM packages have a package name whether they are local or remote so this serves as a base
  class for all concrete manifestations of NPM packages.
  """

  def __init__(self, package_name=None, address=None, payload=None, **kwargs):
    """
    :param string package_name: The remote module package name, if not supplied the target name is
                                used.
    """
    payload = payload or Payload()
    payload.add_fields({
      'package_name': PrimitiveField(package_name or address.target_name),
    })
    super(NpmPackage, self).__init__(address=address, payload=payload, **kwargs)

  @property
  def package_name(self):
    """The name of the remote module package.

    :rtype: string
    """
    return self.payload.package_name
