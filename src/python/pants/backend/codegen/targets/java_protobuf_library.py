# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.collections import OrderedSet
from twitter.common.lang import Compatibility

from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.address import SyntheticAddress
from pants.base.payload import JavaProtobufLibraryPayload


class JavaProtobufLibrary(ExportableJvmLibrary):
  """Generates a stub Java library from protobuf IDL files."""

  class PrematureImportPokeError(Exception):
    """Thrown if something tries to access this target's imports before the build graph has been
    generated.
    """

  def __init__(self, buildflags=None, imports=None, **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the :doc:`target address <target_addresses>`.
    :param sources: Source code files to compile. Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings
    :param provides: The ``artifact``
      to publish that represents this target outside the repo.
    :param dependencies: Other targets that this target depends on.
    :type dependencies: list of target specs
    :param excludes: List of :ref:`exclude <bdict_exclude>`\s
      to filter this target's transitive dependencies against.
    :param buildflags: Unused, and will be removed in a future release.
    :param imports: List of external :class:`pants.backend.jvm.targets.jar_dependency.JarDependency`
      objects and addresses of :class:`pants.backend.jvm.targets.jar_library.JarLibrary` targets
      which contain .proto definitions.
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
    """
    super(JavaProtobufLibrary, self).__init__(**kwargs)
    self.add_labels('codegen')
    if imports:
      self.add_labels('has_imports')
    self.raw_imports = OrderedSet(imports or [])
    self._imports = None
    self.payload = JavaProtobufLibraryPayload(
        sources_rel_path=kwargs.get('sources_rel_path') or self.address.spec_path,
        sources=kwargs.get('sources'),
        provides=kwargs.get('provides'),
        excludes=kwargs.get('excludes'),
        configurations=kwargs.get('configurations'),
        imports=OrderedSet(self.raw_imports),
      )

  @property
  def traversable_specs(self):
    for spec in super(JavaProtobufLibrary, self).traversable_specs:
      yield spec
    for spec in self._library_imports:
      yield spec

  @property
  def _library_imports(self):
    for dep in self.raw_imports:
      if isinstance(dep, Compatibility.string):
        yield dep

  @property
  def imports(self):
    """Returns the set of JarDependencys to be included when compiling this target."""
    if self._imports is None:
      libraries = OrderedSet(self._library_imports)
      import_jars = self.raw_imports - libraries
      for spec in libraries:
        address = SyntheticAddress.parse(spec, relative_to=self.address.spec_path)
        target = self._build_graph.get_target(address)
        if isinstance(target, (JarLibrary, JvmTarget)):
          import_jars.update(target.jar_dependencies)
        else:
          raise self.PrematureImportPokeError(
              "{address}: Failed to resolve import '{spec}'.".format(
                  address=self.address.spec,
                  spec=address.spec))
      self._imports = import_jars
    return self._imports
