# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import six

from pants.backend.jvm.targets.jar_library import JarLibrary


class ImportJarsMixin(object):
  """A Target Mixin to be used when a target declares JarLibraries to be imported."""

  @property
  def imported_jar_library_specs(self):
    """This method must be implemented by the target that includes ImportJarsMixin.

    :returns: list of JarLibrary specs to be imported.
    :rtype: list of JarLibrary
    """
    raise NotImplementedError(
      "This target {0} must provide an implementation of the import_jar_library_specs property."
      .format(type(self)))

  # TODO(Patrick Lawson) Follow up with a cached_property utility for pants to substitute for
  # this way of caching instance attributes using a placeholder class attribute.
  _imported_jars = None
  @property
  def imported_jars(self):
    """:returns: the string specs of JarDependencies referenced by imported_jar_library_specs
    :rtype: list of string
    """
    if self._imported_jars is None:
      self._imported_jars =  JarLibrary.to_jar_dependencies(self.address,
                                                            self.imported_jar_library_specs,
                                                            self._build_graph)
    return self._imported_jars

  @property
  def traversable_specs(self):
    """Tack imported_jar_library_specs onto the traversable_specs generator for this target."""
    for spec in super(ImportJarsMixin, self).traversable_specs:
      yield spec
    if self.imported_jar_library_specs:
      for spec in self.imported_jar_library_specs:
        # For better error handling, this simply skips over non-strings, but we catch them with a
        # WrongTargetType in JarLibrary.to_jar_dependencies.
        if isinstance(spec, six.string_types):
          yield spec
