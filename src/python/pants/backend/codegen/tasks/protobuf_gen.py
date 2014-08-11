# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
from hashlib import sha1
import os
import re
import subprocess

from twitter.common import log
from twitter.common.collections import OrderedDict, OrderedSet, maybe_list

from pants.backend.codegen.targets.java_protobuf_library import JavaProtobufLibrary
from pants.backend.codegen.tasks.code_gen import CodeGen
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.address import SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.target import Target
from pants.binary_util import BinaryUtil
from pants.fs.archive import ZIP
from pants.util.dirutil import safe_mkdir

# Override with protobuf-gen -> supportdir
_PROTOBUF_GEN_SUPPORTDIR_DEFAULT='bin/protobuf'

# Override with protobuf-gen -> version
_PROTOBUF_VERSION_DEFAULT='2.4.1'

# Override with protobuf-gen -> javadeps (Accepts a list)
_PROTOBUF_GEN_JAVADEPS_DEFAULT='3rdparty:protobuf-{version}'

# Override with in protobuf-gen -> pythondeps (Accepts a list)
_PROTOBUF_GEN_PYTHONDEPS_DEFAULT = []

class ProtobufGen(CodeGen):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag('lang'), dest='protobuf_gen_langs', default=[],
                            action='append', type='choice', choices=['python', 'java'],
                            help='Force generation of protobuf code for these languages.')

  def __init__(self, *args, **kwargs):
    super(ProtobufGen, self).__init__(*args, **kwargs)

    self.protoc_supportdir = self.context.config.get('protobuf-gen', 'supportdir',
                                                     default=_PROTOBUF_GEN_SUPPORTDIR_DEFAULT)
    self.protoc_version = self.context.config.get('protobuf-gen', 'version',
                                                  default=_PROTOBUF_VERSION_DEFAULT)
    self.plugins = self.context.config.getlist('protobuf-gen', 'plugins', default=[])

    self.java_out = os.path.join(self.workdir, 'gen-java')
    self.py_out = os.path.join(self.workdir, 'gen-py')

    self.gen_langs = set(self.context.options.protobuf_gen_langs)
    for lang in ('java', 'python'):
      if self.context.products.isrequired(lang):
        self.gen_langs.add(lang)

    self.protobuf_binary = BinaryUtil(config=self.context.config).select_binary(
      self.protoc_supportdir,
      self.protoc_version,
      'protoc'
    )

  def prepare(self, round_manager):
    super(ProtobufGen, self).prepare(round_manager)
    round_manager.require_data('ivy_imports')

  def resolve_deps(self, key, default=[]):
    deps = OrderedSet()
    for dep in self.context.config.getlist('protobuf-gen', key, default=maybe_list(default)):
      if dep:
        deps.update(self.context.resolve(dep))
    return deps

  @property
  def javadeps(self):
    return self.resolve_deps('javadeps',
                             default=_PROTOBUF_GEN_JAVADEPS_DEFAULT
                             .format(version=self.protoc_version))
  @property
  def pythondeps(self):
    return self.resolve_deps('pythondeps', default=_PROTOBUF_GEN_PYTHONDEPS_DEFAULT)

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

  def _same_contents(self, a, b):
    with open(a, 'r') as f:
      a_data = f.read()
    with open(b, 'r') as f:
      b_data = f.read()
    return a_data == b_data

  def genlang(self, lang, targets):
    sources_by_base = self._calculate_sources(targets)
    sources = reduce(lambda a,b: a^b, sources_by_base.values(), OrderedSet())
    bases = OrderedSet(sources_by_base.keys())
    bases.update(self._proto_path_imports(targets))

    # Check for duplicate/conflicting protos.
    sources_by_genfile = {}
    for base in sources_by_base.keys(): # Need to iterate over /original/ bases.
      for path in sources_by_base[base]:
        if not path in sources:
          continue # Check to make sure we haven't already removed it.
        source = path[len(base):]
        genfiles = calculate_genfiles(path, source)
        for key in genfiles.keys():
          for genfile in genfiles[key]:
            if genfile in sources_by_genfile:
              # Possible conflict!
              prev = sources_by_genfile[genfile]
              if not prev in sources:
                # Must have been culled by an earlier pass.
                continue
              if not self._same_contents(path, prev):
                self.context.log.error('Proto conflict detected (.proto files are different):')
                self.context.log.error('  1: {prev}'.format(prev=prev))
                self.context.log.error('  2: {curr}'.format(curr=path))
              else:
                self.context.log.warn('Proto duplication detected (.proto files are identical):')
                self.context.log.warn('  1: {prev}'.format(prev=prev))
                self.context.log.warn('  2: {curr}'.format(curr=path))
              self.context.log.warn('  Arbitrarily favoring proto 1.')
              if path in sources:
                sources.remove(path) # Favor the first version.
              continue
            sources_by_genfile[genfile] = path

    if lang == 'java':
      output_dir = self.java_out
      gen_flag = '--java_out'
    elif lang == 'python':
      output_dir = self.py_out
      gen_flag = '--python_out'
    else:
      raise TaskError('Unrecognized protobuf gen lang: %s' % lang)

    safe_mkdir(output_dir)
    gen = '%s=%s' % (gen_flag, output_dir)

    args = [self.protobuf_binary, gen]

    if self.plugins:
      for plugin in self.plugins:
        # TODO(Eric Ayers) Is it a good assumption that the generated source output dir is
        # acceptable for all plugins?
        args.append("--%s_protobuf_out=%s" % (plugin, output_dir))

    for base in bases:
      args.append('--proto_path=%s' % base)

    args.extend(sources)
    log.debug('Executing: %s' % '\\\n  '.join(args))
    process = subprocess.Popen(args)
    result = process.wait()
    if result != 0:
      raise TaskError('%s ... exited non-zero (%i)' % (self.protobuf_binary, result))

  def _calculate_sources(self, targets):
    walked_targets = set()
    for target in targets:
      walked_targets.update(t for t in target.closure() if self.is_gentarget(t))

    sources_by_base = OrderedDict()
    for target in self.context.build_graph.targets():
      if target in walked_targets:
        base, sources = target.target_base, target.sources_relative_to_buildroot()
        if base not in sources_by_base:
          sources_by_base[base] = OrderedSet()
        sources_by_base[base].update(sources)
    return sources_by_base

  def createtarget(self, lang, gentarget, dependees):
    if lang == 'java':
      return self._create_java_target(gentarget, dependees)
    elif lang == 'python':
      return self._create_python_target(gentarget, dependees)
    else:
      raise TaskError('Unrecognized protobuf gen lang: %s' % lang)

  def _create_java_target(self, target, dependees):
    genfiles = []
    for source in target.sources_relative_to_source_root():
      path = os.path.join(target.target_base, source)
      genfiles.extend(calculate_genfiles(path, source).get('java', []))
    spec_path = os.path.relpath(self.java_out, get_buildroot())
    address = SyntheticAddress(spec_path, target.id)
    deps = OrderedSet(self.javadeps)
    import_jars = target.imports
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
                                      excludes=target.payload.excludes)
    for dependee in dependees:
      dependee.inject_dependency(tgt.address)
    return tgt

  def _create_python_target(self, target, dependees):
    genfiles = []
    for source in target.sources_relative_to_source_root():
      path = os.path.join(target.target_base, source)
      genfiles.extend(calculate_genfiles(path, source).get('py', []))
    spec_path = os.path.relpath(self.py_out, get_buildroot())
    address = SyntheticAddress(spec_path, target.id)
    tgt = self.context.add_new_target(address,
                                      PythonLibrary,
                                      derived_from=target,
                                      sources=genfiles,
                                      dependencies=self.pythondeps)
    tgt.jar_dependencies.update(target.imports)
    for dependee in dependees:
      dependee.inject_dependency(tgt.address)
    return tgt


