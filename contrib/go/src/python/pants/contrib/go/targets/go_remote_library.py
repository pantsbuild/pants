# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.base.target import Target


class GoRemoteLibrary(Target):
  """TODO(John Sirois): DOCME ???"""

  @classmethod
  def from_packages(cls, parse_context, packages, rev='', **kwargs):
    """TODO(John Sirois): DOCME XXX"""
    for pkg in packages:
      name = pkg or os.path.basename(parse_context.rel_path)
      parse_context.create_object(cls, name=name, pkg=pkg, rev=rev, **kwargs)

  def __init__(self, pkg='', rev='', address=None, payload=None, **kwargs):
    """
    :param str pkg: The package name within the remote library; by default the root ('') package.
    :param str rev: Identifies which version of the remote library to download. This could be a
                    commit SHA (git), node id (hg), etc.  If left unspecified the version will
                    default to the latest available.  It's highly recommended to not accept the
                    default and instead pin the rev explicitly for repeatable builds.
    """
    if 'dependencies' in kwargs:
      raise TargetDefinitionException(address.spec,
                                      'A go_remote_library does not accept dependencies; instead, '
                                      'they are discovered and when they are on foreign remote '
                                      'libraries the versions are taken from other '
                                      'go_remote_library targets you\'ve defined in the same '
                                      'source root.')

    payload = payload or Payload()
    payload.add_fields({
      'rev': PrimitiveField(rev or ''),  # Guard against/allow `None`.
      'pkg': PrimitiveField(pkg or ''),  # Guard against/allow `None`.
    })

    super(GoRemoteLibrary, self).__init__(address=address, payload=payload, **kwargs)

  @property
  def pkg(self):
    return self.payload.pkg

  @property
  def rev(self):
    return self.payload.rev

  @property
  def import_path(self):
    rel_path = os.path.relpath(self.address.spec_path, self.target_base)
    return os.path.join(rel_path, self.pkg) if self.pkg else rel_path
