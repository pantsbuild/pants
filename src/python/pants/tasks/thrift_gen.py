# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import errno
import os
import re
import subprocess
from collections import defaultdict, namedtuple

from twitter.common import log
from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir

from pants.base.build_environment import get_buildroot
from pants.targets.internal import InternalTarget
from pants.targets.java_library import JavaLibrary
from pants.targets.java_thrift_library import JavaThriftLibrary
from pants.targets.python_library import PythonLibrary
from pants.targets.python_thrift_library import PythonThriftLibrary
from pants.tasks import TaskError
from pants.tasks.code_gen import CodeGen
from pants.thrift_util import calculate_compile_roots, select_thrift_binary


def _copytree(from_base, to_base):
  def abort(error):
    raise TaskError('Failed to copy from %s to %s: %s' % (from_base, to_base, error))

  # TODO(John Sirois): Consider adding a unit test and lifting this to common/dirutils or similar
  def safe_link(src, dst):
    try:
      os.link(src, dst)
    except OSError as e:
      if e.errno != errno.EEXIST:
        raise e

  for dirpath, dirnames, filenames in os.walk(from_base, topdown=True, onerror=abort):
    to_path = os.path.join(to_base, os.path.relpath(dirpath, from_base))
    for dirname in dirnames:
      safe_mkdir(os.path.join(to_path, dirname))
    for filename in filenames:
      safe_link(os.path.join(dirpath, filename), os.path.join(to_path, filename))


class ThriftGen(CodeGen):
  GenInfo = namedtuple('GenInfo', ['gen', 'deps'])
  ThriftSession = namedtuple('ThriftSession', ['outdir', 'cmd', 'process'])

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("outdir"), dest="thrift_gen_create_outdir",
                            help="Emit generated code in to this directory.")

    option_group.add_option(mkflag("version"), dest="thrift_version",
                            help="Thrift compiler version.")

    option_group.add_option(mkflag("lang"), dest="thrift_gen_langs",  default=[],
                            action="append", type="choice", choices=['python', 'java'],
                            help="Force generation of thrift code for these languages.  Both "
                                 "'python' and 'java' are supported")

  def __init__(self, context):
    CodeGen.__init__(self, context)

    output_dir = (
      context.options.thrift_gen_create_outdir
      or context.config.get('thrift-gen', 'workdir')
    )
    self.combined_dir = os.path.join(output_dir, 'combined')
    self.session_dir = os.path.join(output_dir, 'sessions')

    self.strict = context.config.getbool('thrift-gen', 'strict')
    self.verbose = context.config.getbool('thrift-gen', 'verbose')

    def create_geninfo(key):
      gen_info = context.config.getdict('thrift-gen', key)
      gen = gen_info['gen']
      deps = {}
      for category, depspecs in gen_info['deps'].items():
        dependencies = OrderedSet()
        deps[category] = dependencies
        for depspec in depspecs:
          dependencies.update(context.resolve(depspec))
      return self.GenInfo(gen, deps)

    self.gen_java = create_geninfo('java')
    self.gen_python = create_geninfo('python')

    self.gen_langs = set(context.options.thrift_gen_langs)
    for lang in ('java', 'python'):
      if self.context.products.isrequired(lang):
        self.gen_langs.add(lang)

    self.thrift_binary = select_thrift_binary(context.config,
                                              version=context.options.thrift_version)

  def invalidate_for(self):
    return self.gen_langs

  def invalidate_for_files(self):
    # TODO: This will prevent artifact caching across platforms.
    # Find some cross-platform way to assert the thrift binary version.
    return [self.thrift_binary]

  def is_gentarget(self, target):
    return ((isinstance(target, JavaThriftLibrary) and target.compiler == 'thrift')
            or isinstance(target, PythonThriftLibrary))

  def is_forced(self, lang):
    return lang in self.gen_langs

  def genlangs(self):
    return dict(java=lambda t: t.is_jvm, python=lambda t: t.is_python)

  def genlang(self, lang, targets):
    bases, sources = calculate_compile_roots(targets, self.is_gentarget)

    if lang == 'java':
      gen = self.gen_java.gen
    elif lang == 'python':
      gen = self.gen_python.gen
    else:
      raise TaskError('Unrecognized thrift gen lang: %s' % lang)

    args = [
      self.thrift_binary,
      '--gen', gen,
      '-recurse',
    ]

    if self.strict:
      args.append('-strict')
    if self.verbose:
      args.append('-verbose')
    for base in bases:
      args.extend(('-I', base))

    sessions = []
    for source in sources:
      self.context.log.info('Generating thrift for %s\n' % source)
      # Create a unique session dir for this thrift root.  Sources may be full paths but we only
      # need the path relative to the build root to ensure uniqueness.
      # TODO(John Sirois): file paths should be normalized early on and uniformly, fix the need to
      # relpath here at all.
      relsource = os.path.relpath(source, get_buildroot())
      outdir = os.path.join(self.session_dir, '.'.join(relsource.split(os.path.sep)))
      safe_mkdir(outdir)

      cmd = args[:]
      cmd.extend(('-o', outdir))
      cmd.append(source)
      log.debug('Executing: %s' % ' '.join(cmd))
      sessions.append(self.ThriftSession(outdir, cmd, subprocess.Popen(cmd)))

    result = 0
    for session in sessions:
      if result != 0:
        session.process.kill()
      else:
        result = session.process.wait()
        if result != 0:
          self.context.log.error('Failed: %s' % ' '.join(session.cmd))
        else:
          _copytree(session.outdir, self.combined_dir)
    if result != 0:
      raise TaskError('%s ... exited non-zero (%i)' % (self.thrift_binary, result))

  def createtarget(self, lang, gentarget, dependees):
    if lang == 'java':
      return self._create_java_target(gentarget, dependees)
    elif lang == 'python':
      return self._create_python_target(gentarget, dependees)
    else:
      raise TaskError('Unrecognized thrift gen lang: %s' % lang)

  def _create_java_target(self, target, dependees):
    def create_target(files, deps):
       return self.context.add_new_target(os.path.join(self.combined_dir, 'gen-java'),
                                          JavaLibrary,
                                          name=target.id,
                                          sources=files,
                                          provides=target.provides,
                                          dependencies=deps,
                                          excludes=target.excludes)
    return self._inject_target(target, dependees, self.gen_java, 'java', create_target)

  def _create_python_target(self, target, dependees):
    def create_target(files, deps):
     return self.context.add_new_target(os.path.join(self.combined_dir, 'gen-py'),
                                        PythonLibrary,
                                        name=target.id,
                                        sources=files,
                                        dependencies=deps)
    return self._inject_target(target, dependees, self.gen_python, 'py', create_target)

  def _inject_target(self, target, dependees, geninfo, namespace, create_target):
    files = []
    has_service = False
    for src in target.sources_relative_to_buildroot():
      services, genfiles = calculate_gen(src)
      has_service = has_service or services
      files.extend(genfiles.get(namespace, []))
    deps = geninfo.deps['service' if has_service else 'structs']
    tgt = create_target(files, deps)
    tgt.id = target.id + '.thrift_gen'
    for dependee in dependees:
      if isinstance(dependee, InternalTarget):
        dependee.update_dependencies((tgt,))
      else:
        # TODO(John Sirois): rationalize targets with dependencies.
        # JarLibrary or PythonTarget dependee on the thrift target
        dependee.dependencies.add(tgt)
    return tgt


