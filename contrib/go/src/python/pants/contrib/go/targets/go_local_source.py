# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re

from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.build_graph.address import Address
from pants.util.memo import memoized_property

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
    :type: :class:`pants.build_graph.address.Address`
    :raises: `ValueError` if the address does not reside within the source root.
    """
    return cls.package_path(source_root, address.spec_path)

  @classmethod
  def create(cls, parse_context, **kwargs):
    if 'name' in kwargs:
      raise TargetDefinitionException(Address(parse_context.rel_path, kwargs['name']).spec,
                                      'A {} does not accept a name; instead, the name is taken '
                                      'from the BUILD file location.'.format(cls.alias()))
    name = os.path.basename(parse_context.rel_path)

    if 'sources' in kwargs:
      raise TargetDefinitionException(Address(parse_context.rel_path, name).spec,
                                      'A {} does not accept sources; instead, it always globs all '
                                      'the *.go sources in the BUILD file\'s '
                                      'directory.'.format(cls.alias()))

    parse_context.create_object(cls, type_alias=cls.alias(), name=name, **kwargs)

  def __init__(self, address=None, payload=None, sources=None, **kwargs):
    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources=sources,
                                           sources_rel_path=address.spec_path,
                                           key_arg='sources'),
    })
    super().__init__(address=address, payload=payload, **kwargs)

  @property
  def import_path(self):
    """The import path as used in import statements in `.go` source files."""
    return self.local_import_path(self.target_base, self.address)

  # From `go help test`, ignore files beginning with "_" or ".", but otherwise match the glob
  # "*_test.go".
  _test_file_regexp = re.compile(r'^[^_\.].*_test\.go')

  @classmethod
  def _is_test_file(cls, src_path):
    base = os.path.basename(src_path)
    return re.match(cls._test_file_regexp, base) is not None

  @memoized_property
  def has_tests(self):
    return any(self._is_test_file(src) for src in self.payload.sources.source_paths)
