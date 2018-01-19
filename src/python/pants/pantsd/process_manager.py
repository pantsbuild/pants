# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import signal
import time
import traceback
from contextlib import contextmanager

import psutil

from pants.base.build_environment import get_buildroot
from pants.init.subprocess import Subprocess
from pants.process.lock import OwnerPrintingInterProcessFileLock
from pants.util.dirutil import read_file, rm_rf, safe_file_dump, safe_mkdir
from pants.util.memo import memoized_property
from pants.util.process_handler import subprocess


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

  def __init__(self, name, metadata_base_dir=None):
    self._name = name
    self._metadata_base_dir = metadata_base_dir

  def _instance_from_process(self, process):
    """Default converter from psutil.Process to process instance classes for subclassing."""
    return ProcessManager(name=process.name(),
                          pid=process.pid,
                          process_name=process.name(),
                          metadata_base_dir=self._metadata_base_dir)

  def iter_processes(self, proc_filter=None):
    """Yields processes from psutil.process_iter with an optional filter and swallows psutil errors.

    If a psutil exception is raised during execution of the filter, that process will not be
    yielded but subsequent processes will. On the other hand, if psutil.process_iter raises
    an exception, no more processes will be yielded.
    """
    with swallow_psutil_exceptions():  # process_iter may raise
      for proc in psutil.process_iter():
        with swallow_psutil_exceptions():  # proc_filter may raise
          if (proc_filter is None) or proc_filter(proc):
            yield proc

  def iter_instances(self, *args, **kwargs):
    for item in self.iter_processes(*args, **kwargs):
      yield self._instance_from_process(item)


class ProcessMetadataManager(object):
  """"Manages contextual, on-disk process metadata."""

  class MetadataError(Exception): pass
  class Timeout(Exception): pass

  FAIL_WAIT_SEC = 10
  INFO_INTERVAL_SEC = 5
  WAIT_INTERVAL_SEC = .1

  def __init__(self, metadata_base_dir=None):
    """
    :param str metadata_base_dir: The base directory for process metadata.
    """
    super(ProcessMetadataManager, self).__init__()

    self._metadata_base_dir = (
      metadata_base_dir or
      Subprocess.Factory.global_instance().create().get_subprocess_dir()
    )

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
  def _deadline_until(cls, closure, action_msg, timeout=FAIL_WAIT_SEC,
                      wait_interval=WAIT_INTERVAL_SEC, info_interval=INFO_INTERVAL_SEC):
    """Execute a function/closure repeatedly until a True condition or timeout is met.

    :param func closure: the function/closure to execute (should not block for long periods of time
                         and must return True on success).
    :param str action_msg: a description of the action that is being executed, to be rendered as
                           info while we wait, and as part of any rendered exception.
    :param float timeout: the maximum amount of time to wait for a true result from the closure in
                          seconds. N.B. this is timing based, so won't be exact if the runtime of
                          the closure exceeds the timeout.
    :param float wait_interval: the amount of time to sleep between closure invocations.
    :param float info_interval: the amount of time to wait before and between reports via info
                                logging that we're still waiting for the closure to succeed.
    :raises: :class:`ProcessManager.Timeout` on execution timeout.
    """
    now = time.time()
    deadline = now + timeout
    info_deadline = now + info_interval
    while 1:
      if closure():
        return True

      now = time.time()
      if now > deadline:
        raise cls.Timeout('exceeded timeout of {} seconds while waiting for {}'.format(timeout, action_msg))

      if now > info_deadline:
        logger.info('waiting for {}...'.format(action_msg))
        info_deadline = info_deadline + info_interval
      elif wait_interval:
        time.sleep(wait_interval)

  @classmethod
  def _wait_for_file(cls, filename, timeout=FAIL_WAIT_SEC, want_content=True):
    """Wait up to timeout seconds for filename to appear with a non-zero size or raise Timeout()."""
    def file_waiter():
      return os.path.exists(filename) and (not want_content or os.path.getsize(filename))

    action_msg = 'file {} to appear'.format(filename)
    return cls._deadline_until(file_waiter, action_msg, timeout=timeout)

  def _get_metadata_dir_by_name(self, name):
    """Retrieve the metadata dir by name.

    This should always live outside of the workdir to survive a clean-all.
    """
    return os.path.join(self._metadata_base_dir, name)

  def _maybe_init_metadata_dir_by_name(self, name):
    """Initialize the metadata directory for a named identity if it doesn't exist."""
    safe_mkdir(self._get_metadata_dir_by_name(name))

  def read_metadata_by_name(self, name, metadata_key, caster=None):
    """Read process metadata using a named identity.

    :param string name: The ProcessMetadataManager identity/name (e.g. 'pantsd').
    :param string metadata_key: The metadata key (e.g. 'pid').
    :param func caster: A casting callable to apply to the read value (e.g. `int`).
    """
    try:
      file_path = os.path.join(self._get_metadata_dir_by_name(name), metadata_key)
      return self._maybe_cast(read_file(file_path).strip(), caster)
    except (IOError, OSError):
      return None

  def write_metadata_by_name(self, name, metadata_key, metadata_value):
    """Write process metadata using a named identity.

    :param string name: The ProcessMetadataManager identity/name (e.g. 'pantsd').
    :param string metadata_key: The metadata key (e.g. 'pid').
    :param string metadata_value: The metadata value (e.g. '1729').
    """
    self._maybe_init_metadata_dir_by_name(name)
    file_path = os.path.join(self._get_metadata_dir_by_name(name), metadata_key)
    safe_file_dump(file_path, metadata_value)

  def await_metadata_by_name(self, name, metadata_key, timeout, caster=None):
    """Block up to a timeout for process metadata to arrive on disk.

    :param string name: The ProcessMetadataManager identity/name (e.g. 'pantsd').
    :param string metadata_key: The metadata key (e.g. 'pid').
    :param int timeout: The deadline to write metadata.
    :param type caster: A type-casting callable to apply to the read value (e.g. int, str).
    :returns: The value of the metadata key (read from disk post-write).
    :raises: :class:`ProcessMetadataManager.Timeout` on timeout.
    """
    file_path = os.path.join(self._get_metadata_dir_by_name(name), metadata_key)
    self._wait_for_file(file_path, timeout=timeout)
    return self.read_metadata_by_name(name, metadata_key, caster)

  def purge_metadata_by_name(self, name):
    """Purge a processes metadata directory.

    :raises: `ProcessManager.MetadataError` when OSError is encountered on metadata dir removal.
    """
    meta_dir = self._get_metadata_dir_by_name(name)
    logger.debug('purging metadata directory: {}'.format(meta_dir))
    try:
      rm_rf(meta_dir)
    except OSError as e:
      raise self.MetadataError('failed to purge metadata directory {}: {!r}'.format(meta_dir, e))


