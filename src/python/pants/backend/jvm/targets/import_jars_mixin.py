# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractproperty

import six

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.address_lookup_error import AddressLookupError
from pants.build_graph.target import Target
from pants.util.memo import memoized_property


class ImportJarsMixin(Target):
  """A Target Mixin to be used when a target declares JarLibraries to be imported."""

  class UnresolvedImportError(AddressLookupError):
    """Raised when an imported JarLibrary cannot be resolved."""

  class ExpectedJarLibraryError(AddressLookupError):
    """Raised when a target is referenced by a jar import that is not a JarLibrary."""

  @abstractproperty
  def imported_jar_library_specs(self):
    """This method must be implemented by the target that includes ImportJarsMixin.

    :returns: list of JarLibrary specs to be imported.
    :rtype: list of JarLibrary
    """

  @memoized_property
  def imported_jars(self):
    """:returns: the string specs of JarDependencies referenced by imported_jar_library_specs
    :rtype: list of string
    """
    return JarLibrary.to_jar_dependencies(self.address,
                                          self.imported_jar_library_specs,
                                          self._build_graph)

  @memoized_property
  def imported_jar_libraries(self):
    """:returns: target instances for specs referenced by imported_jar_library_specs.
    :rtype: list of JarLibrary
    """
    libs = []
    if self.imported_jar_library_specs:
      for spec in self.imported_jar_library_specs:
        resolved_target = self._build_graph.get_target_from_spec(spec,
                                                                 relative_to=self.address.spec_path)
        if not resolved_target:
          raise self.UnresolvedImportError(
            'Could not find JarLibrary target {spec} referenced from {relative_to}'
            .format(spec=spec, relative_to=self.address.spec))
        if not isinstance(resolved_target, JarLibrary):
          raise self.ExpectedJarLibraryError(
            'Expected JarLibrary got {target_type} for jar imports in {spec} referenced from '
            '{relative_to}'
            .format(target_type=type(resolved_target), spec=spec,
                    relative_to=self.address.spec))
        libs.append(resolved_target)
    return libs

  @property
  def traversable_dependency_specs(self):
    """Tack imported_jar_library_specs onto the traversable_specs generator for this target."""
    for spec in super(ImportJarsMixin, self).traversable_dependency_specs:
      yield spec
    if self.imported_jar_library_specs:
      for spec in self.imported_jar_library_specs:
        # For better error handling, this simply skips over non-strings, but we catch them with a
        # WrongTargetType in JarLibrary.to_jar_dependencies.
        if isinstance(spec, six.string_types):
          yield spec
