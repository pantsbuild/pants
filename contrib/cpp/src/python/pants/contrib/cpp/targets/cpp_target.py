# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload
from pants.base.target import Target


class CppTarget(Target):
  """A base class for all cpp targets."""

  def __init__(self, address=None, payload=None, sources=None, **kwargs):
    """
    :param sources: Source code files to build. Paths are relative to the BUILD
      file's directory.
    :type sources: ``Fileset`` (from globs or rglobs) or list of strings
    """
    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources=sources,
                                           sources_rel_path=address.spec_path,
                                           key_arg='sources'),
    })
    super(CppTarget, self).__init__(address=address, payload=payload, **kwargs)
