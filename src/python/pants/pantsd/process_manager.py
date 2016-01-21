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
from pants.util.dirutil import read_file, rm_rf, safe_file_dump, safe_mkdir


logger = logging.getLogger(__name__)


@contextmanager
def swallow_psutil_exceptions():
  """A contextmanager that swallows standard psutil access exceptions."""
  try:
    yield
  except (psutil.AccessDenied, psutil.NoSuchProcess):
    # This masks common, but usually benign psutil process access exceptions that might be seen
    # when accessing attributes/methods on psutil.Process objects.
    pass


class ProcessGroup(object):
  """Wraps a logical group of processes and provides convenient access to ProcessManager objects."""

  def __init__(self, name):
    self._name = name

  def _instance_from_process(self, process):
    """Default converter from psutil.Process to process instance classes for subclassing."""
    return ProcessManager(name=process.name(), pid=process.pid, process_name=process.name())

  def iter_processes(self, proc_filter=None):
    proc_filter = proc_filter or (lambda x: True)
    with swallow_psutil_exceptions():
      for proc in (x for x in psutil.process_iter() if proc_filter(x)):
        yield proc

  def iter_instances(self, *args, **kwargs):
    for item in self.iter_processes(*args, **kwargs):
      yield self._instance_from_process(item)


class ProcessMetadataManager(object):
  """"Manages contextual, on-disk process metadata."""

  FILE_WAIT_SEC = 10
  WAIT_INTERVAL_SEC = .1
  PID_DIR_NAME = '.pids'  # TODO(kwlzn): Make this configurable.

  class MetadataError(Exception): pass
  class Timeout(Exception): pass

  @staticmethod
  def _maybe_cast(item, caster):
    """Given a casting function, attempt to cast to that type while masking common cast exceptions.

    N.B. This is mostly suitable for casting string types to numeric types - e.g. a port number
    read from disk into an int.

    :param func caster: A casting callable (e.g. `int`).
    :returns: The result of caster(item) or item if TypeError or ValueError are raised during cast.
    """
    try:
      return caster(item)
    except (TypeError, ValueError):
      # N.B. the TypeError catch here (already) protects against the case that caster is None.
      return item

  @classmethod
  def _get_metadata_dir_by_name(cls, name):
    """Retrieve the metadata dir by name.

    This should always live outside of the workdir to survive a clean-all.
    """
    return os.path.join(get_buildroot(), cls.PID_DIR_NAME, name)

  @classmethod
  def _maybe_init_metadata_dir_by_name(cls, name):
    """Initialize the metadata directory for a named identity if it doesn't exist."""
    safe_mkdir(cls._get_metadata_dir_by_name(name))

  @classmethod
  def read_metadata_by_name(cls, name, metadata_key, caster=None):
    """Read process metadata using a named identity.

    :param string name: The ProcessMetadataManager identity/name (e.g. 'pantsd').
    :param string metadata_key: The metadata key (e.g. 'pid').
    :param func caster: A casting callable to apply to the read value (e.g. `int`).
    """
    try:
      file_path = os.path.join(cls._get_metadata_dir_by_name(name), metadata_key)
      return cls._maybe_cast(read_file(file_path).strip(), caster)
    except (IOError, OSError):
      return None

  @classmethod
  def write_metadata_by_name(cls, name, metadata_key, metadata_value):
    """Write process metadata using a named identity.

    :param string name: The ProcessMetadataManager identity/name (e.g. 'pantsd').
    :param string metadata_key: The metadata key (e.g. 'pid').
    :param string metadata_value: The metadata value (e.g. '1729').
    """
    cls._maybe_init_metadata_dir_by_name(name)
    file_path = os.path.join(cls._get_metadata_dir_by_name(name), metadata_key)
    safe_file_dump(file_path, metadata_value)

  @classmethod
  def _deadline_until(cls, closure, timeout, wait_interval=WAIT_INTERVAL_SEC):
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
        raise cls.Timeout('exceeded timeout of {} seconds for {}'.format(timeout, closure))
      elif wait_interval:
        time.sleep(wait_interval)

  @classmethod
  def _wait_for_file(cls, filename, timeout=FILE_WAIT_SEC, want_content=True):
    """Wait up to timeout seconds for filename to appear with a non-zero size or raise Timeout()."""
    def file_waiter():
      return os.path.exists(filename) and (not want_content or os.path.getsize(filename))

    try:
      return cls._deadline_until(file_waiter, timeout)
    except cls.Timeout:
      # Re-raise with a more helpful exception message.
      raise cls.Timeout('exceeded timeout of {} seconds while waiting for file {} to appear'
                         .format(timeout, filename))

  @classmethod
  def await_metadata_by_name(cls, name, metadata_key, timeout, caster=None):
    """Block up to a timeout for process metadata to arrive on disk.

    :param string name: The ProcessMetadataManager identity/name (e.g. 'pantsd').
    :param string metadata_key: The metadata key (e.g. 'pid').
    :param int timeout: The deadline to write metadata.
    :param type caster: A type-casting callable to apply to the read value (e.g. int, str).
    :returns: The value of the metadata key (read from disk post-write).
    :raises: :class:`ProcessMetadataManager.Timeout` on timeout.
    """
    file_path = os.path.join(cls._get_metadata_dir_by_name(name), metadata_key)
    cls._wait_for_file(file_path, timeout=timeout)
    return cls.read_metadata_by_name(name, metadata_key, caster)

  @classmethod
  def purge_metadata_by_name(cls, name):
    """Purge a processes metadata directory.

    :raises: `ProcessManager.MetadataError` when OSError is encountered on metadata dir removal.
    """
    meta_dir = cls._get_metadata_dir_by_name(name)
    logging.debug('purging metadata directory: {}'.format(meta_dir))
    try:
      rm_rf(meta_dir)
    except OSError as e:
      raise cls.MetadataError('failed to purge metadata directory {}: {!r}'.format(meta_dir, e))


