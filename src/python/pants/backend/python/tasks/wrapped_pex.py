# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
from builtins import object
from copy import copy


logger = logging.getLogger(__name__)


class WrappedPEX(object):
  """Wrapper around a PEX that exposes only its run() method.

  Allows us to set the PEX_PATH in the environment when running.
  """

  _PEX_PATH_ENV_VAR_NAME = 'PEX_PATH'

  def __init__(self, pex, extra_pex_paths=None):
    """
    :param pex: The main pex we wrap.
    :param extra_pex_paths: Other pexes, to "merge" in via the PEX_PATH mechanism.
    """
    self._pex = pex
    self._extra_pex_paths = extra_pex_paths

  @property
  def interpreter(self):
    return self._pex._interpreter

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
    env = copy(kwargs.pop('env', {}))

    pex_path = self._pex_path()
    if pex_path:
      env[self._PEX_PATH_ENV_VAR_NAME] = pex_path

    logger.debug('Executing WrappedPEX using: {}'.format(self.cmdline(args=tuple(*args))))
    return self._pex.run(*args, env=env, **kwargs)

  def _pex_path(self):
    if self._extra_pex_paths:
      return ':'.join(self._extra_pex_paths)
    else:
      return None
