# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import six
from twitter.common.collections import OrderedSet

from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.base.address import Address
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import ExcludesField, JarsField
from pants.build_graph.target import Target


class JarLibrary(Target):
  """A set of jars that may be depended upon."""

  class WrongTargetTypeError(Exception):
    """Thrown if the wrong type of target is encountered."""
    pass

  class ExpectedAddressError(Exception):
    """Thrown if an object that is not an address."""
    pass

  def __init__(self, payload=None, jars=None, **kwargs):
    """
    :param jars: List of `jar <#jar>`_\s to depend upon.
    """
    jars = self.assert_list(jars, expected_type=JarDependency, key_arg='jars')
    payload = payload or Payload()
    payload.add_fields({
      'jars': JarsField(jars),
      'excludes': ExcludesField([]),
    })
    super(JarLibrary, self).__init__(payload=payload, **kwargs)
    # NB: Waiting to validate until superclasses are initialized.
    if not jars:
      raise TargetDefinitionException(self, 'Must have a non-empty list of jars.')
    self.add_labels('jars', 'jvm')

  @property
  def jar_dependencies(self):
    return self.payload.jars

  @property
  def excludes(self):
    return self.payload.excludes

  @staticmethod
  def to_jar_dependencies(relative_to, jar_library_specs, build_graph):
    """Convenience method to resolve a list of specs to JarLibraries and return its jars attributes.

    Expects that the jar_libraries are declared relative to this target.

    :param Address relative_to: address target that references jar_library_specs, for
      error messages
    :param list jar_library_specs: string specs to JavaLibrary targets. Note, this list should be returned
      by the caller's traversable_specs() implementation to make sure that the jar_dependency jars
      have been added to the build graph.
    :param BuildGraph build_graph: build graph instance used to search for specs
    :return: list of JarDependency instances represented by the library_specs
    """
    jar_deps = OrderedSet()
    for spec in jar_library_specs:
      if not isinstance(spec, six.string_types):
        raise JarLibrary.ExpectedAddressError(
          "{address}: expected imports to contain string addresses, got {found_class}."
          .format(address=relative_to.spec,
                  found_class=type(spec).__name__))

      lookup = Address.parse(spec, relative_to=relative_to.spec_path)
      target = build_graph.get_target(lookup)
      if not isinstance(target, JarLibrary):
        raise JarLibrary.WrongTargetTypeError(
          "{address}: expected {spec} to be jar_library target type, got {found_class}"
          .format(address=relative_to.spec,
                  spec=spec,
                  found_class=type(target).__name__))
      jar_deps.update(target.jar_dependencies)

    return list(jar_deps)
