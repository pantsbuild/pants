# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import socket
import threading
import unittest
import unittest.mock
from contextlib import contextmanager
from queue import Queue
from socketserver import TCPServer

from pants.java.nailgun_protocol import ChunkType, MaybeShutdownSocket, NailgunProtocol
from pants.pantsd.pailgun_server import PailgunHandler, PailgunServer


PATCH_OPTS = dict(autospec=True, spec_set=True)


class TestPailgunServer(unittest.TestCase):
    def setUp(self):
        self.mock_handler_inst = unittest.mock.Mock()
        # Add a fake environment for this to not timeout.
        self.fake_environment = {"PANTSD_REQUEST_TIMEOUT_LIMIT": "-1"}
        self.mock_handler_inst.parsed_request.return_value = (None, None, [], self.fake_environment)

        self.mock_runner_factory = unittest.mock.Mock(
            side_effect=Exception("this should never be called")
        )
        self.mock_handler_class = unittest.mock.Mock(return_value=self.mock_handler_inst)
        self.lock = threading.RLock()

        @contextmanager
        def lock():
            with self.lock:
                yield

        self.after_request_callback_calls = 0

        def after_request_callback():
            self.after_request_callback_calls += 1

        with unittest.mock.patch.object(PailgunServer, "server_bind"), unittest.mock.patch.object(
            PailgunServer, "server_activate"
        ):
            self.server = PailgunServer(
                server_address=("0.0.0.0", 0),
                runner_factory=self.mock_runner_factory,
                handler_class=self.mock_handler_class,
                lifecycle_lock=lock,
                request_complete_callback=after_request_callback,
            )

    @unittest.mock.patch.object(TCPServer, "server_bind", **PATCH_OPTS)
    def test_server_bind(self, mock_tcpserver_bind):
        mock_sock = unittest.mock.Mock()
        mock_sock.getsockname.return_value = ("0.0.0.0", 31337)
        self.server.socket = mock_sock
        self.server.server_bind()
        self.assertEqual(self.server.server_port, 31337)
        self.assertIs(mock_tcpserver_bind.called, True)

    @unittest.mock.patch.object(PailgunServer, "close_request", **PATCH_OPTS)
    def test_process_request_thread(self, mock_close_request):
        mock_request = unittest.mock.Mock()
        self.server.process_request_thread(mock_request, ("1.2.3.4", 31338))
        self.assertIs(self.mock_handler_inst.handle_request.called, True)
        mock_close_request.assert_called_once_with(self.server, mock_request)

    @unittest.mock.patch.object(PailgunServer, "close_request", **PATCH_OPTS)
    def test_process_request_calls_callback(self, mock_close_request):
        mock_request = unittest.mock.Mock()
        self.server.process_request_thread(mock_request, ("1.2.3.4", 31338))
        self.assertIs(self.mock_handler_inst.handle_request.called, True)
        assert self.after_request_callback_calls == 1

    @unittest.mock.patch.object(PailgunServer, "shutdown_request", **PATCH_OPTS)
    def test_process_request_thread_error(self, mock_shutdown_request):
        mock_request = unittest.mock.Mock()
        self.mock_handler_inst.handle_request.side_effect = AttributeError("oops")
        self.server.process_request_thread(mock_request, ("1.2.3.4", 31338))
        self.assertIs(self.mock_handler_inst.handle_request.called, True)
        self.assertIs(self.mock_handler_inst.handle_error.called, True)
        mock_shutdown_request.assert_called_once_with(self.server, mock_request)

    def test_ensure_request_is_exclusive(self):
        """Launch many requests, assert that every one is trying to enter the critical section, and assert that only one is doing so at a time."""
        self.threads_to_start = 10

        # Queues are thread safe (https://docs.python.org/2/library/queue.html)
        self.thread_errors = Queue()

        def threaded_assert_equal(one, other, message):
            try:
                self.assertEqual(one, other, message)
            except AssertionError as error:
                self.thread_errors.put(error)

        self.threads_running_cond = threading.Condition()
        self.threads_running = 0

        def handle_thread_tried_to_handle_request():
            """Mark a thread as started, and block until every thread has been marked as starting."""
            self.threads_running_cond.acquire()
            self.threads_running += 1
            if self.threads_running == self.threads_to_start:
                self.threads_running_cond.notify_all()
            else:
                while self.threads_running != self.threads_to_start:
                    self.threads_running_cond.wait()

            threaded_assert_equal(
                self.threads_running,
                self.threads_to_start,
                "This thread is unblocked before all the threads had started.",
            )
            self.threads_running_cond.release()

        def handle_thread_finished():
            """Mark a thread as finished, and block until there are no more threads running."""
            self.threads_running_cond.acquire()
            self.threads_running -= 1
            print("Handle_thread_finished, threads_running are {}".format(self.threads_running))
            if self.threads_running == 0:
                self.threads_running_cond.notify_all()
            else:
                while self.threads_running != 0:
                    self.threads_running_cond.wait()

            threaded_assert_equal(
                self.threads_running,
                0,
                "handle_thread_finished exited when there still were threads running.",
            )
            self.threads_running_cond.release()

        self.threads_handling_requests = 0
        self.threads_handling_requests_lock = threading.Lock()

        def handle_thread_starts_handling_request():
            with self.threads_handling_requests_lock:
                self.threads_handling_requests += 1
                threaded_assert_equal(
                    self.threads_handling_requests, 1, "A thread is already handling a request!"
                )

        def check_only_one_thread_is_handling_a_request():
            """Assert that there's only ever one thread inside the lock."""
            with self.threads_handling_requests_lock:
                threaded_assert_equal(
                    self.threads_handling_requests, 1, "A thread is already handling a request!"
                )

        def handle_thread_finishing_handling_request():
            """Assert that I was the only thread handling a request."""
            with self.threads_handling_requests_lock:
                self.threads_handling_requests -= 1
                threaded_assert_equal(
                    self.threads_handling_requests,
                    0,
                    "There were multiple threads handling a request when a thread finished",
                )

        # Wrap ensure_request_is_exclusive to notify when we acquire and release the lock.
        def mock_ensure_request_is_exclusive(request_lock_under_test):
            """Wrap the lock under test. Every thread that calls this function has reached the critical section."""

            @contextmanager
            def wrapper(environment, request):
                # Assert that all threads are trying to handle a request.
                handle_thread_tried_to_handle_request()
                with request_lock_under_test(environment, request):
                    try:
                        # Assert that only one is allowed to handle a request.
                        print("Thread has entered the request handling code.")
                        handle_thread_starts_handling_request()
                        check_only_one_thread_is_handling_a_request()
                        yield
                        check_only_one_thread_is_handling_a_request()
                        print("Thread has exited the request handling code.")
                    finally:
                        # Account for a thread finishing a request.
                        handle_thread_finishing_handling_request()
                # Notify that a thread is shutting down.
                handle_thread_finished()
                # At this point, we have asserted that all threads are finished.

            return wrapper

        self.server.ensure_request_is_exclusive = mock_ensure_request_is_exclusive(
            self.server.ensure_request_is_exclusive
        )

        # Create as many mock threads as needed. Lauch all of them, and wait for all of them to finish.
        mock_request = unittest.mock.Mock()

        def create_request_thread(port):
            return threading.Thread(
                target=self.server.process_request_thread,
                args=(mock_request, ("1.2.3.4", port)),
                name="MockThread-{}".format(port),
            )

        threads = [create_request_thread(0) for _ in range(0, self.threads_to_start)]
        for thread in threads:
            thread.start()
            self.assertTrue(
                self.thread_errors.empty(),
                "There were some errors in the threads:\n {}".format(self.thread_errors),
            )

        for thread in threads:
            # If this fails because it times out, it's definitely a legitimate error.
            thread.join(10)
            self.assertTrue(
                self.thread_errors.empty(),
                "There were some errors in the threads:\n {}".format(self.thread_errors),
            )


class TestPailgunHandler(unittest.TestCase):
    def setUp(self):
        self.client_sock, self.server_sock = socket.socketpair()
        self.mock_socket = unittest.mock.Mock()
        self.mock_server = unittest.mock.create_autospec(PailgunServer, spec_set=True)
        self.handler = PailgunHandler(
            self.server_sock, self.client_sock.getsockname()[:2], self.mock_server
        )

    def test_handle_error(self):
        self.handler.handle_error()
        maybe_shutdown_socket = MaybeShutdownSocket(self.client_sock)
        last_chunk_type, last_payload = list(NailgunProtocol.iter_chunks(maybe_shutdown_socket))[-1]
        self.assertEqual(last_chunk_type, ChunkType.EXIT)
        self.assertEqual(last_payload, "1")

    @unittest.mock.patch.object(PailgunHandler, "_run_pants", **PATCH_OPTS)
    def test_handle_request(self, mock_run_pants):
        NailgunProtocol.send_request(self.client_sock, "/test", "./pants", "help-advanced")
        self.handler.handle_request()
        self.assertIs(mock_run_pants.called, True)
