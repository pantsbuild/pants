# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import sys

from pants.bin.remote_pants_runner import RemotePantsRunner
from pants.option.options_bootstrapper import OptionsBootstrapper


logger = logging.getLogger(__name__)


class PantsRunner(object):
  """A higher-level runner that delegates runs to either a LocalPantsRunner or RemotePantsRunner."""

  def __init__(self, exiter, args=None, env=None):
    """
    :param Exiter exiter: The Exiter instance to use for this run.
    :param list args: The arguments (sys.argv) for this run. (Optional, default: sys.argv)
    :param dict env: The environment for this run. (Optional, default: os.environ)
    """
    self._exiter = exiter
    self._args = args or sys.argv
    self._env = env or os.environ

  def _run(self, is_remote, exiter, args, env, process_metadata_dir=None, options_bootstrapper=None):
    if is_remote:
      try:
        return RemotePantsRunner(exiter, args, env, process_metadata_dir).run()
      except RemotePantsRunner.RECOVERABLE_EXCEPTIONS as e:
        # N.B. RemotePantsRunner will raise one of RECOVERABLE_EXCEPTIONS in the event we
        # encounter a failure while discovering or initially connecting to the pailgun. In
        # this case, we fall back to LocalPantsRunner which seamlessly executes the requested
        # run and bootstraps pantsd for use in subsequent runs.
        logger.debug('caught client exception: {!r}, falling back to LocalPantsRunner'.format(e))

    # N.B. Inlining this import speeds up the python thin client run by about 100ms.
    from pants.bin.local_pants_runner import LocalPantsRunner

    return LocalPantsRunner(exiter, args, env, options_bootstrapper=options_bootstrapper).run()

  def run(self):
    options_bootstrapper = OptionsBootstrapper(env=self._env, args=self._args)
    global_bootstrap_options = options_bootstrapper.get_bootstrap_options().for_global_scope()

    return self._run(is_remote=global_bootstrap_options.enable_pantsd,
                     exiter=self._exiter,
                     args=self._args,
                     env=self._env,
                     process_metadata_dir=global_bootstrap_options.pants_subprocessdir,
                     options_bootstrapper=options_bootstrapper)
