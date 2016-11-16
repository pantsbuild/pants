# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import socket
import traceback

from six.moves.socketserver import BaseRequestHandler, BaseServer, TCPServer

from pants.java.nailgun_protocol import ChunkType, NailgunProtocol
from pants.util.contextutil import maybe_profiled
from pants.util.socket import RecvBufferedSocket


class PailgunHandlerBase(BaseRequestHandler):
  """Base class for nailgun protocol handlers for use with SocketServer-based servers."""

  def __init__(self, request, client_address, server):
    """Override of BaseRequestHandler.__init__() that defers calling of self.setup().

    :param socket request: The inbound TCPServer request socket.
    :param tuple client_address: The remote client socket address tuple (host, port).
    :param TCPServer server: The parent TCPServer instance.
    """
    self.request = request
    self.client_address = client_address
    self.server = server
    self.logger = logging.getLogger(__name__)

  def handle_request(self):
    """Handle a request (the equivalent of the latter half of BaseRequestHandler.__init__()).

    This is invoked by a TCPServer subclass that overrides process_request().
    """
    self.setup()
    try:
      self.handle()
    finally:
      self.finish()

  def handle(self):
    """Main request handler entrypoint for subclasses."""

  def handle_error(self, exc):
    """Main error handler entrypoint for subclasses."""


class PailgunHandler(PailgunHandlerBase):
  """A nailgun protocol handler for use with forking, SocketServer-based servers."""

  def _run_pants(self, sock, arguments, environment):
    """Execute a given run with a pants runner."""
    runner = self.server.runner_factory(sock, arguments, environment)
    runner.run()

  def handle(self):
    """Request handler for a single Pailgun request."""
    # Parse the Nailgun request portion.
    _, _, arguments, environment = NailgunProtocol.parse_request(self.request)

    # N.B. the first and second nailgun request arguments (working_dir and command) are currently
    # ignored in favor of a get_buildroot() call within LocalPantsRunner.run() and an assumption
    # that anyone connecting to this nailgun server always intends to run pants itself.

    # Prepend the command to our arguments so it aligns with the expected sys.argv format of python
    # (e.g. [list', '::'] -> ['./pants', 'list', '::']).
    arguments.insert(0, './pants')

    self.logger.info('handling pailgun request: `{}`'.format(' '.join(arguments)))
    self.logger.debug('pailgun request environment: %s', environment)

    # Instruct the client to send stdin (if applicable).
    NailgunProtocol.send_start_reading_input(self.request)

    # Execute the requested command with optional daemon-side profiling.
    with maybe_profiled(environment.get('PANTSD_PROFILE')):
      self._run_pants(self.request, arguments, environment)

  def handle_error(self, exc=None):
    """Error handler for failed calls to handle()."""
    if exc:
      NailgunProtocol.write_chunk(self.request, ChunkType.STDERR, traceback.format_exc())
    NailgunProtocol.write_chunk(self.request, ChunkType.EXIT, '1')


class PailgunServer(TCPServer):
  """A (forking) pants nailgun server."""

  def __init__(self, server_address, runner_factory, context_lock,
               handler_class=None, bind_and_activate=True):
    """Override of TCPServer.__init__().

    N.B. the majority of this function is copied verbatim from TCPServer.__init__().

    :param tuple server_address: An address tuple of (hostname, port) for socket.bind().
    :param class runner_factory: A factory function for creating a DaemonPantsRunner for each run.
    :param func context_lock: A contextmgr that will be used as a lock during request handling/forking.
    :param class handler_class: The request handler class to use for each request. (Optional)
    :param bool bind_and_activate: If True, binds and activates networking at __init__ time.
                                   (Optional)
    """
    # Old-style class, so we must invoke __init__() this way.
    BaseServer.__init__(self, server_address, handler_class or PailgunHandler)
    self.socket = RecvBufferedSocket(socket.socket(self.address_family, self.socket_type))
    self.runner_factory = runner_factory
    self.allow_reuse_address = True           # Allow quick reuse of TCP_WAIT sockets.
    self.server_port = None                   # Set during server_bind() once the port is bound.
    self._context_lock = context_lock

    if bind_and_activate:
      try:
        self.server_bind()
        self.server_activate()
      except Exception:
        self.server_close()
        raise

  def server_bind(self):
    """Override of TCPServer.server_bind() that tracks bind-time assigned random ports."""
    TCPServer.server_bind(self)
    _, self.server_port = self.socket.getsockname()[:2]

  def process_request(self, request, client_address):
    """Override of TCPServer.process_request() that provides for forking request handlers and
    delegates error handling to the request handler."""
    # Instantiate the request handler.
    handler = self.RequestHandlerClass(request, client_address, self)

    try:
      # Attempt to handle a request with the handler under the context_lock.
      with self._context_lock():
        handler.handle_request()
    except Exception as e:
      # If that fails, (synchronously) handle the error with the error handler sans-fork.
      try:
        handler.handle_error(e)
      finally:
        # Shutdown the socket since we don't expect a fork() in the exception context.
        self.shutdown_request(request)
    else:
      # At this point, we expect a fork() has taken place - the parent side will return, and so we
      # close the request here from the parent without explicitly shutting down the socket. The
      # child half of this will perform an os._exit() before it gets to this point and is also
      # responsible for shutdown and closing of the socket when its execution is complete.
      self.close_request(request)