class ProcessManager(ProcessMetadataManager):
  """Subprocess/daemon management mixin/superclass. Not intended to be thread-safe."""

  class InvalidCommandOutput(Exception): pass
  class NonResponsiveProcess(Exception): pass
  class ExecutionError(Exception):
    def __init__(self, message, output=None):
      super(ProcessManager.ExecutionError, self).__init__(message)
      self.message = message
      self.output = output

    def __repr__(self):
      return '{}(message={!r}, output={!r})'.format(type(self).__name__, self.message, self.output)

  KILL_WAIT_SEC = 5
  KILL_CHAIN = (signal.SIGTERM, signal.SIGKILL)

  def __init__(self, name, pid=None, socket=None, process_name=None, socket_type=int,
               metadata_base_dir=None):
    """
    :param string name: The process identity/name (e.g. 'pantsd' or 'ng_Zinc').
    :param int pid: The process pid. Overrides fetching of the self.pid @property.
    :param string socket: The socket metadata. Overrides fetching of the self.socket @property.
    :param string process_name: The process name for cmdline executable name matching.
    :param type socket_type: The type to be used for socket type casting (e.g. int).
    :param str metadata_base_dir: The overridden base directory for process metadata.
    """
    super(ProcessManager, self).__init__(metadata_base_dir)
    self._name = name.lower().strip()
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

  @memoized_property
  def process_lock(self):
    """An identity-keyed inter-process lock for safeguarding lifecycle and other operations."""
    safe_mkdir(self._metadata_base_dir)
    return OwnerPrintingInterProcessFileLock(
      # N.B. This lock can't key into the actual named metadata dir (e.g. `.pids/pantsd/lock`
      # via `ProcessMetadataManager._get_metadata_dir_by_name()`) because of a need to purge
      # the named metadata dir on startup to avoid stale metadata reads.
      os.path.join(self._metadata_base_dir, '.lock.{}'.format(self._name))
    )

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
  def get_subprocess_output(cls, command, ignore_stderr=True, **kwargs):
    """Get the output of an executed command.

    :param command: An iterable representing the command to execute (e.g. ['ls', '-al']).
    :param ignore_stderr: Whether or not to ignore stderr output vs interleave it with stdout.
    :raises: `ProcessManager.ExecutionError` on `OSError` or `CalledProcessError`.
    :returns: The output of the command.
    """
    if ignore_stderr is False:
      kwargs.setdefault('stderr', subprocess.STDOUT)

    try:
      return subprocess.check_output(command, **kwargs)
    except (OSError, subprocess.CalledProcessError) as e:
      subprocess_output = getattr(e, 'output', '').strip()
      raise cls.ExecutionError(str(e), subprocess_output)

  def await_pid(self, timeout):
    """Wait up to a given timeout for a process to write pid metadata."""
    return self.await_metadata_by_name(self._name, 'pid', timeout, int)

  def await_socket(self, timeout):
    """Wait up to a given timeout for a process to write socket info."""
    return self.await_metadata_by_name(self._name, 'socket', timeout, self._socket_type)

  def write_pid(self, pid=None):
    """Write the current processes PID to the pidfile location"""
    pid = pid or os.getpid()
    self.write_metadata_by_name(self._name, 'pid', str(pid))

  def write_socket(self, socket_info):
    """Write the local processes socket information (TCP port or UNIX socket)."""
    self.write_metadata_by_name(self._name, 'socket', str(socket_info))

  def write_named_socket(self, socket_name, socket_info):
    """A multi-tenant, named alternative to ProcessManager.write_socket()."""
    self.write_metadata_by_name(self._name, 'socket_{}'.format(socket_name), str(socket_info))

  def read_named_socket(self, socket_name, socket_type):
    """A multi-tenant, named alternative to ProcessManager.socket."""
    return self.read_metadata_by_name(self._name, 'socket_{}'.format(socket_name), socket_type)

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

  def is_alive(self, extended_check=None):
    """Return a boolean indicating whether the process is running or not.

    :param func extended_check: An additional callable that will be invoked to perform an extended
                                liveness check. This callable should take a single argument of a
                                `psutil.Process` instance representing the context-local process
                                and return a boolean True/False to indicate alive vs not alive.
    """
    try:
      process = self._as_process()
      return not (
        # Can happen if we don't find our pid.
        (not process) or
        # Check for walkers.
        (process.status() == psutil.STATUS_ZOMBIE) or
        # Check for stale pids.
        (self.process_name and self.process_name != process.name()) or
        # Extended checking.
        (extended_check and not extended_check(process))
      )
    except (psutil.NoSuchProcess, psutil.AccessDenied):
      # On some platforms, accessing attributes of a zombie'd Process results in NoSuchProcess.
      return False

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
      logger.debug('terminating {}'.format(self._name))
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
          if self._deadline_until(self.is_dead, 'daemon to exit', timeout=kill_wait):
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
    logger.debug('forking %s', self)
    pid = os.fork()
    if pid == 0:
      os.setsid()
      second_pid = os.fork()
      if second_pid == 0:
        try:
          os.chdir(self._buildroot)
          self.post_fork_child(**post_fork_child_opts or {})
        except Exception:
          logger.critical(traceback.format_exc())
        finally:
          os._exit(0)
      else:
        try:
          if write_pid: self.write_pid(second_pid)
          self.post_fork_parent(**post_fork_parent_opts or {})
        except Exception:
          logger.critical(traceback.format_exc())
        finally:
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
        logger.critical(traceback.format_exc())
      finally:
        os._exit(0)
    else:
      try:
        self.post_fork_parent(**post_fork_parent_opts or {})
      except Exception:
        logger.critical(traceback.format_exc())

  def pre_fork(self):
    """Pre-fork callback for subclasses."""

  def post_fork_child(self):
    """Pre-fork child callback for subclasses."""

  def post_fork_parent(self):
    """Post-fork parent callback for subclasses."""


