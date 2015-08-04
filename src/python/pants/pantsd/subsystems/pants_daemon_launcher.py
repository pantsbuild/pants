# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.pantsd.pants_daemon import PantsDaemon
from pants.subsystem.subsystem import Subsystem


class PantsDaemonLauncher(Subsystem):
  """Pantsd launcher subsystem."""

  options_scope = 'pantsd'

  @classmethod
  def register_options(cls, register):
    register('--enabled', advanced=True, default=False, action='store_true',
             help='Whether or not to enable pantsd.')
    register('--http-host', advanced=True, default='127.0.0.1',
             help='The host to bind the HTTP server to.')
    register('--http-port', advanced=True, default=None,
             help='The port to bind the HTTP server to.')
    register('--log-dir', advanced=True, default=None,
             help='The directory to log pantsd output to.')
    register('--log-level', advanced=True, default=None,
             help='The log level for pantsd output.')

  def __init__(self, *args, **kwargs):
    Subsystem.__init__(self, *args, **kwargs)
    self.options = self.get_options()
    self.pantsd = PantsDaemon(self.options)
    self._logger = logging.getLogger()

  def _emit_experimental_warning(self):
    """Emit a (temporary) warning notice about using pantsd."""
    wl = '{0} WARNING! pantsd is an experimental feature, use at your own risk. {0}'.format('*' * 9)
    banner = len(wl) * '*'
    self._logger.warn('\n'.join(('', banner, wl, banner)))

  def maybe_launch(self):
    if self.options.enabled:
      self._emit_experimental_warning()

      if not self.pantsd.is_alive():
        self._logger.debug('launching pantsd')
        self.pantsd.daemonize(post_fork_child_opts=dict(log_level=self._logger.getEffectiveLevel()))

      self._logger.debug('pantsd is running at pid {pid}'.format(pid=self.pantsd.pid))
