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

import StringIO
import os
import re
import signal
import subprocess
import sys
import time

from twitter.common import log
from twitter.common.dirutil import safe_open
from twitter.common.python.platforms import Platform

from twitter.pants import get_buildroot
from twitter.pants.java import NailgunClient, NailgunError
from twitter.pants.tasks import binary_utils, Task

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

  _DAEMON_OPTION_PRESENT = False

  @staticmethod
  def create_pidfile_arg(pidfile):
    return '-Dpidfile=%s' % os.path.relpath(pidfile, get_buildroot())

  @staticmethod
  def _log_kill(log, pid, port=None):
    log.info('killing ng server @ pid:%d%s' % (pid, ' port:%d' % port if port else ''))

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    if not NailgunTask._DAEMON_OPTION_PRESENT:
      option_group.parser.add_option("--ng-daemons", "--no-ng-daemons", dest="nailgun_daemon",
                                     default=True, action="callback", callback=mkflag.set_bool,
                                     help="[%default] Use nailgun daemons to execute java tasks.")
      NailgunTask._DAEMON_OPTION_PRESENT = True

  def __init__(self, context, classpath=None, workdir=None, nailgun_jar=None, args=None,
               stdin=None, stderr=sys.stderr, stdout=sys.stdout):
    Task.__init__(self, context)

    self._classpath = classpath
    self._nailgun_jar = nailgun_jar or context.config.get('nailgun', 'jar')
    self._ng_server_args = args or context.config.getlist('nailgun', 'args')
    self._stdin = stdin
    self._stderr = stderr
    self._stdout = stdout
    self._daemon = context.options.nailgun_daemon

    workdir = workdir or context.config.get('nailgun', 'workdir')
    self._pidfile = os.path.join(workdir, 'pid')
    self._ng_out = os.path.join(workdir, 'stdout')
    self._ng_err = os.path.join(workdir, 'stderr')

  def runjava(self, main, classpath=None, args=None, jvmargs=None):
    """
      Runs the java main using the given classpath and args.  If --no-ng-daemons is specified then
      the java main is run in a freshly spawned subprocess, otherwise a persistent nailgun server
      dedicated to this Task subclass is used to speed up amortized run times.
    """

    cp = (self._classpath or []) + (classpath or [])
    if self._daemon:
      nailgun = self._get_nailgun_client()

      def call_nailgun(main_class, *args):
        if self.dry_run:
          print('********** NailgunClient dry run: %s %s' % (main_class, ' '.join(args)))
          return 0
        else:
          return nailgun(main_class, *args)

      try:
        if cp:
          call_nailgun('ng-cp', *[os.path.relpath(jar, get_buildroot()) for jar in cp])
        return call_nailgun(main, *args)
      except NailgunError as e:
        self._ng_shutdown()
        raise e
    else:
      only_write_cmd_line_to = StringIO.StringIO() if self.dry_run else None
      ret = binary_utils.runjava(main=main, classpath=cp, args=args, jvmargs=jvmargs,
        only_write_cmd_line_to=only_write_cmd_line_to)
      if only_write_cmd_line_to:
        print('********** Direct Java dry run: %s' % only_write_cmd_line_to.getvalue())
        only_write_cmd_line_to.close()
      return ret

  def _ng_shutdown(self):
    endpoint = self._get_nailgun_endpoint()
    if endpoint:
      pid, port = endpoint
      NailgunTask._log_kill(self.context.log, pid, port)
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
          return int(pid.strip()), int(port.strip())
        except ValueError:
          return invalid_pidfile()
    elif NailgunTask._find:
      pid_port = NailgunTask._find(self._pidfile)
      if pid_port:
        self.context.log.info('found ng server @ pid:%d port:%d' % pid_port)
        with safe_open(self._pidfile, 'w') as pidfile:
          pidfile.write('%d:%d\n' % pid_port)
      return pid_port
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
            pidfile.write(':%d\n' % port)
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
    args.append(NailgunTask.create_pidfile_arg(self._pidfile))
    args.extend(['-jar', self._nailgun_jar, ':0'])
    log.debug('Executing: %s' % ' '.join(args))

    with binary_utils.safe_classpath(logger=log.warn):
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


