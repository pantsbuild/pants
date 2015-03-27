# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import os
import re
import subprocess
from collections import OrderedDict, defaultdict
from hashlib import sha1

from twitter.common.collections import OrderedSet

from pants.backend.codegen.targets.java_protobuf_library import JavaProtobufLibrary
from pants.backend.codegen.tasks.code_gen import CodeGen
from pants.backend.codegen.tasks.protobuf_parse import ProtobufParse
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.address import SyntheticAddress
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.source_root import SourceRoot
from pants.base.target import Target
from pants.fs.archive import ZIP
from pants.util.binaryutil import BinaryUtil
from pants.util.dirutil import safe_mkdir


class ProtobufGen(CodeGen):

  @classmethod
  def register_options(cls, register):
    super(ProtobufGen, cls).register_options(register)
    register('--lang', action='append', choices=['python', 'java'],
             help='Force generation of protobuf code for these languages.')
    register('--version', advanced=True,
             help='Version of protoc.  Used to create the default --javadeps and as part of '
                  'the path to lookup the tool with --pants-support-baseurls and '
                  '--pants-bootstrapdir.  When changing this parameter you may also need to '
                  'update --javadeps.',
             default='2.4.1')
    register('--plugins', advanced=True, action='append',
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
    register('--pythondeps', advanced=True, action='append',
             help='Dependencies to bootstrap this task for generating python code.  When changing '
                  'this parameter, you may also need to update --version.',
             default=[])

  # TODO https://github.com/pantsbuild/pants/issues/604 prep start
  @classmethod
  def prepare(cls, options, round_manager):
    super(ProtobufGen, cls).prepare(options, round_manager)
    round_manager.require_data('ivy_imports')
    round_manager.require_data('deferred_sources')
  # TODO https://github.com/pantsbuild/pants/issues/604 prep finish

  def __init__(self, *args, **kwargs):
    """Generates Java and Python files from .proto files using the Google protobuf compiler."""
    super(ProtobufGen, self).__init__(*args, **kwargs)

    self.plugins = self.get_options().plugins
    self._extra_paths = self.get_options().extra_path

    self.java_out = os.path.join(self.workdir, 'gen-java')
    self.py_out = os.path.join(self.workdir, 'gen-py')

    self.gen_langs = set(self.get_options().lang)
    for lang in ('java', 'python'):
      if self.context.products.isrequired(lang):
        self.gen_langs.add(lang)

    self.protobuf_binary = BinaryUtil.from_options(self.get_options()).select_binary('protoc')

  def resolve_deps(self, deps_list, key):
    deps = OrderedSet()
    for dep in deps_list:
      try:
        deps.update(self.context.resolve(dep))
      except AddressLookupError as e:
        raise self.DepLookupError("{message}\n  referenced from --{key} option."
                                  .format(message=e, key=key))
    return deps

  @property
  def javadeps(self):
    return self.resolve_deps(self.get_options().javadeps, 'javadeps')

  @property
  def pythondeps(self):
    return self.resolve_deps(self.get_options().pythondeps, 'pythondeps')

  def invalidate_for_files(self):
    return [self.protobuf_binary]

  def is_gentarget(self, target):
    return isinstance(target, JavaProtobufLibrary)

  def is_forced(self, lang):
    return lang in self.gen_langs

  def genlangs(self):
    return Target.LANG_DISCRIMINATORS

  def _jars_to_directories(self, target):
    """Extracts and maps jars to directories containing their contents.

    :returns: a set of filepaths to directories containing the contents of jar.
    """
    files = set()
    jarmap = self.context.products.get('ivy_imports')
    for folder, names in jarmap.by_target[target].items():
      for name in names:
        files.add(self._extract_jar(os.path.join(folder, name)))
    return files

  def _extract_jar(self, jar_path):
    """Extracts the jar to a subfolder of workdir/extracted and returns the path to it."""
    with open(jar_path, 'rb') as f:
      outdir = os.path.join(self.workdir, 'extracted', sha1(f.read()).hexdigest())
    if not os.path.exists(outdir):
      ZIP.extract(jar_path, outdir)
      self.context.log.debug('Extracting jar at {jar_path}.'.format(jar_path=jar_path))
    else:
      self.context.log.debug('Jar already extracted at {jar_path}.'.format(jar_path=jar_path))
    return outdir

  def _proto_path_imports(self, proto_targets):
    for target in proto_targets:
      for path in self._jars_to_directories(target):
        yield os.path.relpath(path, get_buildroot())

  def genlang(self, lang, targets):
    sources_by_base = self._calculate_sources(targets)
    sources = OrderedSet(itertools.chain.from_iterable(sources_by_base.values()))

    # TODO(Eric Ayers) Push this check up to a superclass so all of codegen can share it?
    if not sources:
      formatted_targets = "\n".join([t.address.spec for t in targets])
      raise TaskError("Had {count} targets but no sources?\n targets={targets}"
                            .format(count=len(targets), targets=formatted_targets))

    bases = OrderedSet(sources_by_base.keys())
    bases.update(self._proto_path_imports(targets))
    check_duplicate_conflicting_protos(self, sources_by_base, sources, self.context.log)

    if lang == 'java':
      output_dir = self.java_out
      gen_flag = '--java_out'
    elif lang == 'python':
      output_dir = self.py_out
      gen_flag = '--python_out'
    else:
      raise TaskError('Unrecognized protobuf gen lang: {0}'.format(lang))

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
    """
    Find the appropriate source roots used for sources.

    :return: mapping of source roots to  set of sources under the roots
    """
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

  def createtarget(self, lang, gentarget, dependees):
    if lang == 'java':
      return self._create_java_target(gentarget, dependees)
    elif lang == 'python':
      return self._create_python_target(gentarget, dependees)
    else:
      raise TaskError('Unrecognized protobuf gen lang: {0}'.format(lang))

  def _create_java_target(self, target, dependees):
    genfiles = []
    for source in target.sources_relative_to_source_root():
      path = os.path.join(target.target_base, source)
      genfiles.extend(self.calculate_genfiles(path, source).get('java', []))
    spec_path = os.path.relpath(self.java_out, get_buildroot())
    address = SyntheticAddress(spec_path, target.id)
    deps = OrderedSet(self.javadeps)
    import_jars = target.imported_jars
    jars_tgt = self.context.add_new_target(SyntheticAddress(spec_path, target.id+str('-rjars')),
                                           JarLibrary,
                                           jars=import_jars,
                                           derived_from=target)
    # Add in the 'spec-rjars' target, which contains all the JarDependency targets passed in via the
    # imports parameter. Each of these jars is expected to contain .proto files bundled together
    # with their .class files.
    deps.add(jars_tgt)
    tgt = self.context.add_new_target(address,
                                      JavaLibrary,
                                      derived_from=target,
                                      sources=genfiles,
                                      provides=target.provides,
                                      dependencies=deps,
                                      excludes=target.payload.get_field_value('excludes'))
    for dependee in dependees:
      dependee.inject_dependency(tgt.address)
    return tgt

  def _create_python_target(self, target, dependees):
    genfiles = []
    for source in target.sources_relative_to_source_root():
      path = os.path.join(target.target_base, source)
      genfiles.extend(self.calculate_genfiles(path, source).get('py', []))
    spec_path = os.path.relpath(self.py_out, get_buildroot())
    address = SyntheticAddress(spec_path, target.id)
    tgt = self.context.add_new_target(address,
                                      PythonLibrary,
                                      derived_from=target,
                                      sources=genfiles,
                                      dependencies=self.pythondeps)
    for dependee in dependees:
      dependee.inject_dependency(tgt.address)
    return tgt


  def calculate_genfiles(self, path, source):
    protobuf_parse = ProtobufParse(path, source)
    protobuf_parse.parse()

    genfiles = defaultdict(set)
    genfiles['py'].update(self.calculate_python_genfiles(source))
    genfiles['java'].update(self.calculate_java_genfiles(protobuf_parse))
    return genfiles


  def calculate_python_genfiles(self, source):
    yield re.sub(r'\.proto$', '_pb2.py', source)


  def calculate_java_genfiles(self, protobuf_parse):
    basepath = protobuf_parse.package.replace('.', os.path.sep)

    classnames = set([protobuf_parse.outer_class_name])
    if protobuf_parse.multiple_files:
      classnames |= protobuf_parse.enums | protobuf_parse.messages | protobuf_parse.services | \
        set(['{name}OrBuilder'.format(name=m) for m in protobuf_parse.messages])

    for classname in classnames:
      yield os.path.join(basepath, '{0}.java'.format(classname))


def _same_contents(a, b):
  """Perform a comparison of the two files"""
  with open(a, 'r') as f:
    a_data = f.read()
  with open(b, 'r') as f:
    b_data = f.read()
  return a_data == b_data


def check_duplicate_conflicting_protos(task, sources_by_base, sources, log):
  """Checks if proto files are duplicate or conflicting.

  There are sometimes two files with the same name on the .proto path.  This causes the protobuf
  compiler to stop with an error.  Some repos have legitimate cases for this, and so this task
  decides to just choose one to keep the entire build from failing.  Sometimes, they are identical
  copies.  That is harmless, but if there are two files with the same name with different contents,
  that is ambiguous and we want to complain loudly.

  :param task: provides an implementation of the method calculate_genfiles()
  :param dict sources_by_base: mapping of base to path
  :param list sources: list of sources
  :param Context.Log log: writes error messages to the console for conflicts
  """
  sources_by_genfile = {}
  for base in sources_by_base.keys(): # Need to iterate over /original/ bases.
    for path in sources_by_base[base]:
      if not path in sources:
        continue # Check to make sure we haven't already removed it.
      source = path[len(base):]

      genfiles = task.calculate_genfiles(path, source)
      for key in genfiles.keys():
        for genfile in genfiles[key]:
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
              sources.remove(path) # Favor the first version.
            continue
          sources_by_genfile[genfile] = path