class ProcessManager(ProcessMetadataManager):
  """Subprocess/daemon management mixin/superclass. Not intended to be thread-safe."""

  class ExecutionError(Exception): pass
  class InvalidCommandOutput(Exception): pass
  class NonResponsiveProcess(Exception): pass

  KILL_WAIT_SEC = 5
  KILL_CHAIN = (signal.SIGTERM, signal.SIGKILL)

  def __init__(self, name, pid=None, socket=None, process_name=None, socket_type=int):
    """
    :param string name: The process identity/name (e.g. 'pantsd' or 'ng_Zinc').
    :param int pid: The process pid. Overrides fetching of the self.pid @property.
    :param string socket: The socket metadata. Overrides fetching of the self.socket @property.
    :param string process_name: The process name for cmdline executable name matching.
    :param type socket_type: The type to be used for socket type casting (e.g. int).
    """
    self._name = name
    self._pid = pid
    self._socket = socket
    self._socket_type = socket_type
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
    with swallow_psutil_exceptions():
      process = self._as_process()
      if process:
        return process.cmdline()
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
    return self._pid or self.read_metadata_by_name(self._name, 'pid', int)

  @property
  def socket(self):
    """The running processes socket/port information (or None)."""
    return self._socket or self.read_metadata_by_name(self._name, 'socket', self._socket_type)

  @classmethod
  def get_subprocess_output(cls, *args):
    """Get the output of an executed command.

    :param *args: An iterable representing the command to execute (e.g. ['ls', '-al']).
    :raises: `ProcessManager.ExecutionError` on `OSError` or `CalledProcessError`.
    :returns: The output of the command.
    """
    try:
      return subprocess.check_output(*args)
    except (OSError, subprocess.CalledProcessError) as e:
      raise cls.ExecutionError(str(e))

  def await_pid(self, timeout):
    """Wait up to a given timeout for a process to write pid metadata."""
    return self.await_metadata_by_name(self._name, 'pid', timeout, int)

  def await_socket(self, timeout):
    """Wait up to a given timeout for a process to write socket info."""
    return self.await_metadata_by_name(self._name, 'socket', timeout, self._socket_type)

  def write_pid(self, pid):
    """Write the current processes PID to the pidfile location"""
    self.write_metadata_by_name(self._name, 'pid', str(pid))

  def write_socket(self, socket_info):
    """Write the local processes socket information (TCP port or UNIX socket)."""
    self.write_metadata_by_name(self._name, 'socket', str(socket_info))

  def write_named_socket(self, socket_name, socket_info):
    """A multi-tenant, named alternative to ProcessManager.write_socket()."""
    self.write_metadata_by_name(self._name, 'socket_{}'.format(socket_name), str(socket_info))

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
    except (psutil.NoSuchProcess, psutil.AccessDenied):
      # On some platforms, accessing attributes of a zombie'd Process results in NoSuchProcess.
      return False

    return True

  def purge_metadata(self, force=False):
    """Instance-based version of ProcessMetadataManager.purge_metadata_by_name() that checks
    for process liveness before purging metadata.

    :param bool force: If True, skip process liveness check before purging metadata.
    :raises: `ProcessManager.MetadataError` when OSError is encountered on metadata dir removal.
    """
    if not force and self.is_alive():
      raise self.MetadataError('cannot purge metadata for a running process!')

    super(ProcessManager, self).purge_metadata_by_name(self._name)

  def _kill(self, kill_sig):
    """Send a signal to the current process."""
    if self.pid:
      os.kill(self.pid, kill_sig)

  def terminate(self, signal_chain=KILL_CHAIN, kill_wait=KILL_WAIT_SEC, purge=True):
    """Ensure a process is terminated by sending a chain of kill signals (SIGTERM, SIGKILL)."""
    alive = self.is_alive()
    if alive:
      for signal_type in signal_chain:
        pid = self.pid
        try:
          logger.debug('sending signal {} to pid {}'.format(signal_type, pid))
          self._kill(signal_type)
        except OSError as e:
          logger.warning('caught OSError({e!s}) during attempt to kill -{signal} {pid}!'
                         .format(e=e, signal=signal_type, pid=pid))

        # Wait up to kill_wait seconds to terminate or move onto the next signal.
        try:
          if self._deadline_until(self.is_dead, kill_wait):
            alive = False
            logger.debug('successfully terminated pid {}'.format(pid))
            break
        except self.Timeout:
          # Loop to the next kill signal on timeout.
          pass

    if alive:
      raise self.NonResponsiveProcess('failed to kill pid {pid} with signals {chain}'
                                      .format(pid=self.pid, chain=signal_chain))

    if purge:
      self.purge_metadata(force=True)

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
    self.purge_metadata()
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
    else:
      # This prevents un-reaped, throw-away parent processes from lingering in the process table.
      os.waitpid(pid, 0)

  def daemon_spawn(self, pre_fork_opts=None, post_fork_parent_opts=None, post_fork_child_opts=None):
    """Perform a single-fork to run a subprocess and write the child pid file.

    Use this if your post_fork_child block invokes a subprocess via subprocess.Popen(). In this
    case, a second fork such as used in daemonize() is extraneous given that Popen() also forks.
    Using this daemonization method vs daemonize() leaves the responsibility of writing the pid
    to the caller to allow for library-agnostic flexibility in subprocess execution.
    """
    self.purge_metadata()
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
