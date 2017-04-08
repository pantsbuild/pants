# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

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
    # TODO: On removal, make ['CPython>=2.7,<3'] the default for --interpreter-constraints.
    register('--interpreter-requirement', advanced=True, default='CPython>=2.7,<3',
             removal_version='1.5.0.dev0', removal_hint='Use --interpreter-constraints instead.',
             help='The interpreter requirement string for this python environment.')
    # Note: This will replace two options:
    # A) The global --interpreter option in the old python tasks.
    #    That flag is only relevant in the python backend, and should never have been
    #    global to begin with.
    # B) The --interpreter-requirement option above.  That flag merely served to set the
    #    effective default for when no other constraints were set, so we might as well
    #    roll that into the more general constraints.
    register('--interpreter-constraints', advanced=True, default=[], type=list,
             metavar='<requirement>',
             help="Constrain the selected Python interpreter.  Specify with requirement syntax, "
                  "e.g. 'CPython>=2.6,<3' or 'PyPy'. Multiple constraints will be ORed together. "
                  "These constraints are applied in addition to any compatibilities required by "
                  "the relevant targets.")
    register('--setuptools-version', advanced=True, default='30.0.0',
             help='The setuptools version for this python environment.')
    register('--wheel-version', advanced=True, default='0.29.0',
             help='The wheel version for this python environment.')
    register('--platforms', advanced=True, type=list, metavar='<platform>', default=['current'],
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

  @property
  def interpreter_constraints(self):
    return (self.get_options().interpreter_constraints or self.get_options().interpreter or
            [self.get_options().interpreter_requirement or b''])

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
  def artifact_cache_dir(self):
    """Note that this is unrelated to the general pants artifact cache."""
    return (self.get_options().artifact_cache_dir or
            os.path.join(self.scratch_dir, 'artifacts'))

  @property
  def scratch_dir(self):
    return os.path.join(self.get_options().pants_workdir, *self.options_scope.split('.'))

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
