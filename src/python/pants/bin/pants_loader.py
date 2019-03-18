# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import importlib
import locale
import os
import sys
import warnings
from builtins import object
from textwrap import dedent


class PantsLoader(object):
  """Loads and executes entrypoints."""

  ENTRYPOINT_ENV_VAR = 'PANTS_ENTRYPOINT'
  DEFAULT_ENTRYPOINT = 'pants.bin.pants_exe:main'

  ENCODING_IGNORE_ENV_VAR = 'PANTS_IGNORE_UNRECOGNIZED_ENCODING'
  INTERPRETER_IGNORE_ENV_VAR = 'PANTS_IGNORE_UNSUPPORTED_PYTHON_INTERPRETER'

  class InvalidLocaleError(Exception):
    """Raised when a valid locale can't be found."""

  class InvalidInterpreter(Exception):
    """Raised when trying to run Pants with an unsupported Python version."""

  @staticmethod
  def is_supported_interpreter(major_version, minor_version):
    return (major_version == 2 and minor_version == 7) \
      or (major_version == 3 and minor_version >= 6)

  @staticmethod
  def setup_warnings():
    # We want to present warnings to the user, set this up before importing any of our own code,
    # to ensure all deprecation warnings are seen, including module deprecations.
    # The "default" action displays a warning for a particular file and line number exactly once.
    # See https://docs.python.org/3/library/warnings.html#the-warnings-filter for the complete list.
    #
    # However, we do turn off deprecation warnings for libraries that Pants uses for which we do not have a fixed
    # upstream version, typically because the library is no longer maintained.
    warnings.simplefilter('default', category=DeprecationWarning)
    # TODO: Future has a pending PR to fix deprecation warnings at https://github.com/PythonCharmers/python-future/pull/421.
    # Remove this filter once that gets merged.
    warnings.filterwarnings('ignore', category=DeprecationWarning, module="future")
    # TODO: Eric-Arellano has emailed the author to see if he is willing to accept a PR fixing the deprecation warnings
    # and to release the fix. If he says yes, remove this once fixed.
    warnings.filterwarnings('ignore', category=DeprecationWarning, module="ansicolors")
    # TODO(7186): remove as part of work to land this PR.
    warnings.filterwarnings('ignore', category=DeprecationWarning, module="pex")

  @classmethod
  def ensure_locale(cls):
    # Sanity check for locale, See https://github.com/pantsbuild/pants/issues/2465.
    # This check is done early to give good feedback to user on how to fix the problem. Other
    # libraries called by Pants may fail with more obscure errors.
    encoding = locale.getpreferredencoding()
    if encoding.lower() != 'utf-8' and os.environ.get(cls.ENCODING_IGNORE_ENV_VAR, None) is None:
      raise cls.InvalidLocaleError(dedent("""
        Your system's preferred encoding is `{}`, but Pants requires `UTF-8`.
        Specifically, Python's `locale.getpreferredencoding()` must resolve to `UTF-8`.

        Fix it by setting the LC_* and LANG environment settings. Example:
          LC_ALL=en_US.UTF-8
          LANG=en_US.UTF-8
        Or, bypass it by setting the below environment variable. 
          {}=1
        Note: we cannot guarantee consistent behavior with this bypass enabled.
        """.format(encoding, cls.ENCODING_IGNORE_ENV_VAR)
      ))

  @classmethod
  def ensure_valid_interpreter(cls):
    """Runtime check that user is using a supported Python version."""
    py_major, py_minor = sys.version_info[0:2]
    if not PantsLoader.is_supported_interpreter(py_major, py_minor) and os.environ.get(cls.INTERPRETER_IGNORE_ENV_VAR, None) is None:
      raise cls.InvalidInterpreter(dedent("""
        You are trying to run Pants with Python {}.{}, which is unsupported.
        Pants requires a Python 2.7 or a Python 3.6+ interpreter to be
        discoverable on your PATH to run.

        If you still get this error after ensuring at least one of these interpreters
        is discoverable on your PATH, you may need to modify your build script
        (e.g. `./pants`) to properly set up a virtual environment with the correct
        interpreter. We recommend following our setup guide and using our setup script
        as a starting point: https://www.pantsbuild.org/setup_repo.html.

        Alternatively, you may bypass this error by setting the below environment variable.
          {}=1
        Note: we cannot guarantee consistent behavior with this bypass enabled.
        """.format(py_major, py_minor, cls.INTERPRETER_IGNORE_ENV_VAR)))

  @staticmethod
  def determine_entrypoint(env_var, default):
    return os.environ.pop(env_var, default)

  @staticmethod
  def load_and_execute(entrypoint):
    assert ':' in entrypoint, 'ERROR: entrypoint must be of the form `module.path:callable`'
    module_path, func_name = entrypoint.split(':', 1)
    module = importlib.import_module(module_path)
    entrypoint_main = getattr(module, func_name)
    assert callable(entrypoint_main), 'ERROR: entrypoint `{}` is not callable'.format(entrypoint)
    entrypoint_main()

  @classmethod
  def run(cls):
    cls.setup_warnings()
    cls.ensure_valid_interpreter()
    cls.ensure_locale()
    entrypoint = cls.determine_entrypoint(cls.ENTRYPOINT_ENV_VAR, cls.DEFAULT_ENTRYPOINT)
    cls.load_and_execute(entrypoint)


def main():
  PantsLoader.run()


if __name__ == '__main__':
  main()
