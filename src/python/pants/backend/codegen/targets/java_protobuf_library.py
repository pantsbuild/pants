# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.build_manual import manual


@manual.builddict(tags=["java"])
class JavaProtobufLibrary(ExportableJvmLibrary):
  """Generates a stub Java library from protobuf IDL files."""

  def __init__(self, buildflags=None, imports=None, **kwargs):
    """
    :param string name: The name of this target, which combined with this build file defines the
      target :class:`pants.base.address.Address`.
    :param sources: A list of filenames representing the source code this library is compiled from.
    :type sources: list of strings
    :param Artifact provides: The :class:`pants.targets.artifact.Artifact` to publish that
      represents this target outside the repo.
    :param dependencies: List of :class:`pants.base.target.Target` instances this target depends on.
    :type dependencies: list of targets
    :param excludes: List of :class:`pants.targets.exclude.Exclude` instances to filter this
      target's transitive dependencies against.
    :param buildflags: Unused, and will be removed in a future release.
    :param imports: External jar(s) which contain .proto definitions, inputted with jar_sources in
      the format: imports=jar_sources(jar(...), jar(...), jar(...)).
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
    """
    super(JavaProtobufLibrary, self).__init__(**kwargs)
    self.add_labels('codegen', 'has_imports')
    self._imports = imports

  _import_jars = None
  _proto_dirs = None
  def _init_jars(self, context):
    if self._import_jars is not None:
      return
    self._import_jars = set()
    self._proto_dirs = set()
    if self._imports:
      for fileset, jar in self._imports(context, self.address.build_file):
        self._proto_dirs.add(fileset)
        self._import_jars.add(jar)

  def import_jars(self, context):
    self._init_jars(context)
    return self._import_jars

  def proto_dirs(self, context):
    self._init_jars(context)
    return self._proto_dirs
