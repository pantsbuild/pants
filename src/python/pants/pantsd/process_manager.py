# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import signal
import subprocess
import time
import traceback
from contextlib import contextmanager

import psutil

from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_delete, safe_mkdir, safe_open


logger = logging.getLogger(__name__)


class ProcessGroup(object):
  """Wraps a logical group of processes and provides convenient access to ProcessManager objects."""

  def __init__(self, name):
    self._name = name

  @contextmanager
  def _swallow_psutil_exceptions(self):
    """A contextmanager that swallows standard psutil access exceptions."""
    try:
      yield
    except (psutil.AccessDenied, psutil.NoSuchProcess):
      # This masks common, but usually benign psutil process access exceptions that might be seen
      # when accessing attributes/methods on psutil.Process objects.
      pass

  def _instance_from_process(self, process):
    """Default converter from psutil.Process to process instance classes for subclassing."""
    return ProcessManager(name=process.name(), pid=process.pid, process_name=process.name())

  def iter_processes(self, proc_filter=None):
    proc_filter = proc_filter or (lambda x: True)
    with self._swallow_psutil_exceptions():
      for proc in (x for x in psutil.process_iter() if proc_filter(x)):
        yield proc

  def iter_instances(self, *args, **kwargs):
    for item in self.iter_processes(*args, **kwargs):
      yield self._instance_from_process(item)


