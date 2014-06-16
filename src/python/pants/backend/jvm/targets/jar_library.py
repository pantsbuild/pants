# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.build_manual import manual
from pants.base.payload import JarLibraryPayload
from pants.base.target import Target


@manual.builddict(tags=["anylang"])
class JarLibrary(Target):
  """A set of jars that may be depended upon."""

  def __init__(self, jars=None, *args, **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`pants.base.address.Address`.
    :param jars: List of :class:`pants.base.target.Target` instances
      this target depends on.
    :param overrides: List of strings, each of which will be recursively resolved to
      any targets that provide artifacts. Those artifacts will override corresponding
      direct/transitive dependencies in the dependencies list.
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
    """
    payload = JarLibraryPayload(jars or [])
    super(JarLibrary, self).__init__(payload=payload, *args, **kwargs)
    self.add_labels('jars')

  @property
  def jar_dependencies(self):
    return self.payload.jars
