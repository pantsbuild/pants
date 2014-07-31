# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.collections import maybe_list
from twitter.common.lang import Compatibility

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.exceptions import TargetDefinitionException
from pants.base.validation import assert_list


class JavaTests(JvmTarget):
  """Tests JVM sources with JUnit."""

  def __init__(self,
               sources=None,
               **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the :doc:`target address <target_addresses>`.
    :param sources: Source code files to compile. Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings
    :param provides: The ``artifact``
      to publish that represents this target outside the repo.
    :param dependencies: Other targets that this target depends on.
    :type dependencies: list of target specs
    :param excludes: List of :ref:`exclude <bdict_exclude>`\s
      to filter this target's transitive dependencies against.
    :param resources: An optional list of ``resources`` targets containing text
      file resources to place in this module's jar.
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
   """
    _sources = self.assert_list(sources)

    super(JavaTests, self).__init__(sources=_sources, **kwargs)

    if not _sources:
      raise TargetDefinitionException(self, 'JavaTests must include a non-empty set of sources.')

    # TODO(John Sirois): These could be scala, clojure, etc.  'jvm' and 'tests' are the only truly
    # applicable labels - fixup the 'java' misnomer.
    self.add_labels('java', 'tests')
