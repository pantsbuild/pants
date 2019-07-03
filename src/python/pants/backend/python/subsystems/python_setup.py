# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import subprocess

from pex.variables import Variables

from pants.option.custom_types import UnsetBool
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property


logger = logging.getLogger(__name__)


class PythonSetup(Subsystem):
  """A python environment."""
  options_scope = 'python-setup'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--interpreter-constraints', advanced=True, fingerprint=True, type=list,
             default=['CPython>=2.7,<3', 'CPython>=3.6,<4'],
             metavar='<requirement>',
             help="Constrain the selected Python interpreter.  Specify with requirement syntax, "
                  "e.g. 'CPython>=2.7,<3' (A CPython interpreter with version >=2.7 AND version <3)"
                  "or 'PyPy' (A pypy interpreter of any version). Multiple constraint strings will "
                  "be ORed together. These constraints are applied in addition to any "
                  "compatibilities required by the relevant targets.")
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
    register('--interpreter-search-paths', advanced=True, type=list,
             default=['<PEXRC>', '<PATH>'], metavar='<binary-paths>',
             help='A list of paths to search for python interpreters. The following special '
                  'strings are supported: '
                  '"<PATH>" (the contents of the PATH env var), '
                  '"<PEXRC>" (paths in the PEX_PYTHON_PATH variable in a pexrc file), '
                  '"<PYENV>" (all python versions under $(pyenv root)/versions).')
    register('--resolver-use-manylinux', advanced=True, type=bool, default=True, fingerprint=True,
             help='Whether to consider manylinux wheels when resolving requirements for linux '
                  'platforms.')

  @property
  def interpreter_constraints(self):
    return tuple(self.get_options().interpreter_constraints)

  @memoized_property
  def interpreter_search_paths(self):
    return self.expand_interpreter_search_paths(self.get_options().interpreter_search_paths)

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

  def compatibility_or_constraints(self, compatibility):
    """
    Return either the given compatibility, or the interpreter constraints. If interpreter
    constraints are supplied by the CLI flag, return those only.

    :param compatibility: Optional[List[str]], e.g. None or ['CPython>3'].
    """
    if self.get_options().is_flagged('interpreter_constraints'):
      return tuple(self.interpreter_constraints)
    return tuple(compatibility or self.interpreter_constraints)

  @classmethod
  def expand_interpreter_search_paths(cls, interpreter_search_paths, pyenv_root_func=None):
    special_strings = {
      '<PEXRC>': cls.get_pex_python_paths,
      '<PATH>': cls.get_environment_paths,
      '<PYENV>': lambda: cls.get_pyenv_paths(pyenv_root_func=pyenv_root_func)
    }
    expanded = []
    from_pexrc = None
    for s in interpreter_search_paths:
      if s in special_strings:
        special_paths = special_strings[s]()
        if s == '<PEXRC>':
          from_pexrc = special_paths
        expanded.extend(special_paths)
      else:
        expanded.append(s)
    # Some special-case logging to avoid misunderstandings.
    if from_pexrc and len(expanded) > len(from_pexrc):
      logger.info('pexrc interpreters requested and found, but other paths were also specified, '
                  'so interpreters may not be restricted to the pexrc ones. Full search path is: '
                  '{}'.format(':'.join(expanded)))
    return expanded

  @staticmethod
  def get_environment_paths():
    """Returns a list of paths specified by the PATH env var."""
    pathstr = os.getenv('PATH')
    if pathstr:
      return pathstr.split(os.pathsep)
    return []

  @staticmethod
  def get_pex_python_paths():
    """Returns a list of paths to Python interpreters as defined in a pexrc file.

    These are provided by a PEX_PYTHON_PATH in either of '/etc/pexrc', '~/.pexrc'.
    PEX_PYTHON_PATH defines a colon-separated list of paths to interpreters
    that a pex can be built and run against.
    """
    ppp = Variables.from_rc().get('PEX_PYTHON_PATH')
    if ppp:
      return ppp.split(os.pathsep)
    else:
      return []

  @staticmethod
  def get_pyenv_paths(pyenv_root_func=None):
    """Returns a list of paths to Python interpreters managed by pyenv.

    :param pyenv_root_func: A no-arg function that returns the pyenv root. Defaults to
                            running `pyenv root`, but can be overridden for testing.
    """
    pyenv_root_func = pyenv_root_func or get_pyenv_root
    pyenv_root = pyenv_root_func()
    if pyenv_root is None:
      return []
    versions_dir = os.path.join(pyenv_root, 'versions')
    paths = []
    for version in sorted(os.listdir(versions_dir)):
      path = os.path.join(versions_dir, version, 'bin')
      if os.path.isdir(path):
        paths.append(path)
    return paths


def get_pyenv_root():
  try:
    return subprocess.check_output(['pyenv', 'root']).decode().strip()
  except (OSError, subprocess.CalledProcessError):
    logger.info('No pyenv binary found. Will not use pyenv interpreters.')
  return None