# Pick implementations for killall and _find. We don't use psutil, as it uses
# native code and so is not portable, leading to packaging and deployment headaches.
# TODO: Extract this to a class and add a paired test guarded by
# http://pytest.org/latest/skipping.html#skipping.
plat = Platform.current()
if plat.startswith('linux') or plat.startswith('macosx'):
  # TODO: add other platforms as needed, after checking that these cmds work there as expected.

  # Returns the cmd's output, as a list of lines, including the newline characters.
  def _run_cmd(cmd):
    runcmd = cmd + ' && echo "\n${PIPESTATUS[*]}"'
    popen = subprocess.Popen(runcmd, shell=True, executable='/bin/bash', bufsize=-1, close_fds=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (stdout_data, _) = popen.communicate()
    stdout_data_lines = [line for line in stdout_data.strip().split('\n') if line]
    if not stdout_data_lines:
      raise NailgunError('No output for command (%s)' % runcmd)
    try:
      # Get the return codes of each piped cmd.
      piped_return_codes = [int(x) for x in stdout_data_lines[-1].split(' ') if x]
    except ValueError:
      raise NailgunError('Failed to parse result (%s) for command (%s)' % (stdout_data_lines, cmd))
    # Drop the echoing of PIPESTATUS, which our caller doesn't care about.
    stdout_data_lines = stdout_data_lines[:-1]
    failed = any(piped_return_codes)
    if failed:
      raise NailgunError('Failed to execute cmd: "%s". Exit codes: %s. Output: "%s"' % \
                        (cmd, piped_return_codes, ''.join(stdout_data_lines)))
    return stdout_data_lines

  def _find_matching_pids(strs):
    # Grep all processes whose cmd-lines contain all the strs, except for the grep process itself.
    filters = ' | '.join(["grep -F -e '%s'" % s for s in strs])
    data = _run_cmd("ps axwww | %s | (grep -v grep || true) | cut -b 1-5" % filters)
    pids = [int(x.strip()) for x in data if x]
    return pids

  def _find_ngs(everywhere=False):
    arg = NailgunTask.PANTS_NG_ARG_PREFIX if everywhere else NailgunTask.PANTS_NG_ARG
    return _find_matching_pids([arg])

  def killall(log, everywhere=False):
    for pid in _find_ngs(everywhere=everywhere):
      try:
        NailgunTask._log_kill(log, pid)
        os.kill(pid, signal.SIGKILL)
      except OSError:
        pass

  NailgunTask.killall = staticmethod(killall)

  DIGITS_RE = re.compile('^\d+$')
  def _find(pidfile):
    pidfile_arg = NailgunTask.create_pidfile_arg(pidfile)
    pids = _find_matching_pids([NailgunTask.PANTS_NG_ARG, pidfile_arg])
    if len(pids) != 1:
      return None
    pid = pids[0]

    # Expected output of the lsof cmd: pPID\nn[::127.0.0.1]:PORT
    lines = _run_cmd('lsof -a -p %s -i TCP -s TCP:LISTEN -Fn' % pid)
    if len(lines) != 2 or lines[0] != 'p%s' % pid:
      return None
    port = lines[1][lines[1].rfind(':') + 1:].strip()
    if not DIGITS_RE.match(port):
      return None
    return pid, int(port)

  NailgunTask._find = staticmethod(_find)

else:
  # This is some other platform. In practice, it's likely that the cmds above will work
  # on this platform (pants assumes a UNIX variant), so test that out and modify the
  # condition above appropriately. Note: This is unlikely to be your biggest headache
  # in porting pants to this other platform, since many pants tasks spawn subprocesses
  # for various commands, and none of them have been tested on unsupported platforms.
  NailgunTask.killall = None
  NailgunTask._find = None
