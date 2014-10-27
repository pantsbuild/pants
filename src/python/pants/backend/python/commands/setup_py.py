# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import ast
from collections import defaultdict
import itertools
import os
import pprint
import shutil

from pex.compatibility import string, to_bytes
from pex.installer import InstallerBase, Packager
from twitter.common.collections import OrderedSet
from twitter.common.dirutil.chroot import Chroot

from pants.backend.codegen.targets.python_antlr_library import PythonAntlrLibrary
from pants.backend.codegen.targets.python_thrift_library import PythonThriftLibrary
from pants.backend.python.antlr_builder import PythonAntlrBuilder
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.thrift_builder import PythonThriftBuilder
from pants.base.build_environment import get_buildroot
from pants.base.config import Config
from pants.base.exceptions import TargetDefinitionException
from pants.commands.command import Command
from pants.util.dirutil import safe_rmtree, safe_walk


SETUP_BOILERPLATE = """
# DO NOT EDIT THIS FILE -- AUTOGENERATED BY PANTS
# Target: %(setup_target)s

from setuptools import setup

setup(**
%(setup_dict)s
)
"""


class SetupPyRunner(InstallerBase):
  def __init__(self, source_dir, setup_command, **kw):
    self.__setup_command = setup_command.split()
    super(SetupPyRunner, self).__init__(source_dir, **kw)

  def _setup_command(self):
    return self.__setup_command


