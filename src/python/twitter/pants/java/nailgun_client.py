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
import select
import socket
import struct
import sys
import threading

from functools import partial
from twitter.common import app
from twitter.common.log import logger

DEFAULT_NG_HOST = 'localhost'
DEFAULT_NG_PORT = 2113

# For backwards compatibility with nails expecting the ng c client special env vars.
ENV_DEFAULTS = dict(
  NAILGUN_FILESEPARATOR = os.sep,
  NAILGUN_PATHSEPARATOR = os.pathsep
)

# See: http://www.martiansoftware.com/nailgun/protocol.html
HEADER_FMT = '>Ic'
HEADER_LENGTH = 5

BUFF_SIZE = 8096


log = logger(name = 'ng')


def _send_chunk(sock, command, payload=''):
  header = struct.pack(HEADER_FMT, len(payload), command)
  sock.sendall(header + payload)


class ProtocolError(Exception):
  """
    Thrown if there is an error in the underlying nailgun protocol.
  """


class NailgunSession(object):
  """
    Handles a single nailgun command session.
  """

  def __init__(self, sock, ins, out, err):
    self._sock = sock
    self._send_chunk = partial(_send_chunk, sock)
    self._input_reader = NailgunSession._InputReader(ins, self._sock) if ins else None
    self._out = out
    self._err = err

  class _InputReader(threading.Thread):
    def __init__(self, ins, sock):
      threading.Thread.__init__(self)
      self.daemon = True
      self._ins = ins
      self._sock = sock
      self._send_chunk = partial(_send_chunk, sock)
      self._stopping = threading.Event()

    def run(self):
      while self._should_run():
        readable, _, errored = select.select([self._ins], [], [self._ins])
        if self._ins in errored:
          self.stop()
        if self._should_run() and self._ins in readable:
          data = os.read(self._ins.fileno(), BUFF_SIZE)
          if self._should_run():
            if data:
              self._send_chunk('0', data)
            else:
              self._send_chunk('.')
              try:
                self._sock.shutdown(socket.SHUT_WR)
              except socket.error:
                # Can happen if response is quick
                pass
              self.stop()

    def stop(self):
      self._stopping.set()

    def _should_run(self):
      return not self._stopping.is_set()


  def execute(self, work_dir, main_class, *args, **environment):
    log.debug('''work_dir: %s
main_class: %s
args: %s
environment: %s''' % (work_dir, main_class, args, environment))

    for arg in args:
      self._send_chunk('A', arg)
    for k, v in environment.items():
      self._send_chunk('E', '%s=%s' % (k, v))
    self._send_chunk('D', work_dir)
    self._send_chunk('C', main_class)

    if self._input_reader:
      self._input_reader.start()
    try:
      return self._read_response()
    finally:
      if self._input_reader:
        self._input_reader.stop()

  def _read_response(self):
    buffer = ''
    while True:
      command, payload, buffer = self._readchunk(buffer)
      if command == '1':
        self._out.write(payload)
        self._out.flush()
      elif command == '2':
        self._err.write(payload)
        self._err.flush()
      elif command == 'X':
        self._out.flush()
        self._err.flush()
        return int(payload)
      else:
        raise ProtocolError('Received unexpected chunk %s -> %s' % (command, payload))

  def _readchunk(self, buffer):
    while len(buffer) < HEADER_LENGTH:
      buffer += self._sock.recv(BUFF_SIZE)

    payload_length, command = struct.unpack(HEADER_FMT, buffer[:HEADER_LENGTH])
    buffer = buffer[HEADER_LENGTH:]
    while len(buffer) < payload_length:
      buffer += self._sock.recv(BUFF_SIZE)

    payload = buffer[:payload_length]
    rest = buffer[payload_length:]
    return command, payload, rest


class NailgunError(Exception): pass


class NailgunClient(object):
  """
    A client for the nailgun protocol that allows execution of java binaries within a resident vm.
  """

  def __init__(self,
               host=DEFAULT_NG_HOST,
               port=DEFAULT_NG_PORT,
               ins=sys.stdin,
               out=sys.stdout,
               err=sys.stderr,
               work_dir=None):
    """
      Creates a nailgun client that can be used to issue zero or more nailgun commands.

      host: the nailgun server to contact (defaults to localhost)
      port: the port the nailgun server is listening on (defaults to the default nailgun port: 2113)
      ins: a file to read command standard input from (defaults to stdin) - can be None in which
           case no input is read
      out: a stream to write command standard output to (defaults to stdout)
      err: a stream to write command standard error to (defaults to stderr)
      work_dir: the working directory for all nailgun commands (defaults to PWD)
    """

    self._host = host
    self._port = port
    self._ins = ins
    self._out = out
    self._err = err
    self._work_dir = work_dir or os.path.abspath(os.path.curdir)

    self.execute = self.__call__

  def try_connect(self):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    return sock if sock.connect_ex((self._host, self._port)) == 0 else None

  def __call__(self, main_class, *args, **environment):
    """
      Executes the given main_class with any supplied args in the given environment.  Returns
      the exit code of the main_class.
    """

    environment = dict(ENV_DEFAULTS.items() + environment.items())

    sock = self.try_connect()
    if not sock:
      raise NailgunError('Problem connecting to nailgun server %s:%d' % (self._host, self._port))

    session = NailgunSession(sock, self._ins, self._out, self._err)
    try:
      return session.execute(self._work_dir, main_class, *args, **environment)
    except socket.error as e:
      raise NailgunError('Problem contacting nailgun server %s:%d %s' % (self._host, self._port, e))
    finally:
      sock.close()


app.add_option('--nailgun-version',
               dest='just_version',
               default=False,
               action='store_true',
               help='print product version and exit')

app.add_option('--nailgun-showversion',
               dest='show_version',
               default=False,
               action='store_true',
               help='print product version and continue')

app.add_option('--nailgun-server',
               dest='ng_host',
               metavar='HOST',
               default=DEFAULT_NG_HOST,
               help='to specify the address of the nailgun server (default is %default)')

app.add_option('--nailgun-port',
               dest='ng_port',
               metavar='PORT',
               default=DEFAULT_NG_PORT,
               type='int',
               help='to specify the port of the nailgun server (default is %default)')

app.add_option('--nailgun-help',
               dest='show_help',
               default=False,
               action='store_true',
               help='print this message and exit')

app.set_usage('''%(command)s class [--nailgun-options] [args]
          (to execute a class)
   or: %(command)s alias [options] [args]
          (to execute an aliased class)
   or: alias [options] [args]
          (to execute an aliased class, where "alias"
           is both the alias for the class and a symbolic
           link to the ng client)
''' % dict(command = sys.argv[0]))


def main(args):
  options = app.get_options()
  if options.show_help:
    app.help()

  if options.show_version or options.just_version:
    print >> sys.stdout, 'Python NailGun client version 0.0.1'
    if options.just_version:
      sys.exit(0)


  # Assume ng.pex has been aliased to the command name
  command = re.compile('.pex$').sub('', os.path.basename(sys.argv[0]))
  args_index = 0

  # Otherwise the command name is the 1st arg
  if command == 'ng':
    if not args:
      app.help()

    command = args[0]
    args_index = 1

  ng = NailgunClient(host=options.ng_host, port=options.ng_port)
  result = ng(command, *args[args_index:], **os.environ)
  sys.exit(result)


app.main()
