# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast
import itertools
import os
import pprint
import shutil
from abc import abstractmethod
from builtins import map, object, str, zip
from collections import OrderedDict, defaultdict

from pex.compatibility import string, to_bytes
from pex.installer import InstallerBase, Packager
from pex.interpreter import PythonInterpreter
from twitter.common.collections import OrderedSet
from twitter.common.dirutil.chroot import Chroot
from wheel.install import WheelFile

from pants.backend.native.config.environment import CCompiler, CppCompiler, Linker, Platform
from pants.backend.python.pex_util import get_local_platform
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.tasks.pex_build_util import is_local_python_dist, resolve_multi
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.base.specs import SiblingAddresses
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_graph import sort_targets
from pants.build_graph.resources import Resources
from pants.engine.rules import rule
from pants.engine.selectors import Select
from pants.task.task import Task
from pants.util.dirutil import safe_rmtree, safe_walk
from pants.util.memo import memoized_property
from pants.util.meta import AbstractClass
from pants.util.objects import datatype
from pants.util.strutil import create_path_env_var, safe_shlex_join, safe_shlex_split


SETUP_BOILERPLATE = """
# DO NOT EDIT THIS FILE -- AUTOGENERATED BY PANTS
# Target: {setup_target}

from setuptools import setup

setup(**
{setup_dict}
)
"""


class SetupPyRunner(InstallerBase):
  _EXTRAS = ('setuptools', 'wheel')

  DIST_DIR = 'dist'

  @classmethod
  def for_bdist_wheel(cls, source_dir, is_platform_specific, **kw):
    cmd = ['bdist_wheel']
    if is_platform_specific:
      cmd.extend(['--plat-name', get_local_platform()])
    else:
      cmd.append('--universal')
    cmd.extend(['--dist-dir', cls.DIST_DIR])
    return cls(source_dir, cmd, **kw)

  def __init__(self, source_dir, setup_command, **kw):
    self.__setup_command = setup_command
    super(SetupPyRunner, self).__init__(source_dir, **kw)

  def mixins(self):
    mixins = super(SetupPyRunner, self).mixins().copy()
    extras = set(self._EXTRAS)
    for (key, version) in self._interpreter.extras:
      if key in extras:
        mixins[key] = '{}=={}'.format(key, version)
        extras.remove(key)
        if not extras:
          break
    else:
      # We know Pants sets up python interpreters with setuptools and wheel via the `PythonSetup`
      # subsystem; so this should never happen
      raise AssertionError("Expected interpreter {} to have the extras {}"
                           .format(self._interpreter, self._EXTRAS))
    return mixins

  def _setup_command(self):
    return self.__setup_command


class SetupPyNativeTools(datatype([
    ('c_compiler', CCompiler),
    ('cpp_compiler', CppCompiler),
    ('linker', Linker),
    ('platform', Platform),
])):
  """The native tools needed for a setup.py invocation.

  This class exists because `SetupPyExecutionEnvironment` is created manually, one per target.
  """


@rule(SetupPyNativeTools, [Select(CCompiler), Select(CppCompiler), Select(Linker), Select(Platform)])
def get_setup_py_native_tools(c_compiler, cpp_compiler, linker, platform):
  yield SetupPyNativeTools(
    c_compiler=c_compiler,
    cpp_compiler=cpp_compiler,
    linker=linker,
    platform=platform)


class SetupRequiresSiteDir(datatype(['site_dir'])): pass


# TODO: This could be formulated as an @rule if targets and `PythonInterpreter` are made available
# to the v2 engine.
def ensure_setup_requires_site_dir(reqs_to_resolve, interpreter, site_dir,
                                   platforms=None):
  if not reqs_to_resolve:
    return None

  setup_requires_dists = resolve_multi(interpreter, reqs_to_resolve, platforms, None)

  # FIXME: there's no description of what this does or why it's necessary.
  overrides = {
    'purelib': site_dir,
    'headers': os.path.join(site_dir, 'headers'),
    'scripts': os.path.join(site_dir, 'bin'),
    'platlib': site_dir,
    'data': site_dir
  }

  # The `python_dist` target builds for the current platform only.
  # FIXME: why does it build for the current platform only?
  for obj in setup_requires_dists['current']:
    wf = WheelFile(obj.location)
    wf.install(overrides=overrides, force=True)

  return SetupRequiresSiteDir(site_dir)


