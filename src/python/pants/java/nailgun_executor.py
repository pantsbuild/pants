# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import logging
import os
import re
import time
from collections import namedtuple

import psutil
from six import string_types
from twitter.common.collections import maybe_list

from pants.base.build_environment import get_buildroot
from pants.java.executor import Executor, SubprocessExecutor
from pants.java.nailgun_client import NailgunClient
from pants.util.dirutil import safe_open


logger = logging.getLogger(__name__)


# TODO: Once we integrate standard logging into our reporting framework, we  can consider making
#  some of the log.debug() below into log.info(). Right now it just looks wrong on the console.


class NailgunExecutor(Executor):
  """Executes java programs by launching them in nailgun server.

  If a nailgun is not available for a given set of jvm args and classpath, one is launched and
  re-used for the given jvm args and classpath on subsequent runs.
  """

  class Endpoint(namedtuple('Endpoint', ['exe', 'fingerprint', 'pid', 'port'])):
    """The coordinates for a nailgun server controlled by NailgunExecutor."""

    @classmethod
    def parse(cls, endpoint):
      """Parses an endpoint from a string of the form exe:fingerprint:pid:port"""
      components = endpoint.split(':')
      if len(components) != 4:
        raise ValueError('Invalid endpoint spec {}'.format(endpoint))
      exe, fingerprint, pid, port = components
      return cls(exe, fingerprint, int(pid), int(port))

  # Used to identify we own a given java nailgun server
  _PANTS_NG_ARG_PREFIX = b'-Dpants.buildroot'
  _PANTS_NG_ARG = b'{0}={1}'.format(_PANTS_NG_ARG_PREFIX, get_buildroot())

  _PANTS_FINGERPRINT_ARG_PREFIX = b'-Dpants.nailgun.fingerprint='

  @staticmethod
  def _check_pid(pid):
    try:
      os.kill(pid, 0)
      return True
    except OSError:
      return False

  @staticmethod
  def create_owner_arg(workdir):
    # Currently the owner is identified via the full path to the workdir.
    return b'-Dpants.nailgun.owner={0}'.format(workdir)

  @classmethod
  def _create_fingerprint_arg(cls, fingerprint):
    return cls._PANTS_FINGERPRINT_ARG_PREFIX + fingerprint

  @classmethod
  def parse_fingerprint_arg(cls, args):
    for arg in args:
      components = arg.split(cls._PANTS_FINGERPRINT_ARG_PREFIX)
      if len(components) == 2 and components[0] == '':
        return components[1]
    return None

  @staticmethod
  def _fingerprint(jvm_options, classpath, java_version):
    """Compute a fingerprint for this invocation of a Java task.

    :param list jvm_options: JVM options passed to the java invocation
    :param list classpath: The -cp arguments passed to the java invocation
    :param Revision java_version: return value from Distribution.version()
    :return: a hexstring representing a fingerprint of the java invocation
    """
    digest = hashlib.sha1()
    digest.update(''.join(sorted(jvm_options)))
    digest.update(''.join(sorted(classpath)))  # TODO(John Sirois): hash classpath contents?
    digest.update(repr(java_version))
    return digest.hexdigest()

  @staticmethod
  def _log_kill(pid, port=None):
    port_desc = ' port:{0}'.format(port if port else '')
    logger.info('killing ng server @ pid:{pid}{port}'.format(pid=pid, port=port_desc))

  @classmethod
  def _find_ngs(cls, everywhere=False):
    def cmdline_matches(cmdline):
      if everywhere:
        return any(filter(lambda arg: arg.startswith(cls._PANTS_NG_ARG_PREFIX), cmdline))
      else:
        return cls._PANTS_NG_ARG in cmdline

    for proc in psutil.process_iter():
      try:
        if b'java' == proc.name and cmdline_matches(proc.cmdline):
          yield proc
      except (psutil.AccessDenied, psutil.NoSuchProcess):
        pass

  @classmethod
  def killall(cls, everywhere=False):
    """Kills all nailgun servers started by pants.

    :param bool everywhere: If ``True`` Kills all pants-started nailguns on this machine; otherwise
      restricts the nailguns killed to those started for the current build root.
    """
    success = True
    for proc in cls._find_ngs(everywhere=everywhere):
      try:
        cls._log_kill(proc.pid)
        proc.kill()
      except (psutil.AccessDenied, psutil.NoSuchProcess):
        success = False
    return success

  @staticmethod
  def _find_ng_listen_port(proc):
    for connection in proc.get_connections(kind=b'tcp'):
      if connection.status == b'LISTEN':
        host, port = connection.laddr
        return port
    return None

  @classmethod
  def _find(cls, workdir):
    owner_arg = cls.create_owner_arg(workdir)
    for proc in cls._find_ngs(everywhere=False):
      try:
        if owner_arg in proc.cmdline:
          fingerprint = cls.parse_fingerprint_arg(proc.cmdline)
          port = cls._find_ng_listen_port(proc)
          exe = proc.cmdline[0]
          if fingerprint and port:
            return cls.Endpoint(exe, fingerprint, proc.pid, port)
      except (psutil.AccessDenied, psutil.NoSuchProcess):
        pass
    return None

  def __init__(self, workdir, nailgun_classpath, distribution=None, ins=None):
    super(NailgunExecutor, self).__init__(distribution=distribution)

    self._nailgun_classpath = maybe_list(nailgun_classpath)
    if not isinstance(workdir, string_types):
      raise ValueError('Workdir must be a path string, given {workdir}'.format(workdir=workdir))

    self._workdir = workdir

    self._ng_out = os.path.join(workdir, 'stdout')
    self._ng_err = os.path.join(workdir, 'stderr')

    self._ins = ins

  def _runner(self, classpath, main, jvm_options, args, cwd=None):
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
          self.kill()
          raise self.Error('Problem launching via {ng_desc} command {main} {args}: {msg}'
                           .format(ng_desc=nailgun, main=main, args=' '.join(args), msg=e))

    return Runner()

  def kill(self):
    """Kills the nailgun server owned by this executor if its currently running."""

    endpoint = self._get_nailgun_endpoint()
    if endpoint:
      self._log_kill(endpoint.pid, endpoint.port)
      try:
        os.kill(endpoint.pid, 9)
      except OSError:
        pass

  def _get_nailgun_endpoint(self):
    endpoint = self._find(self._workdir)
    if endpoint:
      logger.debug('Found ng server launched with {endpoint}'.format(endpoint=repr(endpoint)))
    return endpoint

  def _get_nailgun_client(self, jvm_options, classpath, stdout, stderr):
    classpath = self._nailgun_classpath + classpath
    new_fingerprint = self._fingerprint(jvm_options, classpath, self._distribution.version)

    endpoint = self._get_nailgun_endpoint()
    running = endpoint and self._check_pid(endpoint.pid)
    updated = endpoint and endpoint.fingerprint != new_fingerprint
    updated = updated or (endpoint and endpoint.exe != self._distribution.java)
    if running and not updated:
      return self._create_ngclient(endpoint.port, stdout, stderr)
    else:
      if running and updated:
        logger.debug('Killing ng server launched with {endpoint}'.format(endpoint=repr(endpoint)))
        self.kill()
      return self._spawn_nailgun_server(new_fingerprint, jvm_options, classpath, stdout, stderr)

  # 'NGServer started on 127.0.0.1, port 53785.'
  _PARSE_NG_PORT = re.compile('.*\s+port\s+(\d+)\.$')

  def _parse_nailgun_port(self, line):
    match = self._PARSE_NG_PORT.match(line)
    if not match:
      raise NailgunClient.NailgunError('Failed to determine spawned ng port from response'
                                       ' line: {line}'.format(line=line))
    return int(match.group(1))

  def _await_nailgun_server(self, stdout, stderr, debug_desc):
    # TODO(Eric Ayers) Make these cmdline/config parameters once we have a global way to fetch
    # the global options scope.
    nailgun_timeout_seconds = 10
    max_socket_connect_attempts = 5
    nailgun = None
    port_parse_start = time.time()
    with safe_open(self._ng_out, 'r') as ng_out:
      while not nailgun:
        started = ng_out.readline()
        if started.find('Listening for transport dt_socket at address:') >= 0:
          nailgun_timeout_seconds = 60
          logger.warn('Timeout extended to {timeout} seconds for debugger to attach to ng server.'
                      .format(timeout=nailgun_timeout_seconds))
          started = ng_out.readline()
        if started:
          port = self._parse_nailgun_port(started)
          nailgun = self._create_ngclient(port, stdout, stderr)
          logger.debug('Detected ng server up on port {port}'.format(port=port))
        elif time.time() - port_parse_start > nailgun_timeout_seconds:
          raise NailgunClient.NailgunError(
            'Failed to read ng output after {sec} seconds.\n {desc}'
            .format(sec=nailgun_timeout_seconds, desc=debug_desc))

    attempt = 0
    while nailgun:
      sock = nailgun.try_connect()
      if sock:
        sock.close()
        endpoint = self._get_nailgun_endpoint()
        if endpoint:
          logger.debug('Connected to ng server launched with {endpoint}'
                       .format(endpoint=repr(endpoint)))
        else:
          raise NailgunClient.NailgunError('Failed to connect to ng server.')
        return nailgun
      elif attempt > max_socket_connect_attempts:
        raise nailgun.NailgunError('Failed to connect to ng output after {count} connect attempts'
                                   .format(count=max_socket_connect_attempts))
      attempt += 1
      logger.debug('Failed to connect on attempt {count}'.format(count=attempt))
      time.sleep(0.1)

  def _create_ngclient(self, port, stdout, stderr):
    return NailgunClient(port=port, ins=self._ins, out=stdout, err=stderr, workdir=get_buildroot())

  def _spawn_nailgun_server(self, fingerprint, jvm_options, classpath, stdout, stderr):
    logger.debug('No ng server found with fingerprint {fingerprint}, spawning...'
                 .format(fingerprint=fingerprint))

    with safe_open(self._ng_out, 'w'):
      pass  # truncate

    pid = os.fork()
    if pid != 0:
      # In the parent tine - block on ng being up for connections
      return self._await_nailgun_server(stdout, stderr,
                                        'jvm_options={jvm_options} classpath={classpath}'
                                        .format(jvm_options=jvm_options, classpath=classpath))


    os.setsid()
    in_fd = open('/dev/null', 'r')
    out_fd = safe_open(self._ng_out, 'w')
    err_fd = safe_open(self._ng_err, 'w')

    java = SubprocessExecutor(self._distribution)

    jvm_options = jvm_options + [self._PANTS_NG_ARG,
                           self.create_owner_arg(self._workdir),
                           self._create_fingerprint_arg(fingerprint)]

    process = java.spawn(classpath=classpath,
                         main='com.martiansoftware.nailgun.NGServer',
                         jvm_options=jvm_options,
                         args=[':0'],
                         stdin=in_fd,
                         stdout=out_fd,
                         stderr=err_fd,
                         close_fds=True)

    logger.debug('Spawned ng server with fingerprint {fingerprint} @ {pid}'
                 .format(fingerprint=fingerprint, pid=process.pid))
    # Prevents finally blocks and atexit handlers from being executed, unlike sys.exit(). We
    # don't want to execute finally blocks because we might, e.g., clean up tempfiles that the
    # parent still needs.
    os._exit(0)

  def __str__(self):
    return 'NailgunExecutor({dist}, server={endpoint})' \
      .format(dist=self._distribution, endpoint=self._get_nailgun_endpoint())
