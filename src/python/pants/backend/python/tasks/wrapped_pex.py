# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from copy import copy


class WrappedPEX(object):
  """Wrapper around a PEX that exposes only its run() method.

  Allows us to set the PEX_PATH in the environment when running.
  """

  _PEX_PATH_ENV_VAR_NAME = 'PEX_PATH'

  # TODO(benjy): I think we can get rid of the interpreter argument.
  # In all cases it appears to be set to pex.interpreter.
  def __init__(self, pex, interpreter, extra_pex_paths=None):
    """
    :param pex: The main pex we wrap.
    :param interpreter: The interpreter the main pex will run on.
    :param extra_pex_paths: Other pexes, to "merge" in via the PEX_PATH mechanism.
    """
    self._pex = pex
    self._interpreter = interpreter
    self._extra_pex_paths = extra_pex_paths

  @property
  def interpreter(self):
    return self._interpreter

  def path(self):
    return self._pex.path()

  def cmdline(self, args=()):
    cmdline = ' '.join(self._pex.cmdline(args))
    pex_path = self._pex_path()
    if pex_path:
      return '{env_var_name}={pex_path} {cmdline}'.format(env_var_name=self._PEX_PATH_ENV_VAR_NAME,
                                                          pex_path=pex_path,
                                                          cmdline=cmdline)
    else:
      return cmdline

  def run(self, *args, **kwargs):
    pex_path = self._pex_path()
    if pex_path:
      kwargs_copy = copy(kwargs)
      env = copy(kwargs_copy.get('env')) if 'env' in kwargs_copy else {}
      env[self._PEX_PATH_ENV_VAR_NAME] = self._pex_path()
      kwargs_copy['env'] = env
      return self._pex.run(*args, **kwargs_copy)
    else:
      return self._pex.run(*args, **kwargs)

  def _pex_path(self):
    if self._extra_pex_paths:
      return ':'.join(self._extra_pex_paths)
    else:
      return None
