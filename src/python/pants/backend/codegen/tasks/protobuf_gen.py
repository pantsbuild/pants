# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import os
import subprocess
from collections import OrderedDict
from hashlib import sha1

from twitter.common.collections import OrderedSet

from pants.backend.codegen.targets.java_protobuf_library import JavaProtobufLibrary
from pants.backend.codegen.tasks.protobuf_parse import ProtobufParse
from pants.backend.codegen.tasks.simple_codegen_task import SimpleCodegenTask
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.jar_import_products import JarImportProducts
from pants.base.address import Address
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.source_root import SourceRoot
from pants.binaries.binary_util import BinaryUtil
from pants.fs.archive import ZIP
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_property


class ProtobufGen(SimpleCodegenTask):

  @classmethod
  def global_subsystems(cls):
    return super(ProtobufGen, cls).global_subsystems() + (BinaryUtil.Factory,)

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
    register('--plugins', advanced=True, fingerprint=True, action='append',
             help='Names of protobuf plugins to invoke.  Protoc will look for an executable '
                  'named protoc-gen-$NAME on PATH.',
             default=[])

    register('--extra_path', advanced=True, action='append',
             help='Prepend this path onto PATH in the environment before executing protoc. '
                  'Intended to help protoc find its plugins.',
             default=None)
    register('--supportdir', advanced=True,
             help='Path to use for the protoc binary.  Used as part of the path to lookup the'
                  'tool under --pants-bootstrapdir.',
             default='bin/protobuf')
    register('--javadeps', advanced=True, action='append',
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
    self.plugins = self.get_options().plugins
    self._extra_paths = self.get_options().extra_path

  @memoized_property
  def protobuf_binary(self):
    binary_util = BinaryUtil.Factory.create()
    return binary_util.select_binary(self.get_options().supportdir,
                                     self.get_options().version,
                                     'protoc')

  @property
  def javadeps(self):
    return self.resolve_deps(self.get_options().javadeps)

  def synthetic_target_type(self, target):
    return JavaLibrary

  def synthetic_target_extra_dependencies(self, target):
    deps = OrderedSet()
    if target.imported_jars:
      # We need to add in the proto imports jars.
      jars_address = Address(os.path.relpath(self.codegen_workdir(target), get_buildroot()),
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

  @classmethod
  def supported_strategy_types(cls):
    return [cls.IsolatedCodegenStrategy, cls.ProtobufGlobalCodegenStrategy]

  def sources_generated_by_target(self, target):
    genfiles = []
    for source in target.sources_relative_to_source_root():
      path = os.path.join(target.target_base, source)
      genfiles.extend(self.calculate_genfiles(path, source))
    return genfiles

  def execute_codegen(self, targets):
    if not targets:
      return

    sources_by_base = self._calculate_sources(targets)
    if self.codegen_strategy.name() == 'isolated':
      sources = OrderedSet()
      for target in targets:
        sources.update(target.sources_relative_to_buildroot())
    else:
      sources = OrderedSet(itertools.chain.from_iterable(sources_by_base.values()))

    if not self.validate_sources_present(sources, targets):
      return

    bases = OrderedSet(sources_by_base.keys())
    bases.update(self._proto_path_imports(targets))
    check_duplicate_conflicting_protos(self, sources_by_base, sources, self.context.log)

    for target in targets:
      # NB(gm): If the strategy is set to 'isolated', then 'targets' should contain only a single
      # element, which means this simply sets the output directory depending on that element.
      # If the strategy is set to 'global', the target passed in as a parameter here will be
      # completely arbitrary, but that's OK because the codegen_workdir function completely
      # ignores the target parameter when using a global strategy.
      output_dir = self.codegen_workdir(target)
      break
    gen_flag = '--java_out'

    safe_mkdir(output_dir)
    gen = '{0}={1}'.format(gen_flag, output_dir)

    args = [self.protobuf_binary, gen]

    if self.plugins:
      for plugin in self.plugins:
        # TODO(Eric Ayers) Is it a good assumption that the generated source output dir is
        # acceptable for all plugins?
        args.append("--{0}_out={1}".format(plugin, output_dir))

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

  def _calculate_sources(self, targets):
    gentargets = OrderedSet()

    def add_to_gentargets(target):
      if self.is_gentarget(target):
        gentargets.add(target)
    self.context.build_graph.walk_transitive_dependency_graph(
      [target.address for target in targets],
      add_to_gentargets,
      postorder=True)
    sources_by_base = OrderedDict()
    # TODO(Eric Ayers) Extract this logic for general use? When using unpacked_jars it is needed
    # to get the correct source root for paths outside the current BUILD tree.
    for target in gentargets:
      for source in target.sources_relative_to_buildroot():
        base = SourceRoot.find_by_path(source)
        if not base:
          base, _ = target.target_base, target.sources_relative_to_buildroot()
          self.context.log.debug('Could not find source root for {source}.'
                                 ' Missing call to SourceRoot.register()?  Fell back to {base}.'
                                 .format(source=source, base=base))
        if base not in sources_by_base:
          sources_by_base[base] = OrderedSet()
        sources_by_base[base].add(source)
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

  def calculate_genfiles(self, path, source):
    protobuf_parse = ProtobufParse(path, source)
    protobuf_parse.parse()
    return OrderedSet(self.calculate_java_genfiles(protobuf_parse))

  def calculate_java_genfiles(self, protobuf_parse):
    basepath = protobuf_parse.package.replace('.', os.path.sep)

    classnames = {protobuf_parse.outer_class_name}
    if protobuf_parse.multiple_files:
      classnames |= protobuf_parse.enums | protobuf_parse.messages | protobuf_parse.services | \
        set(['{name}OrBuilder'.format(name=m) for m in protobuf_parse.messages])

    for classname in classnames:
      yield os.path.join(basepath, '{0}.java'.format(classname))

  class ProtobufGlobalCodegenStrategy(SimpleCodegenTask.GlobalCodegenStrategy):

    def find_sources(self, target):
      return self._task.sources_generated_by_target(target)


def _same_contents(a, b):
  """Perform a comparison of the two files"""
  with open(a, 'rb') as fp_a, open(b, 'rb') as fp_b:
    return fp_a.read() == fp_b.read()


def check_duplicate_conflicting_protos(task, sources_by_base, sources, log):
  """Checks if proto files are duplicate or conflicting.

  There are sometimes two files with the same name on the .proto path.  This causes the protobuf
  compiler to stop with an error.  Some repos have legitimate cases for this, and so this task
  decides to just choose one to keep the entire build from failing.  Sometimes, they are identical
  copies.  That is harmless, but if there are two files with the same name with different contents,
  that is ambiguous and we want to complain loudly.

  :param task: provides an implementation of the method calculate_genfiles()
  :param dict sources_by_base: mapping of base to path
  :param set|OrderedSet sources: set of sources
  :param Context.Log log: writes error messages to the console for conflicts
  """
  sources_by_genfile = {}
  for base in sources_by_base.keys():  # Need to iterate over /original/ bases.
    for path in sources_by_base[base]:
      if not path in sources:
        continue  # Check to make sure we haven't already removed it.
      source = path[len(base):]

      genfiles = task.calculate_genfiles(path, source)
      for genfile in genfiles:
        if genfile in sources_by_genfile:
          # Possible conflict!
          prev = sources_by_genfile[genfile]
          if not prev in sources:
            # Must have been culled by an earlier pass.
            continue
          if not _same_contents(path, prev):
            log.error('Proto conflict detected (.proto files are different):\n'
                      '1: {prev}\n2: {curr}'.format(prev=prev, curr=path))
          else:
            log.warn('Proto duplication detected (.proto files are identical):\n'
                     '1: {prev}\n2: {curr}'.format(prev=prev, curr=path))
          log.warn('  Arbitrarily favoring proto 1.')
          if path in sources:
            sources.remove(path)  # Favor the first version.
          continue
        sources_by_genfile[genfile] = path
