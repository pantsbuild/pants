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

import os
import re
import signal
import subprocess
import threading
import time

from twitter.common.dirutil import safe_open
from twitter.common.python.platforms import Platform

from twitter.pants import binary_util, get_buildroot
from twitter.pants.base.workunit import WorkUnit
from twitter.pants.java import NailgunClient, NailgunError
from twitter.pants.tasks import Task


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
  # Args to nailgun processes so we can identify them. Not actually used by the nailgun.

  # All nailguns will have this arg prefix.
  PANTS_NG_ARG_PREFIX = '-Dpants.ng.buildroot'

  # Our nailguns will have this arg.
  # Trailing slash prevents grep matching on buildroots whose name contains ours.
  PANTS_NG_ARG = '%s=%s/' % (PANTS_NG_ARG_PREFIX, get_buildroot())

  # We differentiate among our nailguns using self._identifier_arg.

  _DAEMON_OPTION_PRESENT = False

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

  def __init__(self, context, workdir=None):
    Task.__init__(self, context)

    self._nailgun_bootstrap_key = 'nailgun'
    nailgun_bootstrap_tools = context.config.getlist('nailgun', 'bootstrap-tools',
                                                     default=[':nailgun-server'])

    self._jvm_tool_bootstrapper.register_jvm_tool(self._nailgun_bootstrap_key, nailgun_bootstrap_tools)

    self._ng_server_args = context.config.getlist('nailgun', 'args')
    self._daemon = context.options.nailgun_daemon

    workdir = workdir or context.config.get('nailgun', 'workdir')

    # Allows us to identify the nailgun process by its cmd-line.
    self._identifier_arg = '-Dpants.ng.identifier=%s' % os.path.relpath(workdir, get_buildroot())

    self._current_pidport = None

    self._ng_out = os.path.join(workdir, 'stdout')
    self._ng_err = os.path.join(workdir, 'stderr')

    # Prevent concurrency issues when starting up a nailgun.
    self._spawn_lock = threading.Lock()

  def tool_classpath(self, key, java_runner=None):
    return Task.tool_classpath(self, key, java_runner or self.runjava_indivisible)

  def lazy_tool_classpath(self, key, java_runner=None):
    return Task.lazy_tool_classpath(self, key, java_runner or self.runjava_indivisible)

  def _runjava_common(self, runjava, main, classpath=None, args=None, jvm_options=None,
                      workunit_name=None, workunit_labels=None):
    workunit_labels = workunit_labels[:] if workunit_labels else []
    cp = classpath or []
    cmd_str = binary_util.runjava_cmd_str(jvm_options=jvm_options,
                                          classpath=cp,
                                          main=main,
                                          args=args)
    workunit_name = workunit_name or main
    if self._daemon:
      workunit_labels += [WorkUnit.TOOL, WorkUnit.NAILGUN]
      with self.context.new_workunit(name=workunit_name,
                                     labels=workunit_labels,
                                     cmd=cmd_str) as workunit:
        nailgun = self._get_nailgun_client(workunit)

        def call_nailgun(main_class, *args):
          if self.dry_run:
            print('********** NailgunClient dry run: %s' % cmd_str)
            return 0
          else:
            return nailgun(main_class, *args)

        try:
          if cp:
            call_nailgun('ng-cp', *[os.path.relpath(jar, get_buildroot()) for jar in cp])
          ret = call_nailgun(main, *args)
          workunit.set_outcome(WorkUnit.FAILURE if ret else WorkUnit.SUCCESS)
          return ret
        except NailgunError:
          self._ng_shutdown()
          raise
    else:
      def runjava_workunit_factory(name, labels=list(), cmd=''):
        return self.context.new_workunit(name=name, labels=workunit_labels + labels, cmd=cmd)
      ret = runjava(main=main, classpath=cp, args=args, jvm_options=jvm_options,
                    workunit_factory=runjava_workunit_factory, workunit_name=workunit_name,
                    dryrun=self.dry_run)
      if self.dry_run:
        print('********** Direct Java dry run: %s' % ret)
        return 0
      else:
        return ret

  def runjava(self, main, classpath=None, args=None, jvm_options=None, workunit_name=None,
              workunit_factory=None):
    """Runs the java main using the given classpath and args.

    If --no-ng-daemons is specified then the java main is run in a freshly spawned subprocess,
    otherwise a persistent nailgun server dedicated to this Task subclass is used to speed up
    amortized run times. The args list is divisable so it can be split across multiple invocations
    of the command similiar to xargs.
    """
    # TODO(pl): We're accepting workunit_factory to maintain a consistent interface with
    # binary_util.runjava, but in fact it is just thrown away and a new one will be used
    # in NailgunTask._runjava_common
    return self._runjava_common(binary_util.runjava, main=main, classpath=classpath,
                                args=args, jvm_options=jvm_options, workunit_name=workunit_name)

  def runjava_indivisible(self, main, classpath=None, args=None, jvm_options=None,
                          workunit_name=None, workunit_labels=None, workunit_factory=None):
    """Runs the java main using the given classpath and args.

    If --no-ng-daemons is specified then the java main is run in a freshly spawned subprocess,
    otherwise a persistent nailgun server dedicated to this Task subclass is used to speed up
    amortized run times. The args list is indivisable so it can't be split across multiple
    invocations of the command similiar to xargs.
    """
    # TODO(pl): See above comment on runjava regarding workunit_factory
    return self._runjava_common(binary_util.runjava_indivisible, main=main, classpath=classpath,
                                args=args, jvm_options=jvm_options, workunit_name=workunit_name,
                                workunit_labels=workunit_labels)

  @staticmethod
  def killall(log, everywhere=False):
    NailgunProcessManager.killall(log, everywhere)

  def _ng_shutdown(self):
    endpoint = self._get_nailgun_endpoint()
    if endpoint:
      pid, port = endpoint
      NailgunTask._log_kill(self.context.log, pid, port)
      try:
        os.kill(pid, 9)
      except OSError:
        pass

  def _get_nailgun_endpoint(self):
    if not self._current_pidport:
      self._current_pidport = NailgunTask._find(self._identifier_arg)
      if self._current_pidport:
        self.context.log.debug('found ng server @ pid:%d port:%d' % self._current_pidport)
    return self._current_pidport

  def _get_nailgun_client(self, workunit):
    with self._spawn_lock:
      endpoint = self._get_nailgun_endpoint()
      if endpoint:
        return self._create_ngclient(port=endpoint[1], workunit=workunit)
      else:
        return self._spawn_nailgun_server(workunit)

  # 'NGServer started on 127.0.0.1, port 53785.'
  _PARSE_NG_PORT = re.compile('.*\s+port\s+(\d+)\.$')

  def _parse_nailgun_port(self, line):
    match = NailgunTask._PARSE_NG_PORT.match(line)
    if not match:
      raise NailgunError('Failed to determine spawned ng port from response line: %s' % line)
    return int(match.group(1))

  def _await_nailgun_server(self, workunit):
    nailgun_timeout_seconds = 5
    max_socket_connect_attempts = 10
    start = time.time()

    endpoint = self._get_nailgun_endpoint()
    while endpoint is None:
      if time.time() - start > nailgun_timeout_seconds:
        raise NailgunError('Failed to read ng output after %s seconds' % nailgun_timeout_seconds)
      time.sleep(0.1)
      endpoint = self._get_nailgun_endpoint()

    port = endpoint[1]
    nailgun = self._create_ngclient(port, workunit)
    self.context.log.debug('Detected ng server up on port %d' % port)

    attempt = 0
    while attempt < max_socket_connect_attempts:
      sock = nailgun.try_connect()
      if sock:
        sock.close()
        self.context.log.debug('Connected to ng server pid: %d @ port: %d' % endpoint)
        return nailgun
      attempt += 1
      self.context.log.debug('Failed to connect on attempt %d' % attempt)
      time.sleep(0.1)
    raise NailgunError('Failed to connect to ng after %d connect attempts'
                       % max_socket_connect_attempts)

  def _create_ngclient(self, port, workunit):
    return NailgunClient(port=port, work_dir=get_buildroot(), ins=None,
                         out=workunit.output('stdout'), err=workunit.output('stderr'))

  def _spawn_nailgun_server(self, workunit):
    self.context.log.debug('No ng server found, spawning...')

    with _safe_open(self._ng_out, 'w'):
      pass  # truncate

    ng_classpath = os.pathsep.join(
      self._jvm_tool_bootstrapper.get_jvm_tool_classpath(self._nailgun_bootstrap_key))

    pid = os.fork()
    if pid != 0:
      # In the parent tine - block on ng being up for connections
      return self._await_nailgun_server(workunit)

    # NOTE: Don't use self.context.log or self.context.new_workunit here.
    # They use threadlocal state, which interacts poorly with fork().
    os.setsid()
    in_fd = open('/dev/null', 'w')
    out_fd = safe_open(self._ng_out, 'w')
    err_fd = safe_open(self._ng_err, 'w')
    args = ['java']
    if self._ng_server_args:
      args.extend(self._ng_server_args)
    args.append(NailgunTask.PANTS_NG_ARG)
    args.append(self._identifier_arg)
    args.extend(['-cp', ng_classpath, 'com.martiansoftware.nailgun.NGServer', ':0'])
    s = ' '.join(args)

    with binary_util.safe_classpath():
      subprocess.Popen(
        args,
        stdin=in_fd,
        stdout=out_fd,
        stderr=err_fd,
        close_fds=True,
        cwd=get_buildroot()
      )
      # Prevents finally blocks being executed, unlike sys.exit(). We don't want to execute finally
      # blocks because we might, e.g., clean up tempfiles that the parent still needs.
      os._exit(0)

  @staticmethod
  def _find(identifier_arg):
    return NailgunProcessManager.find(identifier_arg)


