# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload
from pants.build_graph.target import Target


class Resources(Target):
  """Resource files.

  Looking for loose files in your JVM application bundle? Those are `bundle <#bundle>`_\s.

  Resources are files included in deployable units like Java jars or Python wheels and accessible
  via language-specific APIs.

  :API: public
  """

  @classmethod
  def alias(cls):
    return 'resources'

  def __init__(self, address=None, payload=None, sources=None, **kwargs):
    """
    :API: public

    :param sources: Files to "include". Paths are relative to the BUILD file's directory.
    :type sources: :class:`pants.source.wrapped_globs.FilesetWithSpec` or list of strings
    """
    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources,
                                           sources_rel_path=address.spec_path, key_arg='sources'),
    })
    super(Resources, self).__init__(address=address, payload=payload, **kwargs)

  def has_sources(self, extension=None):
    """`Resources` targets never logically "own" sources of any particular type (extension).

    `JavaLibrary` targets, in contrast, logically "own" `.java` files and so target consumers
    (tasks) may collect targets to operate on by checking `has_sources('.java')` instead of
    performing a target type test.

    A `Resources` target may have `.java` sources - for example, a java compiler test might use
    loose `.java` source files in the test tree as compiler inputs - but it does not logically
    "own" `.java` sources like `JavaLibrary` and so any query of `has_sources` with an `extension`
    will return `False` to prevent standard compilation by a `javac` task in this example.

    :API: public

    :param string extension: Suffix of filenames to test for.
    :return: `True` if this target owns at least one source file and `extension` is `None`.
    :rtype: bool
    """
    return extension is None and super(Resources, self).has_sources()
