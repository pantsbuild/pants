# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import io
import multiprocessing
import subprocess
import sys
from typing import Optional


class SubprocessProcessHandler:
    """A `ProcessHandler` that delegates directly to a subprocess.Popen object."""

    def __init__(self, process: subprocess.Popen) -> None:
        self._process = process

    def wait(self, timeout: Optional[float] = None) -> int:
        return self._process.wait(timeout=timeout)

    def kill(self) -> None:
        self._process.kill()

    def terminate(self) -> None:
        self._process.terminate()

    def poll(self) -> Optional[int]:
        return self._process.poll()

    def communicate_teeing_stdout_and_stderr(self, stdin=None):
        """Just like subprocess.communicate, but tees stdout and stderr to both sys.std{out,err} and
        a buffer. Only operates on stdout/stderr if the Popen call send them to subprocess.PIPE.

        :param stdin: A string to send to the stdin of the subprocess.
        :return: (stdout, stderr) as strings.
        """
        if stdin is not None and self._process.stdin is not None:
            self._process.stdin.write(stdin)

        def fork_tee(infile, outfile):
            if infile is None:
                return lambda: None

            queue = multiprocessing.Queue()
            process = multiprocessing.Process(target=_tee, args=(infile, outfile, queue.put))
            process.start()

            def join_and_get_output():
                process.join()
                return queue.get()

            return join_and_get_output

        stdout = fork_tee(self._process.stdout, sys.stdout)
        stderr = fork_tee(self._process.stderr, sys.stderr)

        self._process.wait()

        return stdout(), stderr()


def _tee(infile, outfile, return_function):
    accumulator = io.BytesIO()
    for line in iter(infile.readline, b""):
        accumulator.write(line)
        outfile.buffer.write(line)
    infile.close()
    return_function(accumulator.getvalue())