class SetupPyExecutionEnvironment(datatype([
    # TODO: It might be pretty useful to have an Optional TypeConstraint.
    'setup_requires_site_dir',
    # If None, don't execute in the toolchain environment.
    'setup_py_native_tools',
])):

  _SHARED_CMDLINE_ARGS = {
    'darwin': lambda: [
      '-mmacosx-version-min=10.11',
      '-Wl,-dylib',
      '-undefined',
      'dynamic_lookup',
    ],
    'linux': lambda: ['-shared'],
  }

  def as_environment(self):
    ret = {}

    if self.setup_requires_site_dir:
      ret['PYTHONPATH'] = self.setup_requires_site_dir.site_dir

    # FIXME(#5951): the below is a lot of error-prone repeated logic -- we need a way to compose
    # executables more hygienically. We should probably be composing each datatype's members, and
    # only creating an environment at the very end.
    native_tools = self.setup_py_native_tools
    if native_tools:
      # TODO: an as_tuple() method for datatypes would make this destructuring cleaner!
      plat = native_tools.platform
      cc = native_tools.c_compiler
      cxx = native_tools.cpp_compiler
      linker = native_tools.linker

      all_path_entries = cc.path_entries + cxx.path_entries + linker.path_entries
      ret['PATH'] = create_path_env_var(all_path_entries)

      all_library_dirs = cc.library_dirs + cxx.library_dirs + linker.library_dirs
      if all_library_dirs:
        joined_library_dirs = create_path_env_var(all_library_dirs)
        ret['LIBRARY_PATH'] = joined_library_dirs
        dynamic_lib_env_var = plat.resolve_platform_specific({
          'darwin': lambda: 'DYLD_LIBRARY_PATH',
          'linux': lambda: 'LD_LIBRARY_PATH',
        })
        ret[dynamic_lib_env_var] = joined_library_dirs

      all_include_dirs = cc.include_dirs + cxx.include_dirs
      if all_include_dirs:
        ret['CPATH'] = create_path_env_var(all_include_dirs)

      all_cflags_for_platform = plat.resolve_platform_specific({
        'darwin': lambda: ['-mmacosx-version-min=10.11'],
        'linux': lambda: [],
      })
      if all_cflags_for_platform:
        ret['CFLAGS'] = safe_shlex_join(all_cflags_for_platform)

      ret['CC'] = cc.exe_filename
      ret['CXX'] = cxx.exe_filename
      ret['LDSHARED'] = linker.exe_filename

      all_new_ldflags = plat.resolve_platform_specific(self._SHARED_CMDLINE_ARGS)
      ret['LDFLAGS'] = safe_shlex_join(all_new_ldflags)

    return ret


class TargetAncestorIterator(object):
  """Supports iteration of target ancestor lineages."""

  def __init__(self, build_graph):
    self._build_graph = build_graph

  def iter_target_siblings_and_ancestors(self, target):
    """Produces an iterator over a target's siblings and ancestor lineage.

    :returns: A target iterator yielding the target and its siblings and then it ancestors from
              nearest to furthest removed.
    """
    def iter_targets_in_spec_path(spec_path):
      try:
        siblings = SiblingAddresses(spec_path)
        for address in self._build_graph.inject_specs_closure([siblings]):
          yield self._build_graph.get_target(address)
      except AddressLookupError:
        # A spec path may not have any addresses registered under it and that's ok.
        # For example:
        #  a:a
        #  a/b/c:c
        #
        # Here a/b contains no addresses.
        pass

    def iter_siblings_and_ancestors(spec_path):
      for sibling in iter_targets_in_spec_path(spec_path):
        yield sibling
      parent_spec_path = os.path.dirname(spec_path)
      if parent_spec_path != spec_path:
        for parent in iter_siblings_and_ancestors(parent_spec_path):
          yield parent

    for target in iter_siblings_and_ancestors(target.address.spec_path):
      yield target


