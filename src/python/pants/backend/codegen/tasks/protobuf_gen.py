# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
from collections import OrderedDict
from hashlib import sha1

from twitter.common.collections import OrderedSet

from pants.backend.codegen.targets.java_protobuf_library import JavaProtobufLibrary
from pants.backend.codegen.tasks.simple_codegen_task import SimpleCodegenTask
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.jar_import_products import JarImportProducts
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.binaries.binary_util import BinaryUtil
from pants.build_graph.address import Address
from pants.fs.archive import ZIP
from pants.util.memo import memoized_property


class ProtobufGen(SimpleCodegenTask):

  @classmethod
  def subsystem_dependencies(cls):
    return super(ProtobufGen, cls).subsystem_dependencies() + (BinaryUtil.Factory,)

  @classmethod
  def register_options(cls, register):
    super(ProtobufGen, cls).register_options(register)

    # The protoc version and the plugin names are used as proxies for the identity of the protoc
    # executable environment here.  Although version is an obvious proxy for the protoc binary
    # itself, plugin names are less so and plugin authors must include a version in the name for
    # proper invalidation of protobuf products in the face of plugin modification that affects
    # plugin outputs.
    register('--version', advanced=True, fingerprint=True,
             help='Version of protoc.  Used to create the default --javadeps and as part of '
                  'the path to lookup the tool with --pants-support-baseurls and '
                  '--pants-bootstrapdir.  When changing this parameter you may also need to '
                  'update --javadeps.',
             default='2.4.1')
    register('--protoc-plugins', advanced=True, fingerprint=True, type=list,
             help='Names of protobuf plugins to invoke.  Protoc will look for an executable '
                  'named protoc-gen-$NAME on PATH.')

    register('--extra_path', advanced=True, type=list,
             help='Prepend this path onto PATH in the environment before executing protoc. '
                  'Intended to help protoc find its plugins.',
             default=None)
    register('--supportdir', advanced=True,
             help='Path to use for the protoc binary.  Used as part of the path to lookup the'
                  'tool under --pants-bootstrapdir.',
             default='bin/protobuf')
    register('--javadeps', advanced=True, type=list,
             help='Dependencies to bootstrap this task for generating java code.  When changing '
                  'this parameter you may also need to update --version.',
             default=['3rdparty:protobuf-java'])

  # TODO https://github.com/pantsbuild/pants/issues/604 prep start
  @classmethod
  def prepare(cls, options, round_manager):
    super(ProtobufGen, cls).prepare(options, round_manager)
    round_manager.require_data(JarImportProducts)
    round_manager.require_data('deferred_sources')
  # TODO https://github.com/pantsbuild/pants/issues/604 prep finish

  def __init__(self, *args, **kwargs):
    """Generates Java files from .proto files using the Google protobuf compiler."""
    super(ProtobufGen, self).__init__(*args, **kwargs)
    self.plugins = self.get_options().protoc_plugins or []
    self._extra_paths = self.get_options().extra_path or []

  @memoized_property
  def protobuf_binary(self):
    binary_util = BinaryUtil.Factory.create()
    return binary_util.select_binary(self.get_options().supportdir,
                                     self.get_options().version,
                                     'protoc')

  @property
  def javadeps(self):
    return self.resolve_deps(self.get_options().javadeps or [])

  def synthetic_target_type(self, target):
    return JavaLibrary

  def synthetic_target_extra_dependencies(self, target, target_workdir):
    deps = OrderedSet()
    if target.imported_jars:
      # We need to add in the proto imports jars.
      jars_address = Address(os.path.relpath(target_workdir, get_buildroot()),
                             target.id + '-rjars')
      jars_target = self.context.add_new_target(jars_address,
                                                JarLibrary,
                                                jars=target.imported_jars,
                                                derived_from=target)
      deps.update([jars_target])
    deps.update(self.javadeps)
    return deps

  def is_gentarget(self, target):
    return isinstance(target, JavaProtobufLibrary)

  def execute_codegen(self, target, target_workdir):
    sources_by_base = self._calculate_sources(target)
    sources = target.sources_relative_to_buildroot()

    bases = OrderedSet(sources_by_base.keys())
    bases.update(self._proto_path_imports([target]))

    gen_flag = '--java_out'

    gen = '{0}={1}'.format(gen_flag, target_workdir)

    args = [self.protobuf_binary, gen]

    if self.plugins:
      for plugin in self.plugins:
        args.append("--{0}_out={1}".format(plugin, target_workdir))

    for base in bases:
      args.append('--proto_path={0}'.format(base))

    args.extend(sources)

    # Tack on extra path entries. These can be used to find protoc plugins
    protoc_environ = os.environ.copy()
    if self._extra_paths:
      protoc_environ['PATH'] = os.pathsep.join(self._extra_paths
                                               + protoc_environ['PATH'].split(os.pathsep))

    self.context.log.debug('Executing: {0}'.format('\\\n  '.join(args)))
    process = subprocess.Popen(args, env=protoc_environ)
    result = process.wait()
    if result != 0:
      raise TaskError('{0} ... exited non-zero ({1})'.format(self.protobuf_binary, result))

  def _calculate_sources(self, target):
    gentargets = OrderedSet()

    def add_to_gentargets(target):
      if self.is_gentarget(target):
        gentargets.add(target)
    self.context.build_graph.walk_transitive_dependency_graph(
      [target.address],
      add_to_gentargets,
      postorder=True)
    sources_by_base = OrderedDict()
    for target in gentargets:
      base = target.target_base
      if base not in sources_by_base:
        sources_by_base[base] = OrderedSet()
      sources_by_base[base].update(target.sources_relative_to_buildroot())
    return sources_by_base

  def _jars_to_directories(self, target):
    """Extracts and maps jars to directories containing their contents.

    :returns: a set of filepaths to directories containing the contents of jar.
    """
    files = set()
    jar_import_products = self.context.products.get_data(JarImportProducts)
    imports = jar_import_products.imports(target)
    for coordinate, jar in imports:
      files.add(self._extract_jar(coordinate, jar))
    return files

  def _extract_jar(self, coordinate, jar_path):
    """Extracts the jar to a subfolder of workdir/extracted and returns the path to it."""
    with open(jar_path, 'rb') as f:
      outdir = os.path.join(self.workdir, 'extracted', sha1(f.read()).hexdigest())
    if not os.path.exists(outdir):
      ZIP.extract(jar_path, outdir)
      self.context.log.debug('Extracting jar {jar} at {jar_path}.'
                             .format(jar=coordinate, jar_path=jar_path))
    else:
      self.context.log.debug('Jar {jar} already extracted at {jar_path}.'
                             .format(jar=coordinate, jar_path=jar_path))
    return outdir

  def _proto_path_imports(self, proto_targets):
    for target in proto_targets:
      for path in self._jars_to_directories(target):
        yield os.path.relpath(path, get_buildroot())
