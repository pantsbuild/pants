# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.payload import Payload
from pants.base.payload_field import SourcesField
from pants.backend.core.targets.source_set import SourceSet
from pants.base.target import Target


class Resources(Target):
  """A set of files accessible as resources from the JVM classpath.

  Looking for loose files in your application bundle? Those are
  `bundle <#bundle>`_\s.

  Resources are Java-style resources accessible via the ``Class.getResource``
  and friends API. In the ``jar`` goal, the resource files are placed in the resulting `.jar`.
  """

  def __init__(self, address=None, payload=None, sources=None, build_graph=None, **kwargs):
    """
    :param sources: list of files to "include", Fileset or SourceSet instance. Paths are relative
     to the BUILD file's directory.
    :type sources: ``Fileset`` or list of strings
    """
    payload = payload or Payload()
    payload.add_fields({
      'sources': SourcesField(sources=SourceSet.from_source_object(address,
                                                                   sources,
                                                                   build_graph,
                                                                   rel_path=address.spec_path)),
    })
    super(Resources, self).__init__(address=address, payload=payload, build_graph=build_graph,
                                    **kwargs)

  def has_sources(self, extension=None):
    """``Resources`` never own sources of any particular native type, like for example
    ``JavaLibrary``.
    """
    # TODO(John Sirois): track down the reason for this hack and kill or explain better.
    return extension is None
