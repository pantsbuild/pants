# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import importlib
import locale
import os
import warnings


class PantsLoader(object):
  """Loads and executes entrypoints."""

  ENTRYPOINT_ENV_VAR = 'PANTS_ENTRYPOINT'
  DEFAULT_ENTRYPOINT = 'pants.bin.pants_exe:main'

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
    try:
      locale.getlocale()[1] or locale.getdefaultlocale()[1]
    except Exception as e:
      raise cls.InvalidLocaleError(
        '{}: {}\n'
        '  Could not get a valid locale. Check LC_* and LANG environment settings.\n'
        '  Example for US English:\n'
        '    LC_ALL=en_US.UTF-8\n'
        '    LANG=en_US.UTF-8'.format(type(e).__name__, e)
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
