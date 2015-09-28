# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import logging
import os
import re
import select
import threading
import time
from contextlib import closing

from six import string_types
from twitter.common.collections import maybe_list

from pants.base.build_environment import get_buildroot
from pants.java.executor import Executor, SubprocessExecutor
from pants.java.nailgun_client import NailgunClient
from pants.pantsd.process_manager import ProcessGroup, ProcessManager
from pants.util.dirutil import safe_open


logger = logging.getLogger(__name__)


class NailgunProcessGroup(ProcessGroup):
  _NAILGUN_KILL_LOCK = threading.Lock()

  def __init__(self):
    ProcessGroup.__init__(self, name='nailgun')
    # TODO: this should enumerate the .pids dir first, then fallback to ps enumeration (& warn).

  def _iter_nailgun_instances(self, everywhere=False):
    def predicate(proc):
      if proc.name() == NailgunExecutor._PROCESS_NAME:
        if not everywhere:
          return NailgunExecutor._PANTS_NG_ARG in proc.cmdline()
        else:
          return any(arg.startswith(NailgunExecutor._PANTS_NG_ARG_PREFIX) for arg in proc.cmdline())

    return self.iter_instances(predicate)

  def killall(self, everywhere=False):
    """Kills all nailgun servers started by pants.

       :param bool everywhere: If ``True``, kills all pants-started nailguns on this machine;
                               otherwise restricts the nailguns killed to those started for the
                               current build root.
    """
    with self._NAILGUN_KILL_LOCK:
      for proc in self._iter_nailgun_instances(everywhere):
        logger.info('killing nailgun server pid={pid}'.format(pid=proc.pid))
        proc.terminate()


