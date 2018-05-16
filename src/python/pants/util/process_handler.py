# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import multiprocessing
import os
import StringIO
import sys
from abc import abstractmethod

import six

from pants.util.meta import AbstractClass


# Expose subprocess with python 3.2+ capabilities (namely timeouts) and bugfixes from this module.
# NB: As recommended here: https://github.com/google/python-subprocess32/blob/master/README.md
# which accounts for non-posix, ie: Windows. Although we don't support Windows yet, this sets the
# pattern up in anticipation.
if os.name == 'posix' and six.PY2:
  import subprocess32 as subprocess3
else:
  import subprocess as subprocess3
subprocess = subprocess3


class ProcessHandler(AbstractClass):
  """An abstraction of process handling calls using the same interface as subprocess(32).Popen.

  See SubprocessProcessHandler below for an example.
  """

  @abstractmethod
  def wait(self, timeout=None):
    """Wait for the underlying process to terminate.

    :param float timeout: The time to wait for the process to terminate in fractional seconds. Wait
                          forever by default.
    :returns: The process exit code is it has terminated.
    :rtype: int
    :raises: :class:`subprocess.TimeoutExpired`
    """

  @abstractmethod
  def kill(self):
    pass

  @abstractmethod
  def terminate(self):
    pass

  @abstractmethod
  def poll(self):
    pass


class SubprocessProcessHandler(ProcessHandler):
  """A `ProcessHandler` that delegates directly to a subprocess(32).Popen object."""

  def __init__(self, process):
    self._process = process

  def wait(self, timeout=None):
    return self._process.wait(timeout=timeout)

  def kill(self):
    return self._process.kill()

  def terminate(self):
    return self._process.terminate()

  def poll(self):
    return self._process.poll()

  def communicate_teeing_stdout_and_stderr(self, stdin=None):
    """
    Just like subprocess.communicate, but tees stdout and stderr to both sys.std{out,err} and a
    buffer. Only operates on stdout/stderr if the Popen call send them to subprocess.PIPE.
    :param stdin: A string to send to the stdin of the subprocess.
    :return: (stdout, stderr) as strings.
    """
    if stdin is not None and self._process.stdin is not None:
      self._process.stdin.write(stdin)

    def fork_tee(infile, outfile):
      if infile is None:
        return lambda: None

      queue = multiprocessing.Queue()
      process = multiprocessing.Process(target=_tee, args=(infile, outfile, queue.put))
      process.start()
      def join_and_get_output():
        process.join()
        return queue.get()
      return join_and_get_output

    stdout = fork_tee(self._process.stdout, sys.stdout)
    stderr = fork_tee(self._process.stderr, sys.stderr)

    self._process.wait()

    return stdout(), stderr()


def _tee(infile, outfile, return_function):
  accumulator = StringIO.StringIO()
  for line in iter(infile.readline, ""):
    accumulator.write(line)
    outfile.write(line)
  infile.close()
  return_function(accumulator.getvalue())
