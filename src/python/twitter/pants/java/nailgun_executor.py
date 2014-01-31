# ==================================================================================================
# Copyright 2013 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

from collections import namedtuple

import hashlib
import os
import re
import sys
import time

from twitter.common import log
from twitter.common.collections import maybe_list
from twitter.common.dirutil import safe_open
from twitter.common.lang import Compatibility

from twitter.pants import get_buildroot

from .executor import Executor, SubprocessExecutor

from . import NailgunClient


class NailgunExecutor(Executor):
  """Executes java programs by launching them in nailgun server.

  If a nailgun is not available for a given set of jvm args and classpath, one is launched and
  re-used for the given jvm args and classpath on subsequent runs.
  """

  class Endpoint(namedtuple('Endpoint', ['fingerprint', 'pid', 'port'])):
    """The coordinates for a nailgun server controlled by NailgunExecutor."""

    @classmethod
    def parse(cls, endpoint):
      """Parses an endpoint from a string of the form fingerprint:pid:port"""
      components = endpoint.split(':')
      if len(components) != 3:
        raise ValueError('Invalid endpoint spec %s' % endpoint)
      fingerprint, pid, port = components
      return cls(fingerprint, int(pid), int(port))

  # Used to identify we own a given java nailgun server
  PANTS_NG_ARG_PREFIX = '-Dtwitter.pants.buildroot'
  PANTS_NG_ARG = '%s=%s' % (PANTS_NG_ARG_PREFIX, get_buildroot())

  _PANTS_FINGERPRINT_ARG_PREFIX = '-Dfingerprint='

  @staticmethod
  def _check_pid(pid):
    try:
      os.kill(pid, 0)
      return True
    except OSError:
      return False

  @staticmethod
  def create_pidfile_arg(pidfile):
    return '-Dpidfile=%s' % os.path.relpath(pidfile, get_buildroot())

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
  def _fingerprint(jvm_args, classpath):
    digest = hashlib.sha1()
    digest.update(''.join(sorted(jvm_args)))
    digest.update(''.join(sorted(classpath)))  # TODO(John Sirois): hash classpath contents?
    return digest.hexdigest()

  @staticmethod
  def _log_kill(pid, port=None, logger=None):
    logger = logger or log.info
    logger('killing ng server @ pid:%d%s' % (pid, ' port:%d' % port if port else ''))

  def __init__(self, workdir, nailgun_classpath, distribution=None, ins=None):
    super(NailgunExecutor, self).__init__(distribution=distribution)

    self._nailgun_classpath = maybe_list(nailgun_classpath)

    if not isinstance(workdir, Compatibility.string):
      raise ValueError('Workdir must be a path string, given %s' % workdir)

    self._pidfile = os.path.join(workdir, 'pid')
    self._ng_out = os.path.join(workdir, 'stdout')
    self._ng_err = os.path.join(workdir, 'stderr')

    self._ins = ins

  def _runner(self, classpath, main, jvm_options, args):
    command = self._create_command(classpath, main, jvm_options, args)

    class Runner(self.Runner):
      @property
      def executor(this):
        return self

      @property
      def cmd(this):
        return ' '.join(command)

      def run(this, stdout=sys.stdout, stderr=sys.stderr):
        nailgun = self._get_nailgun_client(jvm_options, classpath, stdout, stderr)
        try:
          log.debug('Executing via %s: %s' % (nailgun, this.cmd))
          return nailgun(main, *args)
        except nailgun.NailgunError as e:
          self.kill()
          raise self.Error('Problem launching via %s command %s %s: %s'
                           % (nailgun, main, ' '.join(args), e))

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
      finally:
        os.remove(self._pidfile)

  def _get_nailgun_endpoint(self):
    if os.path.exists(self._pidfile):
      with safe_open(self._pidfile, 'r') as pidfile:
        contents = pidfile.read().strip()
        try:
          return self.Endpoint.parse(contents)
        except ValueError:
          log.warn('Invalid ng pidfile %s contained: %s' % (self._pidfile, contents))
          return None
    elif self._find:
      endpoint = self._find(self._pidfile)
      if endpoint:
        log.info('found ng server with fingerprint %s @ pid:%d port:%d' % endpoint)
        with safe_open(self._pidfile, 'w') as pidfile:
          pidfile.write('%s:%d:%d\n' % endpoint)
      return endpoint
    return None

  def _get_nailgun_client(self, jvm_args, classpath, stdout, stderr):
    classpath = self._nailgun_classpath + classpath
    new_fingerprint = self._fingerprint(jvm_args, classpath)

    endpoint = self._get_nailgun_endpoint()
    running = endpoint and self._check_pid(endpoint.pid)
    updated = endpoint and endpoint.fingerprint != new_fingerprint
    if running and not updated:
      return self._create_ngclient(endpoint.port, stdout, stderr)
    else:
      if running and updated:
        self.kill()
      return self._spawn_nailgun_server(new_fingerprint, jvm_args, classpath, stdout, stderr)

  # 'NGServer started on 127.0.0.1, port 53785.'
  _PARSE_NG_PORT = re.compile('.*\s+port\s+(\d+)\.$')

  def _parse_nailgun_port(self, line):
    match = self._PARSE_NG_PORT.match(line)
    if not match:
      raise NailgunClient.NailgunError('Failed to determine spawned ng port from response'
                                       ' line: %s' % line)
    return int(match.group(1))

  def _await_nailgun_server(self, stdout, stderr):
    nailgun_timeout_seconds = 5
    max_socket_connect_attempts = 10
    nailgun = None
    port_parse_start = time.time()
    with safe_open(self._ng_out, 'r') as ng_out:
      while not nailgun:
        started = ng_out.readline()
        if started:
          port = self._parse_nailgun_port(started)
          with open(self._pidfile, 'a') as pidfile:
            pidfile.write(':%d\n' % port)
          nailgun = self._create_ngclient(port, stdout, stderr)
          log.debug('Detected ng server up on port %d' % port)
        elif time.time() - port_parse_start > nailgun_timeout_seconds:
          raise NailgunClient.NailgunError('Failed to read ng output after'
                                           ' %s seconds' % nailgun_timeout_seconds)

    attempt = 0
    while nailgun:
      sock = nailgun.try_connect()
      if sock:
        sock.close()
        log.info('Connected to ng server with fingerprint'
                 ' %s pid: %d @ port: %d' % self._get_nailgun_endpoint())
        return nailgun
      elif attempt > max_socket_connect_attempts:
        raise nailgun.NailgunError('Failed to connect to ng output after %d connect attempts'
                                   % max_socket_connect_attempts)
      attempt += 1
      log.debug('Failed to connect on attempt %d' % attempt)
      time.sleep(0.1)

  def _create_ngclient(self, port, stdout, stderr):
    return NailgunClient(port=port, ins=self._ins, out=stdout, err=stderr, work_dir=get_buildroot())

  def _spawn_nailgun_server(self, fingerprint, jvm_args, classpath, stdout, stderr):
    log.info('No ng server found with fingerprint %s, spawning...' % fingerprint)

    with safe_open(self._ng_out, 'w'):
      pass  # truncate

    pid = os.fork()
    if pid != 0:
      # In the parent tine - block on ng being up for connections
      return self._await_nailgun_server(stdout, stderr)

    os.setsid()
    in_fd = open('/dev/null', 'r')
    out_fd = safe_open(self._ng_out, 'w')
    err_fd = safe_open(self._ng_err, 'w')

    java = SubprocessExecutor(self._distribution)

    jvm_args = jvm_args + [self.PANTS_NG_ARG,
                           self.create_pidfile_arg(self._pidfile),
                           self._create_fingerprint_arg(fingerprint)]

    process = java.spawn(classpath=classpath,
                         main='com.martiansoftware.nailgun.NGServer',
                         jvm_options=jvm_args,
                         args=[':0'],
                         stdin=in_fd,
                         stdout=out_fd,
                         stderr=err_fd,
                         close_fds=True,
                         cwd=get_buildroot())

    with safe_open(self._pidfile, 'w') as pidfile:
      pidfile.write('%s:%d' % (fingerprint, process.pid))
    log.debug('Spawned ng server with fingerprint %s @ %d' % (fingerprint, process.pid))
    # Prevents finally blocks and atexit handlers from being executed, unlike sys.exit(). We
    # don't want to execute finally blocks because we might, e.g., clean up tempfiles that the
    # parent still needs.
    os._exit(0)

  def __str__(self):
    return 'NailgunExecutor(%s, server=%s)' % (self._distribution, self._get_nailgun_endpoint())


