# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.base.payload import JarLibraryPayload
from pants.base.target import Target


class JarLibrary(Target):
  """A set of jars that may be depended upon."""

  def __init__(self, jars=None, *args, **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the :doc:`target address <target_addresses>`.
    :param jars: List of :ref:`jar <bdict_jar>`\s to depend upon.
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
    """
    payload = JarLibraryPayload(self.assert_list(jars, expected_type=JarDependency))
    super(JarLibrary, self).__init__(payload=payload, *args, **kwargs)
    self.add_labels('jars', 'jvm')

  @property
  def jar_dependencies(self):
    return self.payload.jars

  @property
  def excludes(self):
    return self.payload.excludes
