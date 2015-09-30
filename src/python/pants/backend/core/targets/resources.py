# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload
from pants.build_graph.target import Target


class Resources(Target):
  """A set of files accessible as resources from the JVM classpath.

  Looking for loose files in your application bundle? Those are
  `bundle <#bundle>`_\s.

  Resources are Java-style resources accessible via the ``Class.getResource``
  and friends API. In the ``jar`` goal, the resource files are placed in the resulting `.jar`.
  """

  def __init__(self, address=None, payload=None, sources=None, **kwargs):
    """
    :param sources: Files to "include". Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings
    """
    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources,
                                           sources_rel_path=address.spec_path, key_arg='sources'),
    })
    super(Resources, self).__init__(address=address, payload=payload, **kwargs)

  def has_sources(self, extension=None):
    """``Resources`` never own sources of any particular native type, like for example
    ``JavaLibrary``.
    """
    # TODO(John Sirois): track down the reason for this hack and kill or explain better.
    return extension is None