class SetupPy(Command):
  """Generate setup.py-based Python projects from python_library targets."""

  GENERATED_TARGETS = {
      PythonAntlrLibrary: PythonAntlrBuilder,
      PythonThriftLibrary: PythonThriftBuilder,
  }
  SOURCE_ROOT = b'src'
  __command__ = 'setup_py'

  @classmethod
  def _combined_dependencies(cls, target):
    dependencies = OrderedSet(target.dependencies)
    if isinstance(target, PythonTarget):
      return dependencies | OrderedSet(target.provided_binaries.values())
    else:
      return dependencies

  @classmethod
  def _construct_provider_map(cls, root_target, descendant, parents, providers, depmap):
    if isinstance(descendant, PythonTarget) and descendant.provides:
      providers.append(descendant)
    for dep in cls._combined_dependencies(descendant):
      for prv in providers:
        depmap[prv].add(dep)
        if dep in parents:
          raise TargetDefinitionException(root_target,
             '%s and %s combined have a cycle!' % (root_target, dep))
        parents.add(dep)
        cls._construct_provider_map(root_target, dep, parents, providers, depmap)
        parents.remove(dep)
    if isinstance(descendant, PythonTarget) and descendant.provides:
      assert providers[-1] == descendant
      providers.pop()

  @classmethod
  def construct_provider_map(cls, root_target):
    """Construct a mapping of provider => minimal target set within :root_target.

       The algorithm works in the following fashion:

         1. Recursively resolve every dependency starting at root_target (the thing
            that setup_py is being called against).  This includes the dependencies
            of any binaries attached to the PythonArtifact using with_binaries
         2. For every PythonTarget that provides a PythonArtifact, add an
            entry for it to depmap[], keyed on the artifact name, containing
            an OrderedSet of all transitively resolved children
            dependencies.
         3. Any concrete target with sources that is provided by another PythonArtifact
            other than the one being built with setup_py will be elided.

       Downsides:
         - Explicitly requested dependencies may be elided if transitively included by others,
           e.g.
             python_library(
               ...,
               dependencies = [
                  pants('src/python/twitter/common/dirutil'),
                  pants('src/python/twitter/common/python'),
               ]
            )
          will result in only pex being exported even if top-level sources
          directly reference twitter.common.dirutil, which could be considered a leak.
    """
    depmap = defaultdict(OrderedSet)
    cls._construct_provider_map(root_target, root_target, parents=set(), providers=[],
                                depmap=depmap)
    return depmap

  @classmethod
  def minified_dependencies(cls, root_target):
    """Minify the dependencies of a PythonTarget."""
    depmap = cls.construct_provider_map(root_target)
    root_deps = depmap.pop(root_target, OrderedSet())

    def elide(target):
      if any(target in depset for depset in depmap.values()):
        root_deps.discard(target)

    root_target.walk(elide)
    return root_deps

  @classmethod
  def iter_entry_points(cls, target):
    """Yields the name, entry_point pairs of binary targets in this PythonArtifact."""
    for name, binary_target in target.provided_binaries.items():
      concrete_target = binary_target
      if not isinstance(concrete_target, PythonBinary) or concrete_target.entry_point is None:
        raise TargetDefinitionException(target,
            'Cannot add a binary to a PythonArtifact if it does not contain an entry_point.')
      yield name, concrete_target.entry_point

  @classmethod
  def declares_namespace_package(cls, filename):
    """Given a filename, walk its ast and determine if it is declaring a namespace package.
       Intended only for __init__.py files though it will work for any .py."""
    with open(filename) as fp:
      init_py = ast.parse(fp.read(), filename)
    calls = [node for node in ast.walk(init_py) if isinstance(node, ast.Call)]
    for call in calls:
      if len(call.args) != 1:
        continue
      if isinstance(call.func, ast.Attribute) and call.func.attr != 'declare_namespace':
        continue
      if isinstance(call.func, ast.Name) and call.func.id != 'declare_namespace':
        continue
      if isinstance(call.args[0], ast.Name) and call.args[0].id == '__name__':
        return True
    return False

  @classmethod
  def iter_generated_sources(cls, target, root, config=None):
    config = config or Config.load()
    # This is sort of facepalmy -- python.new will make this much better.
    for target_type, target_builder in cls.GENERATED_TARGETS.items():
      if isinstance(target, target_type):
        builder_cls = target_builder
        break
    else:
      raise TypeError(
          'write_generated_sources could not find suitable code generator for %s' % type(target))

    builder = builder_cls(target, root, config)
    builder.generate()
    for root, _, files in safe_walk(builder.package_root):
      for fn in files:
        target_file = os.path.join(root, fn)
        yield os.path.relpath(target_file, builder.package_root), target_file

  @classmethod
  def nearest_subpackage(cls, package, all_packages):
    """Given a package, find its nearest parent in all_packages."""
    def shared_prefix(candidate):
      zipped = itertools.izip(package.split('.'), candidate.split('.'))
      matching = itertools.takewhile(lambda pair: pair[0] == pair[1], zipped)
      return [pair[0] for pair in matching]
    shared_packages = list(filter(None, map(shared_prefix, all_packages)))
    return '.'.join(max(shared_packages, key=len)) if shared_packages else package

  @classmethod
  def find_packages(cls, chroot):
    """Detect packages, namespace packages and resources from an existing chroot.

       Returns a tuple of:
         set(packages)
         set(namespace_packages)
         map(package => set(files))
    """
    base = os.path.join(chroot.path(), cls.SOURCE_ROOT)
    packages, namespace_packages = set(), set()
    resources = defaultdict(set)

    def iter_files():
      for root, _, files in safe_walk(base):
        module = os.path.relpath(root, base).replace(os.path.sep, '.')
        for filename in files:
          yield module, filename, os.path.join(root, filename)

    # establish packages, namespace packages in first pass
    for module, filename, real_filename in iter_files():
      if filename != '__init__.py':
        continue
      packages.add(module)
      if cls.declares_namespace_package(real_filename):
        namespace_packages.add(module)

    # second pass establishes non-source content (resources)
    for module, filename, real_filename in iter_files():
      if filename.endswith('.py'):
        if module not in packages:
          # TODO(wickman) Consider changing this to a full-on error as it
          # could indicate bad BUILD hygiene.
          # raise cls.UndefinedSource('%s is source but does not belong to a package!' % filename)
          print('WARNING!  %s is source but does not belong to a package!' % real_filename)
        else:
          continue
      submodule = cls.nearest_subpackage(module, packages)
      if submodule == module:
        resources[submodule].add(filename)
      else:
        assert module.startswith(submodule + '.')
        relative_module = module[len(submodule) + 1:]
        relative_filename = os.path.join(relative_module.replace('.', os.path.sep), filename)
        resources[submodule].add(relative_filename)

    return packages, namespace_packages, resources

  @classmethod
  def install_requires(cls, root_target):
    install_requires = set()
    for dep in cls.minified_dependencies(root_target):
      if isinstance(dep, PythonRequirementLibrary):
        for req in dep.payload.requirements:
          install_requires.add(str(req.requirement))
      elif isinstance(dep, PythonTarget) and dep.provides:
        install_requires.add(dep.provides.key)
    return install_requires

  def setup_parser(self, parser, args):
    parser.set_usage("\n"
                     "  %prog setup_py (options) [spec]\n")
    parser.add_option("--run", dest="run", default=None,
                      help="The command to run against setup.py.  Don't forget to quote "
                           "any additional parameters.  If no run command is specified, "
                           "pants will by default generate and dump the source distribution.")
    parser.add_option("--recursive", dest="recursive", default=False, action="store_true",
                      help="Transitively run setup_py on all provided downstream targets.")

  def __init__(self, *args, **kwargs):
    super(SetupPy, self).__init__(*args, **kwargs)

    if not self.args:
      self.error("A spec argument is required")

    self._config = Config.load()
    self._root = self.root_dir

    self.build_graph.inject_spec_closure(self.args[0])
    self.target = self.build_graph.get_target_from_spec(self.args[0])

    if self.target is None:
      self.error('%s is not a valid target!' % self.args[0])

    if not self.target.provides:
      self.error('Target must provide an artifact.')

  def write_contents(self, root_target, chroot):
    """Write contents of the target."""
    def write_target_source(target, src):
      chroot.link(os.path.join(target.target_base, src), os.path.join(self.SOURCE_ROOT, src))
      # check parent __init__.pys to see if they also need to be linked.  this is to allow
      # us to determine if they belong to regular packages or namespace packages.
      while True:
        src = os.path.dirname(src)
        if not src:
          # Do not allow the repository root to leak (i.e. '.' should not be a package in setup.py)
          break
        if os.path.exists(os.path.join(target.target_base, src, '__init__.py')):
          chroot.link(os.path.join(target.target_base, src, '__init__.py'),
                      os.path.join(self.SOURCE_ROOT, src, '__init__.py'))

    def write_codegen_source(relpath, abspath):
      chroot.link(abspath, os.path.join(self.SOURCE_ROOT, relpath))

    def write_target(target):
      if isinstance(target, tuple(self.GENERATED_TARGETS.keys())):
        for relpath, abspath in self.iter_generated_sources(target, self._root, self._config):
          write_codegen_source(relpath, abspath)
      else:
        sources_and_resources = (list(target.payload.sources.relative_to_buildroot()) +
                                 list(target.payload.resources.relative_to_buildroot()))
        for rel_source in sources_and_resources:
          abs_source_path = os.path.join(get_buildroot(), rel_source)
          abs_source_root_path = os.path.join(get_buildroot(), target.target_base)
          source_root_relative_path = os.path.relpath(abs_source_path, abs_source_root_path)
          write_target_source(target, source_root_relative_path)

    write_target(root_target)
    for dependency in self.minified_dependencies(root_target):
      if isinstance(dependency, PythonTarget) and not dependency.provides:
        write_target(dependency)

  def write_setup(self, root_target, chroot):
    """Write the setup.py of a target.  Must be run after writing the contents to the chroot."""

    # NB: several explicit str conversions below force non-unicode strings in order to comply
    # with setuptools expectations.

    setup_keywords = root_target.provides.setup_py_keywords

    package_dir = {b'': self.SOURCE_ROOT}
    packages, namespace_packages, resources = self.find_packages(chroot)

    if namespace_packages:
      setup_keywords['namespace_packages'] = list(sorted(namespace_packages))

    if packages:
      setup_keywords.update(
          package_dir=package_dir,
          packages=list(sorted(packages)),
          package_data=dict((str(package), list(map(str, rs)))
                            for (package, rs) in resources.items()))

    setup_keywords['install_requires'] = sorted(list(self.install_requires(root_target)))

    for binary_name, entry_point in self.iter_entry_points(root_target):
      if 'entry_points' not in setup_keywords:
        setup_keywords['entry_points'] = {}
      if 'console_scripts' not in setup_keywords['entry_points']:
        setup_keywords['entry_points']['console_scripts'] = []
      setup_keywords['entry_points']['console_scripts'].append(
          '%s = %s' % (binary_name, entry_point))

    # From http://stackoverflow.com/a/13105359
    def convert(input):
      if isinstance(input, dict):
        out = dict()
        for key, value in input.items():
          out[convert(key)] = convert(value)
        return out
      elif isinstance(input, list):
        return [convert(element) for element in input]
      elif isinstance(input, string):
        return to_bytes(input)
      else:
        return input

    # Distutils does not support unicode strings in setup.py, so we must
    # explicitly convert to binary strings as pants uses unicode_literals.
    # Ideally we would write the output stream with an encoding, however,
    # pprint.pformat embeds u's in the string itself during conversion.
    # For that reason we convert each unicode string independently.
    #
    # hoth:~ travis$ python
    # Python 2.6.8 (unknown, Aug 25 2013, 00:04:29)
    # [GCC 4.2.1 Compatible Apple LLVM 5.0 (clang-500.0.68)] on darwin
    # Type "help", "copyright", "credits" or "license" for more information.
    # >>> import pprint
    # >>> data = {u'entry_points': {u'console_scripts': [u'pants = pants.bin.pants_exe:main']}}
    # >>> pprint.pformat(data, indent=4)
    # "{   u'entry_points': {   u'console_scripts': [   u'pants = pants.bin.pants_exe:main']}}"
    # >>>
    #
    # For more information, see http://bugs.python.org/issue13943
    chroot.write(SETUP_BOILERPLATE % {
      'setup_dict': pprint.pformat(convert(setup_keywords), indent=4),
      'setup_target': repr(root_target)
    }, 'setup.py')

    # make sure that setup.py is included
    chroot.write('include *.py'.encode('utf8'), 'MANIFEST.in')

  def run_one(self, target):
    dist_dir = self._config.getdefault('pants_distdir')
    chroot = Chroot(dist_dir, name=target.provides.name)
    self.write_contents(target, chroot)
    self.write_setup(target, chroot)
    target_base = '%s-%s' % (target.provides.name, target.provides.version)
    setup_dir = os.path.join(dist_dir, target_base)
    safe_rmtree(setup_dir)
    shutil.move(chroot.path(), setup_dir)

    if not self.old_options.run:
      print('Running packager against %s' % setup_dir)
      setup_runner = Packager(setup_dir)
      tgz_name = os.path.basename(setup_runner.sdist())
      print('Writing %s' % os.path.join(dist_dir, tgz_name))
      shutil.move(setup_runner.sdist(), os.path.join(dist_dir, tgz_name))
      safe_rmtree(setup_dir)
    else:
      print('Running %s against %s' % (self.old_options.run, setup_dir))
      setup_runner = SetupPyRunner(setup_dir, self.old_options.run)
      setup_runner.run()

  def execute(self):
    if self.old_options.recursive:
      setup_targets = OrderedSet()
      def add_providing_target(target):
        if isinstance(target, PythonTarget) and target.provides:
          setup_targets.add(target)
          return OrderedSet(target.provided_binaries.values())
      self.target.walk(add_providing_target)
    else:
      setup_targets = [self.target]

    for target in setup_targets:
      if isinstance(target, PythonTarget) and target.provides:
        self.run_one(target)
