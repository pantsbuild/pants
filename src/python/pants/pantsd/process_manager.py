# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from contextlib import contextmanager
import logging
import os
import signal
import subprocess
import time
import traceback

from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_delete, safe_mkdir, safe_open

import psutil


logger = logging.getLogger(__name__)


class ProcessGroup(object):
  """Wraps a logical group of processes and provides convenient access to ProcessManager objects."""

  PSUTIL_STD_EXCEPTIONS = (psutil.AccessDenied, psutil.NoSuchProcess)

  def __init__(self, name):
    self._name = name

  @contextmanager
  def _psutil_safe_access(self, exceptions=PSUTIL_STD_EXCEPTIONS, mask_exc=True):
    """A contextmanager that traps standard psutil access exceptions."""
    try:
      yield
    except exceptions:
      if not mask_exc: raise

  def _instance_from_process(self, process):
    """Default converter from psutil.Process to process instance classes for subclassing."""
    return ProcessManager(name=process.cmdline[0], pid=process.pid, process_name=process.cmdline[0])

  def iter_processes(self, proc_filter=None, mask_exc=True):
    proc_filter = proc_filter or (lambda x: True)
    with self._psutil_safe_access(mask_exc=mask_exc):
      for proc in (x for x in psutil.process_iter() if proc_filter(x)):
        yield proc

  def iter_instances(self, *args, **kwargs):
    for item in self.iter_processes(*args, **kwargs):
      yield self._instance_from_process(item)


class ProcessManager(object):
  """Subprocess/daemon management mixin/superclass."""

  class NonResponsiveProcess(Exception): pass
  class Timeout(Exception): pass

  WAIT_INTERVAL = .1
  KILL_WAIT = 1
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
    return self._name

  @property
  def exe(self):
    try:
      return self.as_process().cmdline[0]
    except AssertionError:
      return None

  @property
  def process_name(self):
    return self._process_name

  @property
  def pid(self):
    return self._pid or self.get_pid()

  @property
  def socket(self):
    return self._socket or self.get_socket()

  @staticmethod
  def _maybe_cast(x, caster):
    try:
      return caster(x)
    except (TypeError, ValueError):
      return x

  def as_process(self):
    assert self.is_alive(), 'cannot get process for a non-running process'
    if not self._process:
      self._process = psutil.Process(self.pid)
    return self._process

  def _read_file(self, filename):
    with safe_open(filename, 'rb') as f:
      return f.read().strip()

  def _write_file(self, filename, payload):
    with safe_open(filename, 'wb') as f:
      f.write(payload)

  def _wait_for_file(self, filename, timeout=10, want_content=True):
    """Wait up to timeout seconds for filename to appear with a non-zero size or raise Timeout()."""
    start_time = time.time()
    while 1:
      if os.path.exists(filename) and (not want_content or os.path.getsize(filename)): return

      if time.time() - start_time > timeout:
        raise self.Timeout('exceeded timeout of {sec} seconds while waiting for file {filename}'
                           .format(sec=timeout, filename=filename))
      else:
        time.sleep(self.WAIT_INTERVAL)

  def await_pid(self, timeout):
    """Wait up to a given timeout for a process to launch."""
    self._wait_for_file(self.get_pid_path(), timeout)
    return self._read_file(self.get_pid_path())

  def await_socket(self, timeout):
    """Wait up to a given timeout for a process to write socket info."""
    self._wait_for_file(self.get_socket_path(), timeout)
    return self._read_file(self.get_socket_path())

  def get_metadata_dir(self):
    """Return a deterministic, relative metadata path for the process.

       This should always live outside of the .pants.d dir to survive a clean-all.
    """
    return os.path.join(self._buildroot, '.pids', self._name)

  def _maybe_init_metadata_dir(self):
    safe_mkdir(self.get_metadata_dir())

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

  def write_pid(self, pid):
    """Write the current processes PID to the pidfile location"""
    self._maybe_init_metadata_dir()
    self._write_file(self.get_pid_path(), str(pid))

  def write_socket(self, socket_info):
    """Write the local processes socket information (TCP port or UNIX socket)."""
    self._maybe_init_metadata_dir()
    self._write_file(self.get_socket_path(), str(socket_info))

  def get_pid(self):
    """Retrieve and return the running PID."""
    try:
      return self._maybe_cast(self._read_file(self.get_pid_path()), int) or None
    except (IOError, OSError):
      return None

  def get_socket(self):
    """Retrieve and return the running processes socket info."""
    try:
      return self._maybe_cast(self._read_file(self.get_socket_path()), self._socket_type) or None
    except (IOError, OSError):
      return None

  def is_alive(self, pid=None):
    """Return a boolean indicating whether the process is running."""
    return psutil.pid_exists(pid or self.pid)
    # TODO: consider stale pidfile case and assertion of self.process_name == proc.cmdline[0]

  def kill(self, kill_sig):
    """Send a signal to the current process."""
    os.kill(self.pid, kill_sig)

  def terminate(self, signal_chain=KILL_CHAIN, kill_wait=KILL_WAIT):
    """Ensure a process is terminated by sending a chain of kill signals (SIGTERM, SIGKILL)."""
    for signal_type in signal_chain:
      if not self.is_alive():
        self._purge_metadata()
        return

      self.kill(signal_type)
      time.sleep(kill_wait)

    if self.is_alive():
      raise self.NonResponsiveProcess('failed to kill pid {pid} with signal chain {chain}'
                                      .format(pid=self.pid, chain=signal_chain))

  def monitor(self):
    """Synchronously monitor the current process and actively keep it alive."""
    raise NotImplementedError()

  def _open_process(self, *args, **kwargs):
    return subprocess.Popen(*args, **kwargs)

  def run(self, *args, **kwargs):
    """Synchronously run a subprocess."""
    return self._open_process(*args, **kwargs)

  def daemonize(self, pre_fork_opts=None, post_fork_parent_opts=None, post_fork_child_opts=None,
                write_pid=True):
    """Perform a double-fork, execute callbacks and write the child pid file.

       The double-fork here is necessary to truly daemonize the subprocess such that it can never
       take control of a tty. The initial fork and setsid() creates a new, isolated process group
       and also makes the first child a session leader (which can still acquire a tty). By forking a
       second time, we ensure that the second child can never acquire a controlling terminal because
       it's no longer a session leader - but it now has its own separate process group.
    """
    self.pre_fork(**pre_fork_opts or {})
    pid = os.fork()
    if pid == 0:
      os.setsid()
      second_pid = os.fork()
      if second_pid == 0:
        try:
          os.chdir(self._buildroot)
          os.umask(0)
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
        os.umask(0)
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
    """Pre-fork callback for subclasses. No-op otherwise."""

  def post_fork_child(self):
    """Pre-fork child callback for subclasses. No-op otherwise."""

  def post_fork_parent(self):
    """Post-fork parent callback for subclasses. No-op otherwise."""