try:
  import psutil

  def _find_ngs(everywhere=False):
    def cmdline_matches(cmdline):
      if everywhere:
        return any(filter(lambda arg: arg.startswith(NailgunExecutor.PANTS_NG_ARG_PREFIX), cmdline))
      else:
        return NailgunExecutor.PANTS_NG_ARG in cmdline

    for proc in psutil.process_iter():
      try:
        if 'java' == proc.name and cmdline_matches(proc.cmdline):
          yield proc
      except (psutil.AccessDenied, psutil.NoSuchProcess):
        pass

  def killall(logger=None, everywhere=False):
    success = True
    for proc in _find_ngs(everywhere=everywhere):
      try:
        NailgunExecutor._log_kill(proc.pid, logger=logger)
        proc.kill()
      except (psutil.AccessDenied, psutil.NoSuchProcess):
        success = False
    return success

  NailgunExecutor.killall = staticmethod(killall)

  def _find_ng_listen_port(proc):
    for connection in proc.get_connections(kind='tcp'):
      if connection.status == 'LISTEN':
        host, port = connection.laddr
        return port
    return None

  def _find(pidfile):
    pidfile_arg = NailgunExecutor.create_pidfile_arg(pidfile)
    for proc in _find_ngs(everywhere=False):
      try:
        if pidfile_arg in proc.cmdline:
          fingerprint = NailgunExecutor.parse_fingerprint_arg(proc.cmdline)
          port = _find_ng_listen_port(proc)
          if fingerprint and port:
            return NailgunExecutor.Endpoint(fingerprint, proc.pid, port)
      except (psutil.AccessDenied, psutil.NoSuchProcess):
        pass
    return None

  NailgunExecutor._find = staticmethod(_find)
except ImportError:
  NailgunExecutor.killall = None
  NailgunExecutor._find = None
