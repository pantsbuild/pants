# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy
import os

from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import JarsField, PrimitiveField
from pants.build_graph.address import Address
from pants.build_graph.target import Target
from pants.java.jar.jar_dependency import JarDependency
from pants.util.memo import memoized_property


class ManagedJarDependencies(Target):
  """A set of pinned external artifact versions to apply transitively."""

  def __init__(self, payload=None, artifacts=None, **kwargs):
    """
    :param artifacts: List of `jar <#jar>`_\s or specs to jar_library targets with pinned versions.
      Versions are pinned per (org, name, classifier, ext) artifact coordinate (excludes, etc are
      ignored for the purposes of pinning).
    """
    jar_objects, library_specs = self._split_jars_and_specs(artifacts or ())
    payload = payload or Payload()
    payload.add_fields({
      'artifacts': JarsField(jar_objects),
      'library_specs': PrimitiveField(library_specs)
    })
    super(ManagedJarDependencies, self).__init__(payload=payload, **kwargs)

  @classmethod
  def compute_injectable_specs(cls, kwargs=None, payload=None):
    for spec in super(ManagedJarDependencies, cls).compute_injectable_specs(kwargs, payload):
      yield spec

    if kwargs:
      _, specs = self._split_jars_and_specs(kwargs.get('artifacts', ()))
      for spec in specs:
        yield spec
    elif payload:
      payload_dict = payload.as_dict()
      for spec in payload_dict.get('library_specs', ()):
        yield spec

  @memoized_property
  def library_specs(self):
    """Lists of specs to resolve to jar_libraries containing more jars."""
    return [Address.parse(spec, relative_to=self.address.spec_path).spec
            for spec in self.payload.library_specs]

  @classmethod
  def _split_jars_and_specs(cls, jars):
    library_specs = []
    jar_objects = []
    for item in jars:
      if isinstance(item, JarDependency):
        jar_objects.append(item)
      else:
        library_specs.append(item)
    return jar_objects, library_specs


class ManagedJarLibraries(object):
  """Creates a managed_jar_dependencies(), and also generates a jar_library for each artifact.

  Using this factory saves a lot of duplication. For example, this: ::

      managed_jar_libraries(name='managed',
        artifacts=[
          jar('org.foobar', 'foobar', '1.2'),
          jar('com.example', 'example', '8'),
        ],
      )

  Is equivalent to: ::

      managed_jar_dependencies(name='managed',
        artifacts=[
          jar('org.foobar', 'foobar', '1.2'),
          jar('com.example', 'example', '8'),
        ],
      )

      jar_library(name='org.foobar.foobar',
        jars=[jar('org.foobar', 'foobar')],
        managed_dependencies=':managed',
      )

      jar_library(name='com.example.example',
        jars=[jar('com.example', 'example')],
        managed_dependencies=':managed',
      )

  Which is also equivalent to: ::

      managed_jar_dependencies(name='managed',
        artifacts=[
          ':org.foobar.foobar',
          ':com.example.example',
        ],
      )

      jar_library(name='org.foobar.foobar',
        jars=[jar('org.foobar', 'foobar')],
        managed_dependencies=':managed',
      )

      jar_library(name='com.example.example',
        jars=[jar('com.example', 'example')],
        managed_dependencies=':managed',
      )

  """

  class JarLibraryNameCollision(TargetDefinitionException):
    """Two generated jar_libraries would have the same name."""

  def __init__(self, parse_context):
    self._parse_context = parse_context

  def __call__(self, name=None, artifacts=None, **kwargs):
    """
    :param string name: The optional name of the generated managed_jar_dependencies() target.
    :param artifacts: List of `jar <#jar>`_\s or specs to jar_library targets with pinned versions.
      Versions are pinned per (org, name, classifier, ext) artifact coordinate (excludes, etc are
      ignored for the purposes of pinning).
    """
    # Support the default target name protocol.
    if name is None:
      name = os.path.basename(self._parse_context.rel_path)
    management = self._parse_context.create_object('managed_jar_dependencies',
                                                   name=name,
                                                   artifacts=artifacts,
                                                   **kwargs)
    jars, _ = ManagedJarDependencies._split_jars_and_specs(artifacts)
    for library_name, dep in self._jars_by_name(management, jars).items():
      self._parse_context.create_object('jar_library',
                                        name=library_name,
                                        jars=[copy.deepcopy(dep)],
                                        managed_dependencies=':{}'.format(name))

  @classmethod
  def _jars_by_name(cls, management, jars):
    jars_by_name = {}
    for dep in jars:
      library_name = cls._jar_library_name(dep)
      if library_name in jars_by_name:
        previous = jars_by_name[library_name]
        raise cls.JarLibraryNameCollision(
          management,
          'Two jar coordinates would generate the same name. Please put one of them in a separate '
          'jar_library() definition.\n  {coord1}: {name}\n  {coord2}: {name}\n'.format(
            coord1=previous,
            coord2=dep,
            name=library_name,
          )
        )
      jars_by_name[library_name] = dep
    return jars_by_name

  @classmethod
  def _jar_coordinate_parts(cls, coord):
    yield coord.org
    yield coord.name
    if coord.classifier:
      yield coord.classifier
    if coord.ext:
      yield coord.ext

  @classmethod
  def _jar_library_name(cls, coord):
    return '.'.join(cls._jar_coordinate_parts(coord))
