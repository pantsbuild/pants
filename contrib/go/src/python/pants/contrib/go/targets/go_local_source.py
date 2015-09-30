# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.core.wrapped_globs import Globs
from pants.base.address import Address
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload

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

  @classmethod
  def create(cls, parse_context, **kwargs):
    if 'name' in kwargs:
      raise TargetDefinitionException(Address(parse_context.rel_path, kwargs['name']).spec,
                                      'A {} does not accept a name; instead, the name is taken '
                                      'from the the BUILD file location.'.format(cls.alias()))
    name = os.path.basename(parse_context.rel_path)

    if 'sources' in kwargs:
      raise TargetDefinitionException(Address(parse_context.rel_path, name).spec,
                                      'A {} does not accept sources; instead, it always globs all '
                                      'the *.go sources in the BUILD file\'s '
                                      'directory.'.format(cls.alias()))

    parse_context.create_object(cls, type_alias=cls.alias(), name=name, **kwargs)

  @classmethod
  def alias(cls):
    """Subclasses should return their desired BUILD file alias.

    :rtype: string
    """
    raise NotImplementedError()

  def __init__(self, address=None, payload=None, **kwargs):
    # We grab all files in the current directory except BUILD files for 2 reasons:
    # 1. cgo: If a file imports "C" then it may rely on sibling .c, .cc, etc files that `go build`
    #    will compile.
    # 2. resources: Even though go does not support them; ie by providing a protocol to embed them
    #    in binaries, it does allow them to be placed in a directory where a test might use them
    #    for example via plain old filesystem access.
    globs = Globs(rel_path=os.path.join(get_buildroot(), address.spec_path))
    sources = globs('*', exclude=[globs('BUILD*'),
                                  # This skips dirents.
                                  globs('*/')])

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
