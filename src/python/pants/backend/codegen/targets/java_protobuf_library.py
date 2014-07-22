# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.lang import Compatibility

from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.address import SyntheticAddress
from pants.base.payload import JavaProtobufLibraryPayload


class JavaProtobufLibrary(ExportableJvmLibrary):
  """Generates a stub Java library from protobuf IDL files."""

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
    self.raw_imports = set(imports or [])
    self._imports = None
    self.payload = JavaProtobufLibraryPayload(
        sources_rel_path=kwargs.get('sources_rel_path') or self.address.spec_path,
        sources=kwargs.get('sources'),
        provides=kwargs.get('provides'),
        excludes=kwargs.get('excludes'),
        configurations=kwargs.get('configurations'),
        imports=set(self.imports),
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
    if self._imports:
      return self._imports

    libraries = set(self._library_imports)
    import_jars = list(self.raw_imports - libraries)
    def add_jars(jar_library):
      import_jars.extend(jar_library.jar_dependencies)
    for spec in libraries:
      address = SyntheticAddress.parse(spec, relative_to=self.address.spec_path)
      target = self._build_graph.get_target(address)
      if target:
        target.walk(add_jars, predicate=lambda tgt: tgt.is_jar_library)
    self._imports = set(import_jars)
    return self._imports
