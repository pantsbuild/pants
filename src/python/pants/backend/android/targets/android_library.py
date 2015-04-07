# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.android.targets.android_target import AndroidTarget
from pants.backend.jvm.targets.import_jars_mixin import ImportJarsMixin
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField


class AndroidLibrary(ImportJarsMixin, AndroidTarget):
  """Android library target as a jar."""

  def __init__(self, payload=None, imports=None, **kwargs):
    """
    :param list imports: List of addresses of `jar_library <#jar_library>`_
      targets.
    """
    payload = payload or Payload()
    payload.add_fields({
      'import_specs': PrimitiveField(imports or ()),
    })
    super(AndroidLibrary, self).__init__(payload=payload, **kwargs)

  @property
  def imported_jar_library_specs(self):
    """List of JarLibrary specs to import.

    Required to implement the ImportJarsMixin.
    """
    return self.payload.import_specs
