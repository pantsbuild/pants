# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import sys
import warnings

from pants.base.exception_sink import ExceptionSink
from pants.bin.remote_pants_runner import RemotePantsRunner
from pants.init.logging import init_rust_logger, setup_logging_to_stderr
from pants.init.util import init_workdir
from pants.option.options_bootstrapper import OptionsBootstrapper


logger = logging.getLogger(__name__)


class PantsRunner(ExceptionSink.AccessGlobalExiterMixin):
  """A higher-level runner that delegates runs to either a LocalPantsRunner or RemotePantsRunner."""

  def __init__(self, args=None, env=None, start_time=None):
    """
    :param list args: The arguments (sys.argv) for this run. (Optional, default: sys.argv)
    :param dict env: The environment for this run. (Optional, default: os.environ)
    """
    self._args = args or sys.argv
    self._env = env or os.environ
    self._start_time = start_time

  # This could be a bootstrap option, but it's preferable to keep these very limited to make it
  # easier to make the daemon the default use case. Once the daemon lifecycle is stable enough we
  # should be able to avoid needing to kill it at all.
  _DAEMON_KILLING_GOALS = frozenset(['kill-pantsd', 'clean-all'])

  def will_terminate_pantsd(self):
    return not frozenset(self._args).isdisjoint(self._DAEMON_KILLING_GOALS)

  def _enable_rust_logging(self, global_bootstrap_options):
    levelname = global_bootstrap_options.level.upper()
    init_rust_logger(levelname, global_bootstrap_options.log_show_rust_3rdparty)
    setup_logging_to_stderr(logging.getLogger(None), levelname)

  def _should_run_with_pantsd(self, global_bootstrap_options):
    # If we want concurrent pants runs, we can't have pantsd enabled.
    return global_bootstrap_options.enable_pantsd and \
           not self.will_terminate_pantsd() and \
           not global_bootstrap_options.concurrent

  @staticmethod
  def scrub_pythonpath():
    # If PYTHONPATH was used to set up the Pants runtime environment, its entries our now on our
    # `sys.path` allowing us to run. Do not propagate any of these Pants-specific sys.path entries
    # forward to our subprocesses.
    pythonpath = os.environ.pop('PYTHONPATH', None)
    if pythonpath:
      logger.warning(f'Scrubbed PYTHONPATH={pythonpath} from the environment.')

  def run(self):
    self.scrub_pythonpath()

    options_bootstrapper = OptionsBootstrapper.create(env=self._env, args=self._args)
    bootstrap_options = options_bootstrapper.bootstrap_options
    global_bootstrap_options = bootstrap_options.for_global_scope()

    # Initialize the workdir early enough to ensure that logging has a destination.
    workdir_src = init_workdir(global_bootstrap_options)
    ExceptionSink.reset_log_location(workdir_src)

    # We enable Rust logging here,
    # and everything before it will be routed through regular Python logging.
    self._enable_rust_logging(global_bootstrap_options)

    ExceptionSink.reset_should_print_backtrace_to_terminal(global_bootstrap_options.print_exception_stacktrace)
    ExceptionSink.reset_log_location(global_bootstrap_options.pants_workdir)

    for message_regexp in global_bootstrap_options.ignore_pants_warnings:
      warnings.filterwarnings(action='ignore', message=message_regexp)

    # TODO https://github.com/pantsbuild/pants/issues/7205
    if self._should_run_with_pantsd(global_bootstrap_options):
      try:
        return RemotePantsRunner(self._exiter, self._args, self._env, options_bootstrapper).run()
      except RemotePantsRunner.Fallback as e:
        logger.warning('caught client exception: {!r}, falling back to non-daemon mode'.format(e))

    # N.B. Inlining this import speeds up the python thin client run by about 100ms.
    from pants.bin.local_pants_runner import LocalPantsRunner

    if self.will_terminate_pantsd():
      logger.debug("Pantsd terminating goal detected: {}".format(self._args))

    runner = LocalPantsRunner.create(
        self._args,
        self._env,
        options_bootstrapper=options_bootstrapper
    )
    runner.set_start_time(self._start_time)
    return runner.run()
