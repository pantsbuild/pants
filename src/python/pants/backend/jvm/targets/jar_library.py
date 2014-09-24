# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.payload_field import ExcludesField, JarsField
from pants.base.target import Target


class JarLibrary(Target):
  """A set of jars that may be depended upon."""

  def __init__(self, jars=None, *args, **kwargs):
    """
    :param jars: List of :ref:`jar <bdict_jar>`\s to depend upon.
    """
    self.payload.add_fields({
      'jars': JarsField(jars or []),
      'excludes': ExcludesField([]),
    })
    super(JarLibrary, self).__init__(*args, **kwargs)
    self.add_labels('jars', 'jvm')

  @property
  def jar_dependencies(self):
    return self.payload.jars

  @property
  def excludes(self):
    return self.payload.excludes