# TODO(John Sirois): Get jvm and python publishing on the same page.
# Either python should require all nodes in an exported target closure be either exported or
# 3rdparty or else jvm publishing should use an ExportedTargetDependencyCalculator to aggregate
# un-exported non-3rdparty interior nodes as needed.  It seems like the latter is preferable since
# it can be used with a BUILD graph validator requiring completely exported subgraphs to enforce the
# former as a matter of local repo policy.
class ExportedTargetDependencyCalculator(AbstractClass):
  """Calculates the dependencies of exported targets.

  When a target is exported many of its internal transitive library dependencies may be satisfied by
  other internal targets that are also exported and "own" these internal transitive library deps.
  In other words, exported targets generally can have reduced dependency sets and an
  `ExportedTargetDependencyCalculator` can calculate these reduced dependency sets.

  To use an `ExportedTargetDependencyCalculator` a subclass must be created that implements two
  predicates and a walk function for the class of targets in question.  For example, a
  `JvmDependencyCalculator` would need to be able to identify jvm third party dependency targets,
  and local exportable jvm library targets.  In addition it would need to define a walk function
  that knew how to walk a jvm target's dependencies.
  """

  class UnExportedError(TaskError):
    """Indicates a target is not exported."""

  class NoOwnerError(TaskError):
    """Indicates an exportable target has no owning exported target."""

  class AmbiguousOwnerError(TaskError):
    """Indicates an exportable target has more than one owning exported target."""

  def __init__(self, build_graph):
    self._ancestor_iterator = TargetAncestorIterator(build_graph)

  @abstractmethod
  def requires_export(self, target):
    """Identifies targets that need to be exported (are internal targets owning source code).

    :param target: The target to identify.
    :returns: `True` if the given `target` owns files that should be included in exported packages
              when the target is a member of an exported target's dependency graph.
    """

  @abstractmethod
  def is_exported(self, target):
    """Identifies targets of interest that are exported from this project.

    :param target: The target to identify.
    :returns: `True` if the given `target` represents a top-level target exported from this project.
    """

  @abstractmethod
  def dependencies(self, target):
    """Returns an iterator over the dependencies of the given target.

    :param target: The target to iterate dependencies of.
    :returns: An iterator over all of the target's dependencies.
    """

  def _walk(self, target, visitor):
    """Walks the dependency graph for the given target.

    :param target: The target to start the walk from.
    :param visitor: A function that takes a target and returns `True` if its dependencies should
                    also be visited.
    """
    visited = set()

    def walk(current):
      if current not in visited:
        visited.add(current)
        keep_going = visitor(current)
        if keep_going:
          for dependency in self.dependencies(current):
            walk(dependency)

    walk(target)

  def _closure(self, target):
    """Return the target closure as defined by this dependency calculator's definition of a walk."""
    closure = set()

    def collect(current):
      closure.add(current)
      return True
    self._walk(target, collect)

    return closure

  def reduced_dependencies(self, exported_target):
    """Calculates the reduced transitive dependencies for an exported target.

    The reduced set of dependencies will be just those transitive dependencies "owned" by
    the `exported_target`.

    A target is considered "owned" if:
    1. It's "3rdparty" and "directly reachable" from `exported_target` by at least 1 path.
    2. It's not "3rdparty" and not "directly reachable" by any of `exported_target`'s "3rdparty"
       dependencies.

    Here "3rdparty" refers to targets identified as either `is_third_party` or `is_exported`.

    And in this context "directly reachable" means the target can be reached by following a series
    of dependency links from the `exported_target`, never crossing another exported target and
    staying within the `exported_target` address space.  It's the latter restriction that allows for
    unambiguous ownership of exportable targets and mirrors the BUILD file convention of targets
    only being able to own sources in their filesystem subtree.  The single ambiguous case that can
    arise is when there is more than one exported target in the same BUILD file family that can
    "directly reach" a target in its address space.

    :raises: `UnExportedError` if the given `exported_target` is not, in-fact, exported.
    :raises: `NoOwnerError` if a transitive dependency is found with no proper owning exported
             target.
    :raises: `AmbiguousOwnerError` if there is more than one viable exported owner target for a
             given transitive dependency.
    """
    # The strategy adopted requires 3 passes:
    # 1.) Walk the exported target to collect provisional owned exportable targets, but _not_
    #     3rdparty since these may be introduced by exported subgraphs we discover in later steps!
    # 2.) Determine the owner of each target collected in 1 by walking the ancestor chain to find
    #     the closest exported target.  The ancestor chain is just all targets whose spec path is
    #     a prefix of the descendant.  In other words, all targets in descendant's BUILD file family
    #     (its siblings), all targets in its parent directory BUILD file family, and so on.
    # 3.) Finally walk the exported target once more, replacing each visited dependency with its
    #     owner.

    if not self.is_exported(exported_target):
      raise self.UnExportedError('Cannot calculate reduced dependencies for a non-exported '
                                 'target, given: {}'.format(exported_target))

    owner_by_owned_python_target = OrderedDict()

    # Only check ownership on the original target graph.
    original_exported_target = exported_target.derived_from

    def collect_potentially_owned_python_targets(current):
      if current.is_original:
        owner_by_owned_python_target[current] = None  # We can't know the owner in the 1st pass.
      return (current == exported_target) or not self.is_exported(current)

    self._walk(original_exported_target, collect_potentially_owned_python_targets)

    for owned in owner_by_owned_python_target:
      if self.requires_export(owned) and not self.is_exported(owned):
        potential_owners = set()
        for potential_owner in self._ancestor_iterator.iter_target_siblings_and_ancestors(owned):
          if self.is_exported(potential_owner) and owned in self._closure(potential_owner):
            potential_owners.add(potential_owner)
        if not potential_owners:
          raise self.NoOwnerError('No exported target owner found for {}'.format(owned))
        owner = potential_owners.pop()
        if potential_owners:
          ambiguous_owners = [o for o in potential_owners
                              if o.address.spec_path == owner.address.spec_path]
          if ambiguous_owners:
            raise self.AmbiguousOwnerError('Owners for {} are ambiguous.  Found {} and '
                                           '{} others: {}'.format(owned,
                                                                  owner,
                                                                  len(ambiguous_owners),
                                                                  ambiguous_owners))
        owner_by_owned_python_target[owned] = owner

    reduced_dependencies = OrderedSet()

    def collect_reduced_dependencies(current):
      if current == exported_target:
        return True
      else:
        # The provider will be one of:
        # 1. `None`, ie: a 3rdparty requirement we should collect.
        # 2. `exported_target`, ie: a local exportable target owned by `exported_target` that we
        #    should collect
        # 3. Or else a local exportable target owned by some other exported target in which case
        #    we should collect the exported owner.
        owner = owner_by_owned_python_target.get(current)
        if owner is None or owner == exported_target:
          reduced_dependencies.add(current)
        else:
          reduced_dependencies.add(owner)
        return owner == exported_target or not self.requires_export(current)

    self._walk(exported_target, collect_reduced_dependencies)
    return OrderedSet(d for d in reduced_dependencies if d.is_original)


