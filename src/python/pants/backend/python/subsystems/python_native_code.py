# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from builtins import str
from collections import defaultdict

from pex.pex import PEX

from pants.backend.native.config.environment import CppToolchain, CToolchain, Platform
from pants.backend.native.subsystems.native_toolchain import NativeToolchain
from pants.backend.native.subsystems.xcode_cli_tools import MIN_OSX_VERSION_ARG
from pants.backend.native.targets.native_library import NativeLibrary
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.base.exceptions import IncompatiblePlatformsError
from pants.binaries.executable_pex_tool import ExecutablePexTool
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property
from pants.util.objects import SubclassesOf, datatype
from pants.util.strutil import create_path_env_var


class PythonNativeCode(Subsystem):
  """A subsystem which exposes components of the native backend to the python backend."""

  options_scope = 'python-native-code'

  default_native_source_extensions = ['.c', '.cpp', '.cc']

  class PythonNativeCodeError(Exception): pass

  @classmethod
  def register_options(cls, register):
    super(PythonNativeCode, cls).register_options(register)

    register('--native-source-extensions', type=list, default=cls.default_native_source_extensions,
             fingerprint=True, advanced=True,
             help='The extensions recognized for native source files in `python_dist()` sources.')

  @classmethod
  def subsystem_dependencies(cls):
    return super(PythonNativeCode, cls).subsystem_dependencies() + (
      NativeToolchain.scoped(cls),
      # We generally have to use PythonSetup's global instance, as methods such as
      # `dump_requirements` will use it directly.
      # TODO: when subsystems are more easily requestable from the v2 engine, this restriction could
      # be removed!
      PythonSetup,
    )

  @memoized_property
  def _native_source_extensions(self):
    return self.get_options().native_source_extensions

  @memoized_property
  def native_toolchain(self):
    return NativeToolchain.scoped_instance(self)

  @memoized_property
  def _python_setup(self):
    return PythonSetup.global_instance()

  def pydist_has_native_sources(self, target):
    return target.has_sources(extension=tuple(self._native_source_extensions))

  def native_target_has_native_sources(self, target):
    return target.has_sources()

  @memoized_property
  def _native_target_matchers(self):
    return {
      SubclassesOf(PythonDistribution): self.pydist_has_native_sources,
      SubclassesOf(NativeLibrary): self.native_target_has_native_sources,
    }

  def _any_targets_have_native_sources(self, targets):
    # TODO(#5949): convert this to checking if the closure of python requirements has any
    # platform-specific packages (maybe find the platforms there too?).
    for tgt in targets:
      for type_constraint, target_predicate in self._native_target_matchers.items():
        if type_constraint.satisfied_by(tgt) and target_predicate(tgt):
          return True
    return False

  def get_targets_by_declared_platform(self, targets):
    """
    Aggregates a dict that maps a platform string to a list of targets that specify the platform.
    If no targets have platforms arguments, return a dict containing platforms inherited from
    the PythonSetup object.

    :param tgts: a list of :class:`Target` objects.
    :returns: a dict mapping a platform string to a list of targets that specify the platform.
    """
    targets_by_platforms = defaultdict(list)

    for tgt in targets:
      for platform in tgt.platforms:
        targets_by_platforms[platform].append(tgt)

    if not targets_by_platforms:
      for platform in self._python_setup.platforms:
        targets_by_platforms[platform] = ['(No target) Platform inherited from either the '
                                          '--platforms option or a pants.ini file.']
    return targets_by_platforms

  _PYTHON_PLATFORM_TARGETS_CONSTRAINT = SubclassesOf(PythonBinary, PythonDistribution)

  def check_build_for_current_platform_only(self, targets):
    """
    Performs a check of whether the current target closure has native sources and if so, ensures
    that Pants is only targeting the current platform.

    :param tgts: a list of :class:`Target` objects.
    :return: a boolean value indicating whether the current target closure has native sources.
    :raises: :class:`pants.base.exceptions.IncompatiblePlatformsError`
    """
    if not self._any_targets_have_native_sources(targets):
      return False

    targets_with_platforms = [target for target in targets
                              if self._PYTHON_PLATFORM_TARGETS_CONSTRAINT.satisfied_by(target)]
    platforms_with_sources = self.get_targets_by_declared_platform(targets_with_platforms)
    platform_names = list(platforms_with_sources.keys())

    if len(platform_names) < 1:
      raise self.PythonNativeCodeError(
        "Error: there should be at least one platform in the target closure, because "
        "we checked that there are native sources.")

    if platform_names == ['current']:
      return True

    raise IncompatiblePlatformsError(
      'The target set contains one or more targets that depend on '
      'native code. Please ensure that the platform arguments in all relevant targets and build '
      'options are compatible with the current platform. Found targets for platforms: {}'
      .format(str(platforms_with_sources)))


class BuildSetupRequiresPex(ExecutablePexTool):
  options_scope = 'build-setup-requires-pex'

  @property
  def base_requirements(self):
    # TODO: would we ever want to configure these requirement versions separately from the global
    # PythonSetup values?
    return [
      PythonRequirement('setuptools=={}'.format(self.python_setup.setuptools_version)),
      PythonRequirement('wheel=={}'.format(self.python_setup.wheel_version)),
    ]


class SetupPyNativeTools(datatype([
    ('c_toolchain', CToolchain),
    ('cpp_toolchain', CppToolchain),
    ('platform', Platform),
])):
  """The native tools needed for a setup.py invocation.

  This class exists because `SetupPyExecutionEnvironment` is created manually, one per target.
  """


# TODO: It might be pretty useful to have an Optional TypeConstraint.
class SetupPyExecutionEnvironment(datatype([
    # If None, don't set PYTHONPATH in the setup.py environment.
    ('setup_requires_pex', PEX),
    # If None, don't execute in the toolchain environment.
    'setup_py_native_tools',
])):

  _SHARED_CMDLINE_ARGS = {
    'darwin': lambda: [
      MIN_OSX_VERSION_ARG,
      '-Wl,-dylib',
      '-undefined',
      'dynamic_lookup',
    ],
    'linux': lambda: ['-shared'],
  }

  def as_environment(self):
    ret = {}

    # TODO(#5951): the below is a lot of error-prone repeated logic -- we need a way to compose
    # executables more hygienically. We should probably be composing each datatype's members, and
    # only creating an environment at the very end.
    native_tools = self.setup_py_native_tools
    if native_tools:
      # An as_tuple() method for datatypes could make this destructuring cleaner!  Alternatively,
      # constructing this environment could be done more compositionally instead of requiring all of
      # these disparate fields together at once.
      c_toolchain = native_tools.c_toolchain
      c_compiler = c_toolchain.c_compiler
      c_linker = c_toolchain.c_linker

      cpp_toolchain = native_tools.cpp_toolchain
      cpp_compiler = cpp_toolchain.cpp_compiler
      cpp_linker = cpp_toolchain.cpp_linker

      all_path_entries = (
        c_compiler.path_entries +
        c_linker.path_entries +
        cpp_compiler.path_entries +
        cpp_linker.path_entries)
      # TODO(#6273): We prepend our toolchain to the PATH instead of overwriting it -- we need
      # better control of the distutils compilation environment if we want to actually isolate the
      # PATH (distutils does lots of sneaky things).
      ret['PATH'] = create_path_env_var(all_path_entries, env=os.environ.copy(), prepend=True)

      # GCC will output smart quotes in a variety of situations (leading to decoding errors
      # downstream) unless we set this environment variable.
      ret['LC_ALL'] = 'C'

    return ret
