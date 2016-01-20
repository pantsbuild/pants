# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload
from pants.build_graph.target import Target


class GoThriftLibrary(Target):
  """A Go library generated from Thrift IDL files."""

  def __init__(self,
               address=None,
               payload=None,
               import_path=None,
               sources=None,
               **kwargs):
    """
    :param sources: thrift source files
    :type sources: ``Fileset`` or list of strings. Paths are relative to the
      BUILD file's directory.
    :param import_path: Go code will import this
    """

    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources, address.spec_path, key_arg='sources'),
    })

    super(GoThriftLibrary, self).__init__(payload=payload, address=address, **kwargs)

    self.add_labels('codegen')

  @classmethod
  def alias(cls):
    return "go_thrift_library"
