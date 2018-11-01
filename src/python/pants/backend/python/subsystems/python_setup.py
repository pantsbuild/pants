# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pkg_resources import Requirement

from pants.option.custom_types import UnsetBool
from pants.subsystem.subsystem import Subsystem


class PythonSetup(Subsystem):
  """A python environment."""
  options_scope = 'python-setup'

  @classmethod
  def register_options(cls, register):
    super(PythonSetup, cls).register_options(register)
    register('--interpreter-constraints', advanced=True, default=['CPython>=2.7,<3'], type=list,
             metavar='<requirement>',
             help="Constrain the selected Python interpreter.  Specify with requirement syntax, "
                  "e.g. 'CPython>=2.7,<3' (A CPython interpreter with version >=2.7 AND version <3)"
                  "or 'PyPy' (A pypy interpreter of any version). Multiple constraint strings will "
                  "be ORed together. These constraints are applied in addition to any "
                  "compatibilities required by the relevant targets.")
    register('--setuptools-version', advanced=True, default='40.4.3',
             help='The setuptools version for this python environment.')
    register('--wheel-version', advanced=True, default='0.31.1',
             help='The wheel version for this python environment.')
    register('--platforms', advanced=True, type=list, metavar='<platform>', default=['current'],
             fingerprint=True,
             help='A list of platforms to be supported by this python environment. Each platform'
                  'is a string, as returned by pkg_resources.get_supported_platform().')
    register('--interpreter-cache-dir', advanced=True, default=None, metavar='<dir>',
             help='The parent directory for the interpreter cache. '
                  'If unspecified, a standard path under the workdir is used.')
    register('--chroot-cache-dir', advanced=True, default=None, metavar='<dir>',
             help='The parent directory for the chroot cache. '
                  'If unspecified, a standard path under the workdir is used.')
    register('--resolver-cache-dir', advanced=True, default=None, metavar='<dir>',
             help='The parent directory for the requirement resolver cache. '
                  'If unspecified, a standard path under the workdir is used.')
    register('--resolver-cache-ttl', advanced=True, type=int, metavar='<seconds>',
             default=10 * 365 * 86400,  # 10 years.
             help='The time in seconds before we consider re-resolving an open-ended requirement, '
                  'e.g. "flask>=0.2" if a matching distribution is available on disk.')
    register('--resolver-allow-prereleases', advanced=True, type=bool, default=UnsetBool,
             fingerprint=True, help='Whether to include pre-releases when resolving requirements.')
    register('--artifact-cache-dir', advanced=True, default=None, metavar='<dir>',
             help='The parent directory for the python artifact cache. '
                  'If unspecified, a standard path under the workdir is used.')
    register('--interpreter-search-paths', advanced=True, type=list, default=[],
             metavar='<binary-paths>',
             help='A list of paths to search for python interpreters. Note that if a PEX_PYTHON_PATH '
              'variable is defined in a pexrc file, those interpreter paths will take precedence over ' 
              'this option.')
    register('--resolver-blacklist', advanced=True, type=dict, default={},
             removal_version='1.13.0.dev2',
             removal_hint='Now unused. Pants, via PEX, handles blacklisting automatically via '
                          'PEP-508 environment markers anywhere Python requirements are specified '
                          '(e.g. `requirements.txt` and `python_requirement(...)` in BUILD files): '
                          'https://www.python.org/dev/peps/pep-0508/#environment-markers',
             metavar='<blacklist>',
             help='A blacklist dict (str->str) that maps package name to an interpreter '
              'constraint. If a package name is in the blacklist and its interpreter '
              'constraint matches the target interpreter, skip the requirement. This is needed '
              'to ensure that universal requirement resolves for a target interpreter version do '
              'not error out on interpreter specific requirements such as backport libs like '
              '`functools32`. For example, a valid blacklist is {"functools32": "CPython>3"}. '
              'NOTE: this keyword is a temporary fix and will be reverted per: '
              'https://github.com/pantsbuild/pants/issues/5696. The long term '
              'solution is tracked by: https://github.com/pantsbuild/pex/issues/456.')
    register('--resolver-use-manylinux', advanced=True, type=bool, default=True, fingerprint=True,
             help='Whether to consider manylinux wheels when resolving requirements for linux '
                  'platforms.')

  @property
  def interpreter_constraints(self):
    return tuple(self.get_options().interpreter_constraints)

  @property
  def interpreter_search_paths(self):
    return self.get_options().interpreter_search_paths

  @property
  def setuptools_version(self):
    return self.get_options().setuptools_version

  @property
  def wheel_version(self):
    return self.get_options().wheel_version

  @property
  def platforms(self):
    return self.get_options().platforms

  @property
  def interpreter_cache_dir(self):
    return (self.get_options().interpreter_cache_dir or
            os.path.join(self.scratch_dir, 'interpreters'))

  @property
  def chroot_cache_dir(self):
    return (self.get_options().chroot_cache_dir or
            os.path.join(self.scratch_dir, 'chroots'))

  @property
  def resolver_cache_dir(self):
    return (self.get_options().resolver_cache_dir or
            os.path.join(self.scratch_dir, 'resolved_requirements'))

  @property
  def resolver_cache_ttl(self):
    return self.get_options().resolver_cache_ttl

  @property
  def resolver_allow_prereleases(self):
    return self.get_options().resolver_allow_prereleases

  @property
  def use_manylinux(self):
    return self.get_options().resolver_use_manylinux

  @property
  def artifact_cache_dir(self):
    """Note that this is unrelated to the general pants artifact cache."""
    return (self.get_options().artifact_cache_dir or
            os.path.join(self.scratch_dir, 'artifacts'))

  @property
  def scratch_dir(self):
    return os.path.join(self.get_options().pants_workdir, *self.options_scope.split('.'))

  def compatibility_or_constraints(self, target):
    """
    Return either the compatibility of the given target, or the interpreter constraints.
    If interpreter constraints are supplied by the CLI flag, return those only.
    """
    if self.get_options().is_flagged('interpreter_constraints'):
      return tuple(self.interpreter_constraints)
    return tuple(target.compatibility or self.interpreter_constraints)

  def setuptools_requirement(self):
    return self._failsafe_parse('setuptools=={0}'.format(self.setuptools_version))

  def wheel_requirement(self):
    return self._failsafe_parse('wheel=={0}'.format(self.wheel_version))

  # This is a setuptools <1 and >1 compatible version of Requirement.parse.
  # For setuptools <1, if you did Requirement.parse('setuptools'), it would
  # return 'distribute' which of course is not desirable for us.  So they
  # added a replacement=False keyword arg.  Sadly, they removed this keyword
  # arg in setuptools >= 1 so we have to simply failover using TypeError as a
  # catch for 'Invalid Keyword Argument'.
  def _failsafe_parse(self, requirement):
    try:
      return Requirement.parse(requirement, replacement=False)
    except TypeError:
      return Requirement.parse(requirement)