# TODO: Once we integrate standard logging into our reporting framework, we can consider making
# some of the log.debug() below into log.info(). Right now it just looks wrong on the console.
class NailgunExecutor(Executor, ProcessManager):
  """Executes java programs by launching them in nailgun server.

     If a nailgun is not available for a given set of jvm args and classpath, one is launched and
     re-used for the given jvm args and classpath on subsequent runs.
  """

  # 'NGServer 0.9.1 started on 127.0.0.1, port 53785.'
  _NG_PORT_REGEX = re.compile(r'.*\s+port\s+(\d+)\.$')

  # Used to identify if we own a given nailgun server.
  _PANTS_NG_ARG_PREFIX = b'-Dpants.buildroot'
  _PANTS_FINGERPRINT_ARG_PREFIX = b'-Dpants.nailgun.fingerprint'
  _PANTS_OWNER_ARG_PREFIX = b'-Dpants.nailgun.owner'
  _PANTS_NG_ARG = '='.join((_PANTS_NG_ARG_PREFIX, get_buildroot()))

  _NAILGUN_SPAWN_LOCK = threading.Lock()
  _SELECT_WAIT = 1
  _PROCESS_NAME = b'java'

  def __init__(self, identity, workdir, nailgun_classpath, distribution, ins=None,
               connect_timeout=10, connect_attempts=5):
    Executor.__init__(self, distribution=distribution)
    ProcessManager.__init__(self, name=identity, process_name=self._PROCESS_NAME)

    if not isinstance(workdir, string_types):
      raise ValueError('Workdir must be a path string, not: {workdir}'.format(workdir=workdir))

    self._identity = identity
    self._workdir = workdir
    self._ng_stdout = os.path.join(workdir, 'stdout')
    self._ng_stderr = os.path.join(workdir, 'stderr')
    self._nailgun_classpath = maybe_list(nailgun_classpath)
    self._ins = ins
    self._connect_timeout = connect_timeout
    self._connect_attempts = connect_attempts

  def __str__(self):
    return 'NailgunExecutor({identity}, dist={dist}, pid={pid} socket={socket})'.format(
      identity=self._identity, dist=self._distribution, pid=self.pid, socket=self.socket)

  def _parse_fingerprint(self, cmdline):
    fingerprints = [cmd.split('=')[1] for cmd in cmdline if cmd.startswith(
      self._PANTS_FINGERPRINT_ARG_PREFIX + '=')]
    return fingerprints[0] if fingerprints else None

  @property
  def fingerprint(self):
    """This provides the nailgun fingerprint of the running process otherwise None."""
    if self.cmdline:
      return self._parse_fingerprint(self.cmdline)

  def _create_owner_arg(self, workdir):
    # Currently the owner is identified via the full path to the workdir.
    return '='.join((self._PANTS_OWNER_ARG_PREFIX, workdir))

  def _create_fingerprint_arg(self, fingerprint):
    return '='.join((self._PANTS_FINGERPRINT_ARG_PREFIX, fingerprint))

  @staticmethod
  def _fingerprint(jvm_options, classpath, java_version):
    """Compute a fingerprint for this invocation of a Java task.

       :param list jvm_options: JVM options passed to the java invocation
       :param list classpath: The -cp arguments passed to the java invocation
       :param Revision java_version: return value from Distribution.version()
       :return: a hexstring representing a fingerprint of the java invocation
    """
    digest = hashlib.sha1()
    # TODO(John Sirois): hash classpath contents?
    [digest.update(item) for item in (''.join(sorted(jvm_options)),
                                      ''.join(sorted(classpath)),
                                      repr(java_version))]
    return digest.hexdigest()

  def _runner(self, classpath, main, jvm_options, args, cwd=None):
    """Runner factory. Called via Executor.execute()."""
    command = self._create_command(classpath, main, jvm_options, args)

    class Runner(self.Runner):
      @property
      def executor(this):
        return self

      @property
      def command(self):
        return list(command)

      def run(this, stdout=None, stderr=None, cwd=None):
        nailgun = self._get_nailgun_client(jvm_options, classpath, stdout, stderr)
        try:
          logger.debug('Executing via {ng_desc}: {cmd}'.format(ng_desc=nailgun, cmd=this.cmd))
          return nailgun(main, cwd, *args)
        except nailgun.NailgunError as e:
          self.terminate()
          raise self.Error('Problem launching via {ng_desc} command {main} {args}: {msg}'
                           .format(ng_desc=nailgun, main=main, args=' '.join(args), msg=e))

    return Runner()

  def _check_nailgun_state(self, new_fingerprint):
    running = self.is_alive()
    updated = running and (self.fingerprint != new_fingerprint or
                           self.cmd != self._distribution.java)
    logging.debug('Nailgun {nailgun} state: updated={up!s} running={run!s} fingerprint={old_fp} '
                  'new_fingerprint={new_fp} distribution={old_dist} new_distribution={new_dist}'
                  .format(nailgun=self._identity, up=updated, run=running,
                          old_fp=self.fingerprint, new_fp=new_fingerprint,
                          old_dist=self.cmd, new_dist=self._distribution.java))
    return running, updated

  def _get_nailgun_client(self, jvm_options, classpath, stdout, stderr):
    """This (somewhat unfortunately) is the main entrypoint to this class via the Runner. It handles
       creation of the running nailgun server as well as creation of the client."""
    classpath = self._nailgun_classpath + classpath
    new_fingerprint = self._fingerprint(jvm_options, classpath, self._distribution.version)

    with self._NAILGUN_SPAWN_LOCK:
      running, updated = self._check_nailgun_state(new_fingerprint)

      if running and updated:
        logger.debug('Found running nailgun server that needs updating, killing {server}'
                     .format(server=self._identity))
        self.terminate()

      if (not running) or (running and updated):
        return self._spawn_nailgun_server(new_fingerprint, jvm_options, classpath, stdout, stderr)

    return self._create_ngclient(self.socket, stdout, stderr)

  def _await_socket(self, timeout):
    """Blocks for the nailgun subprocess to bind and emit a listening port in the nailgun stdout."""
    with safe_open(self._ng_stdout, 'r') as ng_stdout:
      start_time = time.time()
      while 1:
        readable, _, _ = select.select([ng_stdout], [], [], self._SELECT_WAIT)
        if readable:
          line = ng_stdout.readline()                          # TODO: address deadlock risk here.
          try:
            return self._NG_PORT_REGEX.match(line).group(1)
          except AttributeError:
            pass

        if (time.time() - start_time) > timeout:
          raise NailgunClient.NailgunError(
            'Failed to read nailgun output after {sec} seconds!'.format(sec=timeout))

  def _create_ngclient(self, port, stdout, stderr):
    return NailgunClient(port=port, ins=self._ins, out=stdout, err=stderr, workdir=get_buildroot())

  def ensure_connectable(self, nailgun):
    """Ensures that a nailgun client is connectable or raises NailgunError."""
    attempt_count = 1
    while 1:
      try:
        with closing(nailgun.try_connect()) as sock:
          logger.debug('Verified new ng server is connectable at {}'.format(sock.getpeername()))
          return
      except nailgun.NailgunConnectionError:
        if attempt_count >= self._connect_attempts:
          logger.debug('Failed to connect to ng after {} attempts'.format(self._connect_attempts))
          raise     # Re-raise the NailgunConnectionError which provides more context to the user.

      attempt_count += 1
      time.sleep(self.WAIT_INTERVAL_SEC)

  def _spawn_nailgun_server(self, fingerprint, jvm_options, classpath, stdout, stderr):
    """Synchronously spawn a new nailgun server."""
    # Truncate the nailguns stdout & stderr.
    self._write_file(self._ng_stdout, '')
    self._write_file(self._ng_stderr, '')

    jvm_options = jvm_options + [self._PANTS_NG_ARG,
                                 self._create_owner_arg(self._workdir),
                                 self._create_fingerprint_arg(fingerprint)]

    post_fork_child_opts = dict(fingerprint=fingerprint,
                                jvm_options=jvm_options,
                                classpath=classpath,
                                stdout=stdout,
                                stderr=stderr)

    logger.debug('Spawning nailgun server {i} with fingerprint={f}, jvm_options={j}, classpath={cp}'
                 .format(i=self._identity, f=fingerprint, j=jvm_options, cp=classpath))

    self.daemon_spawn(post_fork_child_opts=post_fork_child_opts)

    # Wait for and write the port information in the parent so we can bail on exception/timeout.
    self.await_pid(self._connect_timeout)
    self.write_socket(self._await_socket(self._connect_timeout))

    logger.debug('Spawned nailgun server {i} with fingerprint={f}, pid={pid} port={port}'
                 .format(i=self._identity, f=fingerprint, pid=self.pid, port=self.socket))

    client = self._create_ngclient(self.socket, stdout, stderr)
    self.ensure_connectable(client)

    return client

  def post_fork_child(self, fingerprint, jvm_options, classpath, stdout, stderr):
    """Post-fork() child callback for ProcessManager.daemon_spawn()."""
    java = SubprocessExecutor(self._distribution)

    subproc = java.spawn(classpath=classpath,
                         main='com.martiansoftware.nailgun.NGServer',
                         jvm_options=jvm_options,
                         args=[':0'],
                         stdin=safe_open('/dev/null', 'r'),
                         stdout=safe_open(self._ng_stdout, 'w'),
                         stderr=safe_open(self._ng_stderr, 'w'),
                         close_fds=True)

    self.write_pid(subproc.pid)