class NailgunProcessManager(object):
  """A container for some gnarly process id munging logic."""
  # Verify that the gnarly logic works on this platform.
  plat = Platform.current()
  if not (plat.startswith('linux') or plat.startswith('macosx')):
    raise NotImplementedError('Platform %s not supported by pants.' % plat)

  @staticmethod
  def _run_cmd(cmd):
    # Returns the cmd's output, as a list of lines, including the newline characters.
    runcmd = cmd + ' && echo "${PIPESTATUS[*]}"'
    popen = subprocess.Popen(runcmd, shell=True, executable='/bin/bash', bufsize=-1, close_fds=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (stdout_data, _) = popen.communicate()
    stdout_data_lines = [line for line in stdout_data.strip().split('\n') if line]
    if not stdout_data_lines:
      return None #raise NailgunError('No output for command (%s)' % runcmd)
    try:
      # Get the return codes of each piped cmd.
      piped_return_codes = [int(x) for x in stdout_data_lines[-1].split(' ') if x]
    except ValueError:
      raise NailgunError('Failed to parse result (%s) for command (%s)' % (stdout_data_lines, cmd))
      # Drop the echoing of PIPESTATUS, which our caller doesn't care about.
    stdout_data_lines = stdout_data_lines[:-1]
    failed = any(piped_return_codes)
    if failed:
      raise NailgunError('Failed to execute cmd: "%s". Exit codes: %s. Output: "%s"' %\
                         (cmd, piped_return_codes, ''.join(stdout_data_lines)))
    return stdout_data_lines

  @staticmethod
  def _find_matching_pids(strs):
    # Grep all processes whose cmd-lines contain all the strs, except for the grep process itself.
    filters = ' | '.join(["grep -F -e '%s'" % s for s in strs])
    data = NailgunProcessManager._run_cmd(
      "ps axwww | %s | (grep -v grep || true) | cut -b 1-5" % filters)
    pids = [int(x.strip()) for x in data if x]
    return pids

  @staticmethod
  def _find_ngs(everywhere=False):
    arg = NailgunTask.PANTS_NG_ARG_PREFIX if everywhere else NailgunTask.PANTS_NG_ARG
    return NailgunProcessManager._find_matching_pids([arg])

  @staticmethod
  def killall(log, everywhere=False):
    for pid in NailgunProcessManager._find_ngs(everywhere=everywhere):
      try:
        if log:
          NailgunTask._log_kill(log, pid)
        os.kill(pid, signal.SIGKILL)
      except OSError:
        pass

  DIGITS_RE = re.compile('^\d+$')
  @staticmethod
  def find(identifier_arg):
    pids = NailgunProcessManager._find_matching_pids([NailgunTask.PANTS_NG_ARG, identifier_arg])
    if len(pids) != 1:
      return None
    pid = pids[0]

    # Expected output of the lsof cmd: pPID\nn[::127.0.0.1]:PORT
    lines = NailgunProcessManager._run_cmd('lsof -a -p %s -i TCP -s TCP:LISTEN -P -Fn' % pid)
    if lines is None or len(lines) != 2 or lines[0] != 'p%s' % pid:
      return None
    port = lines[1][lines[1].rfind(':') + 1:].strip()
    if not NailgunProcessManager.DIGITS_RE.match(port):
      return None
    return pid, int(port)