class SetupPy(Task):
  """Generate setup.py-based Python projects."""

  SOURCE_ROOT = b'src'

  PYTHON_DISTS_PRODUCT = 'python_dists'

  @staticmethod
  def is_requirements(target):
    return isinstance(target, PythonRequirementLibrary)

  @staticmethod
  def is_python_target(target):
    return isinstance(target, PythonTarget)

  @staticmethod
  def is_resources_target(target):
    return isinstance(target, Resources)

  @classmethod
  def has_provides(cls, target):
    return cls.is_python_target(target) and target.provides is not None

  @classmethod
  def product_types(cls):
    return [cls.PYTHON_DISTS_PRODUCT]

  class DependencyCalculator(ExportedTargetDependencyCalculator):
    """Calculates reduced dependencies for exported python targets."""

    def requires_export(self, target):
      # TODO(John Sirois): Consider switching to the more general target.has_sources() once Benjy's
      # change supporting default globs is in (that change will smooth test migration).
      return SetupPy.is_python_target(target) or SetupPy.is_resources_target(target)

    def is_exported(self, target):
      return SetupPy.has_provides(target)

    def dependencies(self, target):
      for dependency in target.dependencies:
        yield dependency
      if self.is_exported(target):
        for binary in target.provided_binaries.values():
          yield binary

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data(PythonInterpreter)

  @classmethod
  def register_options(cls, register):
    super(SetupPy, cls).register_options(register)
    register('--run',
             help="The command to run against setup.py.  Don't forget to quote any additional "
                  "parameters.  If no run command is specified, pants will by default generate "
                  "and dump the source distribution.")
    register('--recursive', type=bool,
             help='Transitively run setup_py on all provided downstream targets.')

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

    Intended only for __init__.py files though it will work for any .py.
    """
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
  def nearest_subpackage(cls, package, all_packages):
    """Given a package, find its nearest parent in all_packages."""
    def shared_prefix(candidate):
      zipped = zip(package.split('.'), candidate.split('.'))
      matching = itertools.takewhile(lambda pair: pair[0] == pair[1], zipped)
      return [pair[0] for pair in matching]
    shared_packages = [_f for _f in map(shared_prefix, all_packages) if _f]
    return '.'.join(max(shared_packages, key=len)) if shared_packages else package

  @classmethod
  def find_packages(cls, chroot, log=None):
    """Detect packages, namespace packages and resources from an existing chroot.

    :returns: a tuple of:
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
          # TODO(wickman) Consider changing this to a full-on error as it could indicate bad BUILD
          # hygiene.
          # raise cls.UndefinedSource('{} is source but does not belong to a package!'
          #                           .format(filename))
          if log:
            log.warn('{} is source but does not belong to a package.'.format(real_filename))
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
  def install_requires(cls, reduced_dependencies):
    install_requires = OrderedSet()
    for dep in reduced_dependencies:
      if cls.is_requirements(dep):
        for req in dep.payload.requirements:
          install_requires.add(str(req.requirement))
      elif cls.has_provides(dep):
        install_requires.add(dep.provides.key)
    return install_requires

  def __init__(self, *args, **kwargs):
    super(SetupPy, self).__init__(*args, **kwargs)
    self._root = get_buildroot()
    self._run = self.get_options().run
    self._recursive = self.get_options().recursive

  @memoized_property
  def derived_by_original(self):
    derived = self.context.targets(predicate=lambda t: not t.is_original)
    return {t.derived_from: t for t in derived}

  def write_contents(self, root_target, reduced_dependencies, chroot):
    """Write contents of the target."""
    def write_target_source(target, src):
      chroot.copy(os.path.join(get_buildroot(), target.target_base, src),
                  os.path.join(self.SOURCE_ROOT, src))
      # check parent __init__.pys to see if they also need to be copied.  this is to allow
      # us to determine if they belong to regular packages or namespace packages.
      while True:
        src = os.path.dirname(src)
        if not src:
          # Do not allow the repository root to leak (i.e. '.' should not be a package in setup.py)
          break
        if os.path.exists(os.path.join(target.target_base, src, '__init__.py')):
          chroot.copy(os.path.join(target.target_base, src, '__init__.py'),
                      os.path.join(self.SOURCE_ROOT, src, '__init__.py'))

    def write_target(target):
      # We want to operate on the final sources target owns, so we potentially replace it with
      # the target derived from it (by a codegen task).
      subject = self.derived_by_original.get(target, target)
      for rel_source in subject.sources_relative_to_buildroot():
        abs_source_path = os.path.join(get_buildroot(), rel_source)
        abs_source_root_path = os.path.join(get_buildroot(), subject.target_base)
        source_root_relative_path = os.path.relpath(abs_source_path, abs_source_root_path)
        write_target_source(subject, source_root_relative_path)

    write_target(root_target)
    for dependency in reduced_dependencies:
      if self.is_python_target(dependency) and not dependency.provides:
        write_target(dependency)
      elif self.is_resources_target(dependency):
        write_target(dependency)

  def _setup_boilerplate(self):
    return SETUP_BOILERPLATE

  def write_setup(self, root_target, reduced_dependencies, chroot):
    """Write the setup.py of a target.

    Must be run after writing the contents to the chroot.
    """
    # NB: several explicit str conversions below force non-unicode strings in order to comply
    # with setuptools expectations.

    setup_keywords = root_target.provides.setup_py_keywords.copy()

    package_dir = {b'': self.SOURCE_ROOT}
    packages, namespace_packages, resources = self.find_packages(chroot, self.context.log)

    if namespace_packages:
      setup_keywords['namespace_packages'] = list(sorted(namespace_packages))

    if packages:
      setup_keywords.update(
          package_dir=package_dir,
          packages=list(sorted(packages)),
          package_data=dict((str(package), list(map(str, rs)))
                            for (package, rs) in resources.items()))

    setup_keywords['install_requires'] = list(self.install_requires(reduced_dependencies))

    for binary_name, entry_point in self.iter_entry_points(root_target):
      if 'entry_points' not in setup_keywords:
        setup_keywords['entry_points'] = {}
      if 'console_scripts' not in setup_keywords['entry_points']:
        setup_keywords['entry_points']['console_scripts'] = []
      setup_keywords['entry_points']['console_scripts'].append(
          '{} = {}'.format(binary_name, entry_point))

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
    # jsirois@gill ~ $ python2
    # Python 2.7.13 (default, Jul 21 2017, 03:24:34)
    # [GCC 7.1.1 20170630] on linux2
    # Type "help", "copyright", "credits" or "license" for more information.
    # >>> import pprint
    # >>> data = {u'entry_points': {u'console_scripts': [u'pants = pants.bin.pants_exe:main']}}
    # >>> pprint.pformat(data, indent=4)
    # "{   u'entry_points': {   u'console_scripts': [   u'pants = pants.bin.pants_exe:main']}}"
    # >>>
    #
    # For more information, see http://bugs.python.org/issue13943
    chroot.write(self._setup_boilerplate().format(
      setup_dict=pprint.pformat(convert(setup_keywords), indent=4),
      setup_target=repr(root_target)
    ), 'setup.py')

    # make sure that setup.py is included
    chroot.write('include *.py'.encode('utf8'), 'MANIFEST.in')

  def create_setup_py(self, target, dist_dir):
    chroot = Chroot(dist_dir, name=target.provides.name)
    dependency_calculator = self.DependencyCalculator(self.context.build_graph)
    reduced_deps = dependency_calculator.reduced_dependencies(target)
    self.write_contents(target, reduced_deps, chroot)
    self.write_setup(target, reduced_deps, chroot)
    target_base = '{}-{}'.format(target.provides.name, target.provides.version)
    setup_dir = os.path.join(dist_dir, target_base)
    safe_rmtree(setup_dir)
    shutil.move(chroot.path(), setup_dir)
    return setup_dir, reduced_deps

  def execute(self):
    # We drive creation of setup.py distributions from the original target graph, grabbing codegen'd
    # sources when needed. We ignore PythonDistribution targets.
    def is_exported_python_target(t):
      return t.is_original and self.has_provides(t) and not is_local_python_dist(t)

    exported_python_targets = OrderedSet(t for t in self.context.target_roots
                                         if is_exported_python_target(t))
    if not exported_python_targets:
      raise TaskError('setup-py target(s) must provide an artifact.')

    dist_dir = self.get_options().pants_distdir

    # NB: We have to create and then run in 2 steps so that we can discover all exported targets
    # in-play in the creation phase which then allows a tsort of these exported targets in the run
    # phase to ensure an exported target is, for example (--run="sdist upload"), uploaded before any
    # exported target that depends on it is uploaded.

    created = {}

    def create(exported_python_target):
      if exported_python_target not in created:
        self.context.log.info('Creating setup.py project for {}'.format(exported_python_target))
        subject = self.derived_by_original.get(exported_python_target, exported_python_target)
        setup_dir, dependencies = self.create_setup_py(subject, dist_dir)
        created[exported_python_target] = setup_dir
        if self._recursive:
          for dep in dependencies:
            if is_exported_python_target(dep):
              create(dep)

    for exported_python_target in exported_python_targets:
      create(exported_python_target)

    interpreter = self.context.products.get_data(PythonInterpreter)
    python_dists = self.context.products.register_data(self.PYTHON_DISTS_PRODUCT, {})
    for exported_python_target in reversed(sort_targets(list(created.keys()))):
      setup_dir = created.get(exported_python_target)
      if setup_dir:
        if not self._run:
          self.context.log.info('Running packager against {}'.format(setup_dir))
          setup_runner = Packager(setup_dir, interpreter=interpreter)
          tgz_name = os.path.basename(setup_runner.sdist())
          sdist_path = os.path.join(dist_dir, tgz_name)
          self.context.log.info('Writing {}'.format(sdist_path))
          shutil.move(setup_runner.sdist(), sdist_path)
          safe_rmtree(setup_dir)
          python_dists[exported_python_target] = sdist_path
        else:
          self.context.log.info('Running {} against {}'.format(self._run, setup_dir))
          split_command = safe_shlex_split(self._run)
          setup_runner = SetupPyRunner(setup_dir, split_command, interpreter=interpreter)
          setup_runner.run()
          python_dists[exported_python_target] = setup_dir


def create_setup_py_rules():
  return [
    get_setup_py_native_tools,
  ]
