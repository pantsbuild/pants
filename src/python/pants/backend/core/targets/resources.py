# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.payload import ResourcesPayload
from pants.base.target import Target


class Resources(Target):
  """A set of files accessible as resources from the JVM classpath.

  Looking for loose files in your application bundle? Those are :ref:`bdict_bundle`\ s.

  Resources are Java-style resources accessible via the ``Class.getResource``
  and friends API. In the ``jar`` goal, the resource files are placed in the resulting `.jar`.
  """

  def __init__(self, address=None, sources=None, **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the :doc:`target address <target_addresses>`.
    :param sources: Files to "include". Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings
    """
    payload = ResourcesPayload(sources_rel_path=address.spec_path, sources=sources)
    super(Resources, self).__init__(address=address, payload=payload, **kwargs)

  def has_sources(self, extension=None):
    """``Resources`` never own sources of any particular native type, like for example
    ``JavaLibrary``.
    """
    # TODO(John Sirois): track down the reason for this hack and kill or explain better.
    return extension is None
