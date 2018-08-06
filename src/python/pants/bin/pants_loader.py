# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import importlib
import locale
import os
import warnings
from builtins import object


class PantsLoader(object):
  """Loads and executes entrypoints."""

  ENTRYPOINT_ENV_VAR = 'PANTS_ENTRYPOINT'
  DEFAULT_ENTRYPOINT = 'pants.bin.pants_exe:main'

  ENCODING_IGNORE_ENV_VAR = 'PANTS_IGNORE_UNRECOGNIZED_ENCODING'

  class InvalidLocaleError(Exception):
    """Raised when a valid locale can't be found."""

  @staticmethod
  def setup_warnings():
    # We want to present warnings to the user, set this up before importing any of our own code,
    # to ensure all deprecation warnings are seen, including module deprecations.
    # The "default" action displays a warning for a particular file and line number exactly once.
    # See https://docs.python.org/2/library/warnings.html#the-warnings-filter for the complete list.
    warnings.simplefilter('default', DeprecationWarning)

  @classmethod
  def ensure_locale(cls):
    # Sanity check for locale, See https://github.com/pantsbuild/pants/issues/2465.
    # This check is done early to give good feedback to user on how to fix the problem. Other
    # libraries called by Pants may fail with more obscure errors.
    encoding = locale.getpreferredencoding()
    if encoding.lower() != 'utf-8' and os.environ.get(cls.ENCODING_IGNORE_ENV_VAR, None) is None:
      raise cls.InvalidLocaleError(
        'System preferred encoding is `{}`, but `UTF-8` is required.\n'
        'Check and set the LC_* and LANG environment settings. Example:\n'
        '  LC_ALL=en_US.UTF-8\n'
        '  LANG=en_US.UTF-8\n'
        'To bypass this error, please file an issue and then set:\n'
        '  {}=1'.format(encoding, cls.ENCODING_IGNORE_ENV_VAR)
      )

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
    cls.ensure_locale()
    entrypoint = cls.determine_entrypoint(cls.ENTRYPOINT_ENV_VAR, cls.DEFAULT_ENTRYPOINT)
    cls.load_and_execute(entrypoint)


def main():
  PantsLoader.run()


if __name__ == '__main__':
  main()
