# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import six

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.target import Target
from pants.util.memo import memoized_property


class ImportJarsMixin(Target):
  """A Target Mixin to be used when a target declares JarLibraries to be imported."""

  class UnresolvedImportError(AddressLookupError):
    """Raised when an imported JarLibrary cannot be resolved."""

  class ExpectedJarLibraryError(AddressLookupError):
    """Raised when a target is referenced by a jar import that is not a JarLibrary."""

  @classmethod
  def imported_jar_library_spec_fields(cls):
    """This method must be implemented by the target that includes ImportJarsMixin.

    :returns: list of tuples representing fields to source JarLibrary specs to be imported from
              as (pre-init kwargs field, post-init payload field).
    """
    raise NotImplementedError(
      'subclasses of ImportJarsMixin must implement an '
      '`imported_jar_library_spec_fields` classmethod'
    )

  @classmethod
  def imported_jar_library_specs(cls, kwargs=None, payload=None):
    """
    :param kwargs: A kwargs dict representing Target.__init__(**kwargs) (Optional).
    :param payload: A Payload object representing the Target.__init__(payload=...) param.  (Optional).
    :returns: list of JarLibrary specs to be imported.
    :rtype: list of JarLibrary
    """
    assert kwargs is None or payload is None, 'must provide either kwargs or payload'
    assert not (kwargs is not None and payload is not None), 'may not provide both kwargs and payload'

    field_pos = 0 if kwargs is not None else 1
    target_representation = kwargs or payload.as_dict()

    def gen_specs():
      for fields_tuple in cls.imported_jar_library_spec_fields():
        for item in target_representation.get(fields_tuple[field_pos], ()):
          # For better error handling, this simply skips over non-strings, but we catch them
          # with a WrongTargetType in JarLibrary.to_jar_dependencies.
          if not isinstance(item, six.string_types):
            raise JarLibrary.ExpectedAddressError(
              'expected imports to contain string addresses, got {found_class} instead.'
              .format(found_class=type(item).__name__)
            )
          yield item

    return list(gen_specs())

  @memoized_property
  def imported_jars(self):
    """:returns: the string specs of JarDependencies referenced by imported_jar_library_specs
    :rtype: list of string
    """
    return JarLibrary.to_jar_dependencies(self.address,
                                          self.imported_jar_library_specs(payload=self.payload),
                                          self._build_graph)

  @memoized_property
  def imported_jar_libraries(self):
    """:returns: target instances for specs referenced by imported_jar_library_specs.
    :rtype: list of JarLibrary
    """
    libs = []
    for spec in self.imported_jar_library_specs(payload=self.payload):
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

  @classmethod
  def compute_dependency_specs(cls, kwargs=None, payload=None):
    """Tack imported_jar_library_specs onto the traversable_specs generator for this target."""
    for spec in super(ImportJarsMixin, cls).compute_dependency_specs(kwargs, payload):
      yield spec

    imported_jar_library_specs = cls.imported_jar_library_specs(kwargs=kwargs, payload=payload)
    for spec in imported_jar_library_specs:
      yield spec