class ProcessManager(object):
  """Subprocess/daemon management mixin/superclass. Not intended to be thread-safe."""

  class ExecutionError(Exception): pass
  class InvalidCommandOutput(Exception): pass
  class NonResponsiveProcess(Exception): pass
  class Timeout(Exception): pass

  WAIT_INTERVAL_SEC = .1
  FILE_WAIT_SEC = 10
  KILL_WAIT_SEC = 5
  KILL_CHAIN = (signal.SIGTERM, signal.SIGKILL)

  def __init__(self, name, pid=None, socket=None, process_name=None, socket_type=None):
    self._name = name
    self._pid = pid
    self._socket = socket
    self._socket_type = socket_type or int
    self._process_name = process_name
    self._buildroot = get_buildroot()
    self._process = None

  @property
  def name(self):
    """The logical name/label of the process."""
    return self._name

  @property
  def process_name(self):
    """The logical process name. If defined, this is compared to exe_name for stale pid checking."""
    return self._process_name

  @property
  def cmdline(self):
    """The process commandline. e.g. ['/usr/bin/python2.7', 'pants.pex'].

    :returns: The command line or else `None` if the underlying process has died.
    """
    try:
      process = self._as_process()
      if process:
        return process.cmdline()
    except psutil.NoSuchProcess:
      # On some platforms, accessing attributes of a zombie'd Process results in NoSuchProcess.
      pass
    return None

  @property
  def cmd(self):
    """The first element of the process commandline e.g. '/usr/bin/python2.7'.

    :returns: The first element of the process command line or else `None` if the underlying
              process has died.
    """
    return (self.cmdline or [None])[0]

  @property
  def pid(self):
    """The running processes pid (or None)."""
    return self._pid or self._get_pid()

  @property
  def socket(self):
    """The running processes socket/port information (or None)."""
    return self._socket or self._get_socket()

  @staticmethod
  def _maybe_cast(x, caster):
    try:
      return caster(x)
    except (TypeError, ValueError):
      return x

  def _as_process(self):
    """Returns a psutil `Process` object wrapping our pid.

    NB: Even with a process object in hand, subsequent method calls against it can always raise
    `NoSuchProcess`.  Care is needed to document the raises in the public API or else trap them and
    do something sensible for the API.

    :returns: a psutil Process object or else None if we have no pid.
    :rtype: :class:`psutil.Process`
    :raises: :class:`psutil.NoSuchProcess` if the process identified by our pid has died.
    """
    if self._process is None and self.pid:
      self._process = psutil.Process(self.pid)
    return self._process

  def _read_file(self, filename):
    with safe_open(filename, 'rb') as f:
      return f.read().strip()

  def _write_file(self, filename, payload):
    with safe_open(filename, 'wb') as f:
      f.write(payload)

  def _deadline_until(self, closure, timeout, wait_interval=WAIT_INTERVAL_SEC):
    """Execute a function/closure repeatedly until a True condition or timeout is met.

    :param func closure: the function/closure to execute (should not block for long periods of time
                         and must return True on success).
    :param float timeout: the maximum amount of time to wait for a true result from the closure in
                          seconds. N.B. this is timing based, so won't be exact if the runtime of
                          the closure exceeds the timeout.
    :param float wait_interval: the amount of time to sleep between closure invocations.
    :raises: :class:`ProcessManager.Timeout` on execution timeout.
    """
    deadline = time.time() + timeout
    while 1:
      if closure():
        return True
      elif time.time() > deadline:
        raise self.Timeout('exceeded timeout of {} seconds for {}'.format(timeout, closure))
      elif wait_interval:
        time.sleep(wait_interval)

  def _wait_for_file(self, filename, timeout=FILE_WAIT_SEC, want_content=True):
    """Wait up to timeout seconds for filename to appear with a non-zero size or raise Timeout()."""
    def file_waiter():
      return os.path.exists(filename) and (not want_content or os.path.getsize(filename))

    try:
      return self._deadline_until(file_waiter, timeout)
    except self.Timeout:
      # Re-raise with a more helpful exception message.
      raise self.Timeout('exceeded timeout of {} seconds while waiting for file {} to appear'
                         .format(timeout, filename))

  def await_pid(self, timeout):
    """Wait up to a given timeout for a process to launch."""
    self._wait_for_file(self.get_pid_path(), timeout)
    return self._get_pid()

  def await_socket(self, timeout):
    """Wait up to a given timeout for a process to write socket info."""
    self._wait_for_file(self.get_socket_path(), timeout)
    return self._get_socket()

  def get_metadata_dir(self):
    """Return a metadata path for the process.

       This should always live outside of the .pants.d dir to survive a clean-all.
    """
    return os.path.join(self._buildroot, '.pids', self._name)

  def _purge_metadata(self):
    assert not self.is_alive(), 'aborting attempt to purge metadata for a running process!'

    for f in (self.get_pid_path(), self.get_socket_path()):
      if f and os.path.exists(f):
        try:
          logging.debug('purging {file}'.format(file=f))
          safe_delete(f)
        except OSError as e:
          logging.warning('failed to unlink {file}: {exc}'.format(file=f, exc=e))

  def get_pid_path(self):
    """Return the path to the file containing the processes pid."""
    return os.path.join(self.get_metadata_dir(), 'pid')

  def get_socket_path(self):
    """Return the path to the file containing the processes socket."""
    return os.path.join(self.get_metadata_dir(), 'socket')

  def _maybe_init_metadata_dir(self):
    safe_mkdir(self.get_metadata_dir())

  def write_pid(self, pid):
    """Write the current processes PID to the pidfile location"""
    self._maybe_init_metadata_dir()
    self._write_file(self.get_pid_path(), str(pid))

  def write_socket(self, socket_info):
    """Write the local processes socket information (TCP port or UNIX socket)."""
    self._maybe_init_metadata_dir()
    self._write_file(self.get_socket_path(), str(socket_info))

  def _get_pid(self):
    """Retrieve and return the running PID."""
    try:
      return self._maybe_cast(self._read_file(self.get_pid_path()), int) or None
    except (IOError, OSError):
      return None

  def _get_socket(self):
    """Retrieve and return the running processes socket info."""
    try:
      return self._maybe_cast(self._read_file(self.get_socket_path()), self._socket_type) or None
    except (IOError, OSError):
      return None

  def is_dead(self):
    """Return a boolean indicating whether the process is dead or not."""
    return not self.is_alive()

  def is_alive(self):
    """Return a boolean indicating whether the process is running or not."""
    try:
      process = self._as_process()
      if not process:
        # Can happen if we don't find our pid.
        return False
      if (process.status() == psutil.STATUS_ZOMBIE or                    # Check for walkers.
          (self.process_name and self.process_name != process.name())):  # Check for stale pids.
        return False
    except psutil.NoSuchProcess:
      # On some platforms, accessing attributes of a zombie'd Process results in NoSuchProcess.
      return False

    return True

  def _kill(self, kill_sig):
    """Send a signal to the current process."""
    if self.pid:
      os.kill(self.pid, kill_sig)

  def terminate(self, signal_chain=KILL_CHAIN, kill_wait=KILL_WAIT_SEC, purge=True):
    """Ensure a process is terminated by sending a chain of kill signals (SIGTERM, SIGKILL)."""
    alive = self.is_alive()
    if alive:
      for signal_type in signal_chain:
        try:
          self._kill(signal_type)
        except OSError as e:
          logger.warning('caught OSError({e!s}) during attempt to kill -{signal} {pid}!'
                         .format(e=e, signal=signal_type, pid=self.pid))

        # Wait up to kill_wait seconds to terminate or move onto the next signal.
        try:
          if self._deadline_until(self.is_dead, kill_wait):
            alive = False
            break
        except self.Timeout:
          # Loop to the next kill signal on timeout.
          pass

    if alive:
      raise self.NonResponsiveProcess('failed to kill pid {pid} with signals {chain}'
                                      .format(pid=self.pid, chain=signal_chain))

    if purge:
      self._purge_metadata()

  def get_subprocess_output(self, *args):
    try:
      return subprocess.check_output(*args)
    except (OSError, subprocess.CalledProcessError) as e:
      raise self.ExecutionError(str(e))

  def daemonize(self, pre_fork_opts=None, post_fork_parent_opts=None, post_fork_child_opts=None,
                write_pid=True):
    """Perform a double-fork, execute callbacks and write the child pid file.

       The double-fork here is necessary to truly daemonize the subprocess such that it can never
       take control of a tty. The initial fork and setsid() creates a new, isolated process group
       and also makes the first child a session leader (which can still acquire a tty). By forking a
       second time, we ensure that the second child can never acquire a controlling terminal because
       it's no longer a session leader - but it now has its own separate process group.

       Additionally, a normal daemon implementation would typically perform an os.umask(0) to reset
       the processes file mode creation mask post-fork. We do not do this here (and in daemon_spawn
       below) due to the fact that the daemons that pants would run are typically personal user
       daemons. Having a disparate umask from pre-vs-post fork causes files written in each phase to
       differ in their permissions without good reason - in this case, we want to inherit the umask.
    """
    self.pre_fork(**pre_fork_opts or {})
    pid = os.fork()
    if pid == 0:
      os.setsid()
      second_pid = os.fork()
      if second_pid == 0:
        try:
          os.chdir(self._buildroot)
          self.post_fork_child(**post_fork_child_opts or {})
        except Exception:
          logging.critical(traceback.format_exc())

        os._exit(0)
      else:
        try:
          if write_pid: self.write_pid(second_pid)
          self.post_fork_parent(**post_fork_parent_opts or {})
        except Exception:
          logging.critical(traceback.format_exc())

        os._exit(0)

  def daemon_spawn(self, pre_fork_opts=None, post_fork_parent_opts=None, post_fork_child_opts=None):
    """Perform a single-fork to run a subprocess and write the child pid file.

       Use this if your post_fork_child block invokes a subprocess via subprocess.Popen(). In this
       case, a second fork such as used in daemonize() is extraneous given that Popen() also forks.
       Using this daemonization method vs daemonize() leaves the responsibility of writing the pid
       to the caller to allow for library-agnostic flexibility in subprocess execution.
    """
    self.pre_fork(**pre_fork_opts or {})
    pid = os.fork()
    if pid == 0:
      try:
        os.setsid()
        os.chdir(self._buildroot)
        self.post_fork_child(**post_fork_child_opts or {})
      except Exception:
        logging.critical(traceback.format_exc())

      os._exit(0)
    else:
      try:
        self.post_fork_parent(**post_fork_parent_opts or {})
      except Exception:
        logging.critical(traceback.format_exc())

  def pre_fork(self):
    """Pre-fork callback for subclasses."""
    pass

  def post_fork_child(self):
    """Pre-fork child callback for subclasses."""
    pass

  def post_fork_parent(self):
    """Post-fork parent callback for subclasses."""
    pass
