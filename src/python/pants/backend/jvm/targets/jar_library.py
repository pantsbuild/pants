# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.base.payload import Payload
from pants.base.payload_field import ExcludesField, JarsField
from pants.base.target import Target


class JarLibrary(Target):
  """A set of jars that may be depended upon."""

  def __init__(self, payload=None, jars=None, **kwargs):
    """
    :param jars: List of :ref:`jar <bdict_jar>`\s to depend upon.
    """
    payload = payload or Payload()
    payload.add_fields({
      'jars': JarsField(self.assert_list(jars, expected_type=JarDependency)),
      'excludes': ExcludesField([]),
    })
    super(JarLibrary, self).__init__(payload=payload, **kwargs)
    self.add_labels('jars', 'jvm')

  @property
  def jar_dependencies(self):
    return self.payload.jars

  @property
  def excludes(self):
    return self.payload.excludes