DEFAULT_PACKAGE_PARSER = re.compile(r'^\s*package\s+([^;]+)\s*;\s*$')
OPTION_PARSER = re.compile(r'^\s*option\s+([^ =]+)\s*=\s*([^\s]+)\s*;\s*$')
SERVICE_PARSER = re.compile(r'^\s*(service)\s+([^\s{]+).*')
TYPE_PARSER = re.compile(r'^\s*(enum|message)\s+([^\s{]+).*')


def camelcase(string):
  """Convert snake casing where present to camel casing"""
  return ''.join(word.capitalize() for word in re.split('[-_]', string))


def calculate_genfiles(path, source):
  with open(path, 'r') as protobuf:
    lines = protobuf.readlines()
    package = ''
    filename = re.sub(r'\.proto$', '', os.path.basename(source))
    outer_class_name = camelcase(filename)
    multiple_files = False
    outer_types = set()
    type_depth = 0
    for line in lines:
      match = DEFAULT_PACKAGE_PARSER.match(line)
      if match:
        package = match.group(1)
      else:
        match = OPTION_PARSER.match(line)
        if match:
          name = match.group(1)
          value = match.group(2).strip('"')
          if 'java_package' == name:
            package = value
          elif 'java_outer_classname' == name:
            outer_class_name = value
          elif 'java_multiple_files' == name:
            multiple_files = (value == 'true')
        else:
          uline = line.decode('utf-8').strip()
          type_depth += uline.count('{') - uline.count('}')
          match = SERVICE_PARSER.match(line)
          _update_type_list(match, type_depth, outer_types)
          if not match:
            match = TYPE_PARSER.match(line)
            _update_type_list(match, type_depth, outer_types)

    # TODO(Eric Ayers) replace with a real lex/parse understanding of protos. This is a big hack.
    # The parsing for finding type definitions is not reliable. See
    # https://github.com/pantsbuild/pants/issues/96
    types = outer_types if multiple_files and type_depth == 0 else set()

    genfiles = defaultdict(set)
    genfiles['py'].update(calculate_python_genfiles(source))
    genfiles['java'].update(calculate_java_genfiles(package, outer_class_name, types))
    return genfiles


def _update_type_list(match, type_depth, outer_types):
  if match and type_depth < 2: # This takes care of the case where { } are on the same line.
    type_name = match.group(2)
    outer_types.add(type_name)
    if match.group(1) == 'message':
      outer_types.add('%sOrBuilder' % type_name)


def calculate_python_genfiles(source):
  yield re.sub(r'\.proto$', '_pb2.py', source)


def calculate_java_genfiles(package, outer_class_name, types):
  basepath = package.replace('.', '/')

  def path(name):
    return os.path.join(basepath, '%s.java' % name)

  yield path(outer_class_name)
  for type_ in types:
    yield path(type_)
