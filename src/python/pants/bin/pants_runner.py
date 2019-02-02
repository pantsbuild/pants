# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
import sys
from builtins import object

from future.utils import PY3

from pants.base.build_environment import get_buildroot
from pants.base.exception_sink import ExceptionSink
from pants.base.exiter import Exiter
from pants.bin.remote_pants_runner import RemotePantsRunner
from pants.fs.archive import TarArchiver
from pants.option.options_bootstrapper import OptionsBootstrapper


logger = logging.getLogger(__name__)


class FuzzerExiter(Exiter):
  """Override the normal Exiter behavior to just die faster for faster fuzzing iteration."""

  def __init__(self):
    # os._exit() can be faster for fuzzing, see:
    # https://barro.github.io/2018/01/taking-a-look-at-python-afl/
    super(FuzzerExiter, self).__init__(exiter=os._exit)


class PantsRunner(object):
  """A higher-level runner that delegates runs to either a LocalPantsRunner or RemotePantsRunner."""

  def __init__(self, exiter, args=None, env=None, start_time=None):
    """
    :param Exiter exiter: The Exiter instance to use for this run.
    :param list args: The arguments (sys.argv) for this run. (Optional, default: sys.argv)
    :param dict env: The environment for this run. (Optional, default: os.environ)
    """
    logger.info('dropping normal exiter {!r} to use {}...'.format(exiter, FuzzerExiter.__name__))
    self._exiter = FuzzerExiter()
    self._args = args or sys.argv
    self._env = env or os.environ
    self._start_time = start_time

  def run(self):
    # Register our exiter at the beginning of the run() method so that any code in this process from
    # this point onwards will use that exiter in the case of a fatal error.
    ExceptionSink.reset_exiter(self._exiter)

    options_bootstrapper = OptionsBootstrapper.create(env=self._env, args=self._args)
    bootstrap_options = options_bootstrapper.bootstrap_options
    global_bootstrap_options = bootstrap_options.for_global_scope()

    ExceptionSink.reset_should_print_backtrace_to_terminal(global_bootstrap_options.print_exception_stacktrace)
    ExceptionSink.reset_log_location(global_bootstrap_options.pants_workdir)

    if global_bootstrap_options.afl_fuzz_untar_stdin:
      # Initialize python-afl.
      import afl
      afl.init()
      # NB: read the tar file from stdin, extract it into the current directory, then run pants!
      tar_archiver = TarArchiver('r:', 'tar')
      in_stream = sys.stdin.buffer if PY3 else sys.stdin
      # TODO: if there is an error extracting the tar archive, simply exit with 0! We don't want to
      # try to fuzz python tar extraction, so if we quickly succeed we can (hopefully) get afl to
      # find more interesting cases!
      tar_archiver.extract(in_stream, get_buildroot())
      try:
        in_stream.close()
      except ValueError as e:
        logger.exception(e)

    # TODO: use LocalPantsRunner if the goal is kill-pantsd or clean-all!
    if global_bootstrap_options.enable_pantsd:
      try:
        return RemotePantsRunner(self._exiter, self._args, self._env, options_bootstrapper).run()
      except RemotePantsRunner.Fallback as e:
        logger.warn('caught client exception: {!r}, falling back to non-daemon mode'.format(e))

    # N.B. Inlining this import speeds up the python thin client run by about 100ms.
    from pants.bin.local_pants_runner import LocalPantsRunner

    runner = LocalPantsRunner.create(
        self._exiter,
        self._args,
        self._env,
        options_bootstrapper=options_bootstrapper
    )
    runner.set_start_time(self._start_time)
    return runner.run()