NAMESPACE_PARSER = re.compile(r'^\s*namespace\s+([^\s]+)\s+([^\s]+)\s*$')
TYPE_PARSER = re.compile(r'^\s*(const|enum|exception|service|struct|union)\s+([^\s{]+).*')


# TODO(John Sirois): consolidate thrift parsing to 1 pass instead of 2
def calculate_gen(source):
  """Calculates the service types and files generated for the given thrift IDL source.

  Returns a tuple of (service types, generated files).
  """

  with open(source, 'r') as thrift:
    lines = thrift.readlines()
    namespaces = {}
    types = defaultdict(set)
    for line in lines:
      match = NAMESPACE_PARSER.match(line)
      if match:
        lang = match.group(1)
        namespace = match.group(2)
        namespaces[lang] = namespace
      else:
        match = TYPE_PARSER.match(line)
        if match:
          typename = match.group(1)
          name = match.group(2)
          types[typename].add(name)

    genfiles = defaultdict(set)

    namespace = namespaces.get('py')
    if namespace:
      genfiles['py'].update(calculate_python_genfiles(namespace, types))

    namespace = namespaces.get('java')
    if namespace:
      genfiles['java'].update(calculate_java_genfiles(namespace, types))

    return types['service'], genfiles


def calculate_python_genfiles(namespace, types):
  basepath = namespace.replace('.', '/')
  def path(name):
    return os.path.join(basepath, '%s.py' % name)
  yield path('__init__')
  if 'const' in types:
    yield path('constants')
  if set(['enum', 'exception', 'struct', 'union']) & set(types.keys()):
    yield path('ttypes')
  for service in types['service']:
    yield path(service)
    yield os.path.join(basepath, '%s-remote' % service)


def calculate_java_genfiles(namespace, types):
  basepath = namespace.replace('.', '/')
  def path(name):
    return os.path.join(basepath, '%s.java' % name)
  if 'const' in types:
    yield path('Constants')
  for typename in ['enum', 'exception', 'service', 'struct', 'union']:
    for name in types[typename]:
      yield path(name)
