# ==================================================================================================
# Copyright 2011 Twitter, Inc.
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

__author__ = 'John Sirois'

import os
import re
import subprocess
import sys
import time

from twitter.common import log
from twitter.common.dirutil import safe_open
from twitter.pants import get_buildroot
from twitter.pants.java import NailgunClient, NailgunError
from twitter.pants.tasks import Task

def _check_pid(pid):
  try:
    os.kill(pid, 0)
    return True
  except OSError:
    return False


class _safe_open(object):
  def __init__(self, path, *args, **kwargs):
    self._path = path
    self._args = args
    self._kwargs = kwargs


  def __enter__(self):
    self._file = safe_open(self._path, *self._args, **self._kwargs)
    return self._file


  def __exit__(self, exctype, value, traceback):
    self._file.close()


class NailgunTask(Task):
  # Used to identify we own a given java nailgun server
  PANTS_NG_ARG_PREFIX = '-Dtwitter.pants.buildroot'
  PANTS_NG_ARG = '%s=%s' % (PANTS_NG_ARG_PREFIX, get_buildroot())

  @staticmethod
  def log_kill(log, pid, port=None):
    log.info('killing ng server @ pid:%d%s' % (pid, ' port:%d' % port if port else ''))

  def __init__(self, context, classpath=None, workdir=None, nailgun_jar=None, args=None,
               stdin=None, stderr=sys.stderr, stdout=sys.stdout):
    Task.__init__(self, context)

    self._classpath = classpath
    self._nailgun_jar = nailgun_jar or context.config.get('nailgun', 'jar')
    self._ng_server_args = args or context.config.getlist('nailgun', 'args')
    self._stdin = stdin
    self._stderr = stderr
    self._stdout = stdout

    workdir = workdir or context.config.get('nailgun', 'workdir')
    self._pidfile = os.path.join(workdir, 'pid')
    self._ng_out = os.path.join(workdir, 'stdout')
    self._ng_err = os.path.join(workdir, 'stderr')

  def ng(self, main_class, *args, **environment):
    nailgun = self._get_nailgun_client()
    try:
      if self._classpath:
        nailgun('ng-cp', *[os.path.relpath(jar, get_buildroot()) for jar in self._classpath])
      return nailgun(main_class, *args, **environment)
    except NailgunError as e:
      self.ng_shutdown()
      raise e

  def ng_shutdown(self):
    endpoint = self._get_nailgun_endpoint()
    if endpoint:
      pid, port = endpoint
      NailgunTask.log_kill(self.context.log, pid, port)
      try:
        os.kill(pid, 9)
      except OSError:
        pass
      finally:
        os.remove(self._pidfile)

  def _get_nailgun_endpoint(self):
    if os.path.exists(self._pidfile):
      with _safe_open(self._pidfile, 'r') as pidfile:
        contents = pidfile.read()
        def invalid_pidfile():
          log.warn('Invalid ng pidfile %s contained: %s' % (self._pidfile, contents))
          return None
        endpoint = contents.split(':')
        if len(endpoint) != 2:
          return invalid_pidfile()
        pid, port = endpoint
        try:
          return int(pid), int(port)
        except ValueError:
          return invalid_pidfile()
    return None

  def _get_nailgun_client(self):
    endpoint = self._get_nailgun_endpoint()
    if endpoint and _check_pid(endpoint[0]):
      return self._create_ngclient(port=endpoint[1])
    else:
      return self._spawn_nailgun_server()

  # 'NGServer started on 127.0.0.1, port 53785.'
  _PARSE_NG_PORT = re.compile('.*\s+port\s+(\d+)\.$')

  def _parse_nailgun_port(self, line):
    match = NailgunTask._PARSE_NG_PORT.match(line)
    if not match:
      raise NailgunError('Failed to determine spawned ng port from response line: %s' % line)
    return int(match.group(1))

  def _await_nailgun_server(self):
      nailgun = None
      with _safe_open(self._ng_out, 'r') as ng_out:
        while True:
          started = ng_out.readline()
          if started:
            port = self._parse_nailgun_port(started)
            with open(self._pidfile, 'a') as pidfile:
              pidfile.write(':%d' % port)
            nailgun = self._create_ngclient(port)
            log.debug('Detected ng server up on port %d' % port)
            break

      attempt = 0
      while True:
        sock = nailgun.try_connect()
        if sock:
          sock.close()
          log.info('Connected to ng server pid: %d @ port: %d' % self._get_nailgun_endpoint())
          return nailgun
        attempt += 1
        log.debug('Failed to connect on attempt %d' % attempt)
        time.sleep(0.1)

  def _create_ngclient(self, port):
    return NailgunClient(port=port, work_dir=get_buildroot(), ins=self._stdin, out=self._stdout,
                         err=self._stderr)

  def _spawn_nailgun_server(self):
    log.info('No ng server found, spawning...')

    with _safe_open(self._ng_out, 'w'):
      pass # truncate

    pid = os.fork()
    if pid != 0:
      # In the parent tine - block on ng being up for connections
      return self._await_nailgun_server()

    os.setsid()
    in_fd = open('/dev/null', 'w')
    out_fd = safe_open(self._ng_out, 'w')
    err_fd = safe_open(self._ng_err, 'w')

    args = ['java']
    if self._ng_server_args:
      args.extend(self._ng_server_args)
    args.append(NailgunTask.PANTS_NG_ARG)
    args.append('-Dpidfile=%s' % os.path.relpath(self._pidfile, get_buildroot()))
    args.extend(['-jar', self._nailgun_jar, ':0'])
    log.debug('Executing: %s' % ' '.join(args))

    process = subprocess.Popen(
      args,
      stdin=in_fd,
      stdout=out_fd,
      stderr=err_fd,
      close_fds=True,
      cwd=get_buildroot()
    )
    with _safe_open(self._pidfile, 'w') as pidfile:
      pidfile.write('%d' % process.pid)
    log.debug('Spawned ng server @ %d' % process.pid)
    sys.exit(0)

try:
  import psutil

  def killall(log, everywhere=False):
    def cmdline_matches(cmdline):
      if everywhere:
        return any(filter(lambda arg: arg.startswith(NailgunTask.PANTS_NG_ARG_PREFIX), cmdline))
      else:
        return NailgunTask.PANTS_NG_ARG in cmdline

    for proc in psutil.process_iter():
      try:
        if 'java' == proc.name and cmdline_matches(proc.cmdline):
          NailgunTask.log_kill(log, proc.pid)
          proc.kill()
      except psutil.AccessDenied, psutil.NoSuchProcess:
        pass

  NailgunTask.killall = staticmethod(killall)
except ImportError:
  NailgunTask.killall = None