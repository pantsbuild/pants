# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import http.server
import os
import re
import socketserver
from contextlib import contextmanager
from multiprocessing import Process, Queue

from pants.testutil.file_test_util import exact_files
from pants.util.contextutil import pushd, temporary_dir
from pants.util.dirutil import safe_mkdir


# NB: All API methods should follow redirects, so we always inject one redirect for all handler
# methods before serving.
def redirect_once(func):
    def wrapper(self):
        if self.path.endswith("/__redir__"):
            self.path = os.path.dirname(self.path)
            return func(self)
        else:
            self.send_response(307, "Found")
            self.send_header("Location", os.path.join(self.path, "__redir__"))
            self.end_headers()

    return wrapper


# A very trivial server that serves files under the cwd.
class SimpleRESTHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, request, client_address, server):
        # The base class implements GET and HEAD.
        # Old-style class, so we must invoke __init__ this way.
        http.server.SimpleHTTPRequestHandler.__init__(self, request, client_address, server)

    @redirect_once
    def do_HEAD(self):
        return http.server.SimpleHTTPRequestHandler.do_HEAD(self)

    @redirect_once
    def do_GET(self):
        return http.server.SimpleHTTPRequestHandler.do_GET(self)

    @redirect_once
    def do_PUT(self):
        path = self.translate_path(self.path)
        content_length = int(self.headers.get("content-length"))
        content = self.rfile.read(content_length)
        safe_mkdir(os.path.dirname(path))
        with open(path, "wb") as outfile:
            outfile.write(content)
        self.send_response(200)
        self.end_headers()

    @redirect_once
    def do_DELETE(self):
        path = self.translate_path(self.path)
        if os.path.exists(path):
            os.unlink(path)
            self.send_response(200)
        else:
            self.send_error(404, "File not found")
        self.end_headers()


class FailRESTHandler(http.server.SimpleHTTPRequestHandler):
    """Reject all requests."""

    def __init__(self, request, client_address, server):
        # Old-style class, so we must invoke __init__ this way.
        http.server.SimpleHTTPRequestHandler.__init__(self, request, client_address, server)

    def _return_failed(self):
        self.send_response(401, "Forced test failure")
        self.end_headers()

    @redirect_once
    def do_HEAD(self):
        return self._return_failed()

    @redirect_once
    def do_GET(self):
        return self._return_failed()

    @redirect_once
    def do_PUT(self):
        return self._return_failed()

    @redirect_once
    def do_DELETE(self):
        return self._return_failed()


class ConnectionErrorRESTHandler(FailRESTHandler):
    """Fail to connect to all requests."""

    def _return_failed(self):
        raise Exception("Intentional connection failure!")


class TestCacheServer:
    """A wrapper class that represents the underlying REST server.

    To create a TestCacheServer, use the `cache_server` factory function.
    """

    def __init__(self, url, cache_root):
        self.url = url
        self._cache_root = cache_root

    def corrupt_artifacts(self, pattern):
        """Corrupts any artifacts matching the given pattern.

        Returns the number of files affected.
        """
        regex = re.compile(pattern)
        count = 0
        for f in exact_files(self._cache_root, ignore_links=True):
            if not regex.match(f):
                continue

            # Truncate the file.
            abspath = os.path.join(self._cache_root, f)
            artifact_size = os.path.getsize(abspath)
            with open(abspath, "r+") as outfile:
                outfile.truncate(artifact_size // 2)

            count += 1

        return count


def _cache_server_process(queue, return_failed, cache_root):
    """A pickleable top-level function to wrap a SimpleRESTHandler.

    We fork a separate process to avoid affecting the `cwd` of the requesting process.
    """
    httpd = None
    try:
        with temporary_dir() as tmpdir:
            cache_root = cache_root if cache_root else tmpdir
            with pushd(cache_root):  # SimpleRESTHandler serves from the cwd.
                if return_failed is True:
                    handler = FailRESTHandler
                elif return_failed is False:
                    handler = SimpleRESTHandler
                elif return_failed == "connection-error":
                    handler = ConnectionErrorRESTHandler
                httpd = socketserver.TCPServer(("localhost", 0), handler)
                port = httpd.server_address[1]
                queue.put(port)
                httpd.serve_forever()
    finally:
        if httpd:
            httpd.shutdown()


@contextmanager
def cache_server(return_failed=False, cache_root=None):
    """A context manager which launches a temporary cache server on a random port.

    Yields a TestCacheServer to represent the running server.
    """
    queue = Queue()
    process = Process(target=_cache_server_process, args=(queue, return_failed, cache_root))
    process.start()
    try:
        port = queue.get()
        yield TestCacheServer(f"http://localhost:{port}", cache_root)
    finally:
        process.terminate()
