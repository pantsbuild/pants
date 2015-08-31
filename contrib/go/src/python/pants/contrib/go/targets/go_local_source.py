# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.base.payload import Payload
from twitter.common.dirutil.fileset import Fileset

from pants.contrib.go.targets.go_target import GoTarget


class GoLocalSource(GoTarget):

  @classmethod
  def is_go_source(cls, path):
    """Returns `True` if the file at the given `path` is a go source file."""
    return path.endswith('.go') and os.path.isfile(path)

  @classmethod
  def local_import_path(cls, source_root, address):
    """Returns the Go import path for the given address housed under the given source root.

    :param string source_root: The path of the source root the address is found within.
    :param address: The target address of a GoLocalSource target.
    :type: :class:`pants.base.address.Address`
    :raises: `ValueError` if the address does not reside within the source root.
    """
    return cls.package_path(source_root, address.spec_path)

  def __init__(self, address=None, payload=None, **kwargs):
    # TODO(John Sirois): Make pants.backend.core.wrapped_globs.Globs in the core backend
    # constructable with just a rel_path. Right now it violates the Law of Demeter and
    # fundamentally takes a ParseContext, which it doesn't actually need and which other backend
    # consumers should not need to know about or create.
    # Here we depend on twitter/commons which is less than ideal in core pants and even worse in a
    # plugin.  We depend on it here to ensure the globbing is lazy and skipped if the target is
    # never fingerprinted (eg: when running `./pants list`).
    sources = Fileset.globs('*.go', root=os.path.join(get_buildroot(), address.spec_path))

    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources=sources,
                                           sources_rel_path=address.spec_path,
                                           key_arg='sources'),
    })
    super(GoLocalSource, self).__init__(address=address, payload=payload, **kwargs)

  @property
  def import_path(self):
    """The import path as used in import statements in `.go` source files."""
    return self.local_import_path(self.target_base, self.address)