class FingerprintedProcessManager(ProcessManager):
  """A `ProcessManager` subclass that provides a general strategy for process fingerprinting."""

  FINGERPRINT_KEY = 'fingerprint'
  FINGERPRINT_CMD_KEY = None
  FINGERPRINT_CMD_SEP = '='

  @property
  def fingerprint(self):
    """The fingerprint of the current process.

    This can either read the current fingerprint from the running process's psutil.Process.cmdline
    (if the managed process supports that) or from the `ProcessManager` metadata.

    :returns: The fingerprint of the running process as read from the process table, ProcessManager
              metadata or `None`.
    :rtype: string
    """
    return (
      self.parse_fingerprint(self.cmdline) or
      self.read_metadata_by_name(self.name, self.FINGERPRINT_KEY)
    )

  def parse_fingerprint(self, cmdline, key=None, sep=None):
    """Given a psutil.Process.cmdline, parse and return a fingerprint.

    :param list cmdline: The psutil.Process.cmdline of the current process.
    :param string key: The key for fingerprint discovery.
    :param string sep: The key/value separator for fingerprint discovery.
    :returns: The parsed fingerprint or `None`.
    :rtype: string or `None`
    """
    key = key or self.FINGERPRINT_CMD_KEY
    if key:
      sep = sep or self.FINGERPRINT_CMD_SEP
      cmdline = cmdline or []
      for cmd_part in cmdline:
        if cmd_part.startswith('{}{}'.format(key, sep)):
          return cmd_part.split(sep)[1]

  def has_current_fingerprint(self, fingerprint):
    """Determines if a new fingerprint is the current fingerprint of the running process.

    :param string fingerprint: The new fingerprint to compare to.
    :rtype: bool
    """
    return fingerprint == self.fingerprint

  def needs_restart(self, fingerprint):
    """Determines if the current ProcessManager needs to be started or restarted.

    :param string fingerprint: The new fingerprint to compare to.
    :rtype: bool
    """
    return self.is_dead() or not self.has_current_fingerprint(fingerprint)
