# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from hashlib import sha1

import six

from twitter.common.collections import OrderedSet
from twitter.common.lang import Compatibility

from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.address import SyntheticAddress
from pants.base.payload import Payload
from pants.base.payload_field import combine_hashes, PayloadField


class ImportsField(OrderedSet, PayloadField):
  def _compute_fingerprint(self):
    def hashes_iter():
      for item in self:
        if isinstance(item, six.text_type):
          yield sha1(item.encode('utf-8')).hexdigest()
        elif isinstance(item, six.binary_type):
          yield sha1(item).hexdigest()
        elif isinstance(item, JarDependency):
          yield sha1(item.cache_key()).hexdigest()
    return combine_hashes(hashes_iter())


class JavaProtobufLibrary(ExportableJvmLibrary):
  """Generates a stub Java library from protobuf IDL files."""

  class PrematureImportPokeError(Exception):
    """Thrown if something tries to access this target's imports before the build graph has been
    generated.
    """

  def __init__(self, payload=None, buildflags=None, imports=None, **kwargs):
    """
    :param buildflags: Unused, and will be removed in a future release.
    :param imports: List of external :class:`pants.backend.jvm.targets.jar_dependency.JarDependency`
      objects and addresses of :class:`pants.backend.jvm.targets.jar_library.JarLibrary` targets
      which contain .proto definitions.
    """
    payload = payload or Payload()
    # TODO(pl, zundel): Enforce either address specs or JarDependencies for this type, not either.
    payload.add_fields({
      'raw_imports': ImportsField(imports or ())
    })
    super(JavaProtobufLibrary, self).__init__(payload=payload, **kwargs)
    self.add_labels('codegen')
    if imports:
      self.add_labels('has_imports')
    self._imports = None

  @property
  def traversable_specs(self):
    for spec in super(JavaProtobufLibrary, self).traversable_specs:
      yield spec
    for spec in self._library_imports:
      yield spec

  @property
  def _library_imports(self):
    for dep in self.payload.raw_imports:
      if isinstance(dep, Compatibility.string):
        yield dep

  @property
  def imports(self):
    """Returns the set of JarDependencys to be included when compiling this target."""
    if self._imports is None:
      libraries = OrderedSet(self._library_imports)
      import_jars = self.payload.raw_imports - libraries
      for spec in libraries:
        address = SyntheticAddress.parse(spec, relative_to=self.address.spec_path)
        target = self._build_graph.get_target(address)
        if isinstance(target, (JarLibrary, JvmTarget)):
          import_jars.update(target.jar_dependencies)
        else:
          # TODO(pl): This should be impossible, since these specs are in
          # traversable specs.  Likely this only would trigger when someone
          # accidentally included a dependency on a non-{Jvm,JarLib} target.
          # Fix this in a followup.
          raise self.PrematureImportPokeError(
              "{address}: Failed to resolve import '{spec}'.".format(
                  address=self.address.spec,
                  spec=address.spec))
      self._imports = import_jars
    return self._imports
