# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from distutils.command.build_ext import distutils_build_ext
from distutils.core import Extension as DistutilsExtension
from setuptools import setup as setuptools_setup

from pants.util.strutil import safe_shlex_join, safe_shlex_split


class PantsDistutilsExtensionError(Exception): pass


def _parse_exe_flags_into_command(exe_var, flags_var):
  argv = [os.environ[exe_var]] + safe_shlex_split(os.environ[flags_var])
  return safe_shlex_join(argv)


def customize_compiler_from_env(compiler):
  """???"""
  cc_cmd = _parse_exe_flags_into_command('CC', 'CFLAGS')
  cxx_cmd = _parse_exe_flags_into_command('CXX', 'CXXFLAGS')
  link_cmd = _parse_exe_flags_into_command('LDSHARED', 'LDFLAGS')
  compiler.set_executables(
    compiler=cc_cmd,
    compiler_cxx=cxx_cmd,
    linker_so=link_cmd)


class env_only_build_ext(distutils_build_ext):
  """???"""

  def _append_to_compiler_property(elements, append_fun):
    if elements is not None:
      for el in elements:
        append_fun(el)

  def run(self):
        from distutils.ccompiler import new_compiler

        # 'self.extensions', as supplied by setup.py, is a list of
        # Extension instances.  See the documentation for Extension (in
        # distutils.extension) for details.
        #
        # For backwards compatibility with Distutils 0.8.2 and earlier, we
        # also allow the 'extensions' list to be a list of tuples:
        #    (ext_name, build_info)
        # where build_info is a dictionary containing everything that
        # Extension instances do except the name, with a few things being
        # differently named.  We convert these 2-tuples to Extension
        # instances as needed.

        if not self.extensions:
            return

        # If we were asked to build any C/C++ libraries, make sure that the
        # directory where we put them is in the library search path for
        # linking extensions.
        if self.distribution.has_c_libraries():
            build_clib = self.get_finalized_command('build_clib')
            self.libraries.extend(build_clib.get_library_names() or [])
            self.library_dirs.append(build_clib.build_clib)

        # Setup the CCompiler object that we'll use to do all the
        # compiling and linking
        self.compiler = new_compiler(compiler=self.compiler,
                                     verbose=self.verbose,
                                     dry_run=self.dry_run,
                                     force=self.force)
        customize_compiler_from_env(self.compiler)
        # If we are cross-compiling, init the compiler now (if we are not
        # cross-compiling, init would not hurt, but people may rely on
        # late initialization of compiler even if they shouldn't...)
        if os.name == 'nt' and self.plat_name != get_platform():
            self.compiler.initialize(self.plat_name)

        # And make sure that any compile/link-related options (which might
        # come from the command-line or from the setup script) are set in
        # that CCompiler object -- that way, they automatically apply to
        # all compiling and linking done here.
        self._append_to_compiler_property(self.include_dirs, self.compiler.add_include_dir)
        if self.define is not None:
            # 'define' option is a list of (name,value) tuples
            for (name, value) in self.define:
                self.compiler.define_macro(name, value)
        if self.undef is not None:
            for macro in self.undef:
                self.compiler.undefine_macro(macro)
        self._append_to_compiler_property(self.libraries, self.compiler.add_library)
        self._append_to_compiler_property(self.library_dirs, self.compiler.add_library_dir)
        self._append_to_compiler_property(self.rpath, self.compiler.add_runtime_library_dir)
        self._append_to_compiler_property(self.link_objects, self.compiler.add_link_object)

        # Now actually compile and link everything.
        self.build_extensions()


def pants_setup(cmdclass=None, *args, **kwargs):
  """???"""
  if cmdclass is None:
    cmdclass = {}
  if 'build_ext' in cmdclass:
    raise PantsDistutilsExtensionError(
      "Overriding 'build_ext' in the 'cmdclass' keyword argument of pants_setup() "
      "is not supported.")

  cmdclass.add('build_ext', env_only_build_ext)

  setuptools_setup(*args, cmdclass=cmdclass, **kwargs)
